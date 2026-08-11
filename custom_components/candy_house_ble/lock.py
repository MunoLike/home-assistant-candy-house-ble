"""Lock entity for CANDY HOUSE BLE."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CandyHouseConfigEntry
from .entity import CandyHouseEntity
from .protocol import LockState


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the primary SESAME lock entity."""
    async_add_entities([SesameLock(entry)])


class SesameLock(CandyHouseEntity, LockEntity):
    """Represent and operate a SESAME lock over local BLE."""

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "lock")
        self._pending_operation: str | None = None

    @property
    def is_locked(self) -> bool | None:
        """Return whether the SESAME is in its configured lock range."""
        if self.coordinator.data is None:
            return None
        if self.coordinator.data.state is LockState.LOCKED:
            return True
        if self.coordinator.data.state is LockState.UNLOCKED:
            return False
        return None

    @property
    def is_locking(self) -> bool:
        """Return whether a lock command is in progress."""
        return self._pending_operation == "lock"

    @property
    def is_unlocking(self) -> bool:
        """Return whether an unlock command is in progress."""
        return self._pending_operation == "unlock"

    @property
    def is_jammed(self) -> bool:
        """Return whether the mechanism reports a critical motor error."""
        return bool(
            self.coordinator.data is not None
            and self.coordinator.data.critical
        )

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the SESAME."""
        del kwargs
        await self._async_run_operation("lock", self.coordinator.async_lock)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the SESAME."""
        del kwargs
        await self._async_run_operation(
            "unlock", self.coordinator.async_unlock
        )

    async def _async_run_operation(
        self,
        operation: str,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        """Expose an in-progress state while one BLE operation runs."""
        if self._pending_operation is not None:
            raise HomeAssistantError(
                "Another SESAME lock operation is already in progress"
            )
        self._pending_operation = operation
        self.async_write_ha_state()
        try:
            await action()
        finally:
            self._pending_operation = None
            self.async_write_ha_state()
