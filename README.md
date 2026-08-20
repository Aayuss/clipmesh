<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.3-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

This repository is used to build the private ClipMesh source package created for personal/family/friends use.

## Download ClipMesh

### Direct downloads - v0.1.3-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.3-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.3-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.3-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

## v0.1.3 - device-focused UI

The normal application window is now deliberately simple on macOS, Windows, and Android. The home screen focuses on the things needed day to day:

- this device's editable name and short device ID
- known/paired devices, with recently seen devices marked online
- **Copy Pairing Code**
- **Pair Device**, which reveals the pairing-code field, **Join**, **Create New**, and another copy-code action
- **View Clipboard**, which shows the current local clipboard contents/metadata for testing
- **Settings**, with non-pairing controls kept away from the home screen

Device names are now supported consistently across all three platforms. New v0.1.3 pairing codes also include the source device ID and device name, while remaining compatible with older v0.1.x pairing codes that contain only the space/key data.

The known-device list is local. ClipMesh records peer identity/name information from the authenticated LAN discovery and connection handshakes it already uses for synchronization. It does not add a cloud device registry.

### Unified background icon

The background-status icon is now the same simple left/right-arrow concept on every platform:

- macOS menu bar - native `arrow.left.arrow.right` symbol
- Windows notification area/system tray - matching two-way-arrow tray glyph
- Android foreground-service notification - matching two-way-arrow monochrome notification glyph

The full ClipMesh artwork remains the normal application/launcher identity; the compact background indicators use the simpler two-way-arrow symbol.

### Android UI and battery use

Android's home/settings UI has been redesigned with native static views, cards, spacing, and modern button styling. The visual redesign itself adds no timer, animation loop, clipboard polling loop, or additional network discovery loop.

The device list reuses ClipMesh's existing signed LAN discovery traffic and authenticated connections. The optional **Compatibility watchdog (more battery)** remains off by default and is still clearly separated under Settings.

## Desktop background behavior

### macOS

Double-clicking **ClipMesh.app** opens the ClipMesh window and creates the ClipMesh menu-bar icon. Clipboard sync runs in the background.

- Clicking the red window close button hides the window, removes ClipMesh from the Dock, and keeps synchronization running.
- Left-clicking the ClipMesh menu-bar icon restores the application window and normal Dock presence.
- Right-clicking the menu-bar icon opens the ClipMesh menu, including **Show ClipMesh**, **Copy Pairing Code**, and **Quit ClipMesh**.
- **Quit ClipMesh** from the menu-bar menu completely stops the desktop client and its background sync engine.

### Windows

Opening **ClipMesh-Windows.exe** opens the ClipMesh window and creates the ClipMesh system-tray icon.

- Clicking the window **X** hides the ClipMesh window and removes it from the taskbar while synchronization keeps running.
- Left-clicking the tray icon restores the application window.
- Right-clicking the tray icon opens the ClipMesh menu, including **Show ClipMesh**, **Copy Pairing Code**, and **Quit ClipMesh**.
- **Quit ClipMesh** from the tray menu completely stops the desktop client and its background sync engine.

The Windows release remains a single `.exe`: the encrypted Rust sync engine is embedded inside the native tray application and is extracted into ClipMesh's private local runtime directory when needed.

## Secure-key storage and first run

The macOS build is a native Cocoa application and automatically creates its configuration and encryption key on first launch. The Windows tray application performs the equivalent first-run initialization automatically.

Desktop secure keys use the operating system's credential store:

- macOS - Apple Keychain
- Windows - Windows Credential Manager

v0.1.2 and newer also repair the unusable state that could be left by v0.1.1's temporary/mock keyring configuration, preserving the old config as a backup before creating a working secure-key-backed space.

> `SHA256SUMS.txt` is optional. You do **not** need it to install or run ClipMesh. It is only there if you want to verify that a downloaded installer is byte-for-byte identical to the CI-produced file.

> This repository is private. Only GitHub accounts with access to the repository can use these GitHub download links. For friends/family who are not repository collaborators, send them the `.dmg`, `.exe`, or `.apk` directly.

## Builds and releases

Every pull request and push to `main` builds and tests macOS, Windows, and Android.

The macOS job performs a clean first-launch smoke test, initializes the secure key, reloads it from Keychain in a separate process, validates UI-state access, validates the native app bundle, and verifies its ad-hoc signature. The Windows job builds the single-file tray application, starts it in first-run smoke-test mode, verifies that the embedded engine is extracted, and validates its configuration/UI state with the Windows Credential Manager-backed key. Android is built from the same patched source package in CI.

Successful workflow runs expose temporary **Artifacts** under Actions for debugging/testing. A successful `main` build publishes `v0.1.3-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and optional SHA-256 checksum file.
