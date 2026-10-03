"""One-shot SESAME OS3 BLE status and fixed actuation client."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import replace
from time import monotonic
from typing import Any

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.core import HomeAssistant

from .const import (
    BOT_2_COMMAND_COOLDOWN,
    BOT_2_INDETERMINATE_COOLDOWN,
    BOT_MODELS,
    COMMAND_COMPLETION_TIMEOUT,
    COMMAND_TIMEOUT,
    CONNECT_TIMEOUT,
    DISCONNECT_TIMEOUT,
    LOCK_MODELS,
    NOTIFY_CHARACTERISTIC_UUID,
    NOTIFY_TIMEOUT,
    STATUS_TIMEOUT,
    WRITE_CHARACTERISTIC_UUID,
)
from .discovery import async_resolve_service_info
from .metrics import BLERuntimeMetrics
from .protocol import (
    ITEM_INITIAL,
    ITEM_LOCK,
    ITEM_LOGIN,
    ITEM_MECH_STATUS,
    ITEM_UNLOCK,
    OP_PUBLISH,
    OP_RESPONSE,
    LockState,
    MechanismStatus,
    ProtocolError,
    SegmentReceiver,
    SesameSessionCipher,
    bot_2_run_script_item_code,
    build_bot_2_run_script_packet,
    build_lock_packet,
    build_login_packet,
    build_unlock_packet,
    parse_bot_2_mechanism_status,
    parse_mechanism_status,
    parse_notification,
)
from .session import SesameBLESessionGate

_LOGGER = logging.getLogger(__name__)


class SesameConnectionError(Exception):
    """Raised when a constrained BLE status or operation session fails."""


class SesameTransientConnectionError(SesameConnectionError):
    """A status read may recover by opening one fresh BLE session."""


class SesamePollPreempted(Exception):
    """Raised when a UI operation supersedes a background status poll."""


def service_info_rssi(service_info: Any) -> int | None:
    """Return optional RSSI without making mechanism status depend on it."""
    try:
        value = service_info.rssi
    except Exception:
        _LOGGER.debug("Bluetooth service information has no usable RSSI", exc_info=True)
        return None
    return value if isinstance(value, int) else None


class SesameStatusClient:
    """Connect, authenticate, receive current status, and disconnect."""

    def __init__(
        self,
        hass: HomeAssistant,
        model: int,
        device_id: bytes,
        secret_key: bytes,
        name: str,
        session_gate: SesameBLESessionGate | None = None,
    ) -> None:
        self._hass = hass
        self._model = model
        self._device_id = device_id
        self._secret_key = secret_key
        self._name = name
        self._session_gate = session_gate or SesameBLESessionGate()
        self._receiver = SegmentReceiver()
        self._cipher: SesameSessionCipher | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._login_event = asyncio.Event()
        self._notify_ready_event = asyncio.Event()
        self._status_event = asyncio.Event()
        self._command_event = asyncio.Event()
        self._status_queue: asyncio.Queue[MechanismStatus | None] = asyncio.Queue()
        self._status: MechanismStatus | None = None
        self._expected_command_item: int | None = None
        self._command_result: int | None = None
        self._notification_lock = asyncio.Lock()
        self._notification_tasks: set[asyncio.Task[None]] = set()
        self._notification_error: Exception | None = None
        self._last_notification: tuple[int, int, int] | None = None
        self._operation_lock = asyncio.Lock()
        self._actuation_lock = asyncio.Lock()
        self._poll_active = False
        self._poll_preempted = False
        self._poll_preempt_event = asyncio.Event()
        self._session_generation = 0
        self._bot_command_blocked_until = 0.0
        self._metrics = BLERuntimeMetrics()

    def diagnostics_snapshot(self) -> dict[str, Any]:
        """Return aggregate, non-sensitive metrics for this runtime."""
        return self._metrics.snapshot()

    async def async_read_status(self) -> MechanismStatus:
        """Fetch one authenticated mechanism status through HA Bluetooth."""
        started_at = monotonic()
        self._metrics.operation_started("poll")
        try:
            if self._actuation_lock.locked():
                raise SesamePollPreempted
            self._poll_active = True
            self._poll_preempted = False
            self._poll_preempt_event.clear()
            try:
                for attempt in range(2):
                    try:
                        async with (
                            self._session_gate.poll(self._preempt_poll),
                            self._operation_lock,
                        ):
                            if (
                                self._actuation_lock.locked()
                                or self._poll_preempted
                            ):
                                raise SesamePollPreempted
                            status = await self._async_read_status_locked()
                    except SesameTransientConnectionError:
                        if attempt:
                            raise
                        # Retry only read-only status. Release the adapter
                        # between attempts so operations still have priority.
                    else:
                        break
            finally:
                self._poll_active = False
        except SesamePollPreempted:
            self._metrics.operation_preempted("poll")
            raise
        except asyncio.CancelledError:
            self._metrics.operation_cancelled("poll")
            raise
        except Exception as err:
            self._metrics.operation_failed("poll", err)
            raise
        self._metrics.operation_succeeded("poll", monotonic() - started_at)
        return status

    async def async_lock(self) -> MechanismStatus:
        """Send the fixed SESAME lock command."""
        self._require_lock_model()
        return await self._async_recorded_status_operation(
            "lock",
            lambda: self._async_actuate(
                ITEM_LOCK, build_lock_packet, LockState.LOCKED
            ),
        )

    async def async_unlock(self) -> MechanismStatus:
        """Send the fixed SESAME unlock command."""
        self._require_lock_model()
        return await self._async_recorded_status_operation(
            "unlock",
            lambda: self._async_actuate(
                ITEM_UNLOCK, build_unlock_packet, LockState.UNLOCKED
            ),
        )

    async def async_run_script(self, script_index: int) -> None:
        """Run one allowlisted Bot 2/3 on-device script slot once."""
        started_at = monotonic()
        self._metrics.operation_started("bot_script")
        try:
            await self._async_run_script(script_index)
        except asyncio.CancelledError:
            self._metrics.operation_cancelled("bot_script")
            raise
        except Exception as err:
            self._metrics.operation_failed("bot_script", err)
            raise
        self._metrics.operation_succeeded(
            "bot_script", monotonic() - started_at
        )

    async def _async_run_script(self, script_index: int) -> None:
        """Run one Bot 2/3 script inside the metrics boundary."""
        if self._model not in BOT_MODELS:
            raise SesameConnectionError(
                "Bot 2/3 scripts are not supported for this device"
            )
        try:
            item_code = bot_2_run_script_item_code(script_index)
        except ProtocolError as err:
            raise SesameConnectionError(str(err)) from err
        if monotonic() < self._bot_command_blocked_until:
            raise SesameConnectionError(
                "Bot 2/3 command cooldown is active; do not retry yet"
            )
        if self._actuation_lock.locked():
            raise SesameConnectionError(
                "Another SESAME operation is already in progress"
            )
        async with self._actuation_lock:
            self._preempt_poll()
            async with self._session_gate.command(), self._operation_lock:
                await self._async_execute_acknowledged_bot_script(
                    script_index, item_code
                )

    async def _async_recorded_status_operation(
        self,
        name: str,
        operation: Callable[[], Awaitable[MechanismStatus]],
    ) -> MechanismStatus:
        """Record one explicit lock operation without retrying it."""
        started_at = monotonic()
        self._metrics.operation_started(name)
        try:
            status = await operation()
        except asyncio.CancelledError:
            self._metrics.operation_cancelled(name)
            raise
        except Exception as err:
            self._metrics.operation_failed(name, err)
            raise
        self._metrics.operation_succeeded(name, monotonic() - started_at)
        return status

    def _require_lock_model(self) -> None:
        """Prevent non-lock devices from reaching physical commands."""
        if self._model not in LOCK_MODELS:
            raise SesameConnectionError(
                "Physical lock commands are not supported for this device"
            )

    async def _async_actuate(
        self,
        item_code: int,
        packet_builder: Callable[[SesameSessionCipher], bytes],
        desired_state: LockState,
    ) -> MechanismStatus:
        """Reject duplicate requests, then serialize against status polling."""
        if self._actuation_lock.locked():
            raise SesameConnectionError(
                "Another SESAME lock operation is already in progress"
            )
        async with self._actuation_lock:
            self._preempt_poll()
            async with self._session_gate.command(), self._operation_lock:
                return await self._async_execute_command(
                    item_code, packet_builder, desired_state
                )

    def _preempt_poll(self) -> None:
        """Wake and cancel an active background poll before actuation."""
        if self._poll_active:
            self._poll_preempted = True
            self._poll_preempt_event.set()
            self._status_event.set()

    async def _async_read_status_locked(self) -> MechanismStatus:
        """Fetch status while holding the single-connection lock."""
        try:
            service_info = await self._async_connect_for_poll()

            if self._poll_preempted:
                raise SesamePollPreempted

            async with asyncio.timeout(STATUS_TIMEOUT):
                await self._status_event.wait()

            if self._poll_preempted:
                raise SesamePollPreempted
            if self._notification_error is not None:
                raise self._notification_error
            if self._status is None:
                raise SesameTransientConnectionError(
                    "SESAME disconnected before publishing status"
                )
            return replace(self._status, rssi=service_info_rssi(service_info))
        except TimeoutError as err:
            raise SesameTransientConnectionError(
                "Timed out waiting for SESAME status"
                f"{self._notification_context()}"
            ) from err
        except SesamePollPreempted:
            raise
        except SesameConnectionError:
            raise
        except Exception as err:
            raise SesameConnectionError(
                "Unable to read SESAME status: "
                f"{type(err).__name__}: {err}"
            ) from err
        finally:
            await self._async_disconnect()

    async def _async_connect_for_poll(self):
        """Connect for a poll, allowing an explicit operation to cancel it."""
        connect_task = asyncio.create_task(self._async_connect())
        preempt_task = asyncio.create_task(self._poll_preempt_event.wait())
        try:
            done, _pending = await asyncio.wait(
                (connect_task, preempt_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if preempt_task in done or self._poll_preempt_event.is_set():
                # Do not cancel start_notify while BlueZ is writing the CCC
                # descriptor.  That race can abort bluetoothd on low-end Pi
                # adapters.  Finish subscribing, then disconnect in the
                # caller's finally block before handing off the adapter.
                with suppress(Exception):
                    await connect_task
                raise SesamePollPreempted
            return await connect_task
        finally:
            if not connect_task.done():
                connect_task.cancel()
            preempt_task.cancel()
            await asyncio.gather(
                connect_task, preempt_task, return_exceptions=True
            )

    async def _async_execute_command(
        self,
        item_code: int,
        packet_builder: Callable[[SesameSessionCipher], bytes],
        desired_state: LockState,
    ) -> MechanismStatus:
        """Execute one allowlisted command and observe its terminal state."""
        started_at = monotonic()
        try:
            service_info = await self._async_connect()
            connected_at = monotonic()

            async with asyncio.timeout(STATUS_TIMEOUT):
                await self._login_event.wait()
            if self._notification_error is not None:
                raise self._notification_error
            if self._cipher is None or self._client is None:
                raise SesameConnectionError(
                    "SESAME disconnected before command authentication"
                )

            self._expected_command_item = item_code
            self._command_result = None
            self._command_event.clear()
            # Only statuses published after this command may complete it.
            self._status_queue = asyncio.Queue()
            packet = packet_builder(self._cipher)
            await self._client.write_gatt_char(
                WRITE_CHARACTERISTIC_UUID, packet, response=False
            )

            async with asyncio.timeout(COMMAND_TIMEOUT):
                await self._command_event.wait()
            if self._notification_error is not None:
                raise self._notification_error
            if self._command_result is None:
                raise SesameConnectionError(
                    "SESAME disconnected before acknowledging command"
                )
            if self._command_result != 0:
                raise SesameConnectionError(
                    f"SESAME rejected command with result {self._command_result}"
                )
            acknowledged_at = monotonic()

            try:
                async with asyncio.timeout(COMMAND_COMPLETION_TIMEOUT):
                    while True:
                        status = await self._status_queue.get()
                        if status is None:
                            raise SesameConnectionError(
                                "SESAME disconnected before reaching "
                                "the requested state"
                            )
                        if status.critical:
                            raise SesameConnectionError(
                                "SESAME reported a critical mechanism error"
                            )
                        if status.state is desired_state and status.stopped:
                            terminal = replace(
                                status, rssi=service_info_rssi(service_info)
                            )
                            completed_at = monotonic()
                            elapsed = completed_at - started_at
                            log = (
                                _LOGGER.warning
                                if elapsed >= 5.0
                                else _LOGGER.debug
                            )
                            log(
                                "SESAME %s completed in %.2fs "
                                "(connect %.2fs, acknowledge %.2fs, "
                                "terminal %.2fs, RSSI %s, source %s)",
                                desired_state.value,
                                elapsed,
                                connected_at - started_at,
                                acknowledged_at - connected_at,
                                completed_at - acknowledged_at,
                                terminal.rssi,
                                getattr(service_info, "source", "unknown"),
                            )
                            return terminal
                        if status.state is LockState.MOVED and status.stopped:
                            raise SesameConnectionError(
                                "SESAME stopped outside the requested lock range"
                            )
            except TimeoutError as err:
                raise SesameConnectionError(
                    "SESAME acknowledged the command but did not reach "
                    "the requested state"
                ) from err
        except TimeoutError as err:
            raise SesameConnectionError(
                "Timed out waiting for SESAME command acknowledgement"
                f"{self._notification_context()}"
            ) from err
        except SesameConnectionError:
            raise
        except Exception as err:
            raise SesameConnectionError(
                f"Unable to operate SESAME: {type(err).__name__}: {err}"
            ) from err
        finally:
            await self._async_disconnect()

    async def _async_execute_acknowledged_bot_script(
        self, script_index: int, item_code: int
    ) -> None:
        """Execute one fixed Bot 2/3 script and wait only for its response."""
        wrote_command = False
        try:
            await self._async_connect()
            async with asyncio.timeout(STATUS_TIMEOUT):
                await self._login_event.wait()
            if self._notification_error is not None:
                raise self._notification_error
            if self._cipher is None or self._client is None:
                raise SesameConnectionError(
                    "Bot 2/3 disconnected before command authentication"
                )

            self._expected_command_item = item_code
            self._command_result = None
            self._command_event.clear()
            packet = build_bot_2_run_script_packet(
                self._cipher, script_index
            )
            # A transport failure cannot prove whether the peripheral received
            # a write, so delivery becomes indeterminate before awaiting it.
            wrote_command = True
            await self._client.write_gatt_char(
                WRITE_CHARACTERISTIC_UUID, packet, response=False
            )
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await self._command_event.wait()
            if self._notification_error is not None:
                raise self._notification_error
            if self._command_result is None:
                raise SesameConnectionError(
                    "Bot 2/3 disconnected before acknowledging script"
                )
            if self._command_result != 0:
                raise SesameConnectionError(
                    "Bot 2/3 rejected script with result "
                    f"{self._command_result}"
                )
            self._bot_command_blocked_until = max(
                self._bot_command_blocked_until,
                monotonic() + BOT_2_COMMAND_COOLDOWN,
            )
        except TimeoutError as err:
            if wrote_command:
                self._block_indeterminate_bot_retry()
                raise SesameConnectionError(
                    "Bot 2/3 script may have executed but acknowledgement was "
                    "not observed; outcome is indeterminate"
                ) from err
            raise SesameConnectionError(
                "Timed out waiting for Bot 2/3 script authentication"
            ) from err
        except SesameConnectionError as err:
            if wrote_command and self._command_result is None:
                self._block_indeterminate_bot_retry()
                raise SesameConnectionError(
                    "Bot 2/3 script may have executed but acknowledgement was "
                    "not observed; outcome is indeterminate"
                ) from err
            raise
        except Exception as err:
            if wrote_command:
                self._block_indeterminate_bot_retry()
                raise SesameConnectionError(
                    "Bot 2/3 script may have executed but delivery could not be "
                    "confirmed; outcome is indeterminate"
                ) from err
            raise SesameConnectionError(
                "Unable to connect to Bot 2/3 before sending script; no command "
                "was sent"
            ) from err
        finally:
            await self._async_disconnect()

    def _block_indeterminate_bot_retry(self) -> None:
        """Prevent an immediate duplicate after ambiguous delivery."""
        self._bot_command_blocked_until = max(
            self._bot_command_blocked_until,
            monotonic() + BOT_2_INDETERMINATE_COOLDOWN,
        )

    async def _async_connect(self):
        """Resolve and connect while recording one session outcome."""
        started_at = monotonic()
        self._metrics.connection_started()
        try:
            service_info = await self._async_connect_untracked()
        except asyncio.CancelledError:
            self._metrics.connection_cancelled()
            raise
        except Exception as err:
            self._metrics.connection_failed(err)
            raise
        self._metrics.connection_succeeded(monotonic() - started_at)
        return service_info

    async def _async_connect_untracked(self):
        """Resolve, connect, and subscribe to one SESAME session."""
        service_info = await async_resolve_service_info(
            self._hass, self._model, self._device_id
        )
        if service_info is None:
            raise SesameConnectionError(
                "SESAME is not reachable by a connectable scanner"
            )

        self._session_generation += 1
        generation = self._session_generation
        self._receiver = SegmentReceiver()
        self._cipher = None
        self._status = None
        self._expected_command_item = None
        self._command_result = None
        self._notification_error = None
        self._last_notification = None
        self._notify_ready_event = asyncio.Event()
        self._login_event.clear()
        self._status_event.clear()
        self._command_event.clear()
        self._status_queue = asyncio.Queue()

        async with asyncio.timeout(CONNECT_TIMEOUT):
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                service_info.device,
                self._name,
                disconnected_callback=lambda client: self._on_disconnect(
                    generation, client
                ),
                max_attempts=3,
                # BlueZ removes these short-lived GATT object paths on every
                # disconnect. Reusing the Bleak service cache can therefore
                # target a stale WriteValue object on the next session.
                use_services_cache=False,
            )
        # A stalled BlueZ StartNotify call must not hold the adapter-wide
        # session gate forever and block every other SESAME device at setup.
        async with asyncio.timeout(NOTIFY_TIMEOUT):
            await self._client.start_notify(
                NOTIFY_CHARACTERISTIC_UUID,
                lambda sender, data: self._on_notification(
                    generation, sender, data
                ),
            )
        self._notify_ready_event.set()
        return service_info

    def _on_notification(
        self, generation: int, _sender: Any, data: bytearray
    ) -> None:
        if generation != self._session_generation:
            return
        task = self._hass.async_create_task(
            self._async_handle_notification(generation, bytes(data)),
            "candy_house_ble notification",
        )
        self._notification_tasks.add(task)
        task.add_done_callback(self._notification_tasks.discard)

    async def _async_handle_notification(
        self, generation: int, data: bytes
    ) -> None:
        if generation != self._session_generation:
            return
        async with self._notification_lock:
            if generation != self._session_generation:
                return
            try:
                completed = self._receiver.feed(data)
                if completed is None:
                    return
                segment_type, payload = completed
                notification = parse_notification(segment_type, payload, self._cipher)
                self._last_notification = (
                    notification.opcode,
                    notification.item_code,
                    len(notification.payload),
                )
                _LOGGER.debug(
                    "SESAME notification model=%d opcode=%d item=%d "
                    "payload_length=%d",
                    self._model,
                    notification.opcode,
                    notification.item_code,
                    len(notification.payload),
                )

                if (
                    notification.opcode == OP_PUBLISH
                    and notification.item_code == ITEM_INITIAL
                ):
                    if len(notification.payload) != 4:
                        raise ProtocolError("Invalid SESAME initial token")
                    # BlueZ can deliver the initial token before its
                    # StartNotify call has returned.  Wait for CCC setup to
                    # finish before writing login on the other characteristic.
                    await self._notify_ready_event.wait()
                    if generation != self._session_generation:
                        return
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
                ):
                    if notification.result_code != 0:
                        raise SesameConnectionError(
                            "SESAME rejected the manager credential"
                        )
                    self._login_event.set()
                    return

                if (
                    notification.opcode == OP_RESPONSE
                    and notification.item_code == self._expected_command_item
                ):
                    self._command_result = notification.result_code
                    self._command_event.set()
                    return

                if (
                    notification.opcode == OP_PUBLISH
                    and notification.item_code == ITEM_MECH_STATUS
                ):
                    self._status = (
                        parse_bot_2_mechanism_status(notification.payload)
                        if self._model in BOT_MODELS
                        else parse_mechanism_status(notification.payload)
                    )
                    self._status_event.set()
                    self._status_queue.put_nowait(self._status)
            except Exception as err:
                self._notification_error = err
                self._login_event.set()
                self._status_event.set()
                self._command_event.set()
                self._status_queue.put_nowait(None)

    def _on_disconnect(
        self,
        generation: int,
        client: BleakClientWithServiceCache,
    ) -> None:
        # Bleak may disconnect and retry before establish_connection returns.
        # Those callbacks must not wake status/login waiters or release the
        # notification barrier for the connection that eventually succeeds.
        if generation != self._session_generation or client is not self._client:
            return
        self._notify_ready_event.set()
        self._login_event.set()
        self._status_event.set()
        self._command_event.set()
        self._status_queue.put_nowait(None)

    async def _async_disconnect(self) -> None:
        self._session_generation += 1
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
            _LOGGER.debug("Error disconnecting from SESAME", exc_info=True)

    def _notification_context(self) -> str:
        """Describe the last decoded frame without retaining its payload."""
        if self._last_notification is None:
            return "; no notification was decoded"
        opcode, item_code, payload_length = self._last_notification
        return (
            f"; last notification opcode={opcode}, item={item_code}, "
            f"payload_length={payload_length}"
        )
