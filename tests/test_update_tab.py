from pathlib import Path

import pytest

from d64tr_factory_tool.update import ABL_IMAGE_NAME, BOOT_IMAGE_NAME, SYSTEM_IMAGE_NAME
from d64tr_factory_tool.update_tab import UpdateTab
from tests.fakes import FakeRunnerFactory


def create_package(root: Path, include_abl: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / BOOT_IMAGE_NAME).touch()
    (root / SYSTEM_IMAGE_NAME).touch()
    if include_abl:
        (root / ABL_IMAGE_NAME).touch()
    return root


@pytest.fixture
def fake_runner_factory():
    return FakeRunnerFactory()


@pytest.fixture
def tab(qtbot, fake_runner_factory):
    widget = UpdateTab(runner_factory=fake_runner_factory)
    qtbot.addWidget(widget)
    return widget


def detect_fastboot(tab, factory, output="SER\tfastboot\n"):
    tab.enter_mode_button.click()
    factory.current.finish(((0, output, ""),))


def test_update_tab_disables_update_for_missing_required_image(tab, tmp_path):
    tab.set_update_folder(tmp_path)

    assert not tab.update_button.isEnabled()
    assert "Missing" in tab.boot_status.text()
    assert "Missing" in tab.system_status.text()


def test_update_tab_allows_missing_optional_abl_after_fastboot_detection(
    tab, fake_runner_factory, tmp_path
):
    tab.set_update_folder(create_package(tmp_path))
    detect_fastboot(tab, fake_runner_factory)

    assert "Optional" in tab.abl_status.text()
    assert tab.update_button.isEnabled()


def test_enter_mode_uses_existing_fastboot_device_without_adb_reboot(
    tab, fake_runner_factory
):
    detect_fastboot(tab, fake_runner_factory)

    assert [queue[0].program for queue in fake_runner_factory.current.started] == [
        "fastboot"
    ]
    assert tab.fastboot_serial == "SER"


def test_enter_mode_falls_back_to_root_wait_reboot_and_starts_polling(
    tab, fake_runner_factory
):
    tab.enter_mode_button.click()
    fake_runner_factory.current.finish(((0, "", ""),))

    assert fake_runner_factory.current.started[-1][0].program == "adb"
    fake_runner_factory.current.finish(
        ((0, "List of devices attached\nSER\tdevice\n", ""),)
    )
    assert [step.arguments for step in fake_runner_factory.current.started[-1]] == [
        ("-s", "SER", "root"),
        ("-s", "SER", "wait-for-device"),
        ("-s", "SER", "reboot", "bootloader"),
    ]

    fake_runner_factory.current.finish(
        ((0, "", ""), (0, "", ""), (0, "", ""))
    )
    assert fake_runner_factory.current.started[-1][0].program == "fastboot"
    assert tab.phase == "polling"


def test_flash_failure_stops_plan_and_never_enables_reboot(
    tab, fake_runner_factory, tmp_path
):
    tab.set_update_folder(create_package(tmp_path, include_abl=True))
    detect_fastboot(tab, fake_runner_factory)
    tab.update_button.click()

    assert fake_runner_factory.current.current_steps[0].key == "flash-abl-a"
    fake_runner_factory.current.finish(((1, "", "flash failed"),))

    assert not tab.reboot_button.isEnabled()
    assert "abl_a" in tab.log.toPlainText()
    assert "FAILED" in tab.log.toPlainText()


def test_successful_full_flash_enables_reboot_and_logs_optional_abl_skip(
    tab, fake_runner_factory, tmp_path
):
    tab.set_update_folder(create_package(tmp_path))
    detect_fastboot(tab, fake_runner_factory)
    tab.update_button.click()

    fake_runner_factory.current.finish(
        ((0, "boot ok", ""), (0, "system ok", ""))
    )

    assert tab.reboot_button.isEnabled()
    assert "ABL image not present; skipped" in tab.log.toPlainText()
    assert "FULL UPDATE SUCCESS" in tab.log.toPlainText()


def test_multiple_fastboot_devices_never_start_destructive_queue(
    tab, fake_runner_factory
):
    detect_fastboot(tab, fake_runner_factory, "A\tfastboot\nB\tfastboot\n")

    assert "Multiple Fastboot devices" in tab.log.toPlainText()
    assert len(fake_runner_factory.current.started) == 1
    assert tab.enter_mode_button.isEnabled()


def test_missing_fastboot_executable_restores_controls(tab, fake_runner_factory):
    tab.enter_mode_button.click()
    fake_runner_factory.current.fail_to_start("fastboot was not found")

    assert tab.enter_mode_button.isEnabled()
    assert "fastboot was not found" in tab.log.toPlainText()


def test_update_revalidates_package_before_flashing(
    tab, fake_runner_factory, tmp_path
):
    root = create_package(tmp_path)
    tab.set_update_folder(root)
    detect_fastboot(tab, fake_runner_factory)
    (root / SYSTEM_IMAGE_NAME).unlink()

    tab.update_button.click()

    assert "Missing required update files" in tab.log.toPlainText()
    assert fake_runner_factory.current.busy is False
    assert not tab.update_button.isEnabled()


def test_reboot_success_clears_selected_fastboot_device(
    tab, fake_runner_factory, tmp_path
):
    tab.set_update_folder(create_package(tmp_path))
    detect_fastboot(tab, fake_runner_factory)
    tab.update_button.click()
    fake_runner_factory.current.finish(((0, "", ""), (0, "", "")))

    tab.reboot_button.click()
    assert fake_runner_factory.current.current_steps[0].arguments == (
        "-s",
        "SER",
        "reboot",
    )
    fake_runner_factory.current.finish(((0, "", ""),))

    assert tab.fastboot_serial is None
    assert not tab.update_button.isEnabled()
    assert not tab.reboot_button.isEnabled()


def test_shutdown_cancels_runner_and_poll_timer(tab, fake_runner_factory):
    tab.enter_mode_button.click()
    tab.poll_timer.start(1000)

    tab.shutdown()

    assert fake_runner_factory.current.cancelled
    assert not tab.poll_timer.isActive()
