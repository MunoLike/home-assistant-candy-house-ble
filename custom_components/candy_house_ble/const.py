"""Constants for CANDY HOUSE BLE."""

from datetime import timedelta

DOMAIN = "candy_house_ble"

CONF_DEVICE_ID = "device_id"
CONF_MODEL = "model"
CONF_QR_IMAGE = "qr_image"
CONF_REMOTE_ID = "remote_id"
CONF_REMOTES = "remotes"
CONF_SECRET_KEY = "secret_key"

MODEL_SESAME_5_PRO = 7
MODEL_REMOTE_NANO = 15
MODEL_BOT_2 = 17
# Integration-local model value. It is intentionally outside the one-byte
# model range used by physical SESAME advertisements.
MODEL_FAKE_SESAME_BUTTON = 256
MODEL_NAMES = {
    MODEL_SESAME_5_PRO: "SESAME 5 Pro",
    MODEL_BOT_2: "SESAME Bot 2",
    MODEL_FAKE_SESAME_BUTTON: "Fake SESAME Button Bridge",
}

FAKE_SESAME_EVENT = "esphome.candy_house_ble_button"
FAKE_SESAME_EVENT_TYPES = ("lock", "unlock")
FAKE_SESAME_MDNS_TYPE = "_candyhouseble._tcp.local."
FAKE_SESAME_MDNS_KIND = "fake_sesame_button"
FAKE_SESAME_PROTOCOL_VERSION = "1"
# The two-cell battery is measured behind a 1:2 divider. The OS3 status field
# carries divider-side millivolts; the official ESP32 SDK defines low battery at
# an actual pack voltage below 5 V.
SESAME_5_PRO_BATTERY_DIVIDER_RATIO = 2
BOT_2_BATTERY_DIVIDER_RATIO = 1

SERVICE_UUID = "0000fd81-0000-1000-8000-00805f9b34fb"
WRITE_CHARACTERISTIC_UUID = "16860002-a5ae-9856-b6d3-dbb4c676993e"
NOTIFY_CHARACTERISTIC_UUID = "16860003-a5ae-9856-b6d3-dbb4c676993e"

POLL_INTERVAL = timedelta(seconds=30)
CONNECT_TIMEOUT = 20.0
STATUS_TIMEOUT = 12.0
COMMAND_TIMEOUT = 12.0
COMMAND_COMPLETION_TIMEOUT = 15.0

BOT_2_BLE_REFRESH_DELAY = 1.0
BOT_2_COMMAND_COOLDOWN = 2.0
BOT_2_INDETERMINATE_COOLDOWN = 15.0
