# ClipMesh v0.2.4

ClipMesh provides encrypted clipboard sync and direct nearby file transfer across macOS, Windows, and Android.

## Download

Download the current installers directly—there is no need to browse the Releases page:

- [Download ClipMesh for macOS](https://github.com/Aayuss/clipmesh/releases/download/v0.2.4-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows](https://github.com/Aayuss/clipmesh/releases/download/v0.2.4-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android](https://github.com/Aayuss/clipmesh/releases/download/v0.2.4-alpha/ClipMesh-Android.apk)
- [Download SHA-256 checksums](https://github.com/Aayuss/clipmesh/releases/download/v0.2.4-alpha/SHA256SUMS.txt)

These links become live after the `Build ClipMesh` GitHub Action completes and publishes `v0.2.4-alpha`.

## What changed in v0.2.4

- ClipMesh file transfer now uses its own port (`53421`) and `/api/clipmesh/v1` protocol namespace. It no longer binds LocalSend's port, discovers LocalSend devices, or exposes LocalSend routes.
- The desktop and Android interfaces use neutral black surfaces with gold actions, roomier buttons, and corrected desktop sidebar padding.
- Dropping files anywhere in the macOS or Windows ClipMesh window opens File Transfer and selects the dropped files.
- macOS and Windows have a top-right **Choose file manually** action. Android offers **Image**, **Video**, and **File** choices.
- Selected files render in a horizontal, scrollable visual strip with thumbnails/icons and individual remove buttons.
- Clipboard content remains hidden until **View current clipboard** is selected.
- Clipboard starts with this device's name, paired devices, Refresh, Rename, and **Pair new device**.
- Nearby file discovery starts from every main app section instead of waiting for File Transfer to open.
- Every Android bottom-tab change uses the same fade transition.
- Android has a **Receive files when the app is not opened** switch. When enabled, its foreground service keeps the device discoverable; when disabled, receiving is limited to a visible ClipMesh activity.
- Favorited Android senders can still save automatically. Other senders receive Accept/Reject controls in a blurred bottom sheet while ClipMesh is visible, or in a notification while it is in the background.
- macOS packages and refreshes the Finder Share extension. Windows registers **Share with ClipMesh** for files and folders. Shared files open preselected in the recipient chooser.

## Clipboard pairing

Use **Pair new device** to open the pairing controls. The existing pairing code contains the private-space encryption key and ClipMesh deliberately does not send it over the unencrypted file-transfer channel.

A no-copy nearby pairing flow needs an authenticated key exchange (not a plain LAN popup carrying the current secret). That security-sensitive protocol is not represented as complete in v0.2.4.

## Android background receiving

Android requires a foreground service for reliable receiving after the visible UI closes. When **Receive files when the app is not opened** is enabled, ClipMesh shows one low-importance ongoing notification and restores the listener after boot or app replacement.

Unknown senders use a separate high-priority Accept/Reject notification when ClipMesh is not visible. Android/OEM battery controls can still override applications placed in Restricted or deep-sleep modes.

## macOS Finder Share

ClipMesh includes a `com.apple.share-services` extension and refreshes its registration when the app opens. macOS controls whether it is shown directly under Finder → right-click → Share. If it is hidden, enable ClipMesh in System Settings → General → Login Items & Extensions → Sharing.

The GitHub DMG is ad-hoc signed rather than Developer-ID notarized, so macOS may require a one-time approval under Privacy & Security.

## Android installation

The GitHub APK is sideloaded and can trigger Play Protect or Samsung's **Install anyway** flow. Avoiding that distribution warning requires stable release signing and recognized store distribution; it is separate from ClipMesh runtime behavior.

## Security model

- Clipboard mesh: paired-space, end-to-end encrypted synchronization.
- Nearby file transfer: direct ClipMesh-only LAN discovery and HTTP transfer on port `53421`.
- Favorites authorize automatic incoming file acceptance only; they do not grant clipboard-space access.
- The current nearby-file transport is plain HTTP on the local network. Do not use it to transmit clipboard pairing secrets.
