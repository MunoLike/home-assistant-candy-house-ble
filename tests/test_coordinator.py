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
from custom_components.candy_house_ble.coordinator import SesameStatusCoordinator
from custom_components.candy_house_ble.protocol import LockState, MechanismStatus


def coordinator_without_hass() -> SesameStatusCoordinator:
    """Create a coordinator shell for the isolated operation helper."""
    coordinator = object.__new__(SesameStatusCoordinator)
    coordinator.async_set_updated_data = Mock()
    coordinator.async_set_update_error = Mock()
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
