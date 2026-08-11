# Unified HACS and ESPHome release contract

## Objective

Publish the Home Assistant integration and the Fake SESAME ESPHome external
component from one repository under exactly one stable semantic version and
one `vX.Y.Z` Git tag/GitHub Release.

## Acceptance criteria

1. `python scripts/version.py check` exits zero only when `VERSION`, the Home
   Assistant manifest, the README status, the README ESPHome source tag, and
   the firmware component version all contain the same stable version.
2. `python scripts/version.py sync X.Y.Z` updates every representation above,
   including both products even if only one product changed.
3. Firmware unit tests prove that the Fake SESAME version command returns
   `fake-X.Y.Z` from the synchronized firmware version rather than a duplicate
   literal.
4. The Validate workflow runs the repository test suite and compiles the
   published ESPHome example with the pinned ESPHome toolchain.
5. The Release workflow synchronizes all version files, validates both
   products, atomically publishes the version commit and annotated `vX.Y.Z`
   tag, then publishes and verifies one non-draft, non-prerelease GitHub
   Release.
6. Dispatching `0.3.0` from the reviewed `main` commit produces tag `v0.3.0`
   and a matching GitHub Release. This remains unverified until publication.

## Non-goals

- Separate HACS and firmware tags, repositories, or release trains.
- Pre-release versions or moving/replacing published stable tags.
- Bundling a compiled firmware binary as a GitHub Release asset.

## Constraints

- Preserve all current uncommitted integration and firmware work.
- Do not read or modify `secrets.yaml`, `.ssh/`, or `.storage/`.
- The public tag is immutable; a bad publication is corrected with a newer
  patch release, not by moving the tag.
- No real Fake SESAME identity or secret may enter CI or the repository; the
  compile example uses synthetic values only.

## Rollback

Before publication, revert the release-contract changes from Git. After a
public tag/Release, keep the tag immutable and publish a corrected patch
release whose version is synchronized across both products.

## Increments

| Increment | Scope | Verification | Principal risk |
| --- | --- | --- | --- |
| 1 | Centralize and synchronize all version representations | Version unit tests | A hidden literal remains unsynchronized |
| 2 | Make firmware response consume its synchronized version | Protocol tests and ESPHome compile | Compiler define quoting fails |
| 3 | Require firmware compilation in Validate and Release CI | Workflow inspection and local equivalent | Slow or incompatible CI environment |
| 4 | Validate, commit, push, and dispatch `0.3.0` | CI run, tag, Release and remote SHA checks | Irreversible bad public tag |
