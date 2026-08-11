"""ESPHome component for a constrained fake SESAME 5 event bridge."""

from __future__ import annotations

from pathlib import Path

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import esp32_ble
from esphome.components.esp32 import add_idf_sdkconfig_option
from esphome.components.esp32_ble import BTLoggers
from esphome.const import CONF_ID

AUTO_LOAD = ["esp32_ble"]
DEPENDENCIES = ["esp32"]
CODEOWNERS = ["@Khronos31"]
COMPONENT_VERSION = Path(__file__).with_name("VERSION").read_text().strip()

CONF_DEVICE_ID = "device_id"
CONF_SECRET_KEY = "secret_key"
CONF_ON_LOCK = "on_lock"
CONF_ON_UNLOCK = "on_unlock"

fake_sesame_ns = cg.esphome_ns.namespace("fake_sesame")
_USES_BLE_CALLBACK_API = not hasattr(esp32_ble, "GAPEventHandler")
_fake_sesame_bases = [cg.Component]
if not _USES_BLE_CALLBACK_API:
    _fake_sesame_bases.extend(
        [esp32_ble.GAPEventHandler, esp32_ble.GATTsEventHandler]
    )
_fake_sesame_bases.append(cg.Parented.template(esp32_ble.ESP32BLE))
FakeSesame = fake_sesame_ns.class_("FakeSesame", *_fake_sesame_bases)


def _hex_16_bytes(value: object) -> bytes:
    value = cv.string_strict(value).lower()
    if len(value) != 32:
        raise cv.Invalid("value must contain exactly 16 bytes of hexadecimal")
    try:
        return bytes.fromhex(value)
    except ValueError as err:
        raise cv.Invalid("value must contain only hexadecimal characters") from err


def _hex_16_string(value: object) -> str:
    """Validate a 16-byte hex value without discarding sensitivity metadata."""
    value = cv.string_strict(value).lower()
    if len(value) != 32:
        raise cv.Invalid("value must contain exactly 16 bytes of hexadecimal")
    try:
        bytes.fromhex(value)
    except ValueError as err:
        raise cv.Invalid("value must contain only hexadecimal characters") from err
    return value


_secret_hex_16_string = (
    cv.sensitive(_hex_16_string) if hasattr(cv, "sensitive") else _hex_16_string
)


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(FakeSesame),
        cv.GenerateID(esp32_ble.CONF_BLE_ID): cv.use_id(esp32_ble.ESP32BLE),
        cv.Required(CONF_DEVICE_ID): _hex_16_bytes,
        cv.Required(CONF_SECRET_KEY): _secret_hex_16_string,
        cv.Optional(CONF_ON_LOCK): automation.validate_automation(single=True),
        cv.Optional(CONF_ON_UNLOCK): automation.validate_automation(single=True),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    """Generate the dedicated fake-peripheral component."""
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    parent = await cg.get_variable(config[esp32_ble.CONF_BLE_ID])
    cg.add(var.set_parent(parent))
    esp32_ble.register_gap_event_handler(parent, var)
    esp32_ble.register_gatts_event_handler(parent, var)
    esp32_ble.register_ble_status_event_handler(parent, var)
    esp32_ble.register_bt_logger(BTLoggers.GATT)

    if _USES_BLE_CALLBACK_API:
        cg.add_define("FAKE_SESAME_BLE_CALLBACK_API")
    cg.add_define("FAKE_SESAME_VERSION", COMPONENT_VERSION)

    cg.add(var.set_device_id(cg.ArrayInitializer(*config[CONF_DEVICE_ID])))
    cg.add(
        var.set_secret_key(
            cg.ArrayInitializer(*bytes.fromhex(config[CONF_SECRET_KEY]))
        )
    )

    if CONF_ON_LOCK in config:
        await automation.build_automation(
            var.get_lock_trigger(), [(cg.std_string, "remote_id")], config[CONF_ON_LOCK]
        )
    if CONF_ON_UNLOCK in config:
        await automation.build_automation(
            var.get_unlock_trigger(),
            [(cg.std_string, "remote_id")],
            config[CONF_ON_UNLOCK],
        )

    cg.add_define("USE_ESP32_BLE_SERVER")
    cg.add_define("USE_ESP32_BLE_ADVERTISING")
    cg.add_define("USE_ESP32_BLE_UUID")
    add_idf_sdkconfig_option("CONFIG_BT_ENABLED", True)
    add_idf_sdkconfig_option("CONFIG_BT_GATTS_ENABLE", True)
