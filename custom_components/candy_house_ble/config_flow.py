"""Config flow for CANDY HOUSE BLE."""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    FileSelector,
    FileSelectorConfig,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_QR_IMAGE,
    CONF_REMOTES,
    CONF_SECRET_KEY,
    DOMAIN,
    FAKE_SESAME_MDNS_KIND,
    FAKE_SESAME_MDNS_TYPE,
    FAKE_SESAME_PROTOCOL_VERSION,
    MODEL_FAKE_SESAME_BUTTON,
)
from .discovery import async_resolve_service_info
from .qr import (
    ManagerCredentialRequired,
    QRCodeError,
    SesameCredential,
    decode_uploaded_qr,
)


def _decode_uploaded_file(
    hass: HomeAssistant, file_id: str
) -> SesameCredential:
    """Decode and consume one HA-managed temporary upload in an executor."""
    return decode_uploaded_qr(process_uploaded_file(hass, file_id))


class CandyHouseBLEConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a local CANDY HOUSE BLE device."""

    VERSION = 5

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Create a secret-free entry for a discovered Fake SESAME bridge."""
        properties = discovery_info.properties
        if (
            discovery_info.type != FAKE_SESAME_MDNS_TYPE
            or properties.get("kind") != FAKE_SESAME_MDNS_KIND
            or properties.get("version") != FAKE_SESAME_PROTOCOL_VERSION
        ):
            return self.async_abort(reason="unsupported_discovery")

        try:
            device_id = str(uuid.UUID(str(properties[CONF_DEVICE_ID])))
        except (KeyError, TypeError, ValueError, AttributeError):
            return self.async_abort(reason="invalid_discovery")

        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()

        title = str(properties.get("name") or "Fake SESAME Button Bridge")
        return self.async_create_entry(
            title=title,
            data={
                CONF_DEVICE_ID: device_id,
                CONF_MODEL: MODEL_FAKE_SESAME_BUTTON,
                CONF_REMOTES: [],
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle setup using a manager share QR image."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                credential = await self.hass.async_add_executor_job(
                    _decode_uploaded_file,
                    self.hass,
                    user_input[CONF_QR_IMAGE],
                )
                service_info = await async_resolve_service_info(
                    self.hass, credential.model, credential.device_id
                )
                if service_info is None:
                    errors["base"] = "device_not_found"
                else:
                    device_id = str(uuid.UUID(bytes=credential.device_id))
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=credential.name,
                        data={
                            CONF_DEVICE_ID: device_id,
                            CONF_MODEL: credential.model,
                            CONF_SECRET_KEY: credential.secret_key.hex(),
                        },
                    )
            except ManagerCredentialRequired:
                errors["base"] = "manager_key_required"
            except (QRCodeError, ValueError):
                errors["base"] = "invalid_qr"

        schema = vol.Schema(
            {
                vol.Required(CONF_QR_IMAGE): FileSelector(
                    FileSelectorConfig(accept="image/*")
                )
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
