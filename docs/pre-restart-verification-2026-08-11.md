# Pre-restart verification — 2026-08-11

## Acceptance receipt

1. **Pass — unit tests:** `/config/.tools/ha-test-venv/bin/python -m pytest -q` completed with `35 passed`.
2. **Pass — syntax:** `python -m compileall -q custom_components tests` exited successfully.
3. **Pass — QR behavior:** synthetic manager QR parsing and image decoding passed; owner, guest, unsupported model, malformed URI, invalid image, and stale upload paths were rejected.
4. **Pass — upload cleanup:** tests proved the context-managed image is deleted after both successful and failed decoding.
5. **Pass — credential isolation:** the real device UUID and secret key were compared without displaying them and were absent from both the repository worktree and Git object history.
6. **Pass — transient BLE address:** tests proved discovery selects the current advertisement by model and device UUID and resolves a changed address on the next lookup.
7. **Pass — read-only boundary:** mechanical source tests found no lock item, unlock item, encryption method, `async_lock`, or `async_unlock`. The only authenticated outbound packet is login.
8. **Pass — parallel staging:** the component was copied to `/config/custom_components/candy_house_ble`; a recursive diff against the repository component was empty. `sesame_ble_status` remains installed.
9. **Pass — Home Assistant preflight:** `ha core check` completed successfully.
10. **Pass — restart boundary:** `ha core restart` was not executed.

## Red-team

The prior architecture review returned **REVISE**. The required revisions are present in this milestone: real credentials stay outside Git, QR decoder compatibility was tested on amd64 CPython 3.13, addresses are re-resolved from advertisement identity, the deployment is read-only, and the prototype integration remains available for rollback.

## First runtime attempt and remediation

The first configuration-flow launch failed before the form loaded. Home Assistant
Core could not install `zxing-cpp==3.1.1`: that release has no musllinux wheel,
so Core attempted a source build and failed because its runtime image does not
contain CMake. The integration now pins `pyrxing==0.6.1`, which provides a
CPython 3.14 musllinux wheel for the HAOS architecture. QR credentials were not
opened or processed during the failed attempt.

## Increment log

- Repository/HACS skeleton and recorded implementation plan — validated by JSON parsing, lint, and compile checks.
- QR upload/decode layer — 11 focused tests passed before continuing.
- Read-only OS3 protocol and identity discovery — 17 focused tests passed before continuing.
- Config flow and security gates — 7 additional tests passed.
- Production staging — exact component diff passed.
- HA preflight — `ha core check` passed.

## Remaining unverified runtime behavior after remediation

- HA Core installing and importing `pyrxing==0.6.1` during the real config flow.
- Mobile/frontend file selection and Core-managed upload lifecycle in the running HA instance.
- Discovery and authenticated reads through the installed ESPHome Bluetooth proxy.
- Entity creation, repeated polling, disconnect recovery, and address changes after restart.

These require an explicitly authorized Core restart followed by adding the integration from the Home Assistant UI with a manager QR image. No lock or unlock command exists in this milestone.
