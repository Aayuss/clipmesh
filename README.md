# ClipMesh

ClipMesh is a private cross-platform clipboard sync and nearby file-transfer app for macOS, Windows, and Android.

v0.2.1 keeps encrypted clipboard sync and LocalSend-style LAN file transfer together, while rebuilding the Android background path to remove the permanent sync notification, reduce idle wakeups, improve Android image copying, and make the clipboard/file-transfer UI much more useful.

## Download v0.2.1-alpha

- [macOS DMG](https://github.com/Aayuss/clipmesh/releases/download/v0.2.1-alpha/ClipMesh-macOS.dmg)
- [Windows EXE](https://github.com/Aayuss/clipmesh/releases/download/v0.2.1-alpha/ClipMesh-Windows.exe)
- [Android APK](https://github.com/Aayuss/clipmesh/releases/download/v0.2.1-alpha/ClipMesh-Android.apk)
- [SHA-256 checksums](https://github.com/Aayuss/clipmesh/releases/download/v0.2.1-alpha/SHA256SUMS.txt)

## What's new in v0.2.1

### Android - no permanent sync notification

ClipMesh no longer keeps its clipboard/file-transfer runtime alive with its own foreground `SyncService` or `FileTransferService`. Those foreground-service declarations and the old boot receiver were removed, so the permanent **Sync active** notification is gone.

Background clipboard work is now started from the enabled ClipMesh Accessibility service and uses Shizuku for privileged clipboard access. The runtime is event-driven instead of being kept awake by a permanent foreground notification.

This is deliberately a best-effort Android background model: Samsung/Android battery management can still kill an ordinary app process. Opening ClipMesh, using **Share → Send with ClipMesh**, or an Accessibility event can bring the runtime back. ClipMesh does not pretend that a notification-free third-party app can override every OEM process-killing rule.

### Lower idle battery use

The Android network/discovery path was changed to spend far less time waking the CPU while nothing is happening:

- blocking socket receives instead of short periodic socket timeouts
- nearby-device lifetime increased to about 180 seconds
- routine LAN announcements/discovery reduced to roughly 120-second intervals
- immediate discovery is still triggered when you actually open/send from the file-transfer UI
- clipboard wakeups are tied to relevant events instead of a permanent foreground loop

### Android → desktop image clipboard fix

Android clipboard images frequently arrive as `content://` URIs rather than directly readable files. The Shizuku user service now reads those URI bytes through the shell `content read --uri ...` path, with a resolver fallback, and passes the real image bytes back to ClipMesh. This avoids the old Android→Mac path that could see image metadata/URIs without successfully transferring the actual image payload.

### Better clipboard/file-transfer UI

The main surfaces now separate **Clipboard** and **File Transfer** into clear workspace sections instead of mixing both flows together.

Clipboard inspection now shows the actual useful content:

- copied image/screenshot → rendered image preview
- copied text → actual text preview
- copied files → file names rather than raw URI/debug metadata

### Real macOS Share extension

The macOS package now contains a real `com.apple.share-services` extension (`ClipMeshShare.appex`) in addition to ClipMesh's normal menu-bar/file-transfer entry points. Selected Finder files can be handed into ClipMesh's nearby-device picker through the `clipmesh-share` callback.

macOS controls where third-party Share extensions appear in Finder/Share menus, so ClipMesh cannot force an arbitrary root right-click position.

## Clipboard sync

- Text, HTML, images/screenshots, and clipboard file payloads
- End-to-end encrypted ClipMesh spaces
- macOS menu-bar app, Windows tray app, and Android event-driven background runtime
- Android Shizuku integration for reliable clipboard access while the runtime is alive
- Android remote-copy popup can be enabled or disabled
- Background sync is enabled by default after pairing
- Device exclusions and per-platform clipboard handling remain independent from file transfer

## Nearby file transfer

ClipMesh also includes a LocalSend-style LAN file-drop subsystem:

- LAN discovery with UDP multicast on `224.0.0.167:53317`
- direct device-to-device HTTP transfer on the local network - no cloud relay
- prepare/upload handshake with per-file upload tokens
- persistent favorite/trusted devices
- favorite senders can be accepted automatically
- non-favorite senders require explicit Accept/Reject approval
- macOS ↔ Windows ↔ Android, including Android ↔ Android
- file transfer does not require devices to share the same encrypted clipboard space

### Android receiving

Incoming files are stored as:

- Images → `Downloads/ClipMesh/Images`
- Videos → `Downloads/ClipMesh/Videos`
- Everything else → `Downloads/ClipMesh`

A permanent file-transfer notification is no longer used. If a non-favorite sender requests a transfer, ClipMesh can still show a temporary actionable **Accept / Reject** notification because that specific transfer needs a user decision. Favorited senders can save directly while the runtime is available.

### Android sending

Select one or more files/images/videos in another Android app and use:

**Share → Send with ClipMesh**

ClipMesh opens its nearby-device picker and performs immediate discovery. You can also open ClipMesh and use the **File Transfer** section directly.

### macOS sending

Use **Send Files…** from ClipMesh or its menu-bar menu, or use the ClipMesh Share extension from Finder's Share UI when macOS exposes it there.

Incoming non-favorite transfers display an Accept/Reject dialog. Favorite devices save directly to `~/Downloads/ClipMesh`, with image/video subfolders.

### Windows sending

ClipMesh registers a per-user Explorer shell action:

**Right click → Share with ClipMesh**

On Windows 11, Microsoft may place classic app actions under **Show more options**. You can also send from the tray menu or main ClipMesh window.

Incoming non-favorite transfers display an Accept/Reject dialog. Favorite devices save directly to `Downloads\ClipMesh`, with image/video subfolders.

## Favorites and trust

Favorites are a receiver-side convenience rule:

- favorite a device → future incoming files from that device can save automatically
- do not favorite it → each incoming transfer asks first
- favoriting does not grant clipboard-space access
- clipboard encryption/pairing and file-transfer trust remain separate security boundaries

## Network model

ClipMesh has two independent local-network roles:

1. **Encrypted clipboard mesh** - ClipMesh's paired-space clipboard protocol.
2. **Nearby file drop** - LAN discovery and explicit/favorite-gated file transfer.

The file-drop protocol uses LocalSend v2-compatible discovery and upload endpoint semantics (`/api/localsend/v2/prepare-upload`, `/api/localsend/v2/upload`). ClipMesh implements the subsystem natively on each platform rather than embedding the LocalSend application.

## Installation trust

### macOS

The GitHub DMG is ad-hoc signed. Eliminating Gatekeeper's first-run Privacy & Security warning for downloaded builds requires an Apple Developer ID certificate plus Apple notarization/stapling. That cannot be safely or honestly bypassed in application code.

### Android

The GitHub APK is sideloaded. Android/Play Protect/Samsung may show an **Install anyway**-style warning for an app that did not come from a recognized store. The durable solution is a stable private release-signing key and, ideally, Play Store/internal-test distribution. Signing secrets must not be committed to this public repository.

## Build

GitHub Actions reconstructs the source, applies all versioned platform patches through v0.2.1, tests the encrypted clipboard protocol/core/transport, validates the notification-free Android manifest/runtime guards, builds and smoke-tests the Android APK, Windows EXE, macOS app/DMG, validates the packaged macOS Share extension, computes checksums, and publishes the `v0.2.1-alpha` release assets.

## LocalSend acknowledgement

The nearby-transfer design and protocol compatibility were developed after reviewing the open-source LocalSend project and its public protocol specification. LocalSend is licensed under Apache-2.0. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
