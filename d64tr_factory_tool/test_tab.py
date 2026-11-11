from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .commands import CommandResult, CommandStep, QueueResult
from .devices import (
    DeviceSelectionError,
    build_device_list_step,
    require_single_adb_device,
)
from .runner import CommandRunner


class TestTab(QWidget):
    def __init__(
        self,
        runner_factory: Callable[[], CommandRunner] = CommandRunner,
    ) -> None:
        super().__init__()
        self._phase = "idle"
        self._serial: str | None = None
        self._closed = False
        self._runner = runner_factory()
        if self._runner.parent() is None:
            self._runner.setParent(self)
        self._runner.queue_finished.connect(self._on_queue_finished)

        self.sdcard_button = QPushButton("SDCard Test")
        self.sdcard_button.setMinimumHeight(45)
        self.sdcard_button.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.sdcard_result_label = QLabel("")
        self.sdcard_result_label.setFixedWidth(32)
        self.sdcard_result_label.setAlignment(Qt.AlignCenter)
        self.sdcard_result_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.sdcard_result_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        result_layout = QHBoxLayout(self.sdcard_button)
        result_layout.setContentsMargins(12, 0, 12, 0)
        result_layout.addStretch()
        result_layout.addWidget(self.sdcard_result_label)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas; font-size: 14px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.sdcard_button)
        layout.addSpacing(10)
        layout.addWidget(self.log)
        self.sdcard_button.clicked.connect(self.run_sdcard_test)

    def run_sdcard_test(self) -> None:
        if self._closed or self._phase != "idle":
            return
        self.sdcard_result_label.clear()
        self.sdcard_button.setEnabled(False)
        self._serial = None
        self._phase = "probe"
        self.log.append("Detecting ADB device...")
        self._runner.start((build_device_list_step("adb"),))

    def shutdown(self) -> None:
        self._closed = True
        self._phase = "idle"
        self.sdcard_result_label.clear()
        self.sdcard_button.setEnabled(False)
        self._runner.cancel()

    def _on_queue_finished(self, queue: QueueResult) -> None:
        if self._closed or self._phase == "idle":
            return
        if queue.cancelled:
            self._phase = "idle"
            self.sdcard_result_label.clear()
            self.sdcard_button.setEnabled(True)
            return

        result = queue.results[0] if queue.results else None
        if result is not None and not result.success:
            self.log.append(self._failure_message(result))

        if self._phase == "probe":
            if result is None or not result.success:
                self.log.append("ADB device detection FAILED.")
                self._complete(False)
                return
            try:
                self._serial = require_single_adb_device(result.stdout)
            except DeviceSelectionError as error:
                self.log.append(str(error))
                self._complete(False)
                return
            self.log.append(f"Using ADB device: {self._serial}")
            self.log.append("Checking SDCard mount status...")
            self._phase = "mount"
            self._start_shell("sdcard-mount", "mount | grep /mnt/sdcard")
        elif self._phase == "mount":
            if result is None or not result.success or not result.stdout.strip():
                self.log.append("SDCard NOT detected ✗")
                self._complete(False)
                return
            self.log.append("SDCard INSERTED ✓")
            self.log.append("Running SDCard write/read test...")
            self._phase = "write"
            self._start_shell(
                "sdcard-function",
                "echo TEST_OK > /mnt/sdcard/test.tmp && "
                "grep TEST_OK /mnt/sdcard/test.tmp && "
                "rm /mnt/sdcard/test.tmp",
            )
        elif self._phase == "write":
            passed = result is not None and result.success
            self.log.append(
                "SDCard FUNCTION TEST PASS ✓" if passed
                else "SDCard FUNCTION TEST FAIL ✗"
            )
            self._complete(passed)

    def _start_shell(self, key: str, command: str) -> None:
        self._runner.start((CommandStep(
            key=key,
            label="SDCard Test",
            program="adb",
            arguments=("-s", self._serial, "shell", command),
        ),))

    def _complete(self, passed: bool) -> None:
        self._phase = "idle"
        self.sdcard_result_label.setText("✓" if passed else "✗")
        color = "green" if passed else "red"
        self.sdcard_result_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {color};"
        )
        self.sdcard_button.setEnabled(True)

    @staticmethod
    def _failure_message(result: CommandResult) -> str:
        if result.process_error:
            return result.process_error
        if result.timed_out:
            return "Command timed out"
        return result.stderr.strip() or f"exit code {result.exit_code}"
