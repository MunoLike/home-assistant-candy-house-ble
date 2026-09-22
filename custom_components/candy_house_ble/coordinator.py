"""Data coordinator for CANDY HOUSE BLE."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    SesameConnectionError,
    SesamePollPreempted,
    SesameStatusClient,
)
from .const import (
    BOT_2_BLE_REFRESH_DELAY,
    BOT_MODELS,
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_SECRET_KEY,
    LOCK_MODELS,
    POLL_INTERVAL,
)
from .protocol import MechanismStatus
from .session import get_ble_session_gate

_LOGGER = logging.getLogger(__name__)


class SesameStatusCoordinator(DataUpdateCoordinator[MechanismStatus]):
    """Poll a SESAME briefly so other BLE clients are not blocked."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.model = entry.data[CONF_MODEL]
        self._bot_refresh_task: asyncio.Task[None] | None = None
        self.client = SesameStatusClient(
            hass,
            entry.data[CONF_MODEL],
            uuid.UUID(entry.data[CONF_DEVICE_ID]).bytes,
            bytes.fromhex(entry.data[CONF_SECRET_KEY]),
            entry.title,
            get_ble_session_gate(hass),
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=POLL_INTERVAL,
        )
        entry.async_on_unload(self._cancel_delayed_refreshes)

    async def _async_update_data(self) -> MechanismStatus:
        try:
            return await self.client.async_read_status()
        except SesamePollPreempted:
            if self.data is not None:
                return self.data
            raise UpdateFailed("Initial SESAME poll was preempted") from None
        except SesameConnectionError as err:
            raise UpdateFailed(str(err)) from err

    async def async_lock(self) -> None:
        """Lock the SESAME and refresh its observed state."""
        self._require_lock_model()
        await self._async_actuate(self.client.async_lock)

    async def async_unlock(self) -> None:
        """Unlock the SESAME and refresh its observed state."""
        self._require_lock_model()
        await self._async_actuate(self.client.async_unlock)

    async def async_run_script(self, script_index: int) -> None:
        """Run one Bot 2/3 script slot once and refresh observed status."""
        if self.model not in BOT_MODELS:
            raise HomeAssistantError(
                "Bot 2/3 scripts are not supported for this device"
            )
        try:
            await self.client.async_run_script(script_index)
        except SesameConnectionError as err:
            self.async_set_update_error(err)
            raise HomeAssistantError(str(err)) from err
        self._schedule_bot_refresh()

    def _require_lock_model(self) -> None:
        """Reject physical lock commands for every non-lock device."""
        if self.model not in LOCK_MODELS:
            raise HomeAssistantError(
                "Physical lock commands are not supported for this device"
            )

    async def _async_actuate(
        self, operation: Callable[[], Awaitable[MechanismStatus]]
    ) -> None:
        """Run one physical command and publish its observed terminal state."""
        try:
            status = await operation()
        except SesameConnectionError as err:
            self.async_set_update_error(err)
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(status)

    def _schedule_bot_refresh(self) -> None:
        """Refresh Bot 2/3 status after acknowledging a physical action."""
        self._cancel_bot_refresh()
        task = self.hass.async_create_task(
            self._async_delayed_bot_refresh(),
            "candy_house_ble Bot 2/3 post-script refresh",
        )
        self._bot_refresh_task = task
        task.add_done_callback(self._clear_bot_refresh_task)

    async def _async_delayed_bot_refresh(self) -> None:
        """Best-effort refresh without extending the button service call."""
        await asyncio.sleep(BOT_2_BLE_REFRESH_DELAY)
        try:
            status = await self.client.async_read_status()
        except SesamePollPreempted:
            return
        except SesameConnectionError as err:
            _LOGGER.debug("Post-script Bot 2/3 refresh deferred: %s", err)
            return
        self.async_set_updated_data(status)

    def _clear_bot_refresh_task(self, task: asyncio.Task[None]) -> None:
        """Forget a completed Bot 2/3 refresh task."""
        if self._bot_refresh_task is task:
            self._bot_refresh_task = None

    def _cancel_bot_refresh(self) -> None:
        """Cancel a pending Bot 2/3 refresh during replacement or unload."""
        if self._bot_refresh_task is not None:
            self._bot_refresh_task.cancel()
            self._bot_refresh_task = None

    def _cancel_delayed_refreshes(self) -> None:
        """Cancel all model-specific delayed refresh tasks."""
        self._cancel_bot_refresh()
