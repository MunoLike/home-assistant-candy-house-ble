"""Constants for CANDY HOUSE BLE."""

from datetime import timedelta

DOMAIN = "candy_house_ble"

CONF_DEVICE_ID = "device_id"
CONF_MODEL = "model"
CONF_QR_IMAGE = "qr_image"
CONF_SECRET_KEY = "secret_key"

MODEL_SESAME_5_PRO = 7
MODEL_NAMES = {MODEL_SESAME_5_PRO: "SESAME 5 Pro"}
# The two-cell battery is measured behind a 1:2 divider. The OS3 status field
# carries divider-side millivolts; the official ESP32 SDK defines low battery at
# an actual pack voltage below 5 V.
SESAME_5_PRO_BATTERY_DIVIDER_RATIO = 2

SERVICE_UUID = "0000fd81-0000-1000-8000-00805f9b34fb"
WRITE_CHARACTERISTIC_UUID = "16860002-a5ae-9856-b6d3-dbb4c676993e"
NOTIFY_CHARACTERISTIC_UUID = "16860003-a5ae-9856-b6d3-dbb4c676993e"

POLL_INTERVAL = timedelta(seconds=30)
CONNECT_TIMEOUT = 20.0
STATUS_TIMEOUT = 12.0
COMMAND_TIMEOUT = 12.0
COMMAND_COMPLETION_TIMEOUT = 15.0
