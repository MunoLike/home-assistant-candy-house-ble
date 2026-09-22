"""Read-only helpers for inspecting a Remote Nano before provisioning.

This module can authenticate and observe the automatically published target
list.  It deliberately has no add-target, remove-target, or generic command
builder.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.core import HomeAssistant

from .const import (
    CONNECT_TIMEOUT,
    DISCONNECT_TIMEOUT,
    MODEL_REMOTE_NANO,
    NOTIFY_CHARACTERISTIC_UUID,
    STATUS_TIMEOUT,
    WRITE_CHARACTERISTIC_UUID,
)
from .discovery import async_resolve_service_info
from .protocol import (
    ITEM_INITIAL,
    ITEM_LOGIN,
    OP_PUBLISH,
    OP_RESPONSE,
    ProtocolError,
    SegmentReceiver,
    SesameSessionCipher,
    build_login_packet,
    parse_notification,
)
from .session import get_ble_session_gate

ITEM_TARGET_LIST = 102
TARGET_SLOT_SIZE = 23


class RemoteNanoReadError(Exception):
    """Raised when the read-only Remote Nano inspection fails."""


@dataclass(frozen=True, slots=True)
class RemoteNanoTargetSummary:
    """Redacted target-slot counts with no device identifiers."""

    total_slots: int
    occupied_slots: int
    os3_slots: int
    legacy_slots: int

    @property
    def empty(self) -> bool:
        """Return whether the Remote contains no active target."""
        return self.occupied_slots == 0


def parse_remote_nano_target_summary(payload: bytes) -> RemoteNanoTargetSummary:
    """Reduce fixed 23-byte target records to non-sensitive counts."""
    if not payload or len(payload) % TARGET_SLOT_SIZE != 0:
        raise ProtocolError("Invalid Remote Nano target-list payload")
    slots = tuple(
        payload[index : index + TARGET_SLOT_SIZE]
        for index in range(0, len(payload), TARGET_SLOT_SIZE)
    )
    occupied = tuple(slot for slot in slots if slot[22] != 0)
    os3_slots = sum(slot[21] == 0 for slot in occupied)
    return RemoteNanoTargetSummary(
        total_slots=len(slots),
        occupied_slots=len(occupied),
        os3_slots=os3_slots,
        legacy_slots=len(occupied) - os3_slots,
    )


class RemoteNanoTargetReader:
    """Authenticate once, receive item 102, and disconnect."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: bytes,
        secret_key: bytes,
    ) -> None:
        if len(device_id) != 16 or len(secret_key) != 16:
            raise RemoteNanoReadError("Invalid Remote Nano credential")
        self._hass = hass
        self._device_id = device_id
        self._secret_key = secret_key
        self._session_gate = get_ble_session_gate(hass)
        self._receiver = SegmentReceiver()
        self._cipher: SesameSessionCipher | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._login_event = asyncio.Event()
        self._notify_ready_event = asyncio.Event()
        self._target_event = asyncio.Event()
        self._summary: RemoteNanoTargetSummary | None = None
        self._error: Exception | None = None
        self._notification_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._generation = 0

    async def async_read(self) -> RemoteNanoTargetSummary:
        """Read one redacted target-list summary without sending a command."""
        async with self._session_gate.command():
            return await self._async_read_locked()

    async def _async_read_locked(self) -> RemoteNanoTargetSummary:
        """Read target slots while holding the shared BLE adapter gate."""
        service_info = await async_resolve_service_info(
            self._hass, MODEL_REMOTE_NANO, self._device_id
        )
        if service_info is None:
            raise RemoteNanoReadError(
                "Remote Nano is not reachable by a connectable scanner"
            )

        self._generation += 1
        generation = self._generation
        self._receiver = SegmentReceiver()
        self._cipher = None
        self._summary = None
        self._error = None
        self._notify_ready_event = asyncio.Event()
        self._login_event.clear()
        self._target_event.clear()
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    service_info.device,
                    "Remote Nano read-only inspection",
                    disconnected_callback=lambda client: self._on_disconnect(
                        generation, client
                    ),
                    max_attempts=3,
                    use_services_cache=False,
                )
            await self._client.start_notify(
                NOTIFY_CHARACTERISTIC_UUID,
                lambda sender, data: self._on_notification(
                    generation, sender, data
                ),
            )
            self._notify_ready_event.set()
            async with asyncio.timeout(STATUS_TIMEOUT):
                await self._login_event.wait()
            self._raise_notification_error()
            async with asyncio.timeout(STATUS_TIMEOUT):
                await self._target_event.wait()
            self._raise_notification_error()
            if self._summary is None:
                raise RemoteNanoReadError(
                    "Remote Nano disconnected before publishing target slots"
                )
            return self._summary
        except TimeoutError as err:
            raise RemoteNanoReadError(
                "Timed out waiting for Remote Nano target slots"
            ) from err
        except RemoteNanoReadError:
            raise
        except Exception as err:
            raise RemoteNanoReadError(
                "Unable to inspect Remote Nano target slots"
            ) from err
        finally:
            await self._async_disconnect()

    def _raise_notification_error(self) -> None:
        if self._error is not None:
            raise RemoteNanoReadError(
                "Remote Nano notification failed"
            ) from self._error

    def _on_notification(
        self, generation: int, _sender: Any, data: bytearray
    ) -> None:
        if generation != self._generation:
            return
        task = self._hass.async_create_task(
            self._async_handle_notification(generation, bytes(data)),
            "candy_house_ble Remote Nano read-only notification",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _async_handle_notification(
        self, generation: int, data: bytes
    ) -> None:
        if generation != self._generation:
            return
        async with self._notification_lock:
            if generation != self._generation:
                return
            try:
                completed = self._receiver.feed(data)
                if completed is None:
                    return
                segment_type, payload = completed
                notification = parse_notification(
                    segment_type, payload, self._cipher
                )
                if (
                    notification.opcode == OP_PUBLISH
                    and notification.item_code == ITEM_INITIAL
                ):
                    if len(notification.payload) != 4:
                        raise ProtocolError("Invalid Remote Nano initial token")
                    await self._notify_ready_event.wait()
                    if generation != self._generation:
                        return
                    packet, self._cipher = build_login_packet(
                        self._secret_key, notification.payload
                    )
                    if self._client is None:
                        raise RemoteNanoReadError(
                            "Remote Nano connection disappeared"
                        )
                    # Login is the sole outbound packet in this class.
                    await self._client.write_gatt_char(
                        WRITE_CHARACTERISTIC_UUID, packet, response=False
                    )
                    return
                if (
                    notification.opcode == OP_RESPONSE
                    and notification.item_code == ITEM_LOGIN
                ):
                    if notification.result_code != 0:
                        raise RemoteNanoReadError(
                            "Remote Nano rejected the manager credential"
                        )
                    self._login_event.set()
                    return
                if (
                    notification.opcode == OP_PUBLISH
                    and notification.item_code == ITEM_TARGET_LIST
                ):
                    self._summary = parse_remote_nano_target_summary(
                        notification.payload
                    )
                    self._target_event.set()
            except Exception as err:
                self._error = err
                self._login_event.set()
                self._target_event.set()

    def _on_disconnect(
        self,
        generation: int,
        _client: BleakClientWithServiceCache,
    ) -> None:
        if generation != self._generation:
            return
        self._notify_ready_event.set()
        self._login_event.set()
        self._target_event.set()

    async def _async_disconnect(self) -> None:
        self._generation += 1
        self._notify_ready_event.set()
        client, self._client = self._client, None
        if client is None:
            return
        if not client.is_connected:
            return
        try:
            async with asyncio.timeout(DISCONNECT_TIMEOUT):
                await client.disconnect()
        except Exception:
            pass
