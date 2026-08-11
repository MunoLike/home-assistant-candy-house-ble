# Fake SESAME bridge research

Status: research complete enough for a bounded implementation probe; no
firmware implementation, Remote Nano target write or deployment has started.

Research date: 2026-08-11.

## Objective

Determine whether an ESPHome node can emulate the minimum SESAME OS 3 BLE
peripheral required to turn the two fixed buttons on a CANDY HOUSE Remote Nano
into two distinct Home Assistant events.

The intended path is entirely digital:

```text
Remote Nano -> emulated SESAME over BLE -> ESPHome native API -> Home Assistant
```

## Acceptance criteria for the research phase

1. Every required BLE advertisement field, GATT service and characteristic is
   identified from a public primary source or explicitly marked unknown.
2. The registration payload used to add an emulated SESAME to Remote Nano is
   identified without using or recording a real device credential.
3. The login, framing, encryption, command and response state machines are
   described precisely enough to build deterministic host-side test vectors.
4. ESPHome responsibilities are separated into standard declarative features
   and the BLE peripheral work that requires an external C++ component.
5. All assumptions that require a physical Remote Nano are collected into one
   bounded, reversible probe plan.

## Non-goals

- Emulating a complete lock, motor, history store, cloud device or Matter
  bridge.
- Making the emulated device appear in the official CANDY HOUSE app or cloud.
- Modifying Remote Nano settings, paired-device slots or firmware during the
  research phase.
- Modifying an in-service Home Assistant Bluetooth proxy during the research
  phase.
- Supporting arbitrary CANDY HOUSE commands. Only fixed lock and unlock input
  events are in scope.

## Constraints

- Real QR contents, UUIDs, manager keys, SESAME secret keys and captured
  plaintext/ciphertext must remain outside Git and logs.
- `secrets.yaml`, `.ssh/` and `.storage/` are out of scope.
- The first active probe must use a synthetic UUID and secret and must not pair,
  operate or impersonate a real lock.
- Remote Nano paired-device writes and ESPHome firmware installation require a
  separate implementation specification and explicit approval.
- Existing Home Assistant YAML and production ESPHome nodes are unchanged in
  this research phase.

## Proposed minimum design

1. A dedicated M5Stack AtomS3 Lite (ESP32-S3FN8) advertises one synthetic
   SESAME OS 3 lock identity. It uses ESP-IDF through ESPHome and does not act
   as a Bluetooth proxy.
2. An ESPHome external component exposes the SESAME GATT service, accepts one
   Remote Nano client and implements only session authentication plus fixed
   lock/unlock commands.
3. Successful authenticated lock and unlock commands trigger the `lock` and
   `unlock` event types of one ESPHome template event entity. They never
   operate a physical lock.
4. A Home Assistant-side provisioning tool uses the already-supported Remote
   Nano manager session to add or remove only the synthetic target credential.
5. Provisioning and runtime secrets are stored in ignored persistent storage;
   test fixtures use generated credentials only.

The long-term support boundary for CANDY HOUSE BLE is local BLE only. Cloud
command transport through Hub 3 is to be removed in a separate, explicitly
versioned migration. A physical SESAME managed by this integration while the
same SESAME is also actively managed through Hub 3 is unsupported; the
integration will not attempt connection arbitration with Hub 3. This does not
require removing Hub 3 from the household or prohibit using it for devices
outside this integration.

The fake bridge proof and removal of the released cloud transport are separate
changes. Proving the bridge must not modify the working command transport of an
existing lock entry.

## Research conclusion

The bridge is technically plausible. Public CANDY HOUSE sources disclose the
complete host-side registration and SESAME OS 3 session protocol needed for a
minimal target. ESPHome provides a shared BLE stack with GATTS event routing and
a native Home Assistant event entity. Two points still require a physical probe:

1. Remote Nano may connect to the Bluetooth address derived from the registered
   UUID instead of discovering a target solely by its advertisement UUID. The
   AtomS3 Lite must therefore use the derived address with verified byte order.
2. The public sources do not say whether Remote Nano accepts an immediate
   command response by itself or also waits for a mechanism-status transition
   before considering a press complete.

Neither point requires a real lock credential. Both can be tested with one
generated UUID and secret and an otherwise empty Remote Nano target list.

## Why the simpler paths are insufficient

- The public Remote Nano capability exposes trigger-delay configuration and its
  published value, not button presses. A previous bounded listen-only probe saw
  no usable press notification. Treating Remote Nano as a directly observed BLE
  button is therefore not an implementation path.
- An ESPHome Bluetooth proxy forwards scans and Home Assistant-initiated GATT
  client connections. It does not make Home Assistant a GATT peripheral, so it
  cannot impersonate a SESAME target.
- A generic ESPHome button would be much cheaper and more maintainable, but it
  does not satisfy the specific objective of reusing Remote Nano. It remains the
  fallback if private-protocol maintenance becomes disproportionate.

## Minimum SESAME identity

The first target should identify as SESAME 5, product type `0x05`. The Android
SDK treats the manufacturer-specific value as:

| Offset | Size | Meaning |
| --- | ---: | --- |
| 0 | 1 | product type, `0x05` |
| 1 | 1 | reserved, `0x00` |
| 2 | 1 | flags; bit 0 set means registered |
| 3 | 16 | UUID bytes in undashed UUID order |

The exact 30-byte legacy advertising packet is:

```text
02 01 06
16 FF 5A 05 05 00 01 <16-byte synthetic UUID>
03 03 81 FD
```

The three structures are Flags, CANDY HOUSE manufacturer data and the complete
16-bit service UUID list containing `0xFD81`. Advertising must use all three BLE
advertising channels.

The target Bluetooth address is documented as:

```text
token = AES-CMAC(key = synthetic_uuid_bytes, input = ASCII "candy")
controller_address = token[0:6]
controller_address[5] = (controller_address[5] & 0x3F) | 0xC0
esp_idf_address = reverse(controller_address)
```

CANDY HOUSE documents the controller-order derivation with the static-random
bits at index five. ESP-IDF's `esp_bd_addr_t` instead stores the displayed
most-significant address byte at index zero, so the six derived bytes must be
reversed at that API boundary. For the synthetic UUID
`000102030405060708090a0b0c0d0e0f`, the CMAC is
`ae11bdb450299d5d20cb94fc449d28e0`, the controller-order post-mask bytes are
`ae11bdb450e9`, and the ESP-IDF/display-order address is `e950b4bd11ae`.
This vector contains no real credential.

## GATT surface

The target exposes one primary service and two characteristics:

| Role | UUID | Properties |
| --- | --- | --- |
| Service | `0000FD81-0000-1000-8000-00805F9B34FB` | primary |
| Remote to target | `16860002-A5AE-9856-B6D3-DBB4C676993E` | write without response |
| Target to Remote | `16860003-A5AE-9856-B6D3-DBB4C676993E` | notify, with CCCD `0x2902` |

Only one client is accepted. A new connection resets both segment reassembly
and session state. A disconnect destroys the session key, challenge and both
counters.

## Framing and session state machine

Each GATT value is at most 20 bytes. Its first byte is a segment header and the
remaining bytes are payload:

- bit 0 is the start flag;
- bits 7..1 are zero on a non-final segment;
- bits 7..1 are `1` on the final plaintext segment;
- bits 7..1 are `2` on the final encrypted segment.

Consequently a one-segment plaintext message starts with `0x03`, and a
one-segment encrypted message starts with `0x05`. Payloads longer than 19 bytes
are split; only the first segment has bit 0 set and only the last has a non-zero
parsing type.

The minimum connection sequence is:

1. Remote Nano connects and enables notifications through the CCCD.
2. The target generates a fresh four-byte challenge and sends plaintext
   `08 0E <challenge>` (`publish`, `initial`).
3. Both peers derive `session_key = AES-CMAC(secret, challenge)`.
4. Remote Nano sends plaintext `02 <session_key[0:4]>` (`login`). The target
   rejects a mismatching value and emits no event.
5. The target sends the encrypted plaintext
   `07 02 00 <uint32 timestamp little-endian>` (`response`, `login`, `success`).
6. Remote Nano sends an encrypted payload beginning with `52` for lock or `53`
   for unlock. Remaining bytes are an opaque history tag and are never logged.
7. After authenticated parsing and deduplication, the target triggers the
   corresponding ESPHome event and returns encrypted
   `07 <52 or 53> 00`.
8. If the physical probe shows it is required, the target then publishes an
   encrypted seven-byte mechanism status under `08 51`. No motor state or
   history is otherwise implemented.

AES-CCM uses the 16-byte session key, a four-byte authentication tag, one byte
of AAD equal to `0x00`, and this 13-byte nonce:

```text
uint64 counter little-endian || 00 || four-byte challenge
```

Target-to-Remote and Remote-to-target counters are independent and start at
zero after each challenge. Matching the public SDK, a counter advances once for
each complete encrypted frame consumed or emitted. Authentication failure must
terminate the session rather than attempting to resynchronize. Authentication
failure, an unexpected item code, malformed segmentation or a command received
before login must not trigger an event.

Synthetic deterministic vectors already used by the integration's protocol
tests can be reused in the external component tests:

```text
secret     = 00112233445566778899aabbccddeeff
challenge  = a1b2c3d4
sessionKey = ca62eb0cf87a39b1b4d0638b695299bf
login request                         = 03 02 ca 62 eb 0c
lock request at Remote TX counter 0   = 05 49 ed 14 87 f2 8a e9
unlock request at Remote TX counter 0 = 05 48 ed 14 89 b0 ab d7
```

For target TX counter 0, login response plaintext
`07 02 00 78 56 34 12` frames as
`05 1c ef 1a 68 99 34 b7 d8 b7 7b 12`. If a lock response follows in the same
session at target TX counter 1, plaintext `07 52 00` frames as
`05 54 a7 47 9b 1b da 59`.

## Remote Nano provisioning

The public Android SDK uses these authenticated commands on Remote/Remote Nano:

- add target, item `101`: `synthetic_uuid[16] || synthetic_secret[16]`;
- publish target list, item `102`: fixed 23-byte slots, suitable for checking a
  redacted occupied-slot count and locating the synthetic UUID;
- remove target, item `103`: `synthetic_uuid[16]`.

The synthetic target does not need a public key, owner credential, CANDY HOUSE
account or cloud registration. A manager credential for Remote Nano is enough
to authenticate the provisioning session. Whether the device firmware accepts
the synthetic entry remains a physical verification item.

## ESPHome implementation boundary

Declarative ESPHome configuration should own:

- AtomS3 Lite board selection using `esp32-s3-devkitc-1` and ESP-IDF;
- Wi-Fi, native API, OTA, logging and status LED policy;
- one template event entity with fixed `lock` and `unlock` event types;
- references to secrets without placing their values in the public repository.

The external component should own the complete BLE peripheral transport:

- deriving and installing the target BLE interface or static-random address
  before advertising, with a matching advertising address type;
- the exact raw 30-byte legacy advertisement;
- GATT service creation, CCCD lifecycle, per-connection session state and
  notifications;
- segmentation, AES-CMAC, AES-CCM, counters and constant-time login checking;
- the allowlist containing only login, lock and unlock;
- bounded deduplication and diagnostic counters that contain no credential or
  history-tag bytes.

ESPHome's standard BLE server demonstrates that GATT services, write callbacks
and notifications are supported, but it should not own this target at runtime.
ESPHome 2026.7.4 expands every advertised service UUID to 128 bits, while SESAME
needs the compact 16-bit FD81 structure alongside 19 bytes of manufacturer
payload. That expanded packet cannot preserve the documented 30-byte layout.
The standard server also restarts its own generated advertisement after a
disconnect, which would compete with a separately configured raw packet.

The external component should instead depend on ESPHome's shared `esp32_ble`
stack, register its own GAP/GATTS handlers, create the two characteristics and
own every advertisement restart. Its address-preparation stage must run before
ESPHome initializes Bluetooth. ESP-IDF exposes an interface-specific Bluetooth
MAC setter, so this need not alter the Wi-Fi identity; whether Remote Nano's
derived byte sequence must instead be installed as a static-random address is
left to the scanner gate. Every raw advertisement still requires an over-air
byte-for-byte test.

The physical probe established an additional compatibility requirement not
visible in the UUID-level SDK documentation. A SESAME 5 exposes write, notify
and CCCD at ATT handles 13, 15 and 16, and its write characteristic advertises
both `write` and `write-without-response`. Remote Nano did not complete login
with Bluedroid's default operational handles 42, 44 and 45, nor with only the
no-response property. Reserving the fake service at 11-18 produces the required
operational handles without patching ESP-IDF globally. With both write
properties present, Remote Nano subscribed, accepted the initial challenge,
authenticated, sent its segmented encrypted command and produced distinct HA
lock/unlock events.

The standard BLE server and Bluetooth proxy have no compile-time mutual
exclusion, but both share the controller, scanner/advertiser and connection
budget. ESPHome's connection-slot validation also does not reserve a client
slot for a one-client GATT server. This uncertainty is intentionally avoided:
the AtomS3 Lite bridge is a dedicated node and Bluetooth proxy functionality is
out of scope and unsupported.

Use ESP-IDF/mbedTLS CMAC and CCM APIs. Do not copy the official ESP32 demo's
`main/utils/aes-cbc-cmac.c`: although the repository root is MIT licensed, that
bundled file carries a GPLv3-or-later notice.

## Bounded physical probe

No step below is authorized by this research document. The implementation
phase must stop at each stated gate.

1. Build host tests for the byte vectors above, invalid authentication,
   counter separation, segmentation reset, item allowlisting and event
   deduplication.
2. Compile the external component and a dedicated AtomS3 Lite configuration
   against the same ESPHome release as the HA add-on.
3. With generated credentials only, flash the AtomS3 Lite after explicit
   approval. Do not modify a production Bluetooth proxy.
4. Before any Remote write, verify the derived BLE address and exact 30-byte
   advertisement using an independent scanner.
5. Read Remote Nano's target list. Continue only if it contains no real target;
   otherwise abort before any physical button press.
6. After explicit approval, add exactly one synthetic target. Confirm the
   occupied-slot count increased by one and the synthetic UUID is present.
7. Press unlock once and lock once. Record only item codes, packet lengths,
   authentication result, response timing and Home Assistant event type.
8. If both work, run 20 spaced alternating presses. Acceptance is 20 matching
   events, no duplicates, no wrong-button events, and the same result after an
   AtomS3 Lite reboot. Record latency for later threshold selection.
9. Remove the synthetic target, confirm the initial occupied-slot count, and
   erase or disable the test firmware if the probe is abandoned.

If Remote Nano cannot connect using a scanner-verified derived address, or if
it requires an undocumented mechanism exchange that cannot be bounded without
emulating a physical lock, stop rather than expand into a full SESAME clone.

## Red-team adjustments

A self-contained red-team pass returned `REVISE`. Its required adjustments are
incorporated above:

- address derivation and over-air verification precede Remote writes;
- the spare Remote must have no real target before presses;
- success means repeatable, duplicate-free events rather than one press;
- raw advertising is an external-component responsibility;
- fake-bridge work is separated from the later BLE-only integration migration.

## Rollback

Before an active probe, record the Remote Nano paired-target list as redacted
metadata. Rollback consists of removing the one synthetic target through the
same authenticated command, erasing the dedicated ESP32 firmware, and verifying
that the redacted target count and existing physical Remote behavior match the
starting state. No production proxy or real lock credential is replaced.

## Research questions

- Does Remote Nano use the documented derived address in the byte order exposed
  by ESP-IDF, and can the AtomS3 Lite present that identity without affecting
  its Wi-Fi identity?
- Is the initial publish, encrypted login response and encrypted command
  acknowledgement sufficient, or is a mechanism-status transition mandatory?
- What are Remote Nano's disconnect and retry timings after a successful or
  missing acknowledgement?
- How should button commands be deduplicated across reconnects without losing a
  legitimate second press?

## Phase boundary

After the questions above are answered or explicitly marked for physical
verification, start a new Conductor implementation phase with executable host
tests, a bounded provisioning probe and an explicit firmware deployment gate.

The later removal of Hub/cloud command transport gets its own migration
specification, tests and release gate; it is not bundled into the bridge proof.

## Primary sources

- [CANDY HOUSE Sesame OS 3 Bluetooth specification](https://github.com/CANDY-HOUSE/API_document/blob/954ec6b749c5aaa1665f89c9512c9fbd65ca1d4d/SesameOS3/bluetooth.md)
- [Android SDK advertisement parser](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/436249f77f21302aa69956bfe487d2670b997e9f/sesame-sdk/src/main/java/co/candyhouse/sesame/ble/Sesame2BleAdvertisement.kt)
- [Android SDK target provisioning](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/436249f77f21302aa69956bfe487d2670b997e9f/sesame-sdk/src/main/java/co/candyhouse/sesame/open/devices/sesameBiometric/capability/connect/CHDeviceConnectCapableImpl.kt)
- [Android SDK Remote Nano capability](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/436249f77f21302aa69956bfe487d2670b997e9f/sesame-sdk/src/main/java/co/candyhouse/sesame/open/devices/sesameBiometric/capability/remoteNano/CHRemoteNanoCapableImpl.kt)
- [Android SDK framing](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/436249f77f21302aa69956bfe487d2670b997e9f/sesame-sdk/src/main/java/co/candyhouse/sesame/ble/SesameBleReceiver.kt)
- [Android SDK session cipher](https://github.com/CANDY-HOUSE/SesameSDK_Android_with_DemoApp/blob/436249f77f21302aa69956bfe487d2670b997e9f/sesame-sdk/src/main/java/co/candyhouse/sesame/ble/os3/base/SesameOS3BleCipher.kt)
- [Official ESP32 client implementation](https://github.com/CANDY-HOUSE/SesameSDK_ESP32_with_DemoApp/tree/3ee9ceb9a392bf1cfabdd9608034523d3cdf2ff8/main/sesame)
- [ESPHome BLE server](https://esphome.io/components/esp32_ble_server/)
- [ESPHome template event](https://esphome.io/components/event/template/)
- [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/)
- [M5Stack AtomS3 Lite hardware](https://docs.m5stack.com/en/core/AtomS3%20Lite)
- [ESP-IDF ESP32-S3 MAC address APIs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/misc_system_api.html)
