import pytest
from PySide6.QtCore import Qt

from d64tr_factory_tool.info_tab import InfoTab
from tests.fakes import FakeRunnerFactory


@pytest.fixture
def fake_runner_factory():
    return FakeRunnerFactory()


@pytest.fixture
def tab(qtbot, fake_runner_factory):
    widget = InfoTab(runner_factory=fake_runner_factory)
    qtbot.addWidget(widget)
    return widget


def finish_adb_probe(fake_runner_factory, output):
    fake_runner_factory.current.finish(((0, output, ""),))


def test_info_tab_has_refresh_clear_and_read_only_log(tab):
    assert tab.refresh_button.text() == "Refresh"
    assert tab.clear_button.text() == "Clear"
    assert tab.log.isReadOnly()


def test_refresh_detects_device_before_reading_versions(
    tab, fake_runner_factory, qtbot
):
    qtbot.mouseClick(tab.refresh_button, Qt.LeftButton)

    probe = fake_runner_factory.current.started[-1]
    assert [(step.program, step.arguments) for step in probe] == [
        ("adb", ("devices",))
    ]
    assert not tab.refresh_button.isEnabled()

    finish_adb_probe(
        fake_runner_factory,
        "List of devices attached\nSERIAL\tdevice\n",
    )
    version_steps = fake_runner_factory.current.started[-1]
    assert version_steps[0].arguments[:2] == ("-s", "SERIAL")
    assert version_steps[1].arguments[:2] == ("-s", "SERIAL")


def test_info_tab_reports_one_failed_read_and_the_other_result(
    tab, fake_runner_factory
):
    tab.refresh_button.click()
    finish_adb_probe(
        fake_runner_factory,
        "List of devices attached\nSERIAL\tdevice\n",
    )
    fake_runner_factory.current.finish(
        (
            (1, "", "cat: missing"),
            (0, "gimbal-1.2\n", ""),
        )
    )

    text = tab.log.toPlainText()
    assert "Camera Version" in text
    assert "FAILED" in text
    assert "Gimbal Version" in text
    assert "gimbal-1.2" in text
    assert tab.refresh_button.isEnabled()


def test_device_selection_error_is_reported_and_does_not_read_versions(
    tab, fake_runner_factory
):
    tab.refresh_button.click()
    finish_adb_probe(
        fake_runner_factory,
        "List of devices attached\nA\tdevice\nB\tdevice\n",
    )

    assert len(fake_runner_factory.current.started) == 1
    assert "Multiple ADB devices" in tab.log.toPlainText()
    assert tab.refresh_button.isEnabled()


def test_clear_removes_log_without_contacting_device(tab, fake_runner_factory):
    tab.append_log("local text")
    tab.clear_button.click()

    assert tab.log.toPlainText() == ""
    assert fake_runner_factory.current.started == []


def test_shutdown_cancels_active_runner(tab, fake_runner_factory):
    tab.refresh_button.click()
    tab.shutdown()

    assert fake_runner_factory.current.cancelled is True
