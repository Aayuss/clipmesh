# One-command physical development test

Run this from the repository on the Mac that is testing ClipMesh:

```bash
./dev-test.sh
```

The script builds and updates both development apps and performs the physical Mac <-> Android tests itself. You do not manually copy clipboard data, select files, send files, or inspect destinations.

It automatically checks:

- Android -> Mac text clipboard while ClipMesh is hidden on Android.
- Mac -> Android text clipboard using a separate foreground Android test app.
- Android -> Mac image clipboard.
- Mac -> Android image clipboard.
- Android -> Mac file transfer with exact-byte verification.
- Mac -> Android file transfer with exact-byte verification.
- Android BackgroundService, Accessibility and Shizuku state after testing.

## Stable development identities

Signing material is created only on the local Mac under `~/.clipmesh-dev/` and is never committed to GitHub.

- Android uses one permanent local keystore. Future installs use `adb install -r` and keep the same package identity.
- macOS uses an existing Apple Development or Developer ID identity when available. Otherwise the script creates and reuses a local development signing identity.
- The Mac app is always updated at `/Applications/ClipMesh.app` when writable, otherwise `~/Applications/ClipMesh.app`.

The first transition from an APK signed by the old CI debug key may require replacing that installed package. The script handles that replacement, restores pairing from the Mac, enables ClipMesh Accessibility over ADB, starts Shizuku and attempts the Shizuku authorization flow automatically.

A secure phone lock screen and the computer-to-phone ADB trust prompt are intentionally not bypassed.

## Android connection

USB ADB is the most reliable option. Wireless debugging works after it has been paired once. The last ADB serial is remembered in `~/.clipmesh-dev/adb-serial` and the script attempts to reconnect it later.

If more than one Android device is connected:

```bash
ANDROID_SERIAL=<serial> ./dev-test.sh
```

## macOS signing override

To force a particular installed code-signing identity:

```bash
CLIPMESH_CODESIGN_IDENTITY="Apple Development: Your Name (...)" ./dev-test.sh
```

Generated keys, APKs, certificates, logs and temporary test data remain under `~/.clipmesh-dev/`.
