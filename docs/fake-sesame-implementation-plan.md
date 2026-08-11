# Fake SESAME implementation plan

## Objective

Turn the two fixed buttons of one otherwise-empty CANDY HOUSE Remote Nano into
distinct Home Assistant events. A dedicated AtomS3 Lite emulates the minimum
SESAME OS 3 BLE peripheral and forwards authenticated lock/unlock commands over
the ESPHome native API without operating a physical lock.

## Acceptance criteria

1. The supplied Remote Nano manager QR is reduced to model, permission level,
   device UUID and secret key in a separate mode-0600 file under
   `/config/.tools/home-assistant-candy-house-ble/credentials/`. The raw QR URI,
   UUID and secret do not occur in the repository, test output, logs or commits.
   The previously saved Remote Nano credential is not overwritten.
2. Deterministic host-side tests cover target address derivation, OS 3 session
   key derivation, encrypted framing, login, lock/unlock decoding,
   acknowledgement, malformed input, replay/duplicate rejection and event
   mapping. The repository validation suite exits zero.
3. An ESPHome external component for AtomS3 Lite builds with the installed
   ESPHome version and exposes no physical lock output, generic command relay,
   credential logging or cloud operation.
4. The generated synthetic UUID and secret are stored only in an ignored,
   mode-0600 persistent file and injected into the build without becoming part
   of tracked source, generated logs or compiler command output.
5. `esphome config` and `esphome compile` exit zero for the dedicated AtomS3
   Lite configuration without modifying an existing Bluetooth proxy.
6. Before flashing, an independent review proves the firmware advertisement is
   the intended 30-byte SESAME OS 3 packet and the Bluetooth address is derived
   from the synthetic UUID with the documented byte order. Runtime over-air
   confirmation is marked **unverified** until the Atom is flashed.
7. A Home Assistant-side provisioning path can authenticate to Remote Nano and
   read its target list without invoking item 101 (add) or item 103 (remove).
   The physical list-empty observation is **unverified** until the read-only
   probe runs.
8. No firmware flash and no Remote Nano target-list write occurs until the exact
   serial/network target and generated identity have passed all prior checks
   and the user explicitly approves that external-state change.
9. Button-to-event behavior, duplicate-free repeated presses and reboot
   persistence remain **unverified** until after the separately approved flash
   and one-target provisioning probe.

## Non-goals

- Publishing the fake device through CANDY HOUSE cloud or Matter. The official
  app is used only as a local provisioning UI for the synthetic identity.
- Emulating a motor, physical lock, history store, firmware update or complete
  SESAME implementation.
- Reusing a production ESPHome Bluetooth proxy or accepting simultaneous proxy
  operation on the AtomS3 Lite.
- Reading, modifying or relying on a real lock credential.
- Releasing a new HACS version, pushing commits, or restarting Home Assistant.

## Constraints

- Do not touch `/config/secrets.yaml`, `/config/.ssh/` or `/config/.storage/`.
- Real and synthetic credentials stay under ignored persistent storage with
  mode 0600; committed tests use fixed public synthetic vectors only.
- Remote Nano writes, firmware flashing and physical button tests are explicit
  phase gates. Read-only inspection is not permission to write.
- The existing `/config/esphome/hallway.yaml` proxy and every other production
  node remain unchanged.
- A failed BLE authentication or malformed/replayed command produces no event.
  The component accepts one BLE client and drops session state on disconnect.

## Rollback

Before provisioning, rollback is deletion of the dedicated Atom configuration,
external component and generated synthetic credential; no device state changes.
After a future approved provisioning probe, send item 103 for only the generated
synthetic UUID, verify the original target count, then erase or disable the Atom
firmware. Existing Remote credentials and production proxies are retained.

## Implementation increments

### Increment 1: credentials and portable protocol core

- Scope: preserve the new Remote manager credential separately, generate a fake
  identity, and implement protocol/address primitives independently of ESPHome.
- Verification: file-mode and no-secret scans plus deterministic native tests.
- Risk: byte order or counter handling can be internally consistent but wrong
  on air; compare against public SDK vectors and a separately computed packet.

### Increment 2: ESPHome peripheral component

- Scope: implement raw GAP advertising, GATTS characteristics, session state,
  command validation and two ESPHome event types for AtomS3 Lite.
- Verification: component unit/static tests, `esphome config`, and full compile.
- Risk: ESP-IDF callback ownership and pre-initialization MAC configuration may
  conflict with ESPHome's shared BLE stack despite a successful host test.

### Increment 3: read-only Remote provisioning client

- Scope: add Remote Nano QR parsing and target-list read support to the custom
  integration without exposing add/remove operations in Home Assistant UI.
- Verification: synthetic tests prove the read path and prove write item codes
  cannot be reached; `ha core check` after staging Python changes.
- Risk: Remote Nano target slots or model-specific status may differ from the
  public SDK and require a bounded physical read.

### Increment 4: external-state gate

- Scope: report compile artifact, resolved device target, read-only target count,
  over-air verification plan and exact rollback command.
- Verification: acceptance table with flash, item 101 and button behavior still
  marked unverified.
- Risk: proceeding without explicit approval could alter the wrong board or
  Remote; stop before either write.

## Execution record (2026-08-11)

| Check | Result |
|---|---|
| New Remote Nano manager credential stored separately with mode 0600 | Pass |
| Synthetic fake-device identity stored outside the repository with mode 0600 | Pass |
| Exact-credential scan of repository content | Pass |
| Host protocol and integration tests | Pass (176 tests) |
| Reference ESPHome build | Pass |
| Production AtomS3 Lite ESPHome build | Pass (ESPHome 2025.11.0 and 2026.7.4) |
| Home Assistant configuration check after staging the read-only probe | Pass |
| Core restart and physical Remote target-list read | Superseded by official-app provisioning |
| AtomS3 Lite serial target resolution and firmware flash | Pass |
| Synthetic target registration in Remote Nano | Pass, through the official app |
| SESAME-compatible GATT handles and properties | Pass (`13/15/16`, write + write-no-response) |
| Remote Nano authentication and segmented encrypted command | Pass |
| One lock and one unlock Home Assistant event | Pass |
| Repeated 20-press and post-reboot persistence probe | Pending |

The successful runtime path is Remote Nano -> synthetic SESAME BLE peripheral
on AtomS3 Lite -> ESPHome native API ->
`esphome.candy_house_ble_button` Home Assistant event with the synthetic
`device_id`, the authenticated `remote_id`, and `action: lock` or
`action: unlock`. Bluedroid's default
application service range begins at handle 40; the component reserves a
dedicated range so the operational handles match a physical SESAME 5. Remote
Nano also requires the write characteristic to advertise both write modes.
