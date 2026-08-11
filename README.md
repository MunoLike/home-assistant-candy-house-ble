# CANDY HOUSE BLE

Local Bluetooth integration for CANDY HOUSE SESAME devices in Home Assistant.

The integration supports SESAME 5 Pro and SESAME Bot 2 through Home Assistant
Bluetooth and ESPHome Bluetooth proxies. Setup accepts a manager share QR
image, decodes it inside Home Assistant, stores only the parsed credential in
the Home Assistant config entry, and deletes the uploaded image.

The primary entity is a local BLE lock supporting explicit lock and unlock
operations. Diagnostic entities expose battery-critical state, battery voltage,
Bluetooth signal strength, thumb-turn angle, movement, and mechanism errors.
Polling and operations each use one short BLE session. Normal polling runs every
30 seconds; an explicit Home Assistant lock operation preempts an in-flight
background poll instead of waiting behind its timeout.

If Hub 3 is available, the integration options can instead route explicit lock
and unlock commands through the public CANDY HOUSE Web API while keeping all
periodic state and diagnostic polling on local BLE. This hybrid mode avoids the
BLE connection delay seen when Hub 3 and Home Assistant compete for the same
lock. It requires a Web API key and the separate Web API device secret; the BLE
manager key from the setup QR is not interchangeable with that secret.

Remote unlock is disabled by default and must be explicitly enabled in the
integration options. A command is posted exactly once and is never retried. The
service call succeeds when the API accepts the command and consumes one API
request. It does not claim an unobserved target state: the entity retains its
last local BLE state, then starts a delayed BLE refresh in the background.
Hub 3's immediate cloud shadow proved too stale for synchronous physical-state
confirmation. [CANDY HOUSE currently documents](https://jp.candyhouse.co/pages/sesame-biz-operation)
a free allowance of 1,000 requests per month, so cloud mode is intentionally not
used for periodic polling or post-command status reads.

SESAME Bot 2 exposes ten buttons for directly running on-device script slots
0 through 9. Script actions and slot meanings are edited in the official app;
Home Assistant deliberately does not edit scripts or cache semantic aliases.
The item-code mapping is pinned to the official Android SDK behavior at commit
[`436249f`](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/436249f77f21302aa69956bfe487d2670b997e9f/sesame-sdk/src/main/java/co/candyhouse/sesame/ble/os3/CHSesameBot2Device.kt#L73-L110).
Commands are serialized through device acknowledgement and are never retried.
A short cooldown rejects accidental double presses; an acknowledgement timeout
is reported as an indeterminate outcome and applies a longer retry cooldown.
Bot 2 diagnostic entities expose battery voltage, Bluetooth signal strength,
and whether the motor is moving.

Movement is a snapshot taken at the 30-second poll, not an event detector; a
short movement between polls can be missed. The RSSI entity is disabled by
default to avoid noisy Recorder history and can be enabled from the device page.

## Status

Current version: **0.1.0**.
SESAME 5 Pro state reporting and lock/unlock commands, and SESAME Bot 2 BLE
status and script execution, have been physically validated by the device owner
through the Home Assistant UI.

## Releases

`VERSION` is the repository source of truth. Run
`python scripts/version.py sync X.Y.Z` to update it together with the Home
Assistant manifest and this README, or use `python scripts/version.py check` to
verify that all three agree.

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
- The command surface is limited to lock, unlock, and Bot 2 script slots 0
  through 9; there is no generic BLE or Web API command method and no Bot 2
  script-editing method.
- Web API credentials are stored only in the Home Assistant config entry and
  its backups. They are never written to this repository or logs.

See [the implementation plan](docs/implementation-plan.md) for acceptance
criteria, rollback, and the staged rollout procedure.

## License

MIT
