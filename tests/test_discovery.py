"""Tests for advertisement-identity discovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.candy_house_ble.const import SERVICE_UUID
from custom_components.candy_house_ble.discovery import (
    advertisement_matches,
    async_resolve_with_scan,
    find_matching_service_info,
)

DEVICE_ID = bytes.fromhex("12345678123456781234567812345678")


def manufacturer_payload(model: int = 7, device_id: bytes = DEVICE_ID) -> bytes:
    return bytes((model, 0, 0)) + device_id


def service_info(address: str, *, device_id: bytes = DEVICE_ID):
    return SimpleNamespace(
        service_uuids=[SERVICE_UUID.upper()],
        manufacturer_data={0x055A: manufacturer_payload(device_id=device_id)},
        device=SimpleNamespace(address=address),
    )


def test_advertisement_matches_model_and_uuid() -> None:
    assert advertisement_matches(
        [SERVICE_UUID.upper()], {0x055A: manufacturer_payload()}, 7, DEVICE_ID
    )


@pytest.mark.parametrize(
    ("service_uuids", "payload", "model", "device_id"),
    [
        ([], manufacturer_payload(), 7, DEVICE_ID),
        ([SERVICE_UUID], manufacturer_payload(model=6), 7, DEVICE_ID),
        ([SERVICE_UUID], manufacturer_payload(), 7, bytes(16)),
        ([SERVICE_UUID], b"short", 7, DEVICE_ID),
        ([SERVICE_UUID], manufacturer_payload(), 7, b"short"),
    ],
)
def test_advertisement_rejects_mismatch(
    service_uuids: list[str], payload: bytes, model: int, device_id: bytes
) -> None:
    assert not advertisement_matches(
        service_uuids, {0x055A: payload}, model, device_id
    )


@pytest.mark.asyncio
async def test_resolver_requests_scan_then_uses_current_device() -> None:
    discoveries: list[list[object]] = [[], [service_info("address-after-scan")]]
    scan_calls = 0

    def get_current():
        return find_matching_service_info(discoveries.pop(0), 7, DEVICE_ID)

    async def request_scan() -> None:
        nonlocal scan_calls
        scan_calls += 1

    result = await async_resolve_with_scan(get_current, request_scan)

    assert result is not None
    assert result.device.address == "address-after-scan"
    assert scan_calls == 1


@pytest.mark.asyncio
async def test_resolver_does_not_persist_previous_address() -> None:
    current = [service_info("first-address")]

    def get_current():
        return find_matching_service_info(current, 7, DEVICE_ID)

    async def request_scan() -> None:
        raise AssertionError("A scan is not needed for a current advertisement")

    first = await async_resolve_with_scan(get_current, request_scan)
    current[:] = [service_info("rotated-address")]
    second = await async_resolve_with_scan(get_current, request_scan)

    assert first is not None
    assert second is not None
    assert first.device.address == "first-address"
    assert second.device.address == "rotated-address"
