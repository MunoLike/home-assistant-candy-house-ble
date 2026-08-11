# CANDY HOUSE BLE

Local Bluetooth integration for CANDY HOUSE SESAME devices in Home Assistant.

The integration supports SESAME 5 Pro through Home Assistant Bluetooth and
ESPHome Bluetooth proxies. Setup accepts a manager share QR image, decodes it
inside Home Assistant, stores only the parsed credential in the Home Assistant
config entry, and deletes the uploaded image.

The primary entity is a local BLE lock supporting explicit lock and unlock
operations. Diagnostic entities expose battery-critical state, battery voltage,
Bluetooth signal strength, thumb-turn angle, movement, and mechanism errors.
Polling and operations each use one short BLE session.

The original state sensor remains available during the initial lock-entity
validation period. It is deprecated and will be removed only after local
dashboard and automation consumers have been migrated.

Movement is a snapshot taken at the 15-second poll, not an event detector; a
short movement between polls can be missed. The RSSI entity is disabled by
default to avoid noisy Recorder history and can be enabled from the device page.

## Status

This repository is under active development and has no released version yet.
Lock and unlock commands are implemented but still require physical validation
by the device owner through the Home Assistant UI.

## Privacy and security

- QR images and raw `ssm://` URIs are temporary input and are not logged.
- Real device credentials are never test fixtures and must not be committed.
- Tests generate synthetic credentials and QR images at runtime.
- The command surface is limited to lock and unlock; there is no generic BLE
  command API.

See [the implementation plan](docs/implementation-plan.md) for acceptance
criteria, rollback, and the staged rollout procedure.

## License

MIT
