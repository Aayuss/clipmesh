# ClipMesh v0.2.12 continuation

## Current repository state

- Current `main` checkpoint before this continuation update: `fa89e5b9b411a4c29fd5673c7ebea634cc26c6fc`.
- The previous physical verification boundary is `9faf1b8b1baffa2c2a8aee78938ba9d9acf7fe74` and recorded `TOTAL FAILURES: 0` on the Samsung Galaxy S23 Ultra + macOS matrix.
- That old physical boundary is no longer sufficient for release because real shipped-code reconstruction patches were added afterward:
  - `ci/patch-v038-file-transfer-visibility.py` - keeps clipboard-paired devices visible in File Transfer.
  - `ci/patch-v039-lan-discovery.py` - adds IPv4 broadcast fallback alongside multicast for LAN discovery.
  - `ci/patch-v040-macos-resilience.py` - adds macOS clipboard-daemon readiness checks and bounded automatic recovery.
- The release workflow intentionally still points at the old verified SHA, so it refuses to publish while those post-verification runtime changes exist. Do not weaken that guard.

## Current automated verification

At `fa89e5b9b411a4c29fd5673c7ebea634cc26c6fc` all current automated workflows passed:

- `Build ClipMesh`
  - Windows EXE build + smoke test
  - macOS DMG build + smoke/signing/notarization validation
  - Android APK build + Android 15 background send/receive emulator runtime test + release-signing verification
- `Validate ClipMesh Dev Harness`
  - macOS harness build
  - Android harness compile
- `Validate Comprehensive Physical Acceptance Harness`
  - macOS acceptance instrumentation/build
  - Android acceptance instrumentation/compile

These prove buildability, packaging, instrumentation, and emulator/runtime coverage. They do not replace the real Samsung + Mac physical matrix.

## The one remaining release gate

Run the audited physical suite from a checkout pinned to the current `main` commit on the Mac physically paired with the Samsung S23 Ultra:

```bash
git pull --ff-only
export CLIPMESH_ANDROID_ENDPOINT='<wireless-debugging-ip:port>'
./dev-test-final.sh
```

The run must finish with:

```text
TOTAL FAILURES: 0
ALL COMPREHENSIVE PHYSICAL CLIPMESH ACCEPTANCE TESTS PASSED
```

The matrix covers Android -> Mac and Mac -> Android text/image clipboard transfer, foreground/background/tray states, File Transfer visibility and exact-byte transfers in both directions, Shizuku background clipboard access, restart/redetection/persistence, macOS daemon recovery, Android background-service health, ANR/fatal scans, and final listener/process health.

## After the physical run passes

1. Record the exact tested Git SHA in `PHYSICAL_VERIFICATION.md` and update its matrix/date.
2. Update `VERIFIED_PRODUCT_SHA` in `.github/workflows/release-v0.2.12.yml` to that exact tested SHA.
3. From that point until release, change only release metadata/documentation/workflow files allowed by the release boundary guard. Do not change runtime/product reconstruction patches.
4. Confirm the release boundary job passes, then publish `v0.2.12-alpha`.

Do not call the release finalized before the current post-v038/v039/v040 product code has passed the real-device suite.