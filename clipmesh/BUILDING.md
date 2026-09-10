# Building ClipMesh

This archive intentionally contains source rather than pretending Linux-generated binaries were valid native releases. Build each target on its native toolchain, or push the repository to GitHub and run `.github/workflows/build.yml` to get unsigned artifacts.

## macOS

Requirements:

- macOS 13+ recommended
- Xcode Command Line Tools
- current stable Rust

```bash
xcode-select --install
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
./scripts/build-macos.sh
```

Outputs include `dist/macos/clipmesh`, a `ClipMesh.app` bundle, and on macOS a personal-use DMG when `hdiutil` is available. The build script only ad-hoc signs the app. Use your own Apple Developer ID for normal Gatekeeper distribution/notarization.

Install the CLI somewhere stable before installing autostart:

```bash
./scripts/install-macos.sh
$HOME/.local/bin/clipmesh init --name "My Mac"
$HOME/.local/bin/clipmesh pairing-code
$HOME/.local/bin/clipmesh autostart install
```

## Windows

Requirements:

- Windows 10/11
- stable Rust MSVC toolchain
- Visual Studio Build Tools / Desktop C++ workload

PowerShell:

```powershell
./scripts/build-windows.ps1
./scripts/install-windows.ps1
./scripts/windows-firewall.ps1
```

Then initialize using the installed executable shown by the install script.

## Android

Recommended:

- Android Studio with Android SDK 36, or command-line SDK 36
- JDK 17+
- Android 8.0+ device (minSdk 26)

A small bootstrap script named `android/gradlew` downloads the official Gradle 8.13 distribution when Gradle is not already installed; it is intentionally not a binary Gradle-wrapper JAR.

Debug/sideload build:

```bash
./scripts/build-android-debug.sh
adb install -r dist/android/ClipMesh-debug.apk
```

Release build (unsigned unless you add your signing config):

```bash
./scripts/build-android.sh
```

For automatic Android background reads, install/start Shizuku and grant ClipMesh permission inside the app. ClipMesh itself does not download or start Shizuku.

## Quality checks

Desktop/core:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Protocol-independent verification:

```bash
python3 -m pip install cryptography
python3 tools/protocol_selftest.py
```

Android:

```bash
cd android
./gradlew :app:assembleDebug :app:lintDebug
```

The source-generation environment used to create this archive did not contain Rust, the Android SDK, or Gradle, so those native compile commands could not truthfully be executed here.
