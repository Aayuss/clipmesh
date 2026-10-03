# ClipMesh

ClipMesh is a private, cross-platform clipboard and file-transfer suite for macOS, Windows, and Android. It synchronizes clipboard content between paired devices and transfers files directly across the local network without routing them through a cloud service.

## Download

### Current release - `v0.2.27-alpha`

| Platform | Installer |
| --- | --- |
| macOS | [Download DMG](https://github.com/Aayuss/clipmesh/releases/download/v0.2.27-alpha/ClipMesh-macOS.dmg) |
| Windows | [Download EXE](https://github.com/Aayuss/clipmesh/releases/download/v0.2.27-alpha/ClipMesh-Windows.exe) |
| Android | [Download APK](https://github.com/Aayuss/clipmesh/releases/download/v0.2.27-alpha/ClipMesh-Android.apk) |

[Download SHA-256 checksums](https://github.com/Aayuss/clipmesh/releases/download/v0.2.27-alpha/SHA256SUMS.txt) to verify the installers. Release assets are built from the same `main` commit and are published only after the platform build, smoke/runtime, signing, and package-validation jobs pass.

For the newest fully green build from `main`, including changes newer than the current immutable release, use the continuously refreshed [`dev-latest` release](https://github.com/Aayuss/clipmesh/releases/tag/dev-latest): [macOS DMG](https://github.com/Aayuss/clipmesh/releases/download/dev-latest/ClipMesh-macOS.dmg) · [Windows EXE](https://github.com/Aayuss/clipmesh/releases/download/dev-latest/ClipMesh-Windows.exe) · [Android APK](https://github.com/Aayuss/clipmesh/releases/download/dev-latest/ClipMesh-Android.apk).

## What's new in v0.2.27-alpha

- **Always connected on the same network.** Paired devices now redial each other at their last known address (a direct connection wakes a locked phone, unlike broadcasts): immediately when a link drops, then with a short backoff. A handshake timeout prevents hung dials, Android redials paired peers too, and Settings → Stay connected → **Run unrestricted** exempts ClipMesh from battery optimization so the phone stays reachable while locked.

### v0.2.26

- **Self-healing connections.** A newer authenticated connection from a paired device now replaces a stale one instead of being rejected as a duplicate (desktop daemon and Android). A link that died while the phone was dozing can no longer block it from reconnecting, so devices come back Online by themselves.

### v0.2.25

- **Paired devices stay connected and show Online correctly.** A single unreadable or replayed frame used to stop the desktop daemon from reading a peer's connection while keeping it registered, so phone → desktop sync silently stalled, the desktop showed the phone as "Last seen hours ago", and the phone's reconnects were rejected as duplicates. Bad frames are now skipped, silent links time out and reconnect (100s desktop / 300s Android), and teardown always unregisters the peer. Covered by new transport regression tests.
- Includes everything from v0.2.24 below.

### v0.2.24

- **Ember UI on every platform.** Android, macOS and Windows now share one design: Sora typeface, a dark `#131314` canvas with `#E55F11` accents, the same Clipboard / Transfer / Settings layout, and the same motion (spring-driven navigation pill, 220 ms page transitions, 260 ms dialogs, press feedback). Android moves to Jetpack Compose with a floating Suya-style bottom bar.
- **Decluttered screens.** Clipboard shows a live preview card and one Devices list (paired + nearby); Transfer shows the selection, the devices to send to and incoming progress; device name, receive folder and pairing tools live in Settings.
- **Sent files clear automatically.** After a successful transfer the selection empties on every platform (it used to stay selected in the macOS main window). Failed sends keep their files for retry.
- **Real clipboard preview.** The clipboard view shows the actual image, text or files instead of raw pasteboard type identifiers. Finder file copies preview the copied image file itself.
- **macOS Share menu.** The Finder Share extension is rebuilt as a properly linked, sandboxed app extension, so ClipMesh appears under Share and in Share → Edit Extensions. Shared files open straight in the Transfer page.
- **Instant Android screenshots.** Screenshots now sync the moment they are saved instead of after Samsung's preview toolbar closes (MediaStore change events are deferred and retried briefly instead of being dropped).
- **Zero UI polling.** All three apps refresh only on real events: nearby-device changes from the transfer engine, peer updates from the daemon's `peers.json` (file-system watch on desktop, preference listener on Android), runtime status changes, and app activation. The only timers are one-shot deadlines (device expiry, "Online" → "Last seen").
- **Android picker.** A floating **+** on Transfer offers **Photos & videos** (system photo picker, no storage permission) or **Files**; photo-picker items are sent with readable `IMG_`/`VID_` names.
- **Windows Explorer.** Adds a ClipMesh *Send to* entry and hands shared files to the running app instead of starting a second window.

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

**Release discipline:** every user-facing ClipMesh change must advance the app version, advance Android `versionCode`, update this README's current-release/download/changelog sections, and publish fresh macOS, Windows, and Android executables from the same green `main` commit.

Release-signing requirements are documented in [`RELEASE_SIGNING.md`](RELEASE_SIGNING.md), and the physical acceptance boundary is recorded in [`PHYSICAL_VERIFICATION.md`](PHYSICAL_VERIFICATION.md).
