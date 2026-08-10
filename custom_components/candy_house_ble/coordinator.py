"""Data coordinator for CANDY HOUSE BLE."""

from __future__ import annotations

import logging
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import SesameConnectionError, SesameStatusClient
from .const import CONF_DEVICE_ID, CONF_MODEL, CONF_SECRET_KEY, POLL_INTERVAL
from .history_probe import append_history_probe_records
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
            result = await self.client.async_read_status()
            if result.history_records:
                try:
                    await self.hass.async_add_executor_job(
                        append_history_probe_records,
                        self.hass.config.config_dir,
                        result.history_records,
                    )
                except OSError:
                    _LOGGER.warning("Unable to write protected history probe")
            return result.status
        except SesameConnectionError as err:
            raise UpdateFailed(str(err)) from err
