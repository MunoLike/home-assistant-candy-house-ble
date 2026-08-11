"""Data coordinator for CANDY HOUSE BLE."""

from __future__ import annotations

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
from .const import CONF_DEVICE_ID, CONF_MODEL, CONF_SECRET_KEY, POLL_INTERVAL
from .protocol import MechanismStatus

_LOGGER = logging.getLogger(__name__)


class SesameStatusCoordinator(DataUpdateCoordinator[MechanismStatus]):
    """Poll a SESAME briefly so other BLE clients are not blocked."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
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
        await self._async_actuate(self.client.async_lock)

    async def async_unlock(self) -> None:
        """Unlock the SESAME and refresh its observed state."""
        await self._async_actuate(self.client.async_unlock)

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
