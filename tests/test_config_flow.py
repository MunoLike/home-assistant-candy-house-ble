"""Tests for the CANDY HOUSE BLE config flow."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.candy_house_ble.config_flow import CandyHouseBLEConfigFlow
from custom_components.candy_house_ble.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_QR_IMAGE,
    CONF_SECRET_KEY,
    MODEL_BOT_2,
)
from custom_components.candy_house_ble.qr import (
    ManagerCredentialRequired,
    SesameCredential,
)

DEVICE_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")
SECRET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")


class FakeHass:
    """Execute executor jobs inline for config-flow unit tests."""

    def __init__(self, entry=None) -> None:
        self.config_entries = SimpleNamespace(
            async_get_known_entry=lambda _entry_id: entry
        )

    async def async_add_executor_job(self, target, *args):
        return target(*args)


def flow_with_fake_hass() -> CandyHouseBLEConfigFlow:
    """Build a config flow without starting a Home Assistant instance."""
    flow = CandyHouseBLEConfigFlow()
    flow.hass = FakeHass()
    return flow


def test_ble_only_config_flow_has_no_options_flow() -> None:
    assert "async_get_options_flow" not in CandyHouseBLEConfigFlow.__dict__


@pytest.mark.asyncio
async def test_initial_form_uses_qr_image_field() -> None:
    result = await flow_with_fake_hass().async_step_user()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert CONF_QR_IMAGE in {
        marker.schema for marker in result["data_schema"].schema
    }


@pytest.mark.asyncio
async def test_create_entry_stores_parsed_credential_without_address(
    monkeypatch,
) -> None:
    credential = SesameCredential(
        model=7,
        name="Test lock",
        level=1,
        secret_key=SECRET_KEY,
        device_id=DEVICE_UUID.bytes,
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow._decode_uploaded_file",
        lambda _hass, _file_id: credential,
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow."
        "async_resolve_service_info",
        AsyncMock(return_value=SimpleNamespace(device=object())),
    )
    flow = flow_with_fake_hass()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = lambda: None

    result = await flow.async_step_user({CONF_QR_IMAGE: "temporary-file-id"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test lock"
    assert result["data"] == {
        CONF_DEVICE_ID: str(DEVICE_UUID),
        CONF_MODEL: 7,
        CONF_SECRET_KEY: SECRET_KEY.hex(),
    }
    assert "address" not in result["data"]
    flow.async_set_unique_id.assert_awaited_once_with(str(DEVICE_UUID))


@pytest.mark.asyncio
async def test_create_bot_2_entry_uses_model_17(monkeypatch) -> None:
    credential = SesameCredential(
        model=MODEL_BOT_2,
        name="Test Bot 2",
        level=1,
        secret_key=SECRET_KEY,
        device_id=DEVICE_UUID.bytes,
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow._decode_uploaded_file",
        lambda _hass, _file_id: credential,
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow."
        "async_resolve_service_info",
        AsyncMock(return_value=SimpleNamespace(device=object())),
    )
    flow = flow_with_fake_hass()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = lambda: None

    result = await flow.async_step_user({CONF_QR_IMAGE: "temporary-file-id"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Bot 2"
    assert result["data"] == {
        CONF_DEVICE_ID: str(DEVICE_UUID),
        CONF_MODEL: MODEL_BOT_2,
        CONF_SECRET_KEY: SECRET_KEY.hex(),
    }


@pytest.mark.asyncio
async def test_non_manager_image_returns_specific_error(monkeypatch) -> None:
    def reject_manager(_hass, _file_id):
        raise ManagerCredentialRequired

    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow._decode_uploaded_file",
        reject_manager,
    )

    result = await flow_with_fake_hass().async_step_user(
        {CONF_QR_IMAGE: "temporary-file-id"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "manager_key_required"}


@pytest.mark.asyncio
async def test_stale_upload_returns_invalid_qr(monkeypatch) -> None:
    def missing_upload(_hass, _file_id):
        raise ValueError("File does not exist")

    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow._decode_uploaded_file",
        missing_upload,
    )

    result = await flow_with_fake_hass().async_step_user(
        {CONF_QR_IMAGE: "stale-file-id"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_qr"}


@pytest.mark.asyncio
async def test_missing_device_does_not_create_entry(monkeypatch) -> None:
    credential = SesameCredential(
        model=7,
        name="Test lock",
        level=1,
        secret_key=SECRET_KEY,
        device_id=DEVICE_UUID.bytes,
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow._decode_uploaded_file",
        lambda _hass, _file_id: credential,
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow."
        "async_resolve_service_info",
        AsyncMock(return_value=None),
    )

    result = await flow_with_fake_hass().async_step_user(
        {CONF_QR_IMAGE: "temporary-file-id"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "device_not_found"}
