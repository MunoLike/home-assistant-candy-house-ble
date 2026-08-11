# CANDY HOUSE BLE implementation plan

## Objective

Build a HACS-installable Home Assistant custom integration named **CANDY HOUSE BLE** (`candy_house_ble`) that uses Home Assistant's Bluetooth stack and ESPHome Bluetooth proxies to communicate locally with CANDY HOUSE devices. The first supported device is SESAME 5 Pro, starting with read-only state and battery diagnostics. Lock and unlock commands are a later gated increment.

## Acceptance criteria for the pre-restart milestone

1. `python3 -m pytest -q` exits 0 for QR parsing/decoding, uploaded-file cleanup, BLE framing, login authentication, notification parsing, and mechanism-status parsing tests.
2. `python3 -m compileall -q custom_components tests` exits 0.
3. A synthetic manager QR image is accepted and reduced to model, permission level, secret key, and device UUID; invalid, owner, guest, and unsupported-model data is rejected.
4. The uploaded image is deleted on both successful and failed decode paths.
5. The real manager credential, its URI, and its secret key do not occur in the worktree or Git object history. No real credential is used as a committed fixture.
6. BLE connection code resolves the current address from the device's model and UUID advertisement identity instead of treating the configured address as permanent.
7. Only the OS3 login packet can be transmitted. The pre-restart source contains no lock/unlock command builder or operation item codes.
8. The integration is staged at `/config/custom_components/candy_house_ble` alongside the existing `sesame_ble_status` integration.
9. `ha core check` exits successfully after staging.
10. `ha core restart` is not run in this milestone.

Runtime setup, Core-side QR decoder installation, Bluetooth Proxy reconnection, and live entity state remain **unverified** until the user authorizes a Core restart and adds the integration through the UI.

## Non-goals for the first milestone

- Lock or unlock commands.
- Owner or guest keys.
- Cloud API, Hub 3, Matter, firmware updates, or key sharing/management.
- SESAME Touch 2, CANDY HOUSE Remote, Hub 3, Remote nano, or SESAME Bot 3.
- Removal or migration of `sesame_ble_status`.
- A public release, version tag, or HACS default-store submission.

## Constraints

- Never commit or log a real QR URI, device secret key, or uploaded QR image.
- The development credential remains under `/config/.tools/home-assistant-candy-house-ble/credentials` with mode `0600` and is not a runtime configuration source.
- Do not manually access or edit `secrets.yaml`, `.ssh`, or `.storage`.
- Do not restart Home Assistant without fresh, explicit user approval.
- Keep the existing integration operational until the replacement passes runtime observation and entity migration review.

## Rollback

Before restart, remove `/config/custom_components/candy_house_ble`; no running HA state has changed. After a later restart, unload and remove the `candy_house_ble` config entry, remove that component directory, and restart with approval. The existing `sesame_ble_status` integration remains available throughout.

## Increments

### 1. Repository and test harness

- Scope: HACS layout, metadata, test dependencies, synthetic fixtures, CI, and documentation.
- Verification: install development dependencies and run an empty/minimal test suite.
- Risk: tooling may not match HA Core's Python version.

### 2. QR upload spike

- Scope: pure credential parser, image decoder, FileSelector config-flow adapter, and guaranteed uploaded-file cleanup.
- Verification: synthetic QR tests plus dependency installation on amd64 CPython.
- Runtime result: `zxing-cpp` had no musllinux wheel and failed to build in HA Core.
  It was replaced with the pinned `pyrxing` wheel, which publishes CPython 3.14
  musllinux builds for both x86_64 and aarch64.

### 3. Read-only BLE protocol

- Scope: advertising identity match, segmentation, login, authenticated notification decryption, and mechanism-state parsing.
- Verification: deterministic protocol tests with synthetic keys and packets.
- Risk: recorded assumptions may differ from live firmware or proxy behavior.

### 4. Home Assistant integration

- Scope: config entry, coordinator, device registry, state and battery entities, translations, diagnostics, and unload.
- Verification: compile, manifest checks available locally, unit tests, and source review proving no operation path.
- Risk: imports and dependency installation are only fully exercised after Core restart.

### 5. Stage and preflight

- Scope: copy the reviewed component into `/config/custom_components/candy_house_ble` without changing the old integration.
- Verification: exact directory diff, secret scan, and `ha core check`.
- Risk: `ha core check` does not prove config-flow runtime behavior before restart.

### 6. Later runtime and control gates

- Scope: restart with approval, add via uploaded QR, observe read-only state, then separately implement lock control.
- Verification: repeated live reads and reconnects; later, one explicitly authorized unlock and one lock with observed responses.
- Risk: physical-security impact; command retries must not repeat an action.

### 7. Lock entity control milestone — 2026-08-11

- Scope: add a primary `lock` entity, fixed authenticated lock/unlock packets,
  serialized poll/operation sessions, command acknowledgement plus terminal
  mechanism-state checking, and a compatibility period for the superseded
  state sensor.
- Verification: deterministic AES-CCM vectors, mocked GATT success/rejection,
  lock-state mapping, operation pending-state cleanup, duplicate suppression,
  full unit tests, lint, compile, JSON validation, exact production sync, and
  `ha core check`.
- Safety boundary: there is no toggle, open, registration, key-management, or
  generic encrypted-command API. The assistant does not perform physical
  lock/unlock testing; the device owner tests from the Home Assistant UI after
  a separately approved Core restart.
- Remaining runtime risk: BLE firmware response and physical actuation remain
  unverified until that owner-run UI test.
- Migration gate: retain the legacy state sensor until the new entity has passed
  that UI test and local consumers have been inventoried and migrated.

### 8. BLE responsiveness hardening — 2026-08-11

- Give explicit lock operations priority over background status polling. A poll
  that is already waiting for status is ended and disconnected before the
  command session begins; the physical command itself is never retried.
- Relax normal polling from 15 to 30 seconds to reduce connection contention
  with Hub 3, phones, and the selected Home Assistant Bluetooth proxy.
- Keep the cached state only during the short poll-to-operation handoff. If the
  operation then fails, mark coordinator data unavailable rather than presenting
  the cached lock state as current.
- Record phase timing for successful operations that take at least five seconds,
  without logging credentials or packet contents.

### 9. Optional Hub 3 command transport — 2026-08-11

- Keep status and diagnostic polling entirely on local BLE, but allow an
  options-selected hybrid mode in which explicit lock/unlock commands use the
  public CANDY HOUSE Web API through Hub 3.
- Store the Web API key and its separate 16-byte device secret only in the Home
  Assistant config entry. Validate them with one read-only request when options
  are saved; do not reuse or expose the BLE manager key.
- Disable remote unlock by default. Expose no toggle, generic command, history,
  registration, or key-management method.
- Send each physical command exactly once even when cached BLE state already
  matches the target. Never retry a command after HTTP, quota, or confirmation
  failure.
- Confirm the command with a fresh matching cloud shadow. Normal success uses
  one POST and one GET; at most two confirmation GETs are allowed. State polling
  remains BLE to preserve local operation and the Web API quota.
- Harden the BLE handoff at the same time: a user operation can cancel a poll
  while it is still connecting, and notifications from an obsolete BLE session
  are ignored by generation number.
- Verification uses synthetic credentials, a fixed AES-CMAC vector, exact
  mocked HTTP requests, transport-routing tests, BLE race tests, full lint/unit
  tests, compilation, JSON checks, exact production sync, and `ha core check`.
  The assistant does not send a real API command or operate the physical lock.

## Red-team gate

The architecture review verdict was **REVISE**. This plan incorporates its required fixes: synthetic-only repository fixtures, QR dependency as the first spike, advertisement-identity resolution, read-only-first deployment, no physical command retry, and coexistence with the prototype integration.
