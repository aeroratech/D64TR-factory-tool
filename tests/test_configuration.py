import pytest

from d64tr_factory_tool.commands import CommandResult
from d64tr_factory_tool.configuration import (
    ConfigSelection,
    ConfigurationError,
    bps_to_mbps,
    build_adb_reboot_step,
    build_config_apply_steps,
    build_config_read_steps,
    current_config_from_results,
    mbps_to_bps,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("10", "10000000"), (" 2.5 ", "2500000"), ("0.000001", "1")],
)
def test_mbps_to_bps_uses_exact_decimal_conversion(text, expected):
    assert mbps_to_bps(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"), [("10000000", "10"), ("2500000", "2.5")]
)
def test_bps_to_mbps_returns_concise_display_value(text, expected):
    assert bps_to_mbps(text) == expected


@pytest.mark.parametrize(
    "text", ["", "abc", "0", "-1", "NaN", "Infinity", "0.0000001"]
)
def test_mbps_to_bps_rejects_invalid_or_sub_bps_values(text):
    with pytest.raises(ConfigurationError):
        mbps_to_bps(text)


@pytest.mark.parametrize("text", ["", "abc", "0", "-1", "2.5", "NaN"])
def test_bps_to_mbps_rejects_invalid_device_values(text):
    with pytest.raises(ConfigurationError):
        bps_to_mbps(text)


def test_apply_plan_contains_selected_properties_in_ui_order_and_one_sync():
    selection = ConfigSelection(
        ethernet_range="144", bitrate_mbps="2.5", encoder="h265"
    )

    steps = build_config_apply_steps("SER", selection)

    assert [step.arguments[-2:] for step in steps[:-1]] == [
        ("persist.eth0.ip.range", "144"),
        ("persist.video.preview.bitrate", "2500000"),
        ("persist.video.preview.encoder", "h265"),
    ]
    assert [step.key for step in steps] == [
        "set-ethernet",
        "set-bitrate",
        "set-encoder",
        "sync",
    ]
    assert steps[-1].arguments == ("-s", "SER", "shell", "sync")


def test_apply_plan_with_all_settings_uses_documented_values():
    selection = ConfigSelection(
        ethernet_range="199",
        preview_mode="1280x720@30",
        bitrate_mbps="10",
        encoder="h264",
    )

    steps = build_config_apply_steps("SER", selection)

    assert [step.arguments for step in steps] == [
        (
            "-s",
            "SER",
            "shell",
            "setprop",
            "persist.eth0.ip.range",
            "199",
        ),
        (
            "-s",
            "SER",
            "shell",
            "setprop",
            "persist.video.preview.mode",
            "1280x720@30",
        ),
        (
            "-s",
            "SER",
            "shell",
            "setprop",
            "persist.video.preview.bitrate",
            "10000000",
        ),
        (
            "-s",
            "SER",
            "shell",
            "setprop",
            "persist.video.preview.encoder",
            "h264",
        ),
        ("-s", "SER", "shell", "sync"),
    ]


def test_apply_plan_rejects_empty_selection_before_building_commands():
    with pytest.raises(ConfigurationError, match="Select at least one"):
        build_config_apply_steps("SER", ConfigSelection())


@pytest.mark.parametrize(
    "selection",
    [
        ConfigSelection(ethernet_range="200"),
        ConfigSelection(preview_mode="4k"),
        ConfigSelection(encoder="av1"),
    ],
)
def test_apply_plan_rejects_undocumented_choice_values(selection):
    with pytest.raises(ConfigurationError):
        build_config_apply_steps("SER", selection)


def test_read_plan_has_documented_properties_in_ui_order():
    steps = build_config_read_steps("SER")

    assert [step.key for step in steps] == [
        "read-ethernet",
        "read-preview",
        "read-bitrate",
        "read-encoder",
    ]
    assert [step.arguments[-1] for step in steps] == [
        "persist.eth0.ip.range",
        "persist.video.preview.mode",
        "persist.video.preview.bitrate",
        "persist.video.preview.encoder",
    ]
    assert all(step.continue_on_error for step in steps)


def test_current_config_uses_default_for_empty_value_and_keeps_failures_unknown():
    steps = build_config_read_steps("SER")
    results = (
        CommandResult(steps[0], 0, " 199\n", ""),
        CommandResult(steps[1], 0, "", ""),
        CommandResult(steps[2], 1, "", "permission denied"),
        CommandResult(steps[3], 0, "h264\n", ""),
    )

    current = current_config_from_results(results)

    assert current.ethernet_range == "199"
    assert current.preview_mode == "1280x720@30"
    assert current.bitrate_bps is None
    assert current.encoder == "h264"


def test_current_config_uses_device_defaults_when_all_properties_are_empty():
    steps = build_config_read_steps("SER")
    results = tuple(CommandResult(step, 0, "\n", "") for step in steps)

    current = current_config_from_results(results)

    assert current.ethernet_range == "199"
    assert current.preview_mode == "1280x720@30"
    assert current.bitrate_bps == "2000000"
    assert current.encoder == "h264"


def test_current_config_uses_step_keys_not_result_position():
    steps = build_config_read_steps("SER")
    encoder = CommandResult(steps[3], 0, "h265", "")
    ethernet = CommandResult(steps[0], 0, "144", "")

    current = current_config_from_results((encoder, ethernet))

    assert current.ethernet_range == "144"
    assert current.encoder == "h265"
    assert current.preview_mode is None


def test_adb_reboot_step_targets_serial():
    step = build_adb_reboot_step("SER")

    assert step.program == "adb"
    assert step.arguments == ("-s", "SER", "reboot")
