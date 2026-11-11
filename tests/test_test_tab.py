import pytest

from d64tr_factory_tool.runner import CommandRunner
from d64tr_factory_tool.test_tab import TestTab as DeviceTestTab
from tests.fakes import FakeProcessFactory


@pytest.fixture
def setup_tab(qtbot):
    processes = FakeProcessFactory()
    tab = DeviceTestTab(
        runner_factory=lambda: CommandRunner(process_factory=processes)
    )
    qtbot.addWidget(tab)
    return tab, processes


def start_sdcard_test(tab, processes):
    tab.sdcard_button.click()
    processes.finish_current(0, "List of devices attached\nSERIAL\tdevice\n")


def test_sdcard_pass_requires_mount_and_successful_write_read(setup_tab):
    tab, processes = setup_tab
    assert tab.log.isReadOnly()
    start_sdcard_test(tab, processes)
    assert processes.started[-1] == (
        "adb", ("-s", "SERIAL", "shell", "mount | grep /mnt/sdcard")
    )
    assert not tab.sdcard_button.isEnabled()
    assert tab.sdcard_result_label.text() == ""

    processes.finish_current(0, "/dev/mmcblk1p1 on /mnt/sdcard type vfat\n")
    assert processes.started[-1] == (
        "adb", ("-s", "SERIAL", "shell",
                "echo TEST_OK > /mnt/sdcard/test.tmp && "
                "grep TEST_OK /mnt/sdcard/test.tmp && rm /mnt/sdcard/test.tmp")
    )
    assert tab.sdcard_result_label.text() == ""
    processes.finish_current(0, "TEST_OK\n")

    assert tab.sdcard_result_label.text() == "✓"
    assert "green" in tab.sdcard_result_label.styleSheet()
    assert "SDCard FUNCTION TEST PASS" in tab.log.toPlainText()
    assert tab.sdcard_button.isEnabled()
    tab.sdcard_button.click()
    assert tab.sdcard_result_label.text() == ""


@pytest.mark.parametrize("exit_code,output", [(1, ""), (0, ""), (1, "error")])
def test_missing_mount_stops_before_write(setup_tab, exit_code, output):
    tab, processes = setup_tab
    start_sdcard_test(tab, processes)
    processes.finish_current(exit_code, output)
    assert len(processes.started) == 2
    assert tab.sdcard_result_label.text() == "✗"
    assert "SDCard NOT detected" in tab.log.toPlainText()
    assert tab.sdcard_button.isEnabled()


def test_write_failure_marks_red_result_and_logs_error(setup_tab):
    tab, processes = setup_tab
    start_sdcard_test(tab, processes)
    processes.finish_current(0, "/dev/mmcblk1p1 on /mnt/sdcard\n")
    processes.finish_current(1, stderr="Read-only file system")
    assert tab.sdcard_result_label.text() == "✗"
    assert "red" in tab.sdcard_result_label.styleSheet()
    assert "Read-only file system" in tab.log.toPlainText()
    assert "SDCard FUNCTION TEST FAIL" in tab.log.toPlainText()


@pytest.mark.parametrize("output", ["", "A\tdevice\nB\tdevice\n", "A\tunauthorized\n"])
def test_no_unambiguous_device_does_not_run_test(setup_tab, output):
    tab, processes = setup_tab
    tab.sdcard_button.click()
    processes.finish_current(0, output)
    assert len(processes.started) == 1
    assert tab.sdcard_result_label.text() == "✗"
    assert tab.sdcard_button.isEnabled()


@pytest.mark.parametrize("phase", ["probe", "mount", "write"])
def test_process_launch_failure_marks_failed_and_allows_retry(setup_tab, phase):
    tab, processes = setup_tab
    tab.sdcard_button.click()
    if phase != "probe":
        processes.finish_current(0, "SERIAL\tdevice\n")
    if phase == "write":
        processes.finish_current(0, "/dev/mmcblk1p1 on /mnt/sdcard\n")
    processes.fail_current_to_start("adb unavailable")
    assert tab.sdcard_result_label.text() == "✗"
    assert "adb unavailable" in tab.log.toPlainText()
    assert tab.sdcard_button.isEnabled()


def test_shutdown_cancels_test_and_ignores_late_completion(setup_tab):
    tab, processes = setup_tab
    start_sdcard_test(tab, processes)
    process = processes.current
    tab.shutdown()
    process.finish(0, "/dev/mmcblk1p1 on /mnt/sdcard\n")
    assert process.terminated
    assert len(processes.started) == 2
    assert tab.sdcard_result_label.text() == ""
    assert not tab.sdcard_button.isEnabled()
