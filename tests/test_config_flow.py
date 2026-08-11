"""Tests for the CANDY HOUSE BLE config flow."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.candy_house_ble.cloud import (
    SesameCloudAuthenticationError,
    SesameCloudHubOfflineError,
)
from custom_components.candy_house_ble.config_flow import (
    CandyHouseBLEConfigFlow,
    CandyHouseBLEOptionsFlow,
)
from custom_components.candy_house_ble.const import (
    COMMAND_TRANSPORT_BLE,
    COMMAND_TRANSPORT_CLOUD,
    CONF_CLOUD_API_KEY,
    CONF_CLOUD_SECRET_KEY,
    CONF_CLOUD_UNLOCK_ENABLED,
    CONF_COMMAND_TRANSPORT,
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_QR_IMAGE,
    CONF_SECRET_KEY,
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


def options_flow(
    options: dict[str, object] | None = None,
) -> CandyHouseBLEOptionsFlow:
    """Build an options flow attached to a synthetic config entry."""
    entry = SimpleNamespace(
        data={CONF_DEVICE_ID: str(DEVICE_UUID)}, options=options or {}
    )
    flow = CandyHouseBLEOptionsFlow()
    flow.hass = FakeHass(entry)
    flow.handler = "synthetic-entry-id"
    return flow


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


@pytest.mark.asyncio
async def test_options_default_to_local_ble() -> None:
    result = await options_flow().async_step_init()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_selecting_ble_removes_all_cloud_options() -> None:
    flow = options_flow(
        {
            CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_CLOUD,
            CONF_CLOUD_API_KEY: "old-key",
            CONF_CLOUD_SECRET_KEY: "11" * 16,
            CONF_CLOUD_UNLOCK_ENABLED: True,
        }
    )

    result = await flow.async_step_init(
        {CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_BLE}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_BLE
    }


@pytest.mark.asyncio
async def test_cloud_options_validate_read_only_and_store_credentials(
    monkeypatch,
) -> None:
    flow = options_flow()
    get_status = AsyncMock(return_value=SimpleNamespace(hub_online=True))
    client = Mock(async_get_status=get_status)
    constructor = Mock(return_value=client)
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow."
        "SesameCloudCommandClient",
        constructor,
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow."
        "async_get_clientsession",
        Mock(return_value="synthetic-session"),
    )

    next_result = await flow.async_step_init(
        {CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_CLOUD}
    )
    result = await flow.async_step_cloud(
        {
            CONF_CLOUD_API_KEY: " synthetic-api-key ",
            CONF_CLOUD_SECRET_KEY: "AA" * 16,
            CONF_CLOUD_UNLOCK_ENABLED: True,
        }
    )

    assert next_result["type"] is FlowResultType.FORM
    assert next_result["step_id"] == "cloud"
    get_status.assert_awaited_once_with()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_CLOUD,
        CONF_CLOUD_API_KEY: "synthetic-api-key",
        CONF_CLOUD_SECRET_KEY: "aa" * 16,
        CONF_CLOUD_UNLOCK_ENABLED: True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "error_key"),
    [
        (SesameCloudAuthenticationError(), "invalid_cloud_auth"),
        (SesameCloudHubOfflineError(), "cloud_hub_offline"),
    ],
)
async def test_cloud_options_report_validation_errors(
    monkeypatch, error: Exception, error_key: str
) -> None:
    flow = options_flow()
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow."
        "SesameCloudCommandClient",
        Mock(
            return_value=Mock(
                async_get_status=AsyncMock(side_effect=error)
            )
        ),
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.config_flow."
        "async_get_clientsession",
        Mock(return_value="synthetic-session"),
    )

    result = await flow.async_step_cloud(
        {
            CONF_CLOUD_API_KEY: "synthetic-api-key",
            CONF_CLOUD_SECRET_KEY: "aa" * 16,
            CONF_CLOUD_UNLOCK_ENABLED: False,
        }
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error_key}
