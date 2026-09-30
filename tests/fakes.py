from __future__ import annotations

from PySide6.QtCore import QByteArray, QObject, QProcess, Signal

from d64tr_factory_tool.commands import CommandResult, QueueResult


class FakeProcess(QObject):
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    finished = Signal(int, object)
    errorOccurred = Signal(object)

    def __init__(self, factory: "FakeProcessFactory", parent: QObject | None = None):
        super().__init__(parent)
        self.factory = factory
        self._stdout = QByteArray()
        self._stderr = QByteArray()
        self._error_string = ""
        self._state = QProcess.NotRunning
        self.terminated = False
        self.killed = False

    def start(self, program: str, arguments: list[str]) -> None:
        self._state = QProcess.Running
        self.factory.started.append((program, tuple(arguments)))

    def readAllStandardOutput(self) -> QByteArray:
        data = self._stdout
        self._stdout = QByteArray()
        return data

    def readAllStandardError(self) -> QByteArray:
        data = self._stderr
        self._stderr = QByteArray()
        return data

    def errorString(self) -> str:
        return self._error_string

    def state(self) -> QProcess.ProcessState:
        return self._state

    def terminate(self) -> None:
        self.terminated = True
        self._state = QProcess.NotRunning

    def waitForFinished(self, timeout_ms: int) -> bool:
        return True

    def kill(self) -> None:
        self.killed = True
        self._state = QProcess.NotRunning

    def deleteLater(self) -> None:
        # The factory intentionally retains fakes so tests can inspect them.
        # Let QObject parent cleanup own their lifetime instead of scheduling
        # deletion while a Python reference is still retained.
        return

    def finish(self, exit_code: int, stdout: str = "", stderr: str = "") -> None:
        self._stdout.append(stdout.encode())
        self._stderr.append(stderr.encode())
        self._state = QProcess.NotRunning
        self.finished.emit(exit_code, QProcess.NormalExit)

    def fail_to_start(self, message: str) -> None:
        self._error_string = message
        self._state = QProcess.NotRunning
        self.errorOccurred.emit(QProcess.FailedToStart)


class FakeProcessFactory:
    def __init__(self):
        self.started: list[tuple[str, tuple[str, ...]]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, parent: QObject | None = None) -> FakeProcess:
        process = FakeProcess(self, parent)
        self.processes.append(process)
        return process

    @property
    def current(self) -> FakeProcess:
        return self.processes[-1]

    def finish_current(
        self, exit_code: int, stdout: str = "", stderr: str = ""
    ) -> None:
        self.current.finish(exit_code, stdout, stderr)

    def fail_current_to_start(self, message: str) -> None:
        self.current.fail_to_start(message)


class FakeCommandRunner(QObject):
    step_started = Signal(object)
    output_received = Signal(str, str)
    step_finished = Signal(object)
    queue_finished = Signal(object)

    def __init__(self):
        super().__init__()
        self.started: list[tuple] = []
        self.current_steps: tuple = ()
        self.busy = False
        self.cancelled = False
        self.executed_step_keys: list[str] = []

    def start(self, steps) -> None:
        if self.busy:
            raise RuntimeError("Fake runner is already running")
        self.current_steps = tuple(steps)
        self.started.append(self.current_steps)
        self.busy = True

    def finish(self, outcomes) -> QueueResult:
        results = []
        for step, outcome in zip(self.current_steps, outcomes):
            exit_code, stdout, stderr = outcome
            self.executed_step_keys.append(step.key)
            result = CommandResult(step, exit_code, stdout, stderr)
            results.append(result)
            if stdout:
                self.output_received.emit("stdout", stdout)
            if stderr:
                self.output_received.emit("stderr", stderr)
            self.step_finished.emit(result)
        queue_result = QueueResult(tuple(results))
        self.busy = False
        self.current_steps = ()
        self.queue_finished.emit(queue_result)
        return queue_result

    def fail_to_start(self, message: str) -> QueueResult:
        step = self.current_steps[0]
        result = CommandResult(
            step,
            -1,
            "",
            "",
            process_error=message,
        )
        self.step_finished.emit(result)
        queue_result = QueueResult((result,))
        self.busy = False
        self.current_steps = ()
        self.queue_finished.emit(queue_result)
        return queue_result

    def cancel(self) -> None:
        self.cancelled = True
        if self.busy:
            self.busy = False
            self.queue_finished.emit(QueueResult((), cancelled=True))


class FakeRunnerFactory:
    def __init__(self):
        self.instances: list[FakeCommandRunner] = []

    def __call__(self) -> FakeCommandRunner:
        runner = FakeCommandRunner()
        self.instances.append(runner)
        return runner

    @property
    def current(self) -> FakeCommandRunner:
        return self.instances[-1]

    @property
    def device_probe_count(self) -> int:
        return sum(
            1
            for runner in self.instances
            for queue in runner.started
            if queue and queue[0].key == "probe-adb"
        )
