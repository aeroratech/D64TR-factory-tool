from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtGui import QShowEvent, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
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
from .configuration import (
    ConfigSelection,
    ConfigurationError,
    CurrentConfig,
    DEFAULT_BITRATE_BPS,
    DEFAULT_ENCODER,
    DEFAULT_ETHERNET_RANGE,
    DEFAULT_PREVIEW_MODE,
    bps_to_mbps,
    build_adb_reboot_step,
    build_config_apply_steps,
    build_config_read_steps,
    current_config_from_results,
)
from .devices import (
    DeviceSelectionError,
    build_device_list_step,
    require_single_adb_device,
)
from .runner import CommandRunner


class ConfigTab(QWidget):
    UVC_WARNING = (
        "UVC preview is unavailable when H.265 is configured. "
        "Use H.264 when UVC preview is required."
    )

    def __init__(
        self,
        runner_factory: Callable[[], CommandRunner] = CommandRunner,
    ) -> None:
        super().__init__()
        self.phase = "idle"
        self._pending_action: str | None = None
        self._pending_selection: ConfigSelection | None = None
        self._reboot_available = False
        self._initial_refresh_started = False

        self._runner = runner_factory()
        if self._runner.parent() is None:
            self._runner.setParent(self)
        self._runner.output_received.connect(self._on_output)
        self._runner.step_finished.connect(self._on_step_finished)
        self._runner.queue_finished.connect(self._on_queue_finished)

        self.ethernet_current = QLabel("Unknown")
        self.preview_current = QLabel("Unknown")
        self.bitrate_current = QLabel("Unknown")
        self.encoder_current = QLabel("Unknown")

        self.ethernet_combo = QComboBox()
        self.ethernet_combo.addItem("192.168.144.x", "144")
        self.ethernet_combo.addItem("192.168.199.x", "199")
        self.preview_combo = QComboBox()
        self.preview_combo.addItem("1920×1080 @ 30 fps", "1920x1080@30")
        self.preview_combo.addItem("1280×720 @ 30 fps", "1280x720@30")
        self.bitrate_edit = QLineEdit("10")
        self.bitrate_edit.setPlaceholderText("Mbps")
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItem("H.264", "h264")
        self.encoder_combo.addItem("H.265", "h265")

        self.ethernet_combo.setCurrentIndex(
            self.ethernet_combo.findData(DEFAULT_ETHERNET_RANGE)
        )
        self.preview_combo.setCurrentIndex(
            self.preview_combo.findData(DEFAULT_PREVIEW_MODE)
        )
        self.bitrate_edit.setText(bps_to_mbps(DEFAULT_BITRATE_BPS))
        self.encoder_combo.setCurrentIndex(
            self.encoder_combo.findData(DEFAULT_ENCODER)
        )

        self.ethernet_apply = QCheckBox("Apply")
        self.preview_apply = QCheckBox("Apply")
        self.bitrate_apply = QCheckBox("Apply")
        self.encoder_apply = QCheckBox("Apply")
        self.apply_checkboxes = [
            self.ethernet_apply,
            self.preview_apply,
            self.bitrate_apply,
            self.encoder_apply,
        ]

        settings_layout = QGridLayout()
        settings_layout.addWidget(QLabel("Setting"), 0, 0)
        settings_layout.addWidget(QLabel("Current"), 0, 1)
        settings_layout.addWidget(QLabel("New value"), 0, 2)
        rows = (
            (
                "Ethernet Range",
                self.ethernet_current,
                self.ethernet_combo,
                self.ethernet_apply,
            ),
            (
                "Preview Resolution",
                self.preview_current,
                self.preview_combo,
                self.preview_apply,
            ),
            (
                "Preview Bitrate (Mbps)",
                self.bitrate_current,
                self.bitrate_edit,
                self.bitrate_apply,
            ),
            (
                "Encoder",
                self.encoder_current,
                self.encoder_combo,
                self.encoder_apply,
            ),
        )
        for row, (title, current, editor, checkbox) in enumerate(rows, start=1):
            settings_layout.addWidget(QLabel(title), row, 0)
            settings_layout.addWidget(current, row, 1)
            settings_layout.addWidget(editor, row, 2)
            settings_layout.addWidget(checkbox, row, 3)

        self.encoder_warning = QLabel()
        self.encoder_warning.setWordWrap(True)
        self.encoder_warning.setStyleSheet("color: #b45f06;")
        settings_layout.addWidget(self.encoder_warning, 5, 0, 1, 4)

        self.settings_group = QGroupBox("Persistent Configuration")
        self.settings_group.setLayout(settings_layout)

        self.refresh_button = QPushButton("Refresh")
        self.apply_button = QPushButton("Apply Selected")
        self.reboot_button = QPushButton("Reboot Device")
        for button in (self.refresh_button, self.apply_button, self.reboot_button):
            button.setMinimumHeight(42)

        action_layout = QHBoxLayout()
        action_layout.addWidget(self.refresh_button)
        action_layout.addWidget(self.apply_button)
        action_layout.addWidget(self.reboot_button)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas; font-size: 14px;")

        layout = QVBoxLayout(self)
        layout.addWidget(self.settings_group)
        layout.addLayout(action_layout)
        layout.addWidget(self.log)

        self.ethernet_combo.currentIndexChanged.connect(
            lambda: self.ethernet_apply.setChecked(True)
        )
        self.preview_combo.currentIndexChanged.connect(
            lambda: self.preview_apply.setChecked(True)
        )
        self.bitrate_edit.textChanged.connect(
            lambda: self.bitrate_apply.setChecked(True)
        )
        self.encoder_combo.currentIndexChanged.connect(self._encoder_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.apply_button.clicked.connect(self.apply_selected)
        self.reboot_button.clicked.connect(self.reboot_device)
        self._update_encoder_warning()
        self._update_controls()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_refresh_started:
            self._initial_refresh_started = True
            QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        if self._runner.busy or self.phase != "idle":
            return
        self._start_probe("refresh")

    def apply_selected(self) -> None:
        if self._runner.busy or self.phase != "idle":
            return
        selection = self._selection_from_ui()
        try:
            build_config_apply_steps("validation", selection)
        except ConfigurationError as error:
            self.append_log(str(error))
            return
        self._pending_selection = selection
        self._start_probe("apply")

    def reboot_device(self) -> None:
        if (
            self._runner.busy
            or self.phase != "idle"
            or not self._reboot_available
        ):
            return
        self._start_probe("reboot")

    def shutdown(self) -> None:
        self._runner.cancel()

    def append_log(self, text: str, timestamp: bool = True) -> None:
        if timestamp:
            text = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        self.log.append(text)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log.setTextCursor(cursor)

    def _start_probe(self, action: str) -> None:
        self._pending_action = action
        self.phase = "probing"
        self.append_log(f"Detecting ADB device for {action}...")
        self._update_controls()
        self._runner.start((build_device_list_step("adb"),))

    def _selection_from_ui(self) -> ConfigSelection:
        return ConfigSelection(
            ethernet_range=(
                self.ethernet_combo.currentData()
                if self.ethernet_apply.isChecked()
                else None
            ),
            preview_mode=(
                self.preview_combo.currentData()
                if self.preview_apply.isChecked()
                else None
            ),
            bitrate_mbps=(
                self.bitrate_edit.text() if self.bitrate_apply.isChecked() else None
            ),
            encoder=(
                self.encoder_combo.currentData()
                if self.encoder_apply.isChecked()
                else None
            ),
        )

    def _encoder_changed(self) -> None:
        self.encoder_apply.setChecked(True)
        self._update_encoder_warning()

    def _update_encoder_warning(self) -> None:
        is_h265 = self.encoder_combo.currentData() == "h265"
        self.encoder_warning.setText(self.UVC_WARNING if is_h265 else "")
        self.encoder_warning.setVisible(is_h265)

    def _on_output(self, _channel: str, text: str) -> None:
        text = text.strip()
        if text and self.phase in {"applying", "rebooting"}:
            self.append_log(text, timestamp=False)

    def _on_step_finished(self, result: CommandResult) -> None:
        if self.phase == "applying":
            state = "SUCCESS" if result.success else "FAILED"
            self.append_log(f"{result.step.label}: {state}")
            if not result.success:
                self.append_log(self._failure_message(result), timestamp=False)
        elif self.phase == "rebooting" and not result.success:
            self.append_log(
                f"Reboot FAILED: {self._failure_message(result)}"
            )

    def _on_queue_finished(self, queue_result: QueueResult) -> None:
        if queue_result.cancelled:
            self._finish_action()
            return
        if self.phase == "probing":
            self._handle_probe(queue_result)
        elif self.phase == "reading":
            self._handle_read(queue_result)
        elif self.phase == "applying":
            self._handle_apply(queue_result)
        elif self.phase == "rebooting":
            self._handle_reboot(queue_result)

    def _handle_probe(self, queue_result: QueueResult) -> None:
        if not queue_result.results or not queue_result.results[0].success:
            message = (
                self._failure_message(queue_result.results[0])
                if queue_result.results
                else "ADB device detection returned no result"
            )
            self.append_log(f"FAILED: {message}")
            self._finish_action()
            return
        try:
            serial = require_single_adb_device(queue_result.results[0].stdout)
        except DeviceSelectionError as error:
            self.append_log(str(error))
            self._finish_action()
            return

        if self._pending_action == "refresh":
            self.phase = "reading"
            self._runner.start(build_config_read_steps(serial))
        elif self._pending_action == "apply" and self._pending_selection is not None:
            self.phase = "applying"
            self._runner.start(
                build_config_apply_steps(serial, self._pending_selection)
            )
        elif self._pending_action == "reboot":
            self.phase = "rebooting"
            self._runner.start((build_adb_reboot_step(serial),))
        else:
            self.append_log("FAILED: No pending configuration action")
            self._finish_action()

    def _handle_read(self, queue_result: QueueResult) -> None:
        current = current_config_from_results(queue_result.results)
        self._populate_current_config(current)
        if queue_result.success:
            self.append_log("Configuration refreshed.")
        else:
            self.append_log("Configuration refreshed with unavailable values.")
        self._finish_action()

    def _populate_current_config(self, current: CurrentConfig) -> None:
        self.ethernet_current.setText(current.ethernet_range or "Unknown")
        self.preview_current.setText(current.preview_mode or "Unknown")
        self.bitrate_current.setText(current.bitrate_bps or "Unknown")
        self.encoder_current.setText(current.encoder or "Unknown")

        blockers = [
            QSignalBlocker(self.ethernet_combo),
            QSignalBlocker(self.preview_combo),
            QSignalBlocker(self.bitrate_edit),
            QSignalBlocker(self.encoder_combo),
        ]
        self._set_combo_if_known(self.ethernet_combo, current.ethernet_range)
        self._set_combo_if_known(self.preview_combo, current.preview_mode)
        if current.bitrate_bps is not None:
            try:
                self.bitrate_edit.setText(bps_to_mbps(current.bitrate_bps))
            except ConfigurationError:
                pass
        self._set_combo_if_known(self.encoder_combo, current.encoder)
        del blockers

        for checkbox in self.apply_checkboxes:
            checkbox.setChecked(False)
        self._update_encoder_warning()

    @staticmethod
    def _set_combo_if_known(combo: QComboBox, value: str | None) -> None:
        if value is None:
            return
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _handle_apply(self, queue_result: QueueResult) -> None:
        if queue_result.success:
            for checkbox in self.apply_checkboxes:
                checkbox.setChecked(False)
            self._reboot_available = True
            self.append_log(
                "Configuration applied and synced. Reboot to activate changes."
            )
        else:
            self.append_log(
                "Configuration batch incomplete. Refresh before retrying."
            )
        self._finish_action()

    def _handle_reboot(self, queue_result: QueueResult) -> None:
        if queue_result.success:
            self._reboot_available = False
            self.append_log("Device reboot command completed.")
        else:
            self.append_log(
                f"Reboot FAILED: {self._queue_failure(queue_result)}"
            )
        self._finish_action()

    def _finish_action(self) -> None:
        self.phase = "idle"
        self._pending_action = None
        self._pending_selection = None
        self._update_controls()

    def _update_controls(self) -> None:
        active = self.phase != "idle"
        self.settings_group.setEnabled(not active)
        self.refresh_button.setEnabled(not active)
        self.apply_button.setEnabled(not active)
        self.reboot_button.setEnabled(not active and self._reboot_available)

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
