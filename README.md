# CANDY HOUSE BLE

Local Bluetooth integration for CANDY HOUSE SESAME devices in Home Assistant.

The integration supports SESAME 5 Pro, SESAME 6 Pro, SESAME Bot 2, and SESAME
Bot 3 through Home Assistant Bluetooth and ESPHome Bluetooth proxies. It also includes an ESPHome Fake
SESAME button bridge for reusing CANDY HOUSE Remotes as Home Assistant buttons.
Physical-device setup accepts a manager share QR
image, decodes it inside Home Assistant, stores only the parsed credential in
the Home Assistant config entry, and deletes the uploaded image.

The primary entity is a local BLE lock supporting explicit lock and unlock
operations. Diagnostic entities expose battery-critical state, battery voltage,
Bluetooth signal strength, thumb-turn angle, movement, and mechanism errors.
Polling and operations each use one short BLE session. Normal polling runs every
30 seconds; an explicit Home Assistant lock operation preempts an in-flight
background poll instead of waiting behind its timeout.

Version 0.3.0 and later intentionally support only local BLE. Hub 3/cloud command
transport and its options were removed so connection latency and reliability can
be attributed to one transport. Running Hub 3 against the same SESAME at the
same time is outside the supported configuration because it can contend for the
device. Migrating an older config entry removes its saved Web API options; a
downgrade to 0.2.0 requires entering those credentials again.

The Home Assistant diagnostics download includes process-local aggregate BLE
session and operation outcomes and successful timing statistics. It contains no
raw packets or exception messages and resets whenever the entry reloads or Core
restarts. The observation timestamp identifies the measured interval; entity
availability/history is the durable view across restarts.

SESAME Bot 2 and Bot 3 expose ten buttons for directly running on-device script slots
0 through 9. Script actions and slot meanings are edited in the official app;
Home Assistant deliberately does not edit scripts or cache semantic aliases.
The item-code mapping is pinned to the official Android SDK behavior at commit
[`436249f`](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/436249f77f21302aa69956bfe487d2670b997e9f/sesame-sdk/src/main/java/co/candyhouse/sesame/ble/os3/CHSesameBot2Device.kt#L73-L110).
Commands are serialized through device acknowledgement and are never retried.
A short cooldown rejects accidental double presses; an acknowledgement timeout
is reported as an indeterminate outcome and applies a longer retry cooldown.
Bot 2/3 diagnostic entities expose battery voltage, Bluetooth signal strength,
and whether the motor is moving.

## Fake SESAME button bridge

The supplied ESPHome external component turns a dedicated ESP32-S3 into the
minimum authenticated SESAME OS 3 peripheral needed by Remote and Remote Nano.
It has no motor output and does not expose a lock entity.

Use the same stable version as the HACS integration when importing the
component:

```yaml
external_components:
  - source: github://Khronos31/home-assistant-candy-house-ble@v0.3.0
    components: [fake_sesame]
```

1. Run `python firmware/tools/stage_fake_identity.py --rotate` **once** to
   create a synthetic identity, then build the reference layout in
   [`firmware/examples/fake-sesame-atom-s3-lite.yaml`](firmware/examples/fake-sesame-atom-s3-lite.yaml).
   Keep the generated UUID and secret outside the repository. Do not rotate it
   after app/Remote pairing unless you intend to repeat that pairing.
2. Register the synthetic lock in the official SESAME app and use the app to
   pair one or more Remotes with it.
3. When the flashed ESPHome node comes online, its dedicated mDNS record causes
   Home Assistant to add a **Fake SESAME Button Bridge** device automatically
   under CANDY HOUSE BLE. No QR upload is used for this entry.
4. Press each paired Remote once. The integration creates a separate child
   device and **Remote button** event entity for that physical Remote. Its event
   types are `lock` and `unlock`; subsequent presses update only that Remote's
   entity.

Remote discovery occurs on its first authenticated press because the Fake
SESAME cannot enumerate paired Remotes. Discovered identifiers persist across
reloads. Unpaired Remotes must currently be removed manually from Home
Assistant. Events are live, at-most-once notifications. A press made while
ESPHome or its Home Assistant native API connection is offline is not replayed
later. See the
[product specification](docs/fake-sesame-button-product.md) for protocol,
security boundary, acceptance criteria, and rollback.

Movement is a snapshot taken at the 30-second poll, not an event detector; a
short movement between polls can be missed. The RSSI entity is disabled by
default to avoid noisy Recorder history and can be enabled from the device page.

## Status

Current version: **0.3.0**.
SESAME 5 Pro state reporting and lock/unlock commands, SESAME Bot 2 BLE status
and script execution, and authenticated Remote-to-Fake-SESAME press delivery
have been physically validated by the device owner. Automatic button-device
discovery and end-to-end delivery of both `lock` and `unlock` through the
CANDY HOUSE BLE **Remote button** event entity have also been validated. The
per-Remote identity and physical routing paths have been validated with both
buttons on two Remote Nano devices.

SESAME 6 Pro (model 21) and SESAME Bot 3 (model 35) support is a local
extension of v0.3.0. Both pass simulated BLE and entity tests; physical-device
validation is still pending. The official Android SDK maps them to the same
lock and Bot implementations as SESAME 5 Pro and Bot 2, respectively:
[`CHProductModel` at `17b39dd`](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/17b39dd19c0f0a2bb27fb8c6617850fc56f4438a/sesame-sdk/src/main/java/co/candyhouse/sesame/open/devices/base/CHDeivceProtocols.kt).
The existing OS3 status parsing and battery-voltage scaling are reused (locks:
raw millivolts × 2; Bots: raw millivolts). Verify voltage readings on hardware.

To install this local extension, copy `custom_components/candy_house_ble` to
Home Assistant's `config/custom_components/` directory and restart Core. Add
each device under **Settings → Devices & services → Add integration →
CANDY HOUSE BLE** using its manager share QR image from the official app.
Configure Bot 3 script slots in the official app before pressing their buttons.
After installation, check status and battery readings, then test one Bot script
and both lock operations on the physical devices. Reinstalling the published
v0.3.0 through HACS replaces these local changes.

## Releases

`VERSION` is the repository source of truth. Every stable release versions the
HACS integration and ESPHome component together, even when only one side has
code changes. Run `python scripts/version.py sync X.Y.Z` to update it together
with the Home Assistant manifest, firmware component, and README references,
or use `python scripts/version.py check` to verify that all representations
agree.

Repository owners can run the **Release** workflow from the `main` branch with
a stable `X.Y.Z` version. It synchronizes the version, runs the same validation
as pull requests, atomically pushes the version commit and annotated `vX.Y.Z`
tag, and publishes a GitHub Release with generated notes. A rerun safely
finishes a Release that failed after its tag was pushed, provided that the tag
still points to the current `main` commit.

## Privacy and security

- QR images and raw `ssm://` URIs are temporary input and are not logged.
- Real device credentials are never test fixtures and must not be committed.
- Tests generate synthetic credentials and QR images at runtime.
- The command surface is limited to lock, unlock, and Bot 2/3 script slots 0
  through 9; there is no generic BLE or cloud command method and no Bot 2/3
  script-editing method.
- Version 4 config-entry migration removes the Web API options formerly stored
  by version 3. BLE manager credentials remain redacted from diagnostics and
  are never written to repository logs or fixtures.
- Fake SESAME mDNS carries only the synthetic device UUID. Home Assistant
  button events additionally carry the physical Remote UUID and fixed action
  name. They never carry either device's secret key.

See [the implementation plan](docs/implementation-plan.md) for acceptance
criteria, rollback, and the staged rollout procedure.

## License

MIT
