"""Tests for bounded BLE runtime diagnostics."""

from __future__ import annotations

from custom_components.candy_house_ble.metrics import BLERuntimeMetrics


def test_metrics_count_outcomes_and_round_successful_timings() -> None:
    metrics = BLERuntimeMetrics()

    metrics.connection_started()
    metrics.connection_succeeded(1.23456)
    metrics.connection_started()
    metrics.connection_cancelled()
    metrics.operation_started("poll")
    metrics.operation_preempted("poll")
    metrics.operation_started("lock")
    metrics.operation_succeeded("lock", 2.34567)

    snapshot = metrics.snapshot()

    assert snapshot["resets_on_reload_or_restart"] is True
    assert snapshot["observation_started"].endswith("+00:00")
    assert snapshot["connection"] == {
        "attempts": 2,
        "successes": 1,
        "failures": 0,
        "cancellations": 1,
        "preemptions": 0,
        "successful_duration": {
            "samples": 1,
            "last_seconds": 1.235,
            "average_seconds": 1.235,
            "maximum_seconds": 1.235,
        },
    }
    assert snapshot["operations"]["poll"]["preemptions"] == 1
    assert snapshot["operations"]["lock"]["successful_duration"] == {
        "samples": 1,
        "last_seconds": 2.346,
        "average_seconds": 2.346,
        "maximum_seconds": 2.346,
    }


def test_metrics_retain_exception_class_but_not_message() -> None:
    metrics = BLERuntimeMetrics()
    secret_message = "credential-value-must-not-appear"
    root = TimeoutError(secret_message)
    wrapper = RuntimeError("wrapper")
    wrapper.__cause__ = root

    metrics.operation_started("unlock")
    metrics.operation_failed("unlock", wrapper)
    snapshot = metrics.snapshot()

    assert snapshot["operations"]["unlock"]["failures"] == 1
    assert snapshot["last_failure"] == {
        "operation": "unlock",
        "error_type": "TimeoutError",
    }
    assert secret_message not in repr(snapshot)


def test_empty_metrics_have_no_timing_samples() -> None:
    snapshot = BLERuntimeMetrics().snapshot()

    assert snapshot["connection"]["successful_duration"] == {
        "samples": 0,
        "last_seconds": None,
        "average_seconds": None,
        "maximum_seconds": None,
    }
    assert set(snapshot["operations"]) == {
        "poll",
        "lock",
        "unlock",
        "bot_script",
    }
