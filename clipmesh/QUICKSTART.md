# ClipMesh quick start

This is the shortest path from the source archive to a working private Mac/Windows/Android setup.

## A. Build and initialize the first desktop

### macOS

```bash
./scripts/build-macos.sh
./scripts/install-macos.sh
$HOME/.local/bin/clipmesh init --name "My Mac"
$HOME/.local/bin/clipmesh autostart install
$HOME/.local/bin/clipmesh run
```

Run the final command in a second Terminal the first time so you can see logs. After you are happy with it, the login agent starts it automatically.

To get the provisioning URI for another device:

```bash
$HOME/.local/bin/clipmesh pairing-code
```

`pairing-code` prints both a terminal QR and the underlying `clipmesh://pair?...` URI. The URI contains the private 256-bit space key. Do not send it through chat/email/cloud notes.

### Windows

Build/install:

```powershell
./scripts/build-windows.ps1
./scripts/install-windows.ps1
./scripts/windows-firewall.ps1
```

Join the space using the provisioning URI created on the Mac:

```powershell
clipmesh.exe join 'clipmesh://pair?...' --name "My Windows PC"
clipmesh.exe autostart install
clipmesh.exe run
```

If LAN broadcast discovery is blocked by your router, add the other machine as a static LAN peer:

```powershell
clipmesh.exe peer add 192.168.1.20:41474
```

## B. Android

Build and sideload:

```bash
./scripts/build-android-debug.sh
adb install -r dist/android/ClipMesh-debug.apk
```

For the safest local transfer of the pairing secret, connect Android over ADB and run:

```bash
CLIPMESH_BIN=$HOME/.local/bin/clipmesh ./scripts/pair-android-via-adb.sh
```

Then on Android:

1. Open ClipMesh once and tap **Join** if the ADB deep link only prefilled the pairing code.
2. Install/start Shizuku on the phone and tap **Request Shizuku permission** in ClipMesh.
3. Enable **Background auto-sync**.
4. Leave **Compatibility watchdog** OFF unless your phone fails to emit clipboard-change events reliably.
5. Optionally enable the ClipMesh exclusion helper in Android Accessibility settings, then choose apps that must never sync.

After setup, ClipMesh does not need to be open on screen. A low-importance foreground-service notification remains while background sync is enabled.

## C. Recommended privacy configuration

Keep these excluded:

- password managers
- banking/authenticator apps where relevant
- ClipMesh itself

On desktop:

```bash
clipmesh exclude list
clipmesh exclude add "1Password"
clipmesh exclude add "Bitwarden"
```

There is no switch to disable encryption, no cloud/relay mode, and no clipboard-content history database.

## D. Expected usage

```text
Mac Cmd+C       -> Windows Ctrl+V
Windows Ctrl+C  -> Mac Cmd+V
Mac/Windows copy -> Android normal Paste
Android Copy     -> Mac/Windows normal Paste
```

Portable formats supported by this private alpha are text, HTML/RTF where the platform exposes them, images, and ordinary files. Application-private clipboard formats are not guaranteed to translate across operating systems.

## E. Before trusting sensitive data

Run on a machine with Rust installed:

```bash
./scripts/security-audit.sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Run Android checks with the Android SDK installed:

```bash
cd android
./gradlew :app:assembleDebug :app:lintDebug
```

The ZIP was generated in a Linux environment without Rust or the Android SDK, so native compilation could not be performed there. Treat the first build as an alpha until it has passed these native builds and real-device testing.
