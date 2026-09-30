from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .commands import CommandResult, CommandStep, QueueResult


ProcessFactory = Callable[[QObject], QProcess]


class CommandRunner(QObject):
    step_started = Signal(object)
    output_received = Signal(str, str)
    step_finished = Signal(object)
    queue_finished = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._process_factory = process_factory or (lambda owner: QProcess(owner))
        self._pending: deque[CommandStep] = deque()
        self._results: list[CommandResult] = []
        self._process: QProcess | None = None
        self._current_step: CommandStep | None = None
        self._stdout_parts: list[str] = []
        self._stderr_parts: list[str] = []
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self, steps: Sequence[CommandStep]) -> None:
        if self._busy:
            raise RuntimeError("Command runner is already running")
        if not steps:
            raise ValueError("A command queue requires at least one step")

        self._pending = deque(steps)
        self._results = []
        self._busy = True
        self._start_next()

    def cancel(self) -> None:
        if not self._busy:
            return

        self._timer.stop()
        process = self._process
        self._current_step = None
        self._process = None
        self._pending.clear()
        if process is not None:
            self._stop_process(process)
            process.deleteLater()

        self._busy = False
        self.queue_finished.emit(
            QueueResult(tuple(self._results), cancelled=True)
        )

    def _start_next(self) -> None:
        if not self._pending:
            self._finish_queue()
            return

        step = self._pending.popleft()
        process = self._process_factory(self)
        self._current_step = step
        self._process = process
        self._stdout_parts = []
        self._stderr_parts = []

        process.readyReadStandardOutput.connect(
            lambda active=process: self._read_output(active, "stdout")
        )
        process.readyReadStandardError.connect(
            lambda active=process: self._read_output(active, "stderr")
        )
        process.finished.connect(
            lambda exit_code, _exit_status, active=process: self._on_finished(
                active, exit_code
            )
        )
        process.errorOccurred.connect(
            lambda _error, active=process: self._on_process_error(active)
        )

        self.step_started.emit(step)
        if step.timeout_ms is not None:
            self._timer.start(step.timeout_ms)
        process.start(step.program, list(step.arguments))

    def _read_output(self, process: QProcess, channel: str) -> None:
        if process is not self._process:
            return
        if channel == "stdout":
            data = bytes(process.readAllStandardOutput())
            parts = self._stdout_parts
        else:
            data = bytes(process.readAllStandardError())
            parts = self._stderr_parts
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        parts.append(text)
        self.output_received.emit(channel, text)

    def _drain_output(self, process: QProcess) -> None:
        self._read_output(process, "stdout")
        self._read_output(process, "stderr")

    def _on_finished(self, process: QProcess, exit_code: int) -> None:
        if process is not self._process or self._current_step is None:
            return
        step = self._take_current(process)
        result = CommandResult(
            step=step,
            exit_code=exit_code,
            stdout="".join(self._stdout_parts),
            stderr="".join(self._stderr_parts),
        )
        process.deleteLater()
        self._record_result(result)

    def _on_process_error(self, process: QProcess) -> None:
        if process is not self._process or self._current_step is None:
            return
        step = self._take_current(process)
        error_message = process.errorString() or "Process failed"
        result = CommandResult(
            step=step,
            exit_code=-1,
            stdout="".join(self._stdout_parts),
            stderr="".join(self._stderr_parts),
            process_error=error_message,
        )
        process.deleteLater()
        self._record_result(result)

    def _on_timeout(self) -> None:
        process = self._process
        if process is None or self._current_step is None:
            return
        step = self._take_current(process)
        self._stop_process(process)
        result = CommandResult(
            step=step,
            exit_code=-1,
            stdout="".join(self._stdout_parts),
            stderr="".join(self._stderr_parts),
            timed_out=True,
        )
        process.deleteLater()
        self._record_result(result)

    def _take_current(self, process: QProcess) -> CommandStep:
        self._timer.stop()
        self._drain_output(process)
        step = self._current_step
        if step is None:
            raise RuntimeError("No active command step")
        self._current_step = None
        self._process = None
        return step

    @staticmethod
    def _stop_process(process: QProcess) -> None:
        if process.state() == QProcess.NotRunning:
            return
        process.terminate()
        if not process.waitForFinished(250):
            process.kill()
            process.waitForFinished(250)

    def _record_result(self, result: CommandResult) -> None:
        self._results.append(result)
        self.step_finished.emit(result)
        if result.success or result.step.continue_on_error:
            self._start_next()
        else:
            self._pending.clear()
            self._finish_queue()

    def _finish_queue(self) -> None:
        if not self._busy:
            return
        self._timer.stop()
        self._busy = False
        self.queue_finished.emit(QueueResult(tuple(self._results)))
