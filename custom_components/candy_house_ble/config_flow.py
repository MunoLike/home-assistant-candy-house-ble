"""Config flow for CANDY HOUSE BLE."""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    FileSelector,
    FileSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .cloud import (
    SesameCloudAuthenticationError,
    SesameCloudCommandClient,
    SesameCloudConnectionError,
    SesameCloudError,
    SesameCloudHubOfflineError,
)
from .const import (
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
    DOMAIN,
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

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry) -> OptionsFlow:
        """Create the command-transport options flow."""
        return CandyHouseBLEOptionsFlow()

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


class CandyHouseBLEOptionsFlow(OptionsFlow):
    """Configure the optional cloud command transport."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose whether lock commands use BLE or Hub 3 through cloud."""
        if user_input is not None:
            if user_input[CONF_COMMAND_TRANSPORT] == COMMAND_TRANSPORT_BLE:
                return self.async_create_entry(
                    data={CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_BLE}
                )
            return await self.async_step_cloud()

        current = self.config_entry.options.get(
            CONF_COMMAND_TRANSPORT, COMMAND_TRANSPORT_BLE
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_COMMAND_TRANSPORT, default=current): (
                    SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                COMMAND_TRANSPORT_BLE,
                                COMMAND_TRANSPORT_CLOUD,
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key=CONF_COMMAND_TRANSPORT,
                        )
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and store Web API credentials for fixed commands."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                client = SesameCloudCommandClient(
                    async_get_clientsession(self.hass),
                    user_input[CONF_CLOUD_API_KEY],
                    self.config_entry.data[CONF_DEVICE_ID],
                    user_input[CONF_CLOUD_SECRET_KEY],
                )
                status = await client.async_get_status()
                if status.hub_online is False:
                    raise SesameCloudHubOfflineError
            except SesameCloudAuthenticationError:
                errors["base"] = "invalid_cloud_auth"
            except SesameCloudHubOfflineError:
                errors["base"] = "cloud_hub_offline"
            except (SesameCloudConnectionError, SesameCloudError, ValueError):
                errors["base"] = "cannot_connect_cloud"
            else:
                return self.async_create_entry(
                    data={
                        CONF_COMMAND_TRANSPORT: COMMAND_TRANSPORT_CLOUD,
                        CONF_CLOUD_API_KEY: user_input[CONF_CLOUD_API_KEY].strip(),
                        CONF_CLOUD_SECRET_KEY: (
                            user_input[CONF_CLOUD_SECRET_KEY].strip().lower()
                        ),
                        CONF_CLOUD_UNLOCK_ENABLED: user_input[
                            CONF_CLOUD_UNLOCK_ENABLED
                        ],
                    }
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_CLOUD_API_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_CLOUD_SECRET_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_CLOUD_UNLOCK_ENABLED, default=False): (
                    BooleanSelector()
                ),
            }
        )
        return self.async_show_form(
            step_id="cloud", data_schema=schema, errors=errors
        )
