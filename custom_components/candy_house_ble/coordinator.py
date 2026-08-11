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
    BOT_2_BLE_REFRESH_DELAY,
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
    MODEL_BOT_2,
    MODEL_SESAME_5_PRO,
    POLL_INTERVAL,
)
from .protocol import MechanismStatus

_LOGGER = logging.getLogger(__name__)


def command_configuration_for_model(
    model: int, options: dict
) -> tuple[str, bool]:
    """Return command options only for the supported lock model."""
    if model != MODEL_SESAME_5_PRO:
        return COMMAND_TRANSPORT_BLE, False
    return (
        options.get(CONF_COMMAND_TRANSPORT, COMMAND_TRANSPORT_BLE),
        options.get(CONF_CLOUD_UNLOCK_ENABLED, False),
    )


class SesameStatusCoordinator(DataUpdateCoordinator[MechanismStatus]):
    """Poll a SESAME briefly so other BLE clients are not blocked."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        options = getattr(entry, "options", {})
        self.model = entry.data[CONF_MODEL]
        (
            self.command_transport,
            self.cloud_unlock_enabled,
        ) = command_configuration_for_model(
            self.model,
            options,
        )
        self.cloud_client: SesameCloudCommandClient | None = None
        self._cloud_refresh_task: asyncio.Task[None] | None = None
        self._bot_refresh_task: asyncio.Task[None] | None = None
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
        if self.cloud_client is not None:
            before = self._require_current_status()
            await self._async_cloud_actuate(
                lambda: self.cloud_client.async_lock(before)
            )
            self._schedule_cloud_refresh()
            return
        await self._async_actuate(self.client.async_lock)

    async def async_unlock(self) -> None:
        """Unlock the SESAME and refresh its observed state."""
        self._require_lock_model()
        if self.cloud_client is not None:
            if not self.cloud_unlock_enabled:
                raise HomeAssistantError(
                    "Remote unlock is disabled in CANDY HOUSE BLE options"
                )
            before = self._require_current_status()
            await self._async_cloud_actuate(
                lambda: self.cloud_client.async_unlock(before)
            )
            self._schedule_cloud_refresh()
            return
        await self._async_actuate(self.client.async_unlock)

    async def async_run_script(self, script_index: int) -> None:
        """Run one Bot 2 script slot once and refresh observed status."""
        if self.model != MODEL_BOT_2:
            raise HomeAssistantError(
                "Bot 2 scripts are not supported for this device"
            )
        try:
            await self.client.async_run_script(script_index)
        except SesameConnectionError as err:
            self.async_set_update_error(err)
            raise HomeAssistantError(str(err)) from err
        self._schedule_bot_refresh()

    def _require_lock_model(self) -> None:
        """Reject physical lock commands for every non-lock device."""
        if self.model != MODEL_SESAME_5_PRO:
            raise HomeAssistantError(
                "Physical lock commands are not supported for this device"
            )

    async def _async_cloud_actuate(
        self, operation: Callable[[], Awaitable[MechanismStatus]]
    ) -> None:
        """Run a cloud command while reserving the local BLE operation slot."""

        async def reserved_operation() -> MechanismStatus:
            async with self.client.async_external_command():
                return await operation()

        await self._async_actuate(reserved_operation)

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

    def _schedule_bot_refresh(self) -> None:
        """Refresh Bot 2 status after acknowledging a physical action."""
        self._cancel_bot_refresh()
        task = self.hass.async_create_task(
            self._async_delayed_bot_refresh(),
            "candy_house_ble Bot 2 post-script refresh",
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
            _LOGGER.debug("Post-script Bot 2 refresh deferred: %s", err)
            return
        self.async_set_updated_data(status)

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

    def _clear_bot_refresh_task(self, task: asyncio.Task[None]) -> None:
        """Forget a completed Bot 2 refresh task."""
        if self._bot_refresh_task is task:
            self._bot_refresh_task = None

    def _cancel_cloud_refresh(self) -> None:
        """Cancel a pending delayed refresh during replacement or unload."""
        if self._cloud_refresh_task is not None:
            self._cloud_refresh_task.cancel()
            self._cloud_refresh_task = None

    def _cancel_bot_refresh(self) -> None:
        """Cancel a pending Bot 2 refresh during replacement or unload."""
        if self._bot_refresh_task is not None:
            self._bot_refresh_task.cancel()
            self._bot_refresh_task = None

    def _cancel_delayed_refreshes(self) -> None:
        """Cancel all model-specific delayed refresh tasks."""
        self._cancel_cloud_refresh()
        self._cancel_bot_refresh()
