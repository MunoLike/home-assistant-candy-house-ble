"""Tests for CANDY HOUSE BLE diagnostics redaction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.candy_house_ble.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_SECRET_KEY,
    MODEL_SESAME_5_PRO,
)
from custom_components.candy_house_ble.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.candy_house_ble.protocol import LockState, MechanismStatus


@pytest.mark.asyncio
async def test_diagnostics_redact_credentials_and_include_ble_metrics() -> None:
    metrics = {
        "observation_started": "2026-08-11T00:00:00+00:00",
        "last_failure": {"operation": "poll", "error_type": "TimeoutError"},
    }
    entry = SimpleNamespace(
        title="Test lock",
        data={
            CONF_DEVICE_ID: "12345678-1234-5678-1234-567812345678",
            CONF_MODEL: MODEL_SESAME_5_PRO,
            CONF_SECRET_KEY: "credential-value-must-not-appear",
        },
        options={
            "cloud_api_key": "legacy-api-key-must-not-appear",
            "cloud_secret_key": "legacy-cloud-secret-must-not-appear",
        },
        runtime_data=SimpleNamespace(
            data=MechanismStatus(
                state=LockState.LOCKED,
                battery_raw=2925,
                target=None,
                position=-86,
                battery_low=False,
                critical=False,
                stopped=True,
            ),
            client=SimpleNamespace(
                diagnostics_snapshot=Mock(return_value=metrics)
            ),
        ),
    )

    result = await async_get_config_entry_diagnostics(None, entry)

    assert result["config_entry"]["data"][CONF_SECRET_KEY] == "**REDACTED**"
    assert result["ble_runtime"] is metrics
    assert "options" not in result["config_entry"]
    rendered = repr(result)
    assert "credential-value-must-not-appear" not in rendered
    assert "legacy-api-key-must-not-appear" not in rendered
    assert "legacy-cloud-secret-must-not-appear" not in rendered
