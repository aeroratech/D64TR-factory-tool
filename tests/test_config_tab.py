import pytest

from d64tr_factory_tool.config_tab import ConfigTab
from tests.fakes import FakeRunnerFactory


@pytest.fixture
def fake_runner_factory():
    return FakeRunnerFactory()


@pytest.fixture
def tab(qtbot, fake_runner_factory):
    widget = ConfigTab(runner_factory=fake_runner_factory)
    qtbot.addWidget(widget)
    return widget


def set_combo_data(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def finish_device_probe(factory, serial="SER"):
    factory.current.finish(
        ((0, f"List of devices attached\n{serial}\tdevice\n", ""),)
    )


def start_and_finish_refresh(
    tab,
    factory,
    ethernet="199",
    mode="1280x720@30",
    bitrate="2500000",
    encoder="h264",
):
    tab.refresh()
    finish_device_probe(factory)
    factory.current.finish(
        (
            (0, ethernet, ""),
            (0, mode, ""),
            (0, bitrate, ""),
            (0, encoder, ""),
        )
    )


def test_config_tab_has_four_apply_rows_and_manual_reboot(tab):
    assert [box.text() for box in tab.apply_checkboxes] == ["Apply"] * 4
    assert tab.apply_button.text() == "Apply Selected"
    assert tab.reboot_button.text() == "Reboot Device"
    assert not tab.reboot_button.isEnabled()


def test_user_edit_automatically_checks_only_that_row(tab):
    tab.bitrate_edit.setText("2.5")

    assert tab.bitrate_apply.isChecked()
    assert not tab.encoder_apply.isChecked()


def test_refresh_populates_known_values_without_selecting_them(
    tab, fake_runner_factory
):
    start_and_finish_refresh(tab, fake_runner_factory)

    assert tab.ethernet_combo.currentData() == "199"
    assert tab.preview_combo.currentData() == "1280x720@30"
    assert tab.bitrate_edit.text() == "2.5"
    assert tab.encoder_combo.currentData() == "h264"
    assert all(not box.isChecked() for box in tab.apply_checkboxes)


def test_refresh_displays_unknown_raw_value_without_overwriting_editor(
    tab, fake_runner_factory
):
    original = tab.preview_combo.currentData()
    start_and_finish_refresh(tab, fake_runner_factory, mode="custom-mode")

    assert tab.preview_current.text() == "custom-mode"
    assert tab.preview_combo.currentData() == original
    assert not tab.preview_apply.isChecked()


def test_h265_selection_shows_exact_uvc_warning(tab):
    set_combo_data(tab.encoder_combo, "h265")

    assert "UVC preview is unavailable" in tab.encoder_warning.text()


def test_first_show_starts_one_refresh_but_reshow_does_not(
    tab, fake_runner_factory, qtbot
):
    tab.show()
    qtbot.waitUntil(lambda: fake_runner_factory.device_probe_count == 1)
    finish_device_probe(fake_runner_factory)
    fake_runner_factory.current.finish(
        ((0, "144", ""), (0, "1920x1080@30", ""), (0, "10000000", ""), (0, "h264", ""))
    )

    tab.hide()
    tab.show()
    qtbot.wait(0)

    assert fake_runner_factory.device_probe_count == 1


def test_invalid_checked_bitrate_starts_no_device_command(
    tab, fake_runner_factory
):
    tab.bitrate_edit.setText("not-a-number")
    tab.apply_button.click()

    assert fake_runner_factory.current.started == []
    assert "valid positive bitrate" in tab.log.toPlainText()


def test_empty_selection_starts_no_apply_queue(tab, fake_runner_factory):
    tab.apply_button.click()

    assert fake_runner_factory.current.started == []
    assert "Select at least one setting" in tab.log.toPlainText()


def test_selected_subset_stops_before_sync_on_failure(
    tab, fake_runner_factory
):
    set_combo_data(tab.ethernet_combo, "199")
    set_combo_data(tab.encoder_combo, "h265")
    tab.apply_button.click()
    finish_device_probe(fake_runner_factory)

    assert [step.key for step in fake_runner_factory.current.current_steps] == [
        "set-ethernet",
        "set-encoder",
        "sync",
    ]
    fake_runner_factory.current.finish(
        ((0, "", ""), (1, "", "permission denied"))
    )

    assert fake_runner_factory.current.executed_step_keys[-2:] == [
        "set-ethernet",
        "set-encoder",
    ]
    assert "Refresh before retrying" in tab.log.toPlainText()


def test_apply_success_clears_selection_and_enables_manual_reboot(
    tab, fake_runner_factory
):
    set_combo_data(tab.ethernet_combo, "199")
    tab.apply_button.click()
    finish_device_probe(fake_runner_factory)
    fake_runner_factory.current.finish(((0, "", ""), (0, "", "")))

    assert all(not box.isChecked() for box in tab.apply_checkboxes)
    assert tab.reboot_button.isEnabled()
    assert len(fake_runner_factory.current.started) == 2

    tab.bitrate_edit.setText("12")
    assert tab.reboot_button.isEnabled()
    assert tab.bitrate_apply.isChecked()


def test_reboot_resolves_and_targets_the_current_adb_serial(
    tab, fake_runner_factory
):
    set_combo_data(tab.ethernet_combo, "199")
    tab.apply_button.click()
    finish_device_probe(fake_runner_factory)
    fake_runner_factory.current.finish(((0, "", ""), (0, "", "")))

    tab.reboot_button.click()
    finish_device_probe(fake_runner_factory, "NEW-SERIAL")

    assert fake_runner_factory.current.current_steps[-1].arguments == (
        "-s",
        "NEW-SERIAL",
        "reboot",
    )


def test_apply_device_selection_error_restores_controls(tab, fake_runner_factory):
    set_combo_data(tab.ethernet_combo, "199")
    tab.apply_button.click()
    fake_runner_factory.current.finish(
        ((0, "List of devices attached\nA\tdevice\nB\tdevice\n", ""),)
    )

    assert "Multiple ADB devices" in tab.log.toPlainText()
    assert tab.apply_button.isEnabled()


def test_shutdown_cancels_active_runner(tab, fake_runner_factory):
    tab.refresh()
    tab.shutdown()

    assert fake_runner_factory.current.cancelled is True
