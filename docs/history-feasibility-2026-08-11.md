# Local SESAME history feasibility — 2026-08-11

## Decision

Do not ship local BLE history retrieval in CANDY HOUSE BLE. Keep the integration
focused on best-effort current state and battery diagnostics. Use the official
CANDY HOUSE cloud/application when a complete lock/unlock history is needed.

## What was demonstrated

- The SESAME 5 Pro advertisement exposes a pending-history flag in bit 1 of the
  third manufacturer-data byte.
- After OS3 login, the fixed encrypted request `item 4` with payload `01`
  retrieves the current head history record.
- The observed record was 16 bytes: four-byte record ID, one-byte history type,
  little-endian Unix timestamp, and the seven-byte mechanism status.
- The controlled manual lock record timestamp matched the physical operation,
  and its mechanism-status flags decoded as locked.
- No lock, unlock, toggle, settings, firmware, or history-delete command was
  added or sent during the investigation.

## Blocking behavior found on the real device

The real SESAME returned the same 16-byte head record for every repeated history
request. It did not advance to an older record or return an empty response.
Advancing the queue therefore depends on `item 18`, the separate history-delete
command used by the official Android SDK only after a successful cloud upload.

With Hub3 active, a controlled manual unlock/lock was not available to HA: the
first immediate HA connection timed out while another BLE client was active,
and a later successful connection saw no pending-history flag. With Hub3
temporarily disconnected, HA retrieved the record, but 28 requests yielded 28
identical copies until the safety limit stopped the probe. This confirms that a
non-destructive local reader cannot provide the official app's complete list
while Hub3 remains in normal use.

## Why the feature was removed

- Deleting records locally would mutate the lock's history queue and compete
  with the official Hub3/cloud ingestion path.
- Refusing deletion limits HA to one current head record and can miss rapid
  consecutive operations.
- Hub3 is part of the required household setup, so disconnecting or arbitrating
  it for history collection is not operationally acceptable.
- BLE actor tags use environment identifiers that the cloud resolves to account
  labels; a local manager credential alone cannot reproduce labels such as the
  official application's user name reliably.

## Cleanup and rollback

The temporary fixed history request, advertisement flag handling, collection
loop, probe sink, and related tests were removed. The deployed integration was
returned to the read-only status implementation from commit `3e5007d`, retaining
the 15-second polling interval. The mode-0600 raw probe file under
`/config/.tools/home-assistant-candy-house-ble/history-probe` was deleted and was
never committed.

## Sources

- Android SDK: <https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp>
- ESP32 SDK: <https://github.com/CANDY-HOUSE/SesameSDK_ESP32_with_DemoApp>
