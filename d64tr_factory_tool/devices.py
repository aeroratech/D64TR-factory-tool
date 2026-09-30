from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .commands import CommandStep


@dataclass(frozen=True)
class DeviceRecord:
    serial: str
    state: str


class DeviceSelectionError(ValueError):
    """Raised when one unambiguous target cannot be selected."""


def parse_adb_devices(output: str) -> tuple[DeviceRecord, ...]:
    devices: list[DeviceRecord] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("*") or line.startswith("List of devices"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            devices.append(DeviceRecord(fields[0], fields[1]))
    return tuple(devices)


def parse_fastboot_devices(output: str) -> tuple[str, ...]:
    devices: list[str] = []
    for raw_line in output.splitlines():
        fields = raw_line.strip().split()
        if len(fields) >= 2 and fields[1].lower() == "fastboot":
            devices.append(fields[0])
    return tuple(devices)


def _adb_details(records: tuple[DeviceRecord, ...]) -> str:
    if not records:
        return "none reported"
    return ", ".join(f"{record.serial} ({record.state})" for record in records)


def require_single_adb_device(output: str) -> str:
    records = parse_adb_devices(output)
    eligible = [record.serial for record in records if record.state == "device"]
    if not eligible:
        raise DeviceSelectionError(
            f"No eligible ADB device. Observed: {_adb_details(records)}"
        )
    if len(eligible) > 1:
        raise DeviceSelectionError(
            "Multiple ADB devices are eligible: " + ", ".join(eligible)
        )
    return eligible[0]


def require_single_fastboot_device(
    output: str, expected_serial: str | None = None
) -> str:
    devices = parse_fastboot_devices(output)
    if not devices:
        raise DeviceSelectionError("No eligible Fastboot device")
    if len(devices) > 1:
        raise DeviceSelectionError(
            "Multiple Fastboot devices are eligible: " + ", ".join(devices)
        )
    serial = devices[0]
    if expected_serial is not None and serial != expected_serial:
        raise DeviceSelectionError(
            f"Fastboot device {serial} does not match expected {expected_serial}"
        )
    return serial


def build_device_list_step(transport: Literal["adb", "fastboot"]) -> CommandStep:
    if transport not in {"adb", "fastboot"}:
        raise ValueError(f"Unsupported transport: {transport}")
    return CommandStep(
        key=f"probe-{transport}",
        label=f"Detecting {transport.upper()} devices",
        program=transport,
        arguments=("devices",),
    )
