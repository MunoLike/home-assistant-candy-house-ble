"""Data coordinator for CANDY HOUSE BLE."""

from __future__ import annotations

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
            return
        await self._async_actuate(self.client.async_unlock)

    def _require_current_status(self) -> MechanismStatus:
        """Return the latest local BLE status required for cloud confirmation."""
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
