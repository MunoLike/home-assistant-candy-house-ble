# CANDY HOUSE BLE

Local Bluetooth integration for CANDY HOUSE SESAME devices in Home Assistant.

The first development milestone supports read-only status from SESAME 5 Pro
through Home Assistant Bluetooth and ESPHome Bluetooth proxies. Setup accepts a
manager share QR image, decodes it inside Home Assistant, stores only the parsed
credential in the Home Assistant config entry, and deletes the uploaded image.

The read-only entities currently expose mechanism state, battery-critical state,
battery voltage, Bluetooth signal strength, thumb-turn angle, movement, and
mechanism errors. A poll uses one short BLE session and does not send a physical
lock command.

Movement is a snapshot taken at the 15-second poll, not an event detector; a
short movement between polls can be missed. The RSSI entity is disabled by
default to avoid noisy Recorder history and can be enabled from the device page.

## Status

This repository is under active development and has no released version yet.
The current milestone deliberately contains no lock or unlock command path.

## Privacy and security

- QR images and raw `ssm://` URIs are temporary input and are not logged.
- Real device credentials are never test fixtures and must not be committed.
- Tests generate synthetic credentials and QR images at runtime.
- Physical lock commands will be developed and tested in a separate gated
  milestone.

See [the implementation plan](docs/implementation-plan.md) for acceptance
criteria, rollback, and the staged rollout procedure.

## License

MIT
