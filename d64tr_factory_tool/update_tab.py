from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .commands import CommandResult, QueueResult
from .devices import (
    DeviceSelectionError,
    build_device_list_step,
    parse_fastboot_devices,
    require_single_adb_device,
    require_single_fastboot_device,
)
from .runner import CommandRunner
from .update import (
    ABL_IMAGE_NAME,
    BOOT_IMAGE_NAME,
    SYSTEM_IMAGE_NAME,
    PackageValidationError,
    UpdatePackage,
    build_enter_bootloader_steps,
    build_fastboot_reboot_step,
    build_flash_steps,
    validate_update_package,
)


class UpdateTab(QWidget):
    MAX_FASTBOOT_POLLS = 10

    def __init__(
        self,
        runner_factory: Callable[[], CommandRunner] = CommandRunner,
    ) -> None:
        super().__init__()
        self.phase = "idle"
        self.fastboot_serial: str | None = None
        self._expected_fastboot_serial: str | None = None
        self._probe_transport = "fastboot"
        self._poll_attempts = 0
        self._selected_folder: Path | None = None
        self._package: UpdatePackage | None = None

        self._runner = runner_factory()
        if self._runner.parent() is None:
            self._runner.setParent(self)
        self._runner.output_received.connect(self._on_output)
        self._runner.step_finished.connect(self._on_step_finished)
        self._runner.queue_finished.connect(self._on_queue_finished)

        self.poll_timer = QTimer(self)
        self.poll_timer.setSingleShot(True)
        self.poll_timer.timeout.connect(self._start_fastboot_poll)

        self.folder_path = QLineEdit()
        self.folder_path.setReadOnly(True)
        self.select_folder_button = QPushButton("Select Update Folder")
        self.boot_status = QLabel(f"Missing: {BOOT_IMAGE_NAME}")
        self.system_status = QLabel(f"Missing: {SYSTEM_IMAGE_NAME}")
        self.abl_status = QLabel(f"Optional: {ABL_IMAGE_NAME} not selected")

        self.enter_mode_button = QPushButton("Enter Update Mode")
        self.update_button = QPushButton("Update")
        self.reboot_button = QPushButton("Reboot")
        for button in (
            self.enter_mode_button,
            self.update_button,
            self.reboot_button,
        ):
            button.setMinimumHeight(46)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas; font-size: 14px;")

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_path)
        folder_layout.addWidget(self.select_folder_button)

        status_layout = QFormLayout()
        status_layout.addRow("Boot image", self.boot_status)
        status_layout.addRow("System image", self.system_status)
        status_layout.addRow("ABL image", self.abl_status)
        status_group = QGroupBox("Update Package")
        status_group.setLayout(status_layout)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.enter_mode_button)
        button_layout.addWidget(self.update_button)
        button_layout.addWidget(self.reboot_button)

        layout = QVBoxLayout(self)
        layout.addLayout(folder_layout)
        layout.addWidget(status_group)
        layout.addLayout(button_layout)
        layout.addWidget(self.log)

        self.select_folder_button.clicked.connect(self._choose_folder)
        self.enter_mode_button.clicked.connect(self.enter_update_mode)
        self.update_button.clicked.connect(self.start_update)
        self.reboot_button.clicked.connect(self.reboot_device)
        self._update_controls()

    def set_update_folder(self, path: Path) -> None:
        self._selected_folder = Path(path)
        self.folder_path.setText(str(self._selected_folder))
        self._refresh_package_status()

    def enter_update_mode(self) -> None:
        if self._runner.busy:
            return
        self.fastboot_serial = None
        self._expected_fastboot_serial = None
        self._probe_transport = "fastboot"
        self.phase = "probing"
        self.append_log("Checking for a Fastboot device...")
        self._update_controls()
        self._runner.start((build_device_list_step("fastboot"),))

    def start_update(self) -> None:
        if self._runner.busy or self.fastboot_serial is None:
            return
        if self._selected_folder is None:
            self.append_log("Select an update folder first.")
            return
        try:
            self._package = validate_update_package(self._selected_folder)
        except PackageValidationError as error:
            self.append_log(str(error))
            self._refresh_package_status()
            return

        if self._package.abl is None:
            self.append_log("ABL image not present; skipped.")
        self.phase = "flashing"
        self.append_log("Starting FULL UPDATE...")
        self._update_controls()
        self._runner.start(build_flash_steps(self._package, self.fastboot_serial))

    def reboot_device(self) -> None:
        if (
            self._runner.busy
            or self.fastboot_serial is None
            or self.phase != "ready_to_reboot"
        ):
            return
        self.phase = "rebooting"
        self._update_controls()
        self._runner.start((build_fastboot_reboot_step(self.fastboot_serial),))

    def shutdown(self) -> None:
        self.poll_timer.stop()
        self._runner.cancel()

    def append_log(self, text: str, timestamp: bool = True) -> None:
        if timestamp:
            text = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        self.log.append(text)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log.setTextCursor(cursor)

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Update Folder")
        if selected:
            self.set_update_folder(Path(selected))

    def _refresh_package_status(self) -> None:
        root = self._selected_folder
        if root is None:
            self._package = None
            self._update_controls()
            return

        boot = root / BOOT_IMAGE_NAME
        system = root / SYSTEM_IMAGE_NAME
        abl = root / ABL_IMAGE_NAME
        self.boot_status.setText(
            "Ready" if boot.is_file() else f"Missing: {BOOT_IMAGE_NAME}"
        )
        self.system_status.setText(
            "Ready" if system.is_file() else f"Missing: {SYSTEM_IMAGE_NAME}"
        )
        self.abl_status.setText(
            "Ready" if abl.is_file() else "Optional — skipped"
        )
        try:
            self._package = validate_update_package(root)
        except PackageValidationError:
            self._package = None
        self._update_controls()

    def _on_output(self, _channel: str, text: str) -> None:
        text = text.strip()
        if text:
            self.append_log(text, timestamp=False)

    def _on_step_finished(self, result: CommandResult) -> None:
        if self.phase not in {"entering", "flashing", "rebooting"}:
            return
        state = "SUCCESS" if result.success else "FAILED"
        self.append_log(f"{result.step.label}: {state}")
        if not result.success:
            self.append_log(self._failure_message(result), timestamp=False)

    def _on_queue_finished(self, queue_result: QueueResult) -> None:
        if queue_result.cancelled:
            self.phase = "idle"
            self._update_controls()
            return

        phase = self.phase
        if phase == "probing":
            self._handle_probe(queue_result)
        elif phase == "entering":
            self._handle_entering(queue_result)
        elif phase == "polling":
            self._handle_poll(queue_result)
        elif phase == "flashing":
            self._handle_flash(queue_result)
        elif phase == "rebooting":
            self._handle_reboot(queue_result)

    def _handle_probe(self, queue_result: QueueResult) -> None:
        result = self._single_result(queue_result)
        if result is None:
            self._fail_phase("Device detection returned no result.")
            return
        if not result.success:
            self._fail_phase(self._failure_message(result))
            return

        if self._probe_transport == "fastboot":
            if not parse_fastboot_devices(result.stdout):
                self.append_log("No Fastboot device found; checking ADB...")
                self._probe_transport = "adb"
                self._runner.start((build_device_list_step("adb"),))
                return
            try:
                self.fastboot_serial = require_single_fastboot_device(result.stdout)
            except DeviceSelectionError as error:
                self._fail_phase(str(error))
                return
            self.append_log(f"Using Fastboot device: {self.fastboot_serial}")
            self.phase = "idle"
            self._update_controls()
            return

        try:
            adb_serial = require_single_adb_device(result.stdout)
        except DeviceSelectionError as error:
            self._fail_phase(str(error))
            return
        self._expected_fastboot_serial = adb_serial
        self.phase = "entering"
        self.append_log(f"Using ADB device: {adb_serial}")
        self._update_controls()
        self._runner.start(build_enter_bootloader_steps(adb_serial))

    def _handle_entering(self, queue_result: QueueResult) -> None:
        if not queue_result.success:
            self._fail_phase(self._queue_failure(queue_result))
            return
        self.phase = "polling"
        self._poll_attempts = 0
        self.append_log("Waiting for Fastboot device...")
        self._update_controls()
        self._start_fastboot_poll()

    def _start_fastboot_poll(self) -> None:
        if self.phase != "polling" or self._runner.busy:
            return
        self._poll_attempts += 1
        self._runner.start((build_device_list_step("fastboot"),))

    def _handle_poll(self, queue_result: QueueResult) -> None:
        result = self._single_result(queue_result)
        if result is None or not result.success:
            message = (
                self._failure_message(result)
                if result is not None
                else "Fastboot detection returned no result."
            )
            self._fail_phase(message)
            return

        devices = parse_fastboot_devices(result.stdout)
        if not devices:
            if self._poll_attempts >= self.MAX_FASTBOOT_POLLS:
                self._fail_phase("No Fastboot device found after 10 attempts.")
            else:
                self.poll_timer.start(1000)
            return
        try:
            self.fastboot_serial = require_single_fastboot_device(
                result.stdout, self._expected_fastboot_serial
            )
        except DeviceSelectionError as error:
            self._fail_phase(str(error))
            return
        self.append_log(f"Using Fastboot device: {self.fastboot_serial}")
        self.phase = "idle"
        self._update_controls()

    def _handle_flash(self, queue_result: QueueResult) -> None:
        if queue_result.success:
            self.phase = "ready_to_reboot"
            self.append_log("FULL UPDATE SUCCESS. Device is ready to reboot.")
        else:
            self.phase = "idle"
            self.append_log(f"FULL UPDATE FAILED: {self._queue_failure(queue_result)}")
        self._update_controls()

    def _handle_reboot(self, queue_result: QueueResult) -> None:
        if queue_result.success:
            self.append_log("Device reboot command completed.")
            self.fastboot_serial = None
            self._expected_fastboot_serial = None
            self.phase = "idle"
        else:
            self.append_log(f"Reboot FAILED: {self._queue_failure(queue_result)}")
            self.phase = "ready_to_reboot"
        self._update_controls()

    def _fail_phase(self, message: str) -> None:
        self.append_log(f"FAILED: {message}")
        self.phase = "idle"
        self.fastboot_serial = None
        self._expected_fastboot_serial = None
        self._update_controls()

    def _update_controls(self) -> None:
        active = self.phase in {
            "probing",
            "entering",
            "polling",
            "flashing",
            "rebooting",
        }
        self.select_folder_button.setEnabled(not active)
        self.enter_mode_button.setEnabled(not active)
        self.update_button.setEnabled(
            not active
            and self._package is not None
            and self.fastboot_serial is not None
        )
        self.reboot_button.setEnabled(
            self.phase == "ready_to_reboot" and self.fastboot_serial is not None
        )

    @staticmethod
    def _single_result(queue_result: QueueResult) -> CommandResult | None:
        return queue_result.results[0] if queue_result.results else None

    @staticmethod
    def _failure_message(result: CommandResult) -> str:
        if result.process_error:
            return result.process_error
        if result.timed_out:
            return f"{result.step.label} timed out"
        return result.stderr.strip() or f"{result.step.label} exited {result.exit_code}"

    @classmethod
    def _queue_failure(cls, queue_result: QueueResult) -> str:
        for result in reversed(queue_result.results):
            if not result.success:
                return cls._failure_message(result)
        return "Operation did not complete"
