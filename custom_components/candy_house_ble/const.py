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
MODEL_SESAME_6_PRO = 21
MODEL_BOT_3 = 35
# Official Android SDK CHProductModel maps these pairs to CHSesame5Device
# and CHSesameBot2Device respectively (commit 17b39dd19c0f0a2bb27fb8c6617850fc56f4438a).
LOCK_MODELS = frozenset({MODEL_SESAME_5_PRO, MODEL_SESAME_6_PRO})
BOT_MODELS = frozenset({MODEL_BOT_2, MODEL_BOT_3})
# Integration-local model value. It is intentionally outside the one-byte
# model range used by physical SESAME advertisements.
MODEL_FAKE_SESAME_BUTTON = 256
MODEL_NAMES = {
    MODEL_SESAME_5_PRO: "SESAME 5 Pro",
    MODEL_BOT_2: "SESAME Bot 2",
    MODEL_SESAME_6_PRO: "SESAME 6 Pro",
    MODEL_BOT_3: "SESAME Bot 3",
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
DISCONNECT_TIMEOUT = 5.0
# BlueZ may still be completing notification teardown when disconnect returns.
# A short adapter-wide quiet period prevents the next session from racing it.
BLE_SESSION_SETTLE_DELAY = 0.25

BOT_2_BLE_REFRESH_DELAY = 1.0
BOT_2_COMMAND_COOLDOWN = 2.0
BOT_2_INDETERMINATE_COOLDOWN = 15.0
