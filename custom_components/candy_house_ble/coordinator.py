"""Data coordinator for CANDY HOUSE BLE."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    SesameConnectionError,
    SesamePollPreempted,
    SesameStatusClient,
)
from .cloud import SesameCloudCommandClient, SesameCloudError
from .const import (
    CLOUD_BLE_REFRESH_DELAY,
    COMMAND_TRANSPORT_BLE,
    COMMAND_TRANSPORT_CLOUD,
    CONF_CLOUD_API_KEY,
    CONF_CLOUD_SECRET_KEY,
    CONF_CLOUD_UNLOCK_ENABLED,
    CONF_COMMAND_TRANSPORT,
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_SECRET_KEY,
    POLL_INTERVAL,
)
from .protocol import MechanismStatus

_LOGGER = logging.getLogger(__name__)


class SesameStatusCoordinator(DataUpdateCoordinator[MechanismStatus]):
    """Poll a SESAME briefly so other BLE clients are not blocked."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        options = getattr(entry, "options", {})
        self.command_transport = options.get(
            CONF_COMMAND_TRANSPORT, COMMAND_TRANSPORT_BLE
        )
        self.cloud_unlock_enabled = options.get(
            CONF_CLOUD_UNLOCK_ENABLED, False
        )
        self.cloud_client: SesameCloudCommandClient | None = None
        self._cloud_refresh_task: asyncio.Task[None] | None = None
        if self.command_transport == COMMAND_TRANSPORT_CLOUD:
            self.cloud_client = SesameCloudCommandClient(
                async_get_clientsession(hass),
                options[CONF_CLOUD_API_KEY],
                entry.data[CONF_DEVICE_ID],
                options[CONF_CLOUD_SECRET_KEY],
            )
        self.client = SesameStatusClient(
            hass,
            entry.data[CONF_MODEL],
            uuid.UUID(entry.data[CONF_DEVICE_ID]).bytes,
            bytes.fromhex(entry.data[CONF_SECRET_KEY]),
            entry.title,
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=POLL_INTERVAL,
        )
        entry.async_on_unload(self._cancel_cloud_refresh)

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
        if self.cloud_client is not None:
            before = self._require_current_status()
            await self._async_actuate(
                lambda: self.cloud_client.async_lock(before)
            )
            self._schedule_cloud_refresh()
            return
        await self._async_actuate(self.client.async_lock)

    async def async_unlock(self) -> None:
        """Unlock the SESAME and refresh its observed state."""
        if self.cloud_client is not None:
            if not self.cloud_unlock_enabled:
                raise HomeAssistantError(
                    "Remote unlock is disabled in CANDY HOUSE BLE options"
                )
            before = self._require_current_status()
            await self._async_actuate(
                lambda: self.cloud_client.async_unlock(before)
            )
            self._schedule_cloud_refresh()
            return
        await self._async_actuate(self.client.async_unlock)

    def _require_current_status(self) -> MechanismStatus:
        """Return the latest local BLE state preserved across a cloud command."""
        if self.data is None:
            raise HomeAssistantError(
                "No local BLE status is available for the SESAME"
            )
        return self.data

    async def _async_actuate(
        self, operation: Callable[[], Awaitable[MechanismStatus]]
    ) -> None:
        """Run one physical command and publish its observed terminal state."""
        try:
            status = await operation()
        except (SesameConnectionError, SesameCloudError) as err:
            self.async_set_update_error(err)
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(status)

    def _schedule_cloud_refresh(self) -> None:
        """Verify accepted cloud commands later using authoritative local BLE."""
        self._cancel_cloud_refresh()
        task = self.hass.async_create_task(
            self._async_delayed_ble_refresh(),
            "candy_house_ble post-command BLE refresh",
        )
        self._cloud_refresh_task = task
        task.add_done_callback(self._clear_cloud_refresh_task)

    async def _async_delayed_ble_refresh(self) -> None:
        """Let Hub 3 finish, then refresh without delaying the service call."""
        await asyncio.sleep(CLOUD_BLE_REFRESH_DELAY)
        try:
            status = await self.client.async_read_status()
        except SesamePollPreempted:
            return
        except SesameConnectionError as err:
            _LOGGER.debug(
                "Post-command BLE verification deferred: %s", err
            )
            return
        self.async_set_updated_data(status)

    def _clear_cloud_refresh_task(self, task: asyncio.Task[None]) -> None:
        """Forget a completed delayed refresh task."""
        if self._cloud_refresh_task is task:
            self._cloud_refresh_task = None

    def _cancel_cloud_refresh(self) -> None:
        """Cancel a pending delayed refresh during replacement or unload."""
        if self._cloud_refresh_task is not None:
            self._cloud_refresh_task.cancel()
            self._cloud_refresh_task = None
