# Local SESAME history implementation plan

## Objective

Expose locally retrieved SESAME 5 Pro lock/unlock history in Home Assistant,
including the device timestamp and the actor/source information that can be
decoded from the record, without adding lock control or deleting history from
the SESAME.

## Acceptance criteria

1. `python -m pytest -q` exits 0 for a constrained encrypted OS3 history-read
   request, a single bounded head-record response, timeout handling, record
   parsing, deduplication, and entity event delivery.
2. A source gate proves that the integration contains no OS3 lock item (82),
   unlock item (83), history-delete item (18), generic encrypted-command API,
   `async_lock`, or `async_unlock`.
3. Synthetic records with a known record ID are emitted once, remain
   deduplicated after the persistence layer is reconstructed, and never expose
   raw encrypted payloads or the device secret as entity attributes.
4. A bounded Home Assistant event entity reports each new record with action,
   device timestamp, actor/source type, and actor label when the format carries
   one. Unknown values remain explicit rather than guessed.
5. Existing status and battery entities continue to pass their tests, and
   `ruff check` plus `python -m compileall` exit 0.
6. The reviewed component is identical in the repository and
   `/config/custom_components/candy_house_ble`; `ha core check` exits 0.
7. **Unverified until an approved runtime probe:** a real SESAME 5 Pro returns
   OS3 history payloads in the inferred format through the configured ESPHome
   Bluetooth proxy.
8. **Unverified until an approved Core restart and manual operation:** new
   manual/app operations appear once in Home Assistant with the correct action,
   time, source, and label.

## Non-goals

- A `lock` entity or any lock, unlock, toggle, delete-history, firmware, or
  settings command.
- CANDY HOUSE cloud/AWS access or importing the cloud-side history list.
- Reproducing the official app's history UI.
- Support for devices other than SESAME 5 Pro in this increment.

## Constraints

- The only new authenticated outbound command may be the fixed OS3 history
  request: item 4 with payload `01`.
- Never send item 18 (history delete); repeated sessions must use persistent
  record-ID deduplication instead.
- Never log or commit a real secret key, QR URI, raw history tag, or raw record.
- A temporary runtime probe may save raw records only in a mode-0600 file under
  `/config/.tools/home-assistant-candy-house-ble/history-probe`, outside Git;
  it must be removed from the integration before the final milestone.
- Do not manually access or edit `secrets.yaml`, `.ssh`, or `.storage`.
- Do not restart Home Assistant without fresh, explicit user approval.

## Runtime finding — 2026-08-11

With Hub3 temporarily disconnected, a real SESAME 5 Pro returned one 16-byte
record repeatedly for every item-4 request. Contrary to the initial assumption
from the ESP32 demo's request loop, the device did not advance to the next
record or return an empty response without item 18 deletion. The repeated
record contained a four-byte record ID, a one-byte history type, a little-endian
Unix timestamp, and the seven-byte mechanism status. The integration therefore
requests only one head record per connection and deduplicates it; it still never
sends item 18. Rapid consecutive operations can overwrite which head record HA
observes, so the resulting local feed is explicitly best-effort.

## Rollback

Before restart, restore the deployed component from the last committed source.
After restart, restore commit `3e5007d`, synchronize the component, run
`ha core check`, and restart only with approval. Existing state and battery
entities then resume their prior behavior; no device history is deleted.

## Increments

### 1. Protocol and secure runtime probe

- Scope: fixed encrypted history-read packet, one head-record response per
  connection, and temporary mode-0600 deduplicated raw capture outside Git.
- Verification: deterministic AES-CCM/segmentation tests and the source safety
  gate; then an explicitly approved Core restart and one manual operation.
- Risk: the public SDK uploads opaque records to its server, so the local raw
  record schema is not documented and must not be guessed into production.

### 2. Record parser and persistent deduplication

- Scope: parse only fields demonstrated by captured records and official SDK
  constants; persist a bounded set of record IDs through Home Assistant Store.
- Verification: synthetic fixtures derived from the demonstrated structure,
  restart-style reconstruction tests, malformed input tests, and raw-data
  exposure scan.
- Risk: tags may differ by manual, BLE, Hub3, Touch, and automation sources.

### 3. Home Assistant event entity

- Scope: an `event` platform that emits each unseen history record with typed,
  non-secret attributes.
- Verification: entity tests for ordered one-time emission and unknown-value
  handling.
- Risk: imported backlog is received now even though the device timestamp is
  older; consumers must use the explicit device timestamp attribute.

### 4. Stage and preflight

- Scope: remove temporary probe output, synchronize the reviewed component,
  run full tests and Home Assistant preflight, and stop before restart.
- Verification: exact recursive diff, source safety gate, secret scan, tests,
  compile, lint, and `ha core check`.
- Risk: real event delivery remains unverified until restart.

### 5. Runtime observation

- Scope: restart with approval, perform user-driven manual/app operations, and
  compare HA events against observed physical actions and official-app history.
- Verification: action, device timestamp, source, label, deduplication, and
  absence of BLE timeout regressions.
- Risk: Hub3 or the official app may upload/delete records before HA reads them.
