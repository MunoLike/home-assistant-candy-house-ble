"""Discover CANDY HOUSE devices by advertisement identity."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from homeassistant.core import HomeAssistant

from .const import SERVICE_UUID


class ServiceInfoLike(Protocol):
    """Advertisement fields required for SESAME identity matching."""

    service_uuids: Iterable[str]
    manufacturer_data: Mapping[int, bytes]


def advertisement_matches(
    service_uuids: Iterable[str],
    manufacturer_data: Mapping[int, bytes],
    model: int,
    device_id: bytes,
) -> bool:
    """Return whether an advertisement belongs to one configured device."""
    if len(device_id) != 16:
        return False
    if SERVICE_UUID not in {item.lower() for item in service_uuids}:
        return False
    return any(
        len(payload) >= 19
        and payload[0] == model
        and payload[3:19] == device_id
        for payload in manufacturer_data.values()
    )


def find_matching_service_info[ServiceInfoT: ServiceInfoLike](
    service_infos: Iterable[ServiceInfoT], model: int, device_id: bytes
) -> ServiceInfoT | None:
    """Find a configured device in the supplied current advertisements."""
    for info in service_infos:
        if advertisement_matches(
            info.service_uuids,
            info.manufacturer_data,
            model,
            device_id,
        ):
            return info
    return None


async def async_resolve_with_scan[ServiceInfoT](
    get_current: Callable[[], ServiceInfoT | None],
    request_scan: Callable[[], Awaitable[object]],
) -> ServiceInfoT | None:
    """Return current info, requesting one fresh scan only when absent."""
    if info := get_current():
        return info
    await request_scan()
    return get_current()


async def async_resolve_service_info(
    hass: HomeAssistant, model: int, device_id: bytes
) -> BluetoothServiceInfoBleak | None:
    """Resolve the current BLE device, requesting one fresh scan if necessary."""
    from homeassistant.components import bluetooth

    def get_current() -> BluetoothServiceInfoBleak | None:
        return find_matching_service_info(
            bluetooth.async_discovered_service_info(hass, connectable=True),
            model,
            device_id,
        )

    return await async_resolve_with_scan(
        get_current, lambda: bluetooth.async_request_active_scan(hass)
    )
