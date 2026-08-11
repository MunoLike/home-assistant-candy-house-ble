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
from custom_components.candy_house_ble.cloud import SesameCloudRateLimitError
from custom_components.candy_house_ble.coordinator import SesameStatusCoordinator
from custom_components.candy_house_ble.protocol import LockState, MechanismStatus


def coordinator_without_hass() -> SesameStatusCoordinator:
    """Create a coordinator shell for the isolated operation helper."""
    coordinator = object.__new__(SesameStatusCoordinator)
    coordinator.async_set_updated_data = Mock()
    coordinator.async_set_update_error = Mock()
    coordinator.cloud_client = None
    coordinator.cloud_unlock_enabled = False
    return coordinator


@pytest.mark.asyncio
async def test_actuation_publishes_observed_terminal_state() -> None:
    coordinator = coordinator_without_hass()
    terminal = MechanismStatus(
        state=LockState.LOCKED,
        battery_raw=2925,
        target=None,
        position=-86,
        battery_low=False,
        critical=False,
        stopped=True,
    )
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
    terminal = MechanismStatus(
        state=LockState.LOCKED,
        battery_raw=2925,
        target=None,
        position=-86,
        battery_low=False,
        critical=False,
        stopped=True,
    )
    coordinator.data = terminal
    coordinator.client = SimpleNamespace(
        async_read_status=AsyncMock(side_effect=SesamePollPreempted)
    )

    result = await coordinator._async_update_data()

    assert result is terminal


@pytest.mark.asyncio
async def test_cloud_lock_uses_local_status_and_not_ble_command() -> None:
    coordinator = coordinator_without_hass()
    before = MechanismStatus(
        state=LockState.UNLOCKED,
        battery_raw=2925,
        target=None,
        position=80,
        battery_low=False,
        critical=False,
        stopped=True,
    )
    after = MechanismStatus(
        state=LockState.LOCKED,
        battery_raw=2925,
        target=None,
        position=-86,
        battery_low=False,
        critical=False,
        stopped=True,
    )
    coordinator.data = before
    coordinator.client = SimpleNamespace(async_lock=AsyncMock())
    coordinator.cloud_client = SimpleNamespace(
        async_lock=AsyncMock(return_value=after)
    )

    await coordinator.async_lock()

    coordinator.cloud_client.async_lock.assert_awaited_once_with(before)
    coordinator.client.async_lock.assert_not_awaited()
    coordinator.async_set_updated_data.assert_called_once_with(after)


@pytest.mark.asyncio
async def test_cloud_unlock_requires_explicit_option() -> None:
    coordinator = coordinator_without_hass()
    coordinator.data = Mock()
    coordinator.client = SimpleNamespace(async_unlock=AsyncMock())
    coordinator.cloud_client = SimpleNamespace(async_unlock=AsyncMock())

    with pytest.raises(HomeAssistantError, match="Remote unlock is disabled"):
        await coordinator.async_unlock()

    coordinator.cloud_client.async_unlock.assert_not_awaited()
    coordinator.client.async_unlock.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_unlock_routes_when_explicitly_enabled() -> None:
    coordinator = coordinator_without_hass()
    before = Mock()
    after = Mock()
    coordinator.data = before
    coordinator.client = SimpleNamespace(async_unlock=AsyncMock())
    coordinator.cloud_client = SimpleNamespace(
        async_unlock=AsyncMock(return_value=after)
    )
    coordinator.cloud_unlock_enabled = True

    await coordinator.async_unlock()

    coordinator.cloud_client.async_unlock.assert_awaited_once_with(before)
    coordinator.client.async_unlock.assert_not_awaited()
    coordinator.async_set_updated_data.assert_called_once_with(after)


@pytest.mark.asyncio
async def test_cloud_failure_marks_coordinator_unavailable() -> None:
    coordinator = coordinator_without_hass()
    coordinator.data = Mock()
    coordinator.cloud_client = SimpleNamespace(
        async_lock=AsyncMock(
            side_effect=SesameCloudRateLimitError("quota exhausted")
        )
    )

    with pytest.raises(HomeAssistantError, match="quota exhausted"):
        await coordinator.async_lock()

    coordinator.async_set_updated_data.assert_not_called()
    coordinator.async_set_update_error.assert_called_once()


@pytest.mark.asyncio
async def test_cloud_command_requires_local_ble_baseline() -> None:
    coordinator = coordinator_without_hass()
    coordinator.data = None
    coordinator.cloud_client = SimpleNamespace(async_lock=AsyncMock())

    with pytest.raises(HomeAssistantError, match="No local BLE status"):
        await coordinator.async_lock()

    coordinator.cloud_client.async_lock.assert_not_awaited()
