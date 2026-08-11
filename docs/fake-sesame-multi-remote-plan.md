# Fake SESAME multi-Remote plan

## Objective

Represent every physical CANDY HOUSE Remote paired with one Fake SESAME as a
separate Home Assistant device, with one button-class event entity carrying
`lock` and `unlock` events.

## Acceptance criteria

1. Protocol capture from at least two physical Remotes shows a stable identifier
   for each Remote, identical for repeated lock/unlock presses and distinct
   between the two Remotes. If this cannot be demonstrated, implementation
   stops before using BLE peer addresses or another unstable surrogate.
2. Firmware validation proves that authenticated lock/unlock commands emit
   `esphome.candy_house_ble_button` with `device_id`, `remote_id`, and `action`,
   while malformed or identifier-free commands do not create an identified
   Remote event.
3. Integration tests prove that the first valid event from a new `remote_id`
   creates exactly one event entity and one child device, and that later events
   update only that Remote's entity.
4. Integration tests prove that two distinct `remote_id` values under one bridge
   create two distinct devices/entities, while the same `remote_id` under two
   bridges cannot collide.
5. Discovered Remote identifiers persist in the Fake SESAME config entry and are
   restored after an integration/Core reload without requiring another press.
6. Migration removes the former aggregate bridge event entity without touching
   physical SESAME lock or Bot 2 entities.
7. `./scripts/validate.sh`, both ESPHome configuration validations, the production
   ESPHome compile, and `ha core check` exit zero.
8. Physical verification with two paired Remotes confirms that each Remote
   updates only its own HA event entity for both buttons. This criterion remains
   unverified until the device owner performs the four presses.

## Non-goals

- Importing Remote names, rooms, or metadata from the CANDY HOUSE cloud.
- Identifying an unpaired or unauthenticated transmitter.
- Treating a BLE peer address as durable identity.
- Replaying presses made while the ESPHome native API is disconnected.

## Constraints

- Preserve all existing uncommitted repository work.
- Do not read or modify `secrets.yaml`, `.ssh/`, or `.storage/`.
- Never log a full Remote identifier at normal log levels; short suffixes are
  acceptable for operator diagnostics.
- Keep the physical BLE authentication and Fake SESAME identity unchanged so
  already paired Remotes do not require re-pairing.
- Do not restart Home Assistant or deploy firmware without the user's existing
  explicit authorization; run `ha core check` before any Core restart.

## Rollback

Restore the pre-change firmware component, YAML event payload, event platform,
config-flow version, translations, and tests from the working-tree diff; flash
the previous known-good ESPHome binary; stage the previous custom component;
run `ha core check`; then restart Core only with authorization. Existing
physical pairing survives because the Fake SESAME UUID and secret are not
rotated.

## Increments

| Increment | Scope | Verification | Principal risk |
| --- | --- | --- | --- |
| 1 | Capture and parse the authenticated command history tag | Two-Remote repeated-press matrix | Tag may omit or change Remote identity |
| 2 | Carry validated `remote_id` from firmware to HA event | Unit tests plus generated-code inspection | Exposing or misparsing identifiers |
| 3 | Dynamically create and persist one child device/entity per Remote | Integration tests including reload | First press loss or duplicate entities |
| 4 | Migrate aggregate entity and stage production files | Full validation and `ha core check` | Existing entity registry residue |
| 5 | Deploy and verify two physical Remotes | Four observed event updates | Runtime timing or API disconnects |

## Execution record (2026-08-12)

- Two Remote Nano devices produced distinct stable 16-byte identifiers across
  repeated lock and unlock commands. No BLE peer address is used as identity.
- Firmware now emits the validated identifier as `remote_id`; malformed or
  identifier-free commands do not emit a Remote button event.
- The production ESPHome configuration compiles successfully with ESPHome
  2026.7.4.
- HA migration removed the aggregate event entity. Two child devices were then
  discovered independently on first press and persisted in the config entry.
- All 192 tests, static checks, production ESPHome compile, OTA, and
  `ha core check` passed.
- Physical verification passed for both lock and unlock on each of two Remote
  Nano devices; each action updated only the matching child event entity.
