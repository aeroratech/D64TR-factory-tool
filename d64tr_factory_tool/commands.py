from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandStep:
    key: str
    label: str
    program: str
    arguments: tuple[str, ...]
    timeout_ms: int | None = 10_000
    continue_on_error: bool = False


@dataclass(frozen=True)
class CommandResult:
    step: CommandStep
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    process_error: str | None = None

    @property
    def success(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and self.process_error is None
        )


@dataclass(frozen=True)
class QueueResult:
    results: tuple[CommandResult, ...]
    cancelled: bool = False

    @property
    def success(self) -> bool:
        return not self.cancelled and all(result.success for result in self.results)
