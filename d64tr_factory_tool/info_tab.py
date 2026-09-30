from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .commands import CommandResult, QueueResult
from .devices import (
    DeviceSelectionError,
    build_device_list_step,
    require_single_adb_device,
)
from .info import build_info_steps
from .runner import CommandRunner


class InfoTab(QWidget):
    def __init__(
        self,
        runner_factory: Callable[[], CommandRunner] = CommandRunner,
    ) -> None:
        super().__init__()
        self._phase = "idle"
        self._runner = runner_factory()
        if self._runner.parent() is None:
            self._runner.setParent(self)
        self._runner.step_finished.connect(self._on_step_finished)
        self._runner.queue_finished.connect(self._on_queue_finished)

        self.refresh_button = QPushButton("Refresh")
        self.clear_button = QPushButton("Clear")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas; font-size: 14px;")

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.addLayout(button_layout)
        layout.addWidget(self.log)

        self.refresh_button.clicked.connect(self.refresh)
        self.clear_button.clicked.connect(self.log.clear)

    def refresh(self) -> None:
        if self._runner.busy:
            return
        self._phase = "probe"
        self.refresh_button.setEnabled(False)
        self.append_log("Detecting ADB device...")
        self._runner.start((build_device_list_step("adb"),))

    def append_log(self, text: str, timestamp: bool = True) -> None:
        if timestamp:
            text = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        self.log.append(text)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log.setTextCursor(cursor)

    def shutdown(self) -> None:
        self._runner.cancel()

    def _on_step_finished(self, result: CommandResult) -> None:
        if self._phase != "info":
            return
        self.append_log(f"{result.step.label}:")
        if result.success:
            value = result.stdout.strip() or "(empty)"
            self.append_log(value, timestamp=False)
            return
        self.append_log(f"FAILED: {self._failure_message(result)}", timestamp=False)

    def _on_queue_finished(self, result: QueueResult) -> None:
        phase = self._phase
        if result.cancelled:
            self._finish()
            return
        if phase == "probe":
            self._handle_probe_result(result)
        elif phase == "info":
            self.append_log("Done." if result.success else "Completed with errors.")
            self._finish()

    def _handle_probe_result(self, queue_result: QueueResult) -> None:
        if not queue_result.results or not queue_result.results[0].success:
            message = (
                self._failure_message(queue_result.results[0])
                if queue_result.results
                else "ADB device detection failed"
            )
            self.append_log(f"FAILED: {message}")
            self._finish()
            return

        try:
            serial = require_single_adb_device(queue_result.results[0].stdout)
        except DeviceSelectionError as error:
            self.append_log(str(error))
            self._finish()
            return

        self.append_log(f"Using ADB device: {serial}")
        self._phase = "info"
        self._runner.start(build_info_steps(serial))

    def _finish(self) -> None:
        self._phase = "idle"
        self.refresh_button.setEnabled(True)

    @staticmethod
    def _failure_message(result: CommandResult) -> str:
        if result.process_error:
            return result.process_error
        if result.timed_out:
            return "Command timed out"
        return result.stderr.strip() or f"exit code {result.exit_code}"
