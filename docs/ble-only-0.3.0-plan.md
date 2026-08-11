# BLE-only 0.3.0 implementation plan

## Objective

Release 0.3.0 as a local-BLE-only integration. Remove the optional CANDY
HOUSE cloud/Hub 3 command path, migrate existing entries to BLE without user
interaction, and add non-sensitive runtime diagnostics that make a BLE-only
stability trial measurable.

## Acceptance criteria

1. Lock, unlock, status polling, and Bot 2 script execution have exactly one
   transport implementation: local BLE through Home Assistant Bluetooth.
2. New config entries do not offer a command-transport options flow and do not
   accept cloud credentials.
3. A version 3 entry containing any former cloud option is migrated to version
   4. Former cloud keys are removed from the stored options and the entry loads
   using BLE without asking the user to reconfigure it.
4. No runtime cloud client, cloud endpoint, cloud authentication constant, or
   cloud-specific coordinator branch remains under `custom_components/`.
5. Home Assistant diagnostics report only aggregate, process-local BLE
   reliability data: observation start, session and operation outcomes, timing
   aggregates, and the class of the most recent failure. Credentials, command
   payloads, device history, and exception messages are excluded.
6. Lock and unlock commands are never automatically repeated. A transport
   failure remains visible to Home Assistant instead of risking a duplicate
   physical action.
7. Version metadata is synchronized to 0.3.0, the repository validation suite
   passes, and the deployed integration passes `ha core check`.
8. Home Assistant Core is not restarted as part of implementation. Runtime
   verification starts only after explicit restart permission.

## Non-goals

- Supporting simultaneous Hub 3/cloud and BLE control.
- Collecting lock history from the cloud.
- Persisting diagnostic counters across an integration reload or Core restart.
- Adding diagnostic entities or changing the 30-second polling interval before
  the initial BLE-only observation provides evidence.
- Automatically powering down, unpairing, or reconfiguring Hub 3.
- Adding retries for physical commands.

## Constraints and measurement assumptions

- The stability result is meaningful only when Hub 3 is no longer controlling
  the same SESAME and no phone keeps a BLE session open during the observation.
- Runtime counters cover the interval beginning when the config entry is set up.
  Core crashes or reloads start a new interval, so the observation timestamp is
  part of the diagnostic output.
- Home Assistant entity availability/history remains the durable view across
  restarts; the integration diagnostics explain failures within one runtime.
- Migration deliberately removes stored cloud API credentials. This reduces
  retained secret material but makes rollback to 0.2.0 require re-entering the
  credentials.

## Rollback

1. Reinstall or check out 0.2.0.
2. Restart Home Assistant Core after `ha core check` passes.
3. Open the integration options and re-enter the CANDY HOUSE API key and API
   secret if cloud command transport is required again.

The migration does not alter device-side pairing, SESAME keys, or Hub 3 setup.

## Implementation increments

### Increment 1: configuration and migration

- Scope: bump config entry version to 4, remove the options flow, and strip the
  former cloud option keys during migration.
- Verification: config-flow and migration tests, including a version 3 cloud
  entry whose resulting options contain none of the former credentials.
- Main risk: a downgrade needs credentials to be entered again.

### Increment 2: BLE-only runtime

- Scope: delete the cloud client and coordinator branching; retain BLE locking,
  polling, and Bot 2 behavior.
- Verification: coordinator/client tests prove all supported commands call only
  the BLE client and retain command serialization.
- Main risk: BLE becomes the only command path and exposes any remaining local
  radio contention immediately.

### Increment 3: stability diagnostics

- Scope: collect aggregate session, poll, lock, unlock, and Bot-script outcomes
  plus bounded timing aggregates and sanitized failure categories.
- Verification: unit tests for accounting and diagnostics redaction.
- Main risk: process-local counters can be mistaken for durable history; expose
  their observation start and document the reset behavior.

### Increment 4: release candidate validation

- Scope: update user documentation and synchronize version metadata to 0.3.0.
- Verification: version check, pytest, compileall, Ruff, deployed-tree comparison,
  and `ha core check`.
- Main risk: deployment without a restart leaves the running process on 0.2.0;
  report that state explicitly and wait for restart permission.
