"""Tests for CANDY HOUSE BLE command coordination."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.candy_house_ble.client import (
    SesameConnectionError,
    SesamePollPreempted,
)
from custom_components.candy_house_ble.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_SECRET_KEY,
    MODEL_BOT_2,
    MODEL_SESAME_5_PRO,
)
from custom_components.candy_house_ble.coordinator import SesameStatusCoordinator
from custom_components.candy_house_ble.protocol import LockState, MechanismStatus


def coordinator_without_hass() -> SesameStatusCoordinator:
    """Create a coordinator shell for isolated operation helpers."""
    coordinator = object.__new__(SesameStatusCoordinator)
    coordinator.async_set_updated_data = Mock()
    coordinator.async_set_update_error = Mock()
    coordinator.model = MODEL_SESAME_5_PRO
    coordinator._schedule_bot_refresh = Mock()
    return coordinator


def test_coordinator_ignores_removed_transport_options(monkeypatch) -> None:
    """Stale version 3 options cannot change the BLE-only runtime."""
    local_constructor = Mock(return_value=Mock())
    monkeypatch.setattr(
        "custom_components.candy_house_ble.coordinator.SesameStatusClient",
        local_constructor,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator."
        "__init__",
        lambda _self, *_args, **_kwargs: None,
    )
    entry = SimpleNamespace(
        data={
            CONF_MODEL: MODEL_SESAME_5_PRO,
            CONF_DEVICE_ID: "12345678-1234-5678-1234-567812345678",
            CONF_SECRET_KEY: "00" * 16,
        },
        options={
            "command_transport": "cloud",
            "cloud_api_key": "must-not-be-used",
            "cloud_secret_key": "11" * 16,
            "cloud_unlock_enabled": True,
        },
        title="Test lock",
        async_on_unload=Mock(),
    )

    coordinator = SesameStatusCoordinator(SimpleNamespace(), entry)

    local_constructor.assert_called_once()
    assert not hasattr(coordinator, "cloud_client")
    assert not hasattr(coordinator, "command_transport")


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["async_lock", "async_unlock"])
async def test_bot_2_coordinator_rejects_all_lock_commands(
    method_name: str,
) -> None:
    coordinator = coordinator_without_hass()
    coordinator.model = MODEL_BOT_2
    coordinator.client = SimpleNamespace(
        async_lock=AsyncMock(), async_unlock=AsyncMock()
    )

    with pytest.raises(HomeAssistantError, match="not supported"):
        await getattr(coordinator, method_name)()

    coordinator.client.async_lock.assert_not_awaited()
    coordinator.client.async_unlock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_state"),
    [
        ("async_lock", LockState.LOCKED),
        ("async_unlock", LockState.UNLOCKED),
    ],
)
async def test_lock_commands_always_use_local_ble(
    method_name: str, expected_state: LockState
) -> None:
    coordinator = coordinator_without_hass()
    terminal = mechanism_status(expected_state)
    coordinator.client = SimpleNamespace(
        async_lock=AsyncMock(return_value=terminal),
        async_unlock=AsyncMock(return_value=terminal),
    )

    await getattr(coordinator, method_name)()

    getattr(coordinator.client, method_name).assert_awaited_once_with()
    coordinator.async_set_updated_data.assert_called_once_with(terminal)


@pytest.mark.asyncio
async def test_bot_2_script_runs_local_fixed_action_then_refreshes() -> None:
    coordinator = coordinator_without_hass()
    coordinator.model = MODEL_BOT_2
    coordinator.client = SimpleNamespace(async_run_script=AsyncMock())

    await coordinator.async_run_script(4)

    coordinator.client.async_run_script.assert_awaited_once_with(4)
    coordinator._schedule_bot_refresh.assert_called_once_with()


@pytest.mark.asyncio
async def test_lock_model_rejects_bot_2_script() -> None:
    coordinator = coordinator_without_hass()
    coordinator.client = SimpleNamespace(async_run_script=AsyncMock())

    with pytest.raises(HomeAssistantError, match="not supported"):
        await coordinator.async_run_script(4)

    coordinator.client.async_run_script.assert_not_awaited()


@pytest.mark.asyncio
async def test_actuation_publishes_observed_terminal_state() -> None:
    coordinator = coordinator_without_hass()
    terminal = mechanism_status(LockState.LOCKED)
    operation = AsyncMock(return_value=terminal)

    await coordinator._async_actuate(operation)

    operation.assert_awaited_once_with()
    coordinator.async_set_updated_data.assert_called_once_with(terminal)


@pytest.mark.asyncio
async def test_actuation_error_does_not_update_data() -> None:
    coordinator = coordinator_without_hass()
    operation = AsyncMock(side_effect=SesameConnectionError("rejected"))

    with pytest.raises(HomeAssistantError, match="rejected"):
        await coordinator._async_actuate(operation)

    coordinator.async_set_updated_data.assert_not_called()
    coordinator.async_set_update_error.assert_called_once()


@pytest.mark.asyncio
async def test_preempted_poll_preserves_data_for_operation_handoff() -> None:
    coordinator = coordinator_without_hass()
    terminal = mechanism_status(LockState.LOCKED)
    coordinator.data = terminal
    coordinator.client = SimpleNamespace(
        async_read_status=AsyncMock(side_effect=SesamePollPreempted)
    )

    result = await coordinator._async_update_data()

    assert result is terminal


@pytest.mark.asyncio
async def test_delayed_bot_2_refresh_publishes_status(monkeypatch) -> None:
    coordinator = coordinator_without_hass()
    observed = Mock()
    coordinator.client = SimpleNamespace(
        async_read_status=AsyncMock(return_value=observed)
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.coordinator.asyncio.sleep",
        AsyncMock(),
    )

    await coordinator._async_delayed_bot_refresh()

    coordinator.async_set_updated_data.assert_called_once_with(observed)


@pytest.mark.asyncio
async def test_failed_delayed_bot_2_refresh_preserves_state(
    monkeypatch,
) -> None:
    coordinator = coordinator_without_hass()
    coordinator.client = SimpleNamespace(
        async_read_status=AsyncMock(
            side_effect=SesameConnectionError("sleeping")
        )
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.coordinator.asyncio.sleep",
        AsyncMock(),
    )

    await coordinator._async_delayed_bot_refresh()

    coordinator.async_set_updated_data.assert_not_called()
    coordinator.async_set_update_error.assert_not_called()


def mechanism_status(state: LockState) -> MechanismStatus:
    """Build a synthetic terminal lock status."""
    return MechanismStatus(
        state=state,
        battery_raw=2925,
        target=None,
        position=-86 if state is LockState.LOCKED else 80,
        battery_low=False,
        critical=False,
        stopped=True,
    )
