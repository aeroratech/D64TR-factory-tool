from __future__ import annotations

from .commands import CommandStep


def build_info_steps(serial: str) -> tuple[CommandStep, CommandStep]:
    return (
        CommandStep(
            key="camera-version",
            label="Camera Version",
            program="adb",
            arguments=(
                "-s",
                serial,
                "shell",
                "cat",
                "/etc/aerora-version",
            ),
            continue_on_error=True,
        ),
        CommandStep(
            key="gimbal-version",
            label="Gimbal Version",
            program="adb",
            arguments=(
                "-s",
                serial,
                "shell",
                "cat",
                "/etc/gimbal-version",
            ),
            continue_on_error=True,
        ),
    )
