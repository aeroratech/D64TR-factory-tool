from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .commands import CommandStep


BOOT_IMAGE_NAME = "qti-ubuntu-robotics-image-qrb5165-rb5-boot.img"
SYSTEM_IMAGE_NAME = "qti-ubuntu-robotics-image-qrb5165-rb5-sysfs.ext4"
ABL_IMAGE_NAME = "abl.elf"


@dataclass(frozen=True)
class UpdatePackage:
    root: Path
    boot: Path
    system: Path
    abl: Path | None


class PackageValidationError(ValueError):
    def __init__(self, message: str, missing: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.missing = missing


def validate_update_package(root: Path) -> UpdatePackage:
    resolved_root = Path(root).expanduser().resolve()
    if not resolved_root.is_dir():
        raise PackageValidationError(
            f"Selected update path is not a directory: {resolved_root}"
        )

    boot = resolved_root / BOOT_IMAGE_NAME
    system = resolved_root / SYSTEM_IMAGE_NAME
    required = ((BOOT_IMAGE_NAME, boot), (SYSTEM_IMAGE_NAME, system))
    missing = tuple(name for name, path in required if not path.is_file())
    if missing:
        raise PackageValidationError(
            "Missing required update files: " + ", ".join(missing),
            missing=missing,
        )

    abl_path = resolved_root / ABL_IMAGE_NAME
    return UpdatePackage(
        root=resolved_root,
        boot=boot,
        system=system,
        abl=abl_path if abl_path.is_file() else None,
    )


def build_enter_bootloader_steps(serial: str) -> tuple[CommandStep, ...]:
    return (
        CommandStep(
            "adb-root",
            "Restarting ADB as root",
            "adb",
            ("-s", serial, "root"),
            timeout_ms=15_000,
        ),
        CommandStep(
            "adb-wait",
            "Waiting for ADB device",
            "adb",
            ("-s", serial, "wait-for-device"),
            timeout_ms=30_000,
        ),
        CommandStep(
            "adb-reboot-bootloader",
            "Rebooting into bootloader",
            "adb",
            ("-s", serial, "reboot", "bootloader"),
            timeout_ms=10_000,
        ),
    )


def build_flash_steps(
    package: UpdatePackage, serial: str
) -> tuple[CommandStep, ...]:
    steps: list[CommandStep] = []
    if package.abl is not None:
        steps.extend(
            (
                CommandStep(
                    "flash-abl-a",
                    "Flashing abl_a",
                    "fastboot",
                    ("-s", serial, "flash", "abl_a", str(package.abl)),
                    timeout_ms=None,
                ),
                CommandStep(
                    "flash-abl-b",
                    "Flashing abl_b",
                    "fastboot",
                    ("-s", serial, "flash", "abl_b", str(package.abl)),
                    timeout_ms=None,
                ),
            )
        )
    steps.extend(
        (
            CommandStep(
                "flash-boot",
                "Flashing boot",
                "fastboot",
                (
                    "-s",
                    serial,
                    "--slot",
                    "all",
                    "flash",
                    "boot",
                    str(package.boot),
                ),
                timeout_ms=None,
            ),
            CommandStep(
                "flash-system",
                "Flashing system",
                "fastboot",
                (
                    "-s",
                    serial,
                    "--slot",
                    "all",
                    "flash",
                    "system",
                    str(package.system),
                ),
                timeout_ms=None,
            ),
        )
    )
    return tuple(steps)


def build_fastboot_reboot_step(serial: str) -> CommandStep:
    return CommandStep(
        "fastboot-reboot",
        "Rebooting device",
        "fastboot",
        ("-s", serial, "reboot"),
        timeout_ms=10_000,
    )
