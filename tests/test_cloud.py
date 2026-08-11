"""Tests for the optional fixed-command CANDY HOUSE cloud path."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from custom_components.candy_house_ble.cloud import (
    SesameCloudApiError,
    SesameCloudAuthenticationError,
    SesameCloudCommandClient,
    SesameCloudRateLimitError,
    normalize_cloud_secret_key,
)
from custom_components.candy_house_ble.protocol import (
    ITEM_LOCK,
    ITEM_UNLOCK,
    LockState,
    MechanismStatus,
)

DEVICE_UUID = "12345678-1234-5678-1234-567812345678"
SECRET_KEY = "00000000000000000000000000000000"
API_KEY = "synthetic-api-key"
BASE_URL = "https://example.invalid/api/sesame2"
FIXED_TIMESTAMP = 1_621_854_456


@dataclass(slots=True)
class FakeResponse:
    """Small aiohttp response context manager."""

    status: int
    body: object

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def text(self) -> str:
        if self.body is None:
            return ""
        if isinstance(self.body, str):
            return self.body
        return json.dumps(self.body)


class FakeSession:
    """Return queued responses and record exact HTTP requests."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses: Iterator[FakeResponse] = iter(responses)
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        return next(self._responses)


def status(state: LockState = LockState.MOVED) -> MechanismStatus:
    """Build a synthetic local BLE status."""
    return MechanismStatus(
        state=state,
        battery_raw=2925,
        target=None,
        position=-10,
        battery_low=False,
        critical=False,
        stopped=True,
        rssi=-70,
    )


def client(session: FakeSession) -> SesameCloudCommandClient:
    """Build a client using only synthetic credentials."""
    return SesameCloudCommandClient(
        session,  # type: ignore[arg-type]
        API_KEY,
        DEVICE_UUID,
        SECRET_KEY,
        base_url=BASE_URL,
    )


def cloud_status(
    state: LockState,
    *,
    timestamp: int = FIXED_TIMESTAMP,
    online: bool = True,
    position: int = -86,
) -> dict[str, object]:
    """Build a synthetic CANDY HOUSE status response."""
    return {
        "CHSesame2Status": state.value,
        "timestamp": timestamp,
        "wm2State": online,
        "position": position,
    }


def test_secret_normalization_and_fixed_signature() -> None:
    cloud = client(FakeSession([]))

    assert normalize_cloud_secret_key(f" {SECRET_KEY.upper()} ") == SECRET_KEY
    assert cloud.generate_sign(FIXED_TIMESTAMP) == "147f0730c167544df86ac37f483547ab"


@pytest.mark.parametrize("value", ["", "00", "not-hex", "00" * 17])
def test_secret_validation(value: str) -> None:
    with pytest.raises(ValueError, match="32 hexadecimal"):
        normalize_cloud_secret_key(value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "command", "target"),
    [
        ("async_lock", ITEM_LOCK, LockState.LOCKED),
        ("async_unlock", ITEM_UNLOCK, LockState.UNLOCKED),
    ],
)
async def test_fixed_command_posts_once_and_preserves_observed_ble_state(
    monkeypatch, operation: str, command: int, target: LockState
) -> None:
    session = FakeSession([FakeResponse(200, {"statusCode": 200})])
    cloud = client(session)
    monkeypatch.setattr(
        "custom_components.candy_house_ble.cloud.time.time",
        lambda: FIXED_TIMESTAMP,
    )
    before = status(
        LockState.UNLOCKED
        if target is LockState.LOCKED
        else LockState.LOCKED
    )

    result = await getattr(cloud, operation)(before)

    assert result is before
    assert [request[:2] for request in session.requests] == [
        (
            "POST",
            f"{BASE_URL}/{DEVICE_UUID.upper()}/cmd",
        )
    ]
    request_kwargs = session.requests[0][2]
    assert request_kwargs["headers"] == {"x-api-key": API_KEY}
    assert request_kwargs["json"] == {
        "cmd": command,
        "history": "SG9tZSBBc3Npc3RhbnQ=",
        "sign": "147f0730c167544df86ac37f483547ab",
    }


@pytest.mark.asyncio
async def test_rate_limit_is_not_retried(monkeypatch) -> None:
    session = FakeSession([FakeResponse(429, {})])
    cloud = client(session)
    monkeypatch.setattr(
        "custom_components.candy_house_ble.cloud.time.time",
        lambda: FIXED_TIMESTAMP,
    )

    with pytest.raises(SesameCloudRateLimitError):
        await cloud.async_unlock(status())

    assert len(session.requests) == 1


@pytest.mark.asyncio
async def test_authentication_error_does_not_include_credentials() -> None:
    session = FakeSession([FakeResponse(403, {})])
    cloud = client(session)

    with pytest.raises(SesameCloudAuthenticationError) as raised:
        await cloud.async_get_status()

    message = str(raised.value)
    assert API_KEY not in message
    assert SECRET_KEY not in message


@pytest.mark.asyncio
async def test_rejected_command_is_not_retried(monkeypatch) -> None:
    session = FakeSession([FakeResponse(200, {"statusCode": 500})])
    cloud = client(session)
    monkeypatch.setattr(
        "custom_components.candy_house_ble.cloud.time.time",
        lambda: FIXED_TIMESTAMP,
    )

    with pytest.raises(SesameCloudApiError, match="did not accept"):
        await cloud.async_unlock(status())

    assert [request[0] for request in session.requests] == ["POST"]


@pytest.mark.asyncio
async def test_read_only_status_reports_offline_hub() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                cloud_status(LockState.UNLOCKED, online=False),
            )
        ]
    )

    result = await client(session).async_get_status()

    assert result.hub_online is False
