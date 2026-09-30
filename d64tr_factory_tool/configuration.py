from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .commands import CommandResult, CommandStep


ETHERNET_PROPERTY = "persist.eth0.ip.range"
PREVIEW_PROPERTY = "persist.video.preview.mode"
BITRATE_PROPERTY = "persist.video.preview.bitrate"
ENCODER_PROPERTY = "persist.video.preview.encoder"
WESTON_CONFIG_PATH = "/etc/xdg/weston/weston.ini"

DEFAULT_ETHERNET_RANGE = "199"
DEFAULT_PREVIEW_MODE = "1280x720@30"
DEFAULT_BITRATE_BPS = "2000000"
DEFAULT_ENCODER = "h264"
DEFAULT_TRANSFORM = "normal"

# These match the target services' runtime fallbacks when a property is unset.
_READ_DEFAULTS = {
    "read-ethernet": DEFAULT_ETHERNET_RANGE,
    "read-preview": DEFAULT_PREVIEW_MODE,
    "read-bitrate": DEFAULT_BITRATE_BPS,
    "read-encoder": DEFAULT_ENCODER,
    "read-transform": DEFAULT_TRANSFORM,
}

_WESTON_TRANSFORM_READ_SCRIPT = r"""awk '
BEGIN { in_streaming = 0; found_section = 0 }
/^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
    if (in_streaming) exit
    in_streaming = ($0 ~ /^[[:space:]]*\[streaming-output\][[:space:]]*$/)
    if (in_streaming) found_section = 1
    next
}
in_streaming && /^[[:space:]]*transform[[:space:]]*=/ {
    value = $0
    sub(/^[^=]*=[[:space:]]*/, "", value)
    sub(/[[:space:]]*$/, "", value)
    print value
    exit
}
END { if (!found_section) exit 42 }
' "$1"
""".strip()

_WESTON_TRANSFORM_UPDATE_SCRIPT = r"""file=$1
value=$2
tmp="${file}.factory-tool.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
awk -v value="$value" '
BEGIN { in_streaming = 0; found_section = 0; wrote = 0 }
function write_transform() {
    if (!wrote) {
        print "transform=" value
        wrote = 1
    }
}
/^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
    if (in_streaming) write_transform()
    in_streaming = ($0 ~ /^[[:space:]]*\[streaming-output\][[:space:]]*$/)
    if (in_streaming) {
        found_section = 1
        wrote = 0
    }
}
in_streaming && /^[[:space:]]*transform[[:space:]]*=/ {
    write_transform()
    next
}
{ print }
END {
    if (in_streaming) write_transform()
    if (!found_section) exit 42
}
' "$file" > "$tmp" || exit $?
cat "$tmp" > "$file"
""".strip()


@dataclass(frozen=True)
class ConfigSelection:
    ethernet_range: str | None = None
    preview_mode: str | None = None
    bitrate_mbps: str | None = None
    encoder: str | None = None
    transform: str | None = None


@dataclass(frozen=True)
class CurrentConfig:
    ethernet_range: str | None = None
    preview_mode: str | None = None
    bitrate_bps: str | None = None
    encoder: str | None = None
    transform: str | None = None


class ConfigurationError(ValueError):
    """Raised when selected configuration cannot be safely applied."""


def _remote_sh_command(script: str, *arguments: str) -> str:
    return shlex.join(("sh", "-c", script, "factory-tool", *arguments))


def _positive_decimal(text: str, unit: str) -> Decimal:
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError):
        raise ConfigurationError(f"Enter a valid positive {unit} value") from None
    if not value.is_finite() or value <= 0:
        raise ConfigurationError(f"Enter a valid positive {unit} value")
    return value


def mbps_to_bps(text: str) -> str:
    value = _positive_decimal(text, "bitrate")
    bps = value * Decimal("1000000")
    if bps != bps.to_integral_value():
        raise ConfigurationError(
            "Bitrate must convert to a whole number of bits per second"
        )
    return format(bps.to_integral_value(), "f")


def bps_to_mbps(text: str) -> str:
    value = _positive_decimal(text, "device bitrate")
    if value != value.to_integral_value():
        raise ConfigurationError("Device bitrate must be a whole number")
    mbps = value / Decimal("1000000")
    return format(mbps.normalize(), "f")


def build_weston_transform_read_step(
    serial: str, config_path: str = WESTON_CONFIG_PATH
) -> CommandStep:
    return CommandStep(
        "read-transform",
        "Reading preview transform",
        "adb",
        (
            "-s",
            serial,
            "shell",
            _remote_sh_command(_WESTON_TRANSFORM_READ_SCRIPT, config_path),
        ),
        continue_on_error=True,
    )


def build_weston_transform_step(
    serial: str,
    transform: str,
    config_path: str = WESTON_CONFIG_PATH,
) -> CommandStep:
    if transform not in {"normal", "180"}:
        raise ConfigurationError("Transform must be normal or 180")
    return CommandStep(
        "set-transform",
        "Applying preview transform",
        "adb",
        (
            "-s",
            serial,
            "shell",
            _remote_sh_command(
                _WESTON_TRANSFORM_UPDATE_SCRIPT, config_path, transform
            ),
        ),
    )


def build_config_read_steps(serial: str) -> tuple[CommandStep, ...]:
    settings = (
        ("read-ethernet", "Reading Ethernet range", ETHERNET_PROPERTY),
        ("read-preview", "Reading preview resolution", PREVIEW_PROPERTY),
        ("read-bitrate", "Reading preview bitrate", BITRATE_PROPERTY),
        ("read-encoder", "Reading preview encoder", ENCODER_PROPERTY),
    )
    property_steps = tuple(
        CommandStep(
            key,
            label,
            "adb",
            ("-s", serial, "shell", "getprop", property_name),
            continue_on_error=True,
        )
        for key, label, property_name in settings
    )
    return property_steps + (build_weston_transform_read_step(serial),)


def current_config_from_results(results: Sequence[CommandResult]) -> CurrentConfig:
    values: dict[str, str | None] = {
        "read-ethernet": None,
        "read-preview": None,
        "read-bitrate": None,
        "read-encoder": None,
        "read-transform": None,
    }
    for result in results:
        if result.step.key in values and result.success:
            value = result.stdout.strip()
            values[result.step.key] = value or _READ_DEFAULTS[result.step.key]
    return CurrentConfig(
        ethernet_range=values["read-ethernet"],
        preview_mode=values["read-preview"],
        bitrate_bps=values["read-bitrate"],
        encoder=values["read-encoder"],
        transform=values["read-transform"],
    )


def build_config_apply_steps(
    serial: str, selection: ConfigSelection
) -> tuple[CommandStep, ...]:
    values: list[tuple[str, str, str, str]] = []
    if selection.ethernet_range is not None:
        if selection.ethernet_range not in {"144", "199"}:
            raise ConfigurationError("Ethernet range must be 144 or 199")
        values.append(
            (
                "set-ethernet",
                "Applying Ethernet range",
                ETHERNET_PROPERTY,
                selection.ethernet_range,
            )
        )
    if selection.preview_mode is not None:
        if selection.preview_mode not in {"1920x1080@30", "1280x720@30"}:
            raise ConfigurationError("Unsupported preview resolution")
        values.append(
            (
                "set-preview",
                "Applying preview resolution",
                PREVIEW_PROPERTY,
                selection.preview_mode,
            )
        )
    if selection.bitrate_mbps is not None:
        values.append(
            (
                "set-bitrate",
                "Applying preview bitrate",
                BITRATE_PROPERTY,
                mbps_to_bps(selection.bitrate_mbps),
            )
        )
    if selection.encoder is not None:
        if selection.encoder not in {"h264", "h265"}:
            raise ConfigurationError("Encoder must be h264 or h265")
        values.append(
            (
                "set-encoder",
                "Applying preview encoder",
                ENCODER_PROPERTY,
                selection.encoder,
            )
        )
    if not values and selection.transform is None:
        raise ConfigurationError("Select at least one setting")

    steps = [
        CommandStep(
            key,
            label,
            "adb",
            ("-s", serial, "shell", "setprop", property_name, value),
        )
        for key, label, property_name, value in values
    ]
    if selection.transform is not None:
        steps.append(build_weston_transform_step(serial, selection.transform))
    steps.append(
        CommandStep(
            "sync",
            "Syncing file system",
            "adb",
            ("-s", serial, "shell", "sync"),
        )
    )
    return tuple(steps)


def build_adb_reboot_step(serial: str) -> CommandStep:
    return CommandStep(
        "adb-reboot",
        "Rebooting device",
        "adb",
        ("-s", serial, "reboot"),
    )
