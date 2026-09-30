import pytest

from d64tr_factory_tool.commands import CommandResult, CommandStep, QueueResult
from d64tr_factory_tool.devices import (
    DeviceSelectionError,
    build_device_list_step,
    parse_adb_devices,
    parse_fastboot_devices,
    require_single_adb_device,
    require_single_fastboot_device,
)


def test_parse_adb_devices_preserves_noneligible_states_and_ignores_chatter():
    output = (
        "* daemon started successfully *\r\n"
        "List of devices attached\r\n"
        "ABC\tdevice\r\n"
        "BAD\tunauthorized\r\n"
        "OFF\toffline\r\n\r\n"
    )

    assert [(item.serial, item.state) for item in parse_adb_devices(output)] == [
        ("ABC", "device"),
        ("BAD", "unauthorized"),
        ("OFF", "offline"),
    ]


def test_require_single_adb_device_rejects_no_eligible_device():
    with pytest.raises(DeviceSelectionError, match="No eligible ADB device"):
        require_single_adb_device("List of devices attached\nBAD\tunauthorized\n")


def test_require_single_adb_device_rejects_multiple_eligible_devices():
    with pytest.raises(DeviceSelectionError, match="Multiple ADB devices"):
        require_single_adb_device(
            "List of devices attached\nA\tdevice\nB\tdevice\n"
        )


def test_require_single_adb_device_returns_only_eligible_serial():
    output = "List of devices attached\nGOOD\tdevice\nBAD\toffline\n"

    assert require_single_adb_device(output) == "GOOD"


def test_parse_fastboot_devices_ignores_blank_and_malformed_lines():
    output = "ABC\tfastboot\r\n\r\nmalformed\nDEF\tfastboot\r\n"

    assert parse_fastboot_devices(output) == ("ABC", "DEF")


def test_require_single_fastboot_device_enforces_expected_serial():
    assert require_single_fastboot_device("ABC\tfastboot\r\n", "ABC") == "ABC"

    with pytest.raises(DeviceSelectionError, match="expected ABC"):
        require_single_fastboot_device("OTHER\tfastboot\n", "ABC")


def test_require_single_fastboot_device_rejects_multiple_devices():
    with pytest.raises(DeviceSelectionError, match="Multiple Fastboot devices"):
        require_single_fastboot_device("A\tfastboot\nB\tfastboot\n")


def test_device_list_steps_are_argument_arrays():
    adb_step = build_device_list_step("adb")
    fastboot_step = build_device_list_step("fastboot")

    assert adb_step.program == "adb"
    assert adb_step.arguments == ("devices",)
    assert fastboot_step.program == "fastboot"
    assert fastboot_step.arguments == ("devices",)


def test_device_list_step_rejects_unknown_transport():
    with pytest.raises(ValueError, match="Unsupported transport"):
        build_device_list_step("serial")


def test_queue_result_success_requires_every_result_to_succeed():
    step = CommandStep("probe", "Probe", "adb", ("devices",))
    success = CommandResult(step, 0, "", "")
    failure = CommandResult(step, 1, "", "failed")

    assert QueueResult((success,)).success is True
    assert QueueResult((success, failure)).success is False
    assert QueueResult((success,), cancelled=True).success is False
