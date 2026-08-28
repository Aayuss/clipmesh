# ClipMesh

ClipMesh is a private cross-platform clipboard sync and nearby file-transfer app for macOS, Windows, and Android.

Clipboard sync is still a first-class part of ClipMesh. v0.2.0 adds a LocalSend-style LAN file-drop system alongside it, so the same lightweight background app can handle both everyday copy/paste and deliberate file transfers.

## Download v0.2.0-alpha

- [macOS DMG](https://github.com/Aayuss/clipmesh/releases/download/v0.2.0-alpha/ClipMesh-macOS.dmg)
- [Windows EXE](https://github.com/Aayuss/clipmesh/releases/download/v0.2.0-alpha/ClipMesh-Windows.exe)
- [Android APK](https://github.com/Aayuss/clipmesh/releases/download/v0.2.0-alpha/ClipMesh-Android.apk)
- [SHA-256 checksums](https://github.com/Aayuss/clipmesh/releases/download/v0.2.0-alpha/SHA256SUMS.txt)

## Clipboard sync

- Text, HTML, images/screenshots, and clipboard file payloads
- End-to-end encrypted ClipMesh spaces
- macOS menu-bar app, Windows tray app, and Android background service
- Android Shizuku integration for reliable background clipboard access
- Android remote-copy popup can be enabled or disabled
- Background sync is enabled by default after pairing
- Device exclusions and per-platform clipboard handling remain independent from file transfer

## Nearby file transfer

ClipMesh v0.2.0 adds a second LAN subsystem inspired by LocalSend's open protocol and UX model:

- LAN discovery with UDP multicast on `224.0.0.167:53317`
- Direct device-to-device HTTP transfer on the local network - no cloud relay
- Prepare/upload handshake with per-file upload tokens
- Persistent favorite/trusted devices
- Favorite senders are accepted automatically
- Non-favorite senders require explicit Accept/Reject confirmation
- Works macOS ↔ Windows ↔ Android, including Android ↔ Android
- File transfer does not require the devices to share the same encrypted clipboard space

### Android receiving

The Android file-transfer service can stay running while the main UI is closed. Incoming files are stored as:

- Images → `Downloads/ClipMesh/Images`
- Videos → `Downloads/ClipMesh/Videos`
- Everything else → `Downloads/ClipMesh`

If the sender is not favorited, Android shows an incoming-transfer notification with **Accept** and **Reject** actions. Favorited senders save directly without opening ClipMesh.

### Android sending

Select one or more files/images/videos in another Android app and use:

**Share → Send with ClipMesh**

ClipMesh opens its nearby-device picker. Tap a visible device to send, or star it to mark it trusted for future incoming transfers.

You can also open ClipMesh and choose **Send files** manually.

### macOS sending

ClipMesh runs in the menu bar and provides **Send Files…** from both the app and menu-bar menu.

Finder also registers **Share with ClipMesh** as a macOS Service. Depending on the macOS/Finder version, Apple may surface Services under the right-click **Services** or **Quick Actions** section rather than allowing an ordinary app to choose the exact root-menu placement. Selecting the service opens ClipMesh's live LAN device picker for the selected file(s).

Incoming non-favorite transfers display an Accept/Reject dialog. Favorite devices save directly to `~/Downloads/ClipMesh`, with image/video subfolders.

### Windows sending

ClipMesh registers a per-user Explorer shell verb:

**Right click → Share with ClipMesh**

On Windows 11, Microsoft may place classic app verbs under **Show more options**. The command opens ClipMesh's nearby-device picker for the selected file.

You can also send from the tray menu or the main ClipMesh window.

Incoming non-favorite transfers display an Accept/Reject dialog. Favorite devices save directly to `Downloads\ClipMesh`, with image/video subfolders.

## Favorites and trust

Favorites are a receiver-side convenience rule, similar to LocalSend's paired/quick-save behavior:

- Favorite a device → future incoming files from that device can save automatically
- Do not favorite it → each incoming transfer asks first
- Favoriting does not grant clipboard-space access
- Clipboard encryption/pairing and file-transfer trust remain separate security boundaries

## v0.2.0 design

The Android, macOS, and Windows surfaces now use a shared warmer, darker, minimal visual direction:

- warm charcoal/taupe surfaces
- large clear headings
- rounded cards and pill-style actions
- quieter secondary text
- dedicated nearby-device transfer picker
- less stock utility-app styling while keeping native platform behavior

## Network model

ClipMesh has two independent local-network roles:

1. **Encrypted clipboard mesh** - existing ClipMesh paired-space protocol.
2. **Nearby file drop** - LAN discovery and explicit/favorite-gated file transfer.

The file-drop protocol uses LocalSend v2-compatible discovery and upload endpoint semantics (`/api/localsend/v2/prepare-upload`, `/api/localsend/v2/upload`) so the design stays simple, local-first, and auditable. ClipMesh implements the subsystem natively on each platform rather than embedding the LocalSend application.

## Android notes

Android requires a foreground service notification for reliable continuous background work. ClipMesh keeps this channel at minimum importance and does not show the old peer-count status. Incoming non-favorite transfer requests use a separate actionable notification because user approval must remain visible.

On newer Android versions, aggressive OEM battery restrictions can still stop any background app. Opening ClipMesh or using the Android Share sheet starts the receiver again.

## Installation trust

### macOS

The GitHub DMG is ad-hoc signed. Eliminating Gatekeeper's first-run warning for downloaded builds requires an Apple Developer ID certificate plus Apple notarization/stapling. That cannot be honestly bypassed in application code.

### Android

The GitHub APK is sideloaded. Android/Play Protect/Samsung may show an install warning for apps that were not installed from a recognized store. The durable fix is a stable release-signing key and, ideally, Play Store/internal-test distribution. Signing secrets should never be committed to this public repository.

## Build

GitHub Actions reconstructs the source, applies the versioned platform patches, tests the existing encrypted clipboard core/protocol, compiles the native macOS/Windows wrappers and Android APK, smoke-tests the packaged apps, computes checksums, and publishes the `v0.2.0-alpha` release assets.

## LocalSend acknowledgement

The nearby-transfer design and protocol compatibility were developed after reviewing the open-source LocalSend project and its public protocol specification. LocalSend is licensed under Apache-2.0. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
