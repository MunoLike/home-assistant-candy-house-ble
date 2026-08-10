"""One-shot, read-only SESAME 5 Pro BLE client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.core import HomeAssistant

from .const import (
    CONNECT_TIMEOUT,
    NOTIFY_CHARACTERISTIC_UUID,
    STATUS_TIMEOUT,
    WRITE_CHARACTERISTIC_UUID,
)
from .discovery import async_resolve_service_info
from .protocol import (
    ITEM_INITIAL,
    ITEM_LOGIN,
    ITEM_MECH_STATUS,
    OP_PUBLISH,
    OP_RESPONSE,
    MechanismStatus,
    ProtocolError,
    ReadOnlyCipher,
    SegmentReceiver,
    build_login_packet,
    parse_mechanism_status,
    parse_notification,
)

_LOGGER = logging.getLogger(__name__)


class SesameConnectionError(Exception):
    """Raised when a read-only BLE status fetch fails."""


class SesameStatusClient:
    """Connect, authenticate, receive current status, and disconnect."""

    def __init__(
        self,
        hass: HomeAssistant,
        model: int,
        device_id: bytes,
        secret_key: bytes,
        name: str,
    ) -> None:
        self._hass = hass
        self._model = model
        self._device_id = device_id
        self._secret_key = secret_key
        self._name = name
        self._receiver = SegmentReceiver()
        self._cipher: ReadOnlyCipher | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._status_event = asyncio.Event()
        self._status: MechanismStatus | None = None
        self._notification_lock = asyncio.Lock()
        self._notification_tasks: set[asyncio.Task[None]] = set()
        self._notification_error: Exception | None = None
        self._operation_lock = asyncio.Lock()

    async def async_read_status(self) -> MechanismStatus:
        """Fetch one authenticated mechanism status through HA Bluetooth."""
        async with self._operation_lock:
            return await self._async_read_status_locked()

    async def _async_read_status_locked(self) -> MechanismStatus:
        """Fetch status while holding the single-connection lock."""
        service_info = await async_resolve_service_info(
            self._hass, self._model, self._device_id
        )
        if service_info is None:
            raise SesameConnectionError(
                "SESAME is not reachable by a connectable scanner"
            )

        self._receiver = SegmentReceiver()
        self._cipher = None
        self._status = None
        self._notification_error = None
        self._status_event.clear()

        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    service_info.device,
                    self._name,
                    disconnected_callback=self._on_disconnect,
                    max_attempts=3,
                )
            await self._client.start_notify(
                NOTIFY_CHARACTERISTIC_UUID, self._on_notification
            )

            async with asyncio.timeout(STATUS_TIMEOUT):
                await self._status_event.wait()

            if self._notification_error is not None:
                raise self._notification_error
            if self._status is None:
                raise SesameConnectionError(
                    "SESAME disconnected before publishing status"
                )
            return self._status
        except TimeoutError as err:
            raise SesameConnectionError(
                "Timed out waiting for SESAME status"
            ) from err
        except SesameConnectionError:
            raise
        except Exception as err:
            raise SesameConnectionError("Unable to read SESAME status") from err
        finally:
            await self._async_disconnect()

    def _on_notification(self, _sender: Any, data: bytearray) -> None:
        task = self._hass.async_create_task(
            self._async_handle_notification(bytes(data)),
            "candy_house_ble notification",
        )
        self._notification_tasks.add(task)
        task.add_done_callback(self._notification_tasks.discard)

    async def _async_handle_notification(self, data: bytes) -> None:
        async with self._notification_lock:
            try:
                completed = self._receiver.feed(data)
                if completed is None:
                    return
                segment_type, payload = completed
                notification = parse_notification(segment_type, payload, self._cipher)

                if (
                    notification.opcode == OP_PUBLISH
                    and notification.item_code == ITEM_INITIAL
                ):
                    if len(notification.payload) != 4:
                        raise ProtocolError("Invalid SESAME initial token")
                    login_packet, self._cipher = build_login_packet(
                        self._secret_key, notification.payload
                    )
                    if self._client is None:
                        raise SesameConnectionError("SESAME connection disappeared")
                    await self._client.write_gatt_char(
                        WRITE_CHARACTERISTIC_UUID, login_packet, response=False
                    )
                    return

                if (
                    notification.opcode == OP_RESPONSE
                    and notification.item_code == ITEM_LOGIN
                    and notification.result_code != 0
                ):
                    raise SesameConnectionError(
                        "SESAME rejected the manager credential"
                    )

                if (
                    notification.opcode == OP_PUBLISH
                    and notification.item_code == ITEM_MECH_STATUS
                ):
                    self._status = parse_mechanism_status(notification.payload)
                    self._status_event.set()
            except Exception as err:
                self._notification_error = err
                self._status_event.set()

    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        self._status_event.set()

    async def _async_disconnect(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            _LOGGER.debug("Error disconnecting from SESAME", exc_info=True)
