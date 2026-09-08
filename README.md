# ClipMesh

ClipMesh is a private, cross-platform clipboard and file-transfer suite for macOS, Windows, and Android. It synchronizes clipboard content between paired devices and transfers files directly across the local network without routing them through a cloud service.

## Download

### Current release - `v0.2.17-alpha`

| Platform | Installer |
| --- | --- |
| macOS | [Download DMG](https://github.com/Aayuss/clipmesh/releases/download/v0.2.17-alpha/ClipMesh-macOS.dmg) |
| Windows | [Download EXE](https://github.com/Aayuss/clipmesh/releases/download/v0.2.17-alpha/ClipMesh-Windows.exe) |
| Android | [Download APK](https://github.com/Aayuss/clipmesh/releases/download/v0.2.17-alpha/ClipMesh-Android.apk) |

[Download SHA-256 checksums](https://github.com/Aayuss/clipmesh/releases/download/v0.2.17-alpha/SHA256SUMS.txt) to verify the installers.

For the newest fully green build from `main`, including changes newer than the current immutable release, use the continuously refreshed [`dev-latest` release](https://github.com/Aayuss/clipmesh/releases/tag/dev-latest): [macOS DMG](https://github.com/Aayuss/clipmesh/releases/download/dev-latest/ClipMesh-macOS.dmg) · [Windows EXE](https://github.com/Aayuss/clipmesh/releases/download/dev-latest/ClipMesh-Windows.exe) · [Android APK](https://github.com/Aayuss/clipmesh/releases/download/dev-latest/ClipMesh-Android.apk).

## What's new in v0.2.17-alpha

- Replaces Android's recurring 650 ms clipboard watchdog with event-driven Shizuku/Binder clipboard-change callbacks.
- Removes the macOS 350 ms clipboard fallback polling loop.
- Removes recurring 5-second file-transfer announcers on Android, macOS, and Windows; discovery/advertising now happens on meaningful runtime events.
- Removes redundant clipboard callback worker threads while retaining serialized/coalesced clipboard capture.
- Keeps clipboard echo/duplicate suppression so a remotely received clipboard write is not sent back again.
- Uses callback-driven transfer byte progress instead of progress polling.
- Shows transfer progress inside the application on all platforms, with macOS Dock progress, Windows taskbar progress, and native completion/failure notifications where supported.
- Preserves low-frequency connection health/recovery behavior needed for sleep/wake, network changes, peer restarts, and reconnect reliability.

The optimization target is near-zero unnecessary idle CPU wakeups and minimal background pressure while keeping ClipMesh immediately responsive to real clipboard, network, and transfer events.

## Capabilities

- Synchronizes text and images between paired devices.
- Uses event-driven clipboard change handling instead of continuously polling the clipboard.
- Prevents cross-device clipboard echo loops and adjacent duplicate writes.
- Preserves image orientation across Android and desktop platforms.
- Detects Android screenshots and delivers them to paired desktops.
- Transfers files directly over the local network with real byte-level progress.
- Shows compact in-app transfer progress on every platform, Android transfer notifications, macOS Dock progress, Windows taskbar progress, and native desktop completion/failure notifications where supported.
- Clears a completed selection automatically while retaining failed selections for retry.
- Supports trusted senders for automatic incoming-file saves, with a confirmation notification on Android.
- Provides native Finder sharing on macOS, Explorer integration on Windows, and Android share-sheet support.

## Getting started

1. Install ClipMesh on each device.
2. Connect the devices to the same local network.
3. Open **Clipboard**, select the nearby device, and confirm the six-digit pairing code on both sides.
4. Enable clipboard sending and receiving as required.
5. Open **File Transfer**, choose one or more files, and select a nearby recipient.

Clipboard pairing and file-transfer trust are intentionally separate. Pairing grants access to the encrypted clipboard space; marking a file sender as a favorite permits automatic incoming-file acceptance from that sender.

## Android background operation

Android restricts clipboard access outside the foreground. ClipMesh uses event-driven clipboard signals rather than repeatedly reading the clipboard. When Shizuku background access is enabled, its privileged UserService registers for Android clipboard-change events and performs a clipboard read only when the platform reports an actual change. Accessibility remains available for the Android interaction paths that require it.

For reliable operation:

- Enable ClipMesh Accessibility access when required by your Android configuration.
- Authorize ClipMesh in Shizuku when background clipboard synchronization is required.
- Enable **Receive files when the app is not opened** for background file receiving.
- Exclude ClipMesh from restricted battery or deep-sleep modes if your OEM otherwise stops its receiver.

Android displays a low-importance foreground-service notification while background receiving is active. Unknown file senders require explicit acceptance; favorite senders can save automatically when that setting is enabled.

## Security and privacy

- Clipboard synchronization uses authenticated, end-to-end encrypted paired spaces.
- Nearby pairing uses ephemeral P-256 ECDH, HKDF-SHA256, authenticated encryption, and a six-digit verification code.
- Clipboard data and transferred files are not uploaded to a ClipMesh cloud service.
- File discovery and transfer remain on the local network. The file-transfer service uses TCP port `53421`; clipboard transport uses `41474`; nearby pairing uses `53422`.
- Favorite status applies only to incoming file acceptance and does not grant clipboard access.
- Local file transfer currently uses plain HTTP on the LAN. Do not transfer pairing credentials or other secrets over an untrusted network.

## Platform notes

### macOS

The release includes a Finder Share extension. If ClipMesh does not appear in Finder's Share menu, enable it under **System Settings → General → Login Items & Extensions → Sharing**.

GitHub-hosted macOS builds are Developer ID signed and notarized when the required Apple credentials are configured. Otherwise the workflow explicitly publishes an ad-hoc-signed build, which may require approval under **Privacy & Security** before first launch.

### Windows

ClipMesh registers **Share with ClipMesh** for files and folders and runs its clipboard engine in the background while the desktop application is active. File-transfer progress is mirrored to the Windows taskbar.

### Android

The GitHub APK is signed with ClipMesh's permanent release identity. Android may still show Play Protect or sideloading warnings because the APK is distributed outside an app store.

## Development

The repository retains a compact canonical source archive and reconstructs platform projects through ordered patch layers in [`ci/reconstruct.py`](ci/reconstruct.py).

```bash
python3 ci/reconstruct.py --platform Darwin   # macOS
python3 ci/reconstruct.py --platform Linux    # Android
python3 ci/reconstruct.py --platform Windows  # Windows
```

The main verification workflows reconstruct every platform, run protocol and regression tests, compile the native applications, validate package metadata, and verify the signed Android release artifact. Local Mac-to-Android physical testing is available through `dev-test.sh` when an authorized Android Debug Bridge device is connected.

Release-signing requirements are documented in [`RELEASE_SIGNING.md`](RELEASE_SIGNING.md), and the physical acceptance boundary is recorded in [`PHYSICAL_VERIFICATION.md`](PHYSICAL_VERIFICATION.md).
