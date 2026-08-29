# ClipMesh v0.2.3

ClipMesh combines encrypted clipboard sync with nearby LAN file transfer across macOS, Windows, and Android.

## v0.2.3

- macOS, Windows, and Android use the dark charcoal, warm-white, amber ClipMesh interface introduced in v0.2.2.
- Clipboard and file transfer remain separate workflows, with actual clipboard content previews instead of raw URI/MIME dumps.
- Desktop file transfer supports drag and drop plus normal file selection.
- Android supports sending through the system share sheet and receiving while the ClipMesh UI is closed.
- Android now uses one `connectedDevice` foreground service to own the encrypted clipboard runtime and nearby LAN file-transfer listener. This is the Android-supported mechanism for reliable continuous peer connectivity.
- The Android service is `START_STICKY`, survives closing the visible activity, and is restored after boot/app replacement.
- Unknown Android senders trigger a high-priority Accept/Reject notification. Favorited senders can be auto-accepted when that setting is enabled.
- Incoming Android files are saved under `Downloads/ClipMesh`, with images in `Downloads/ClipMesh/Images` and videos in `Downloads/ClipMesh/Videos`.
- macOS packages a real `com.apple.share-services` Share extension for Finder sharing.
- Clipboard pairing links are excluded from clipboard propagation so pairing does not overwrite useful clipboard content.
- CI builds and runtime-smoke-tests native macOS and Windows packages and now installs the Android APK into an Android 15 emulator. The Android runtime gate closes the visible UI, confirms the background service remains alive, calls the actual LocalTransferEngine HTTP endpoint, and verifies an unknown sender produces the Accept/Reject notification.
- CI also runs the authenticated clipboard transport tests and a LocalSend-v2-style prepare/upload byte-transfer loopback.

## Downloads

Release assets are published at:

https://github.com/Aayuss/clipmesh/releases/tag/v0.2.3-alpha

Expected assets:

- `ClipMesh-macOS.dmg`
- `ClipMesh-Windows.exe`
- `ClipMesh-Android.apk`
- `ClipMesh-icon.png`
- `SHA256SUMS.txt`

## Android background behavior

Reliable always-ready receiving on modern Android requires a foreground service. ClipMesh therefore shows one low-importance ongoing **ClipMesh** notification while background clipboard/file receiving is active. This replaces the unreliable no-notification approach from v0.2.2.

The persistent notification is deliberately low importance. Incoming transfers from an unknown sender use a separate high-priority notification with **Reject** and **Accept** actions.

Android/OEM battery controls can still override applications if the user manually places ClipMesh in a restricted/deep-sleep state. For reliable receiving, do not put ClipMesh in Samsung Deep sleeping apps or Android's Restricted battery mode.

## macOS Finder Share

ClipMesh includes an actual macOS Share extension. macOS decides whether it appears directly in Finder's Share submenu and whether a newly installed extension is automatically enabled. If it is disabled, enable **ClipMesh** in System Settings → General → Login Items & Extensions → Sharing.

Because the GitHub DMG is ad-hoc signed rather than Developer-ID notarized, macOS can still require the one-time Privacy & Security approval for the application itself.

## Android installation

The GitHub APK is sideloaded and can still trigger Play Protect/Samsung's **Install anyway** flow. Removing that distribution warning reliably requires stable release signing and recognized store distribution; it is separate from ClipMesh's runtime behavior.

## Security model

Clipboard sync and nearby file transfer remain separate:

- Clipboard mesh: paired-space encrypted synchronization.
- Nearby file transfer: direct LAN LocalSend-v2-style discovery/prepare/upload semantics.

The current nearby-file transport is plain HTTP on the local network. Favorites affect automatic file acceptance only and do not grant clipboard-space access.
