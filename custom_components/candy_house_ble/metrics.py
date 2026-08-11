"""Process-local, non-sensitive BLE reliability metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_OPERATION_NAMES = ("poll", "lock", "unlock", "bot_script")


@dataclass(slots=True)
class TimingStats:
    """Track bounded aggregate duration data without retaining samples."""

    samples: int = 0
    total_seconds: float = 0.0
    maximum_seconds: float | None = None
    last_seconds: float | None = None

    def record(self, duration: float) -> None:
        """Record one non-negative elapsed duration."""
        value = max(0.0, duration)
        self.samples += 1
        self.total_seconds += value
        self.last_seconds = value
        self.maximum_seconds = (
            value
            if self.maximum_seconds is None
            else max(self.maximum_seconds, value)
        )

    def snapshot(self) -> dict[str, int | float | None]:
        """Return rounded values suitable for Home Assistant diagnostics."""
        average = (
            self.total_seconds / self.samples if self.samples else None
        )
        return {
            "samples": self.samples,
            "last_seconds": _rounded(self.last_seconds),
            "average_seconds": _rounded(average),
            "maximum_seconds": _rounded(self.maximum_seconds),
        }


@dataclass(slots=True)
class OutcomeStats:
    """Count terminal outcomes and successful operation durations."""

    attempts: int = 0
    successes: int = 0
    failures: int = 0
    cancellations: int = 0
    preemptions: int = 0
    successful_duration: TimingStats = field(default_factory=TimingStats)

    def snapshot(self) -> dict[str, Any]:
        """Return one operation's aggregate diagnostics."""
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "cancellations": self.cancellations,
            "preemptions": self.preemptions,
            "successful_duration": self.successful_duration.snapshot(),
        }


class BLERuntimeMetrics:
    """Aggregate BLE outcomes for the lifetime of one config-entry setup."""

    def __init__(self) -> None:
        self._observation_started = datetime.now(UTC).isoformat(
            timespec="seconds"
        )
        self._connection = OutcomeStats()
        self._operations = {
            name: OutcomeStats() for name in _OPERATION_NAMES
        }
        self._last_failure: dict[str, str] | None = None

    def connection_started(self) -> None:
        """Count an attempt to resolve and connect to a device."""
        self._connection.attempts += 1

    def connection_succeeded(self, duration: float) -> None:
        """Count a connected, notification-subscribed BLE session."""
        self._connection.successes += 1
        self._connection.successful_duration.record(duration)

    def connection_failed(self, error: Exception) -> None:
        """Count a failed BLE session without retaining an error message."""
        self._connection.failures += 1
        self._set_last_failure("connection", error)

    def connection_cancelled(self) -> None:
        """Count a session cancelled by operation preemption or shutdown."""
        self._connection.cancellations += 1

    def operation_started(self, name: str) -> None:
        """Count one supported operation request."""
        self._operations[name].attempts += 1

    def operation_succeeded(self, name: str, duration: float) -> None:
        """Count one successful operation and its end-to-end duration."""
        stats = self._operations[name]
        stats.successes += 1
        stats.successful_duration.record(duration)

    def operation_failed(self, name: str, error: Exception) -> None:
        """Count one failed operation and retain only its exception class."""
        self._operations[name].failures += 1
        self._set_last_failure(name, error)

    def operation_cancelled(self, name: str) -> None:
        """Count an operation cancelled by Home Assistant shutdown/reload."""
        self._operations[name].cancellations += 1

    def operation_preempted(self, name: str) -> None:
        """Count a background operation superseded by an explicit command."""
        self._operations[name].preemptions += 1

    def snapshot(self) -> dict[str, Any]:
        """Return safe diagnostics for the current process-local interval."""
        return {
            "observation_started": self._observation_started,
            "resets_on_reload_or_restart": True,
            "connection": self._connection.snapshot(),
            "operations": {
                name: stats.snapshot()
                for name, stats in self._operations.items()
            },
            "last_failure": self._last_failure,
        }

    def _set_last_failure(self, operation: str, error: Exception) -> None:
        """Retain a bounded category, never an exception's message."""
        cause: BaseException = error
        while cause.__cause__ is not None:
            cause = cause.__cause__
        self._last_failure = {
            "operation": operation,
            "error_type": type(cause).__name__,
        }


def _rounded(value: float | None) -> float | None:
    """Round diagnostic durations while preserving missing samples."""
    return None if value is None else round(value, 3)
