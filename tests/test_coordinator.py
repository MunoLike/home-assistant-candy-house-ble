"""Tests for CANDY HOUSE BLE command coordination."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.candy_house_ble.client import (
    SesameConnectionError,
    SesamePollPreempted,
)
from custom_components.candy_house_ble.cloud import SesameCloudRateLimitError
from custom_components.candy_house_ble.const import (
    COMMAND_TRANSPORT_BLE,
    COMMAND_TRANSPORT_CLOUD,
    CONF_CLOUD_UNLOCK_ENABLED,
    CONF_COMMAND_TRANSPORT,
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_SECRET_KEY,
    MODEL_BOT_2,
    MODEL_SESAME_5_PRO,
)
from custom_components.candy_house_ble.coordinator import (
    SesameStatusCoordinator,
    command_configuration_for_model,
)
from custom_components.candy_house_ble.protocol import LockState, MechanismStatus


def coordinator_without_hass() -> SesameStatusCoordinator:
    """Create a coordinator shell for the isolated operation helper."""
    coordinator = object.__new__(SesameStatusCoordinator)
    coordinator.async_set_updated_data = Mock()
    coordinator.async_set_update_error = Mock()
    coordinator.cloud_client = None
    coordinator.cloud_unlock_enabled = False
    coordinator.model = MODEL_SESAME_5_PRO
    coordinator._schedule_cloud_refresh = Mock()
    coordinator._schedule_bot_refresh = Mock()
    return coordinator


def test_bot_2_ignores_stale_cloud_command_options() -> None:
    assert command_configuration_for_model(
        MODEL_BOT_2,
        {
            CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_CLOUD,
            CONF_CLOUD_UNLOCK_ENABLED: True,
        },
    ) == (COMMAND_TRANSPORT_BLE, False)


def test_bot_2_coordinator_never_constructs_cloud_client(
    monkeypatch,
) -> None:
    cloud_constructor = Mock(
        side_effect=AssertionError("cloud client constructed")
    )
    local_constructor = Mock(return_value=Mock())
    monkeypatch.setattr(
        "custom_components.candy_house_ble.coordinator."
        "SesameCloudCommandClient",
        cloud_constructor,
    )
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
            CONF_MODEL: MODEL_BOT_2,
            CONF_DEVICE_ID: "12345678-1234-5678-1234-567812345678",
            CONF_SECRET_KEY: "00" * 16,
        },
        options={
            CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_CLOUD,
            CONF_CLOUD_UNLOCK_ENABLED: True,
            "cloud_api_key": "must-not-be-used",
            "cloud_secret_key": "11" * 16,
        },
        title="Test Bot 2",
        async_on_unload=Mock(),
    )

    coordinator = SesameStatusCoordinator(SimpleNamespace(), entry)

    assert coordinator.command_transport == COMMAND_TRANSPORT_BLE
    assert coordinator.cloud_unlock_enabled is False
    assert coordinator.cloud_client is None
    cloud_constructor.assert_not_called()
    local_constructor.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["async_lock", "async_unlock"])
async def test_bot_2_coordinator_rejects_all_lock_commands(
    method_name: str,
) -> None:
    coordinator = coordinator_without_hass()
    coordinator.model = MODEL_BOT_2
    coordinator.cloud_client = SimpleNamespace(
        async_lock=AsyncMock(), async_unlock=AsyncMock()
    )
    coordinator.client = SimpleNamespace(
        async_lock=AsyncMock(), async_unlock=AsyncMock()
    )

    with pytest.raises(HomeAssistantError, match="not supported"):
        await getattr(coordinator, method_name)()

    coordinator.cloud_client.async_lock.assert_not_awaited()
    coordinator.cloud_client.async_unlock.assert_not_awaited()
    coordinator.client.async_lock.assert_not_awaited()
    coordinator.client.async_unlock.assert_not_awaited()


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


@asynccontextmanager
async def external_command_slot():
    """Provide an observable no-op external command reservation."""
    yield


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
    coordinator.data = before
    reserve = Mock(side_effect=external_command_slot)
    coordinator.client = SimpleNamespace(
        async_lock=AsyncMock(), async_external_command=reserve
    )
    coordinator.cloud_client = SimpleNamespace(
        async_lock=AsyncMock(return_value=before)
    )

    await coordinator.async_lock()

    coordinator.cloud_client.async_lock.assert_awaited_once_with(before)
    reserve.assert_called_once_with()
    coordinator.client.async_lock.assert_not_awaited()
    coordinator.async_set_updated_data.assert_called_once_with(before)
    coordinator._schedule_cloud_refresh.assert_called_once_with()


@pytest.mark.asyncio
async def test_cloud_unlock_requires_explicit_option() -> None:
    coordinator = coordinator_without_hass()
    coordinator.data = Mock()
    reserve = Mock(side_effect=external_command_slot)
    coordinator.client = SimpleNamespace(
        async_unlock=AsyncMock(), async_external_command=reserve
    )
    coordinator.cloud_client = SimpleNamespace(async_unlock=AsyncMock())

    with pytest.raises(HomeAssistantError, match="Remote unlock is disabled"):
        await coordinator.async_unlock()

    coordinator.cloud_client.async_unlock.assert_not_awaited()
    coordinator.client.async_unlock.assert_not_awaited()
    reserve.assert_not_called()


@pytest.mark.asyncio
async def test_cloud_unlock_routes_when_explicitly_enabled() -> None:
    coordinator = coordinator_without_hass()
    before = Mock()
    coordinator.data = before
    reserve = Mock(side_effect=external_command_slot)
    coordinator.client = SimpleNamespace(
        async_unlock=AsyncMock(), async_external_command=reserve
    )
    coordinator.cloud_client = SimpleNamespace(
        async_unlock=AsyncMock(return_value=before)
    )
    coordinator.cloud_unlock_enabled = True

    await coordinator.async_unlock()

    coordinator.cloud_client.async_unlock.assert_awaited_once_with(before)
    reserve.assert_called_once_with()
    coordinator.client.async_unlock.assert_not_awaited()
    coordinator.async_set_updated_data.assert_called_once_with(before)
    coordinator._schedule_cloud_refresh.assert_called_once_with()


@pytest.mark.asyncio
async def test_cloud_failure_marks_coordinator_unavailable() -> None:
    coordinator = coordinator_without_hass()
    coordinator.data = Mock()
    reserve = Mock(side_effect=external_command_slot)
    coordinator.client = SimpleNamespace(async_external_command=reserve)
    coordinator.cloud_client = SimpleNamespace(
        async_lock=AsyncMock(
            side_effect=SesameCloudRateLimitError("quota exhausted")
        )
    )

    with pytest.raises(HomeAssistantError, match="quota exhausted"):
        await coordinator.async_lock()

    coordinator.async_set_updated_data.assert_not_called()
    coordinator.async_set_update_error.assert_called_once()
    reserve.assert_called_once_with()


@pytest.mark.asyncio
async def test_cloud_reservation_failure_is_reported_as_ha_error() -> None:
    coordinator = coordinator_without_hass()
    coordinator.data = Mock()

    @asynccontextmanager
    async def rejected_slot():
        raise SesameConnectionError(
            "Another SESAME lock operation is already in progress"
        )
        yield

    coordinator.client = SimpleNamespace(async_external_command=rejected_slot)
    coordinator.cloud_client = SimpleNamespace(async_lock=AsyncMock())

    with pytest.raises(HomeAssistantError, match="already in progress"):
        await coordinator.async_lock()

    coordinator.cloud_client.async_lock.assert_not_awaited()
    coordinator.async_set_updated_data.assert_not_called()
    coordinator.async_set_update_error.assert_called_once()


@pytest.mark.asyncio
async def test_cloud_command_requires_local_ble_baseline() -> None:
    coordinator = coordinator_without_hass()
    coordinator.data = None
    reserve = Mock(side_effect=external_command_slot)
    coordinator.client = SimpleNamespace(async_external_command=reserve)
    coordinator.cloud_client = SimpleNamespace(async_lock=AsyncMock())

    with pytest.raises(HomeAssistantError, match="No local BLE status"):
        await coordinator.async_lock()

    coordinator.cloud_client.async_lock.assert_not_awaited()
    reserve.assert_not_called()


@pytest.mark.asyncio
async def test_delayed_cloud_verification_publishes_local_ble_state(
    monkeypatch,
) -> None:
    coordinator = coordinator_without_hass()
    observed = Mock()
    coordinator.client = SimpleNamespace(
        async_read_status=AsyncMock(return_value=observed)
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.coordinator.asyncio.sleep",
        AsyncMock(),
    )

    await coordinator._async_delayed_ble_refresh()

    coordinator.async_set_updated_data.assert_called_once_with(observed)


@pytest.mark.asyncio
async def test_failed_delayed_verification_preserves_last_state(
    monkeypatch,
) -> None:
    coordinator = coordinator_without_hass()
    coordinator.client = SimpleNamespace(
        async_read_status=AsyncMock(
            side_effect=SesameConnectionError("still contended")
        )
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.coordinator.asyncio.sleep",
        AsyncMock(),
    )

    await coordinator._async_delayed_ble_refresh()

    coordinator.async_set_updated_data.assert_not_called()
    coordinator.async_set_update_error.assert_not_called()


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
