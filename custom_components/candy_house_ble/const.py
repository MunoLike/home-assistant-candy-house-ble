"""Constants for CANDY HOUSE BLE."""

from datetime import timedelta

DOMAIN = "candy_house_ble"

CONF_DEVICE_ID = "device_id"
CONF_MODEL = "model"
CONF_QR_IMAGE = "qr_image"
CONF_SECRET_KEY = "secret_key"
CONF_COMMAND_TRANSPORT = "command_transport"
CONF_CLOUD_API_KEY = "cloud_api_key"
CONF_CLOUD_SECRET_KEY = "cloud_secret_key"
CONF_CLOUD_UNLOCK_ENABLED = "cloud_unlock_enabled"

COMMAND_TRANSPORT_BLE = "ble"
COMMAND_TRANSPORT_CLOUD = "cloud"

MODEL_SESAME_5_PRO = 7
MODEL_BOT_2 = 17
MODEL_NAMES = {
    MODEL_SESAME_5_PRO: "SESAME 5 Pro",
    MODEL_BOT_2: "SESAME Bot 2",
}
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

CLOUD_API_BASE_URL = "https://app.candyhouse.co/api/sesame2"
CLOUD_API_TIMEOUT = 10.0
CLOUD_BLE_REFRESH_DELAY = 3.0
BOT_2_BLE_REFRESH_DELAY = 1.0
BOT_2_COMMAND_COOLDOWN = 2.0
BOT_2_INDETERMINATE_COOLDOWN = 15.0
CLOUD_HISTORY_TAG = "Home Assistant"
