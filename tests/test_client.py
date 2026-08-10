"""Tests for optional BLE transport diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.candy_house_ble.client import service_info_rssi


class BrokenRSSI:
    """Model service information whose RSSI property cannot be read."""

    @property
    def rssi(self) -> int:
        raise RuntimeError("scanner data unavailable")


@pytest.mark.parametrize(
    ("service_info", "expected"),
    [
        (SimpleNamespace(rssi=-63), -63),
        (SimpleNamespace(rssi=None), None),
        (SimpleNamespace(), None),
        (BrokenRSSI(), None),
        (SimpleNamespace(rssi=-63.5), None),
    ],
)
def test_service_info_rssi_is_optional(
    service_info: object, expected: int | None
) -> None:
    assert service_info_rssi(service_info) == expected
