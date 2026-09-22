"""Adapter-wide arbitration for short-lived CANDY HOUSE BLE sessions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from homeassistant.core import HomeAssistant

from .const import BLE_SESSION_SETTLE_DELAY, DOMAIN

DATA_BLE_SESSION_GATE = "ble_session_gate"


class SesameBLESessionGate:
    """Allow only one GATT session and give explicit operations priority."""

    def __init__(self, settle_delay: float = 0.0) -> None:
        self._condition = asyncio.Condition()
        self._settle_delay = settle_delay
        self._active = False
        self._active_poll_preempt: Callable[[], None] | None = None
        self._command_waiters = 0

    @asynccontextmanager
    async def poll(
        self, preempt: Callable[[], None]
    ) -> AsyncIterator[None]:
        """Reserve the adapter for a background poll."""
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._active and self._command_waiters == 0
            )
            self._active = True
            self._active_poll_preempt = preempt
        try:
            yield
        finally:
            await self._release(preempt)

    @asynccontextmanager
    async def command(self) -> AsyncIterator[None]:
        """Reserve the adapter for an explicit operation, preempting a poll."""
        acquired = False
        async with self._condition:
            self._command_waiters += 1
            if self._active_poll_preempt is not None:
                self._active_poll_preempt()
            try:
                await self._condition.wait_for(lambda: not self._active)
                self._active = True
                acquired = True
            finally:
                self._command_waiters -= 1
                if not acquired:
                    self._condition.notify_all()
        try:
            yield
        finally:
            await self._release(None)

    async def _release(
        self, poll_preempt: Callable[[], None] | None
    ) -> None:
        """Release one session after BlueZ has time to finish GATT cleanup."""
        try:
            if self._settle_delay:
                await asyncio.sleep(self._settle_delay)
        finally:
            async with self._condition:
                self._active = False
                if self._active_poll_preempt is poll_preempt:
                    self._active_poll_preempt = None
                self._condition.notify_all()


def get_ble_session_gate(hass: HomeAssistant) -> SesameBLESessionGate:
    """Return the integration-wide session gate for this HA instance."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    gate = domain_data.get(DATA_BLE_SESSION_GATE)
    if not isinstance(gate, SesameBLESessionGate):
        gate = SesameBLESessionGate(BLE_SESSION_SETTLE_DELAY)
        domain_data[DATA_BLE_SESSION_GATE] = gate
    return gate
