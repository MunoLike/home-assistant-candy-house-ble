"""Optional fixed-command client for the CANDY HOUSE public Web API."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, replace
from uuid import UUID

import aiohttp
from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import algorithms

from .const import (
    CLOUD_API_BASE_URL,
    CLOUD_API_TIMEOUT,
    CLOUD_CONFIRM_ATTEMPTS,
    CLOUD_CONFIRM_DELAY,
    CLOUD_HISTORY_TAG,
)
from .protocol import ITEM_LOCK, ITEM_UNLOCK, LockState, MechanismStatus


class SesameCloudError(Exception):
    """Base error for the optional SESAME cloud command path."""


class SesameCloudAuthenticationError(SesameCloudError):
    """The public API rejected its credentials."""


class SesameCloudConnectionError(SesameCloudError):
    """The public API could not be reached."""


class SesameCloudApiError(SesameCloudError):
    """The public API returned an invalid response."""


class SesameCloudRateLimitError(SesameCloudApiError):
    """The public API quota was reached."""


class SesameCloudHubOfflineError(SesameCloudError):
    """Hub 3 is reported offline."""


class SesameCloudCommandNotConfirmedError(SesameCloudError):
    """The cloud accepted a command without a fresh matching shadow."""


def normalize_cloud_secret_key(value: str) -> str:
    """Validate and normalize a 128-bit Web API device secret."""
    try:
        key = bytes.fromhex(value.strip())
    except (AttributeError, TypeError, ValueError) as err:
        raise ValueError(
            "cloud device secret must be 32 hexadecimal characters"
        ) from err
    if len(key) != 16:
        raise ValueError(
            "cloud device secret must be 32 hexadecimal characters"
        )
    return key.hex()


def _normalize_timestamp(value: object) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    timestamp = int(value)
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return timestamp


@dataclass(frozen=True, slots=True)
class SesameCloudStatus:
    """Fields needed to confirm one Web API command."""

    state: LockState
    timestamp: int | None
    hub_online: bool | None
    position: int | None

    @classmethod
    def from_payload(cls, payload: object) -> SesameCloudStatus:
        """Normalize a CANDY HOUSE cloud shadow."""
        if not isinstance(payload, dict):
            raise SesameCloudApiError(
                "CANDY HOUSE API returned an invalid status payload"
            )
        try:
            state = LockState(payload.get("CHSesame2Status"))
        except (TypeError, ValueError) as err:
            raise SesameCloudApiError(
                "CANDY HOUSE API status is missing lock state"
            ) from err
        hub_online = payload.get("wm2State")
        if not isinstance(hub_online, bool):
            hub_online = None
        raw_position = payload.get("position")
        position = (
            int(raw_position)
            if isinstance(raw_position, (int, float))
            and not isinstance(raw_position, bool)
            else None
        )
        return cls(
            state=state,
            timestamp=_normalize_timestamp(payload.get("timestamp")),
            hub_online=hub_online,
            position=position,
        )


class SesameCloudCommandClient:
    """Send only fixed lock/unlock commands and confirm their cloud shadow."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        device_uuid: str,
        secret_key: str,
        *,
        base_url: str = CLOUD_API_BASE_URL,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("cloud API key is required")
        self._session = session
        self._api_key = api_key.strip()
        self._device_uuid = str(UUID(device_uuid.strip())).upper()
        self._secret_key = bytes.fromhex(normalize_cloud_secret_key(secret_key))
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=CLOUD_API_TIMEOUT)
        self._operation_lock = asyncio.Lock()

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key}

    def generate_sign(self, timestamp: int | None = None) -> str:
        """Generate the documented AES-CMAC timestamp signature."""
        unix_seconds = int(time.time()) if timestamp is None else int(timestamp)
        message = unix_seconds.to_bytes(4, "little", signed=False)[1:4]
        signer = cmac.CMAC(algorithms.AES(self._secret_key))
        signer.update(message)
        return signer.finalize().hex()

    async def _async_request(
        self,
        method: str,
        suffix: str = "",
        *,
        payload: dict[str, object] | None = None,
    ) -> object:
        url = f"{self._base_url}/{self._device_uuid}{suffix}"
        try:
            async with self._session.request(
                method,
                url,
                headers=self._headers,
                json=payload,
                timeout=self._timeout,
            ) as response:
                if response.status in (401, 403):
                    raise SesameCloudAuthenticationError(
                        "CANDY HOUSE API rejected the cloud credentials"
                    )
                if response.status == 429:
                    raise SesameCloudRateLimitError(
                        "CANDY HOUSE API rate limit reached"
                    )
                if response.status >= 400:
                    raise SesameCloudApiError(
                        f"CANDY HOUSE API returned HTTP {response.status}"
                    )
                body = await response.text()
        except (SesameCloudAuthenticationError, SesameCloudApiError):
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SesameCloudConnectionError(
                "Unable to reach CANDY HOUSE API"
            ) from err

        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as err:
            raise SesameCloudApiError(
                "CANDY HOUSE API returned invalid JSON"
            ) from err

    async def async_get_status(self) -> SesameCloudStatus:
        """Fetch the current cloud shadow without moving the lock."""
        return SesameCloudStatus.from_payload(await self._async_request("GET"))

    async def async_lock(self, before: MechanismStatus) -> MechanismStatus:
        """Send and confirm the fixed lock command."""
        return await self._async_execute(ITEM_LOCK, LockState.LOCKED, before)

    async def async_unlock(self, before: MechanismStatus) -> MechanismStatus:
        """Send and confirm the fixed unlock command."""
        return await self._async_execute(
            ITEM_UNLOCK, LockState.UNLOCKED, before
        )

    async def _async_execute(
        self,
        command: int,
        target: LockState,
        before: MechanismStatus,
        *,
        timestamp: int | None = None,
    ) -> MechanismStatus:
        """Send once, then confirm a fresh target state without command retry."""
        async with self._operation_lock:
            command_timestamp = (
                int(time.time()) if timestamp is None else int(timestamp)
            )
            response = await self._async_request(
                "POST",
                "/cmd",
                payload={
                    "cmd": command,
                    "history": base64.b64encode(
                        CLOUD_HISTORY_TAG.encode()
                    ).decode(),
                    "sign": self.generate_sign(command_timestamp),
                },
            )
            if (
                isinstance(response, dict)
                and "statusCode" in response
                and response["statusCode"] != 200
            ):
                raise SesameCloudApiError(
                    "CANDY HOUSE cloud did not accept the command"
                )

            for _attempt in range(CLOUD_CONFIRM_ATTEMPTS):
                await asyncio.sleep(CLOUD_CONFIRM_DELAY)
                status = await self.async_get_status()
                if status.hub_online is False:
                    raise SesameCloudHubOfflineError(
                        "CANDY HOUSE cloud reports that Hub 3 is offline"
                    )
                is_fresh = (
                    status.timestamp is not None
                    and status.timestamp >= command_timestamp
                )
                if is_fresh and status.state is target:
                    return replace(
                        before,
                        state=target,
                        target=None,
                        position=(
                            status.position
                            if status.position is not None
                            else before.position
                        ),
                        stopped=True,
                    )
            raise SesameCloudCommandNotConfirmedError(
                "CANDY HOUSE cloud accepted the command but no fresh matching "
                "lock state was observed"
            )
