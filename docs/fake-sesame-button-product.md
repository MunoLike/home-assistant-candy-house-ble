# Fake SESAME button bridge product specification

## Product outcome

1. Build a Fake SESAME lock with the supplied ESPHome external component,
   register it in the official SESAME app, and pair one or more CANDY HOUSE
   Remotes with it.
2. Home Assistant discovers the Fake SESAME bridge over mDNS without a QR
   upload or a manual integration flow.
3. The first authenticated press from each paired Remote creates a separate
   child device with one button-class event entity. Lock and unlock commands
   update only that Remote's entity with event type `lock` or `unlock`.

One Fake SESAME is one bridge device with zero or more physical Remote child
devices. The authenticated history tag supplies a stable 16-byte Remote
identifier. The bridge cannot enumerate its pairing list, so discovery is
deliberately press-driven.

## Architecture

- Discovery uses `_candyhouseble._tcp.local.`. Its TXT records contain a
  protocol version, bridge kind, and the synthetic SESAME UUID. The UUID is an
  identifier, not the synthetic secret key.
- Press delivery uses the Home Assistant event
  `esphome.candy_house_ble_button` with `device_id`, `remote_id`, and `action`
  fields.
- A zeroconf config flow creates a secret-free Fake SESAME config entry. The
  entry loads only the `event` platform and never opens a BLE connection.
- The event manager accepts only `lock` and `unlock` events whose `device_id`
  exactly matches its config entry and whose `remote_id` is a valid UUID.
- Discovered Remote UUIDs persist in the config entry and are restored on
  reload. The former aggregate bridge event entity is removed by migration.
- The physical Remote-to-Fake-SESAME link remains authenticated SESAME OS 3
  BLE. Home Assistant and Wi-Fi are downstream of that authenticated command.

## Executable acceptance criteria

1. Config-flow tests feed a valid zeroconf service record and assert that a
   config entry is created with the synthetic UUID as unique ID and without a
   secret key.
2. Config-flow tests reject an unsupported bridge kind, protocol version,
   malformed UUID, and duplicate discovery.
3. Platform tests assert that the Fake SESAME entry loads only `event`, restores
   one button-class event entity per persisted Remote, and exposes `lock` and
   `unlock` as its event types.
4. Event tests assert that a first valid press creates and persists exactly one
   Remote entity without losing that press, repeated presses do not duplicate
   it, and malformed or cross-bridge events are ignored.
5. The ESPHome reference configuration and the production configuration both
   validate and compile with the installed ESPHome CLI. Generated sources must
   contain the dedicated mDNS service and both structured event actions.
6. The repository validation script exits zero, including the complete test
   suite and exact-secret scans.
7. The staged custom component passes `ha core check`. Home Assistant is not
   restarted without a separate user-approved deployment step.
8. Physical verification with two paired Remotes confirms that each Remote's
   lock and unlock buttons update only its own event entity.

## Non-goals

- Replaying a press that occurred while Home Assistant or the ESPHome native
  API was disconnected.
- Operating a motor, exposing a lock entity, or publishing the fake device to
  CANDY HOUSE cloud or Matter.
- Discovering Fake SESAME devices by imitating or heuristically matching a real
  SESAME BLE advertisement.
- Supporting arbitrary hand-written ESPHome configurations that omit the mDNS
  and structured-event portions of the supplied reference configuration.

## Rollback

Remove the automatically created Fake SESAME config entry and flash or disable
the bridge configuration. Existing real lock and Bot 2 entries are independent.
Remote target removal remains an official-app operation.
The corresponding Home Assistant child device currently requires manual
removal after unpairing because there is no reliable local absence signal.

## Execution record (2026-08-11)

| Criterion | Result |
|---|---|
| Zeroconf entry creation and rejection tests | Pass |
| Event-platform isolation and event filtering tests | Pass |
| Full repository validation | Pass (187 tests) |
| ESPHome 2026.7.4 reference build | Pass |
| ESPHome 2026.7.4 production build | Pass |
| Generated mDNS and structured-event code inspection | Pass |
| Live custom-component staging and `ha core check` | Pass |
| Atom OTA with discovery/event firmware | Pass |
| Core restart and automatic config-entry discovery | Pass |
| Physical `lock` and `unlock` event-entity verification | Pass |
| Stable per-Remote identifier across repeated lock/unlock presses | Pass (two Remote Nano devices) |
| Separate HA child devices and physical 2x2 routing | Pass (two Remote Nano devices) |
