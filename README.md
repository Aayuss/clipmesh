<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.2-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

This repository is used to build the private ClipMesh source package created for personal/family/friends use.

## Download ClipMesh

### Direct downloads - v0.1.2-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.2-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.2-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.2-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

## Desktop behavior - v0.1.2

### macOS

Double-clicking **ClipMesh.app** opens the ClipMesh window and creates a ClipMesh menu-bar icon. Clipboard sync runs in the background.

- Clicking the red window close button hides the ClipMesh window, removes ClipMesh from the Dock, and keeps synchronization running.
- Left-clicking the ClipMesh menu-bar icon opens the application window again and restores normal Dock presence while the window is open.
- Right-clicking the menu-bar icon opens the ClipMesh menu, including **Show ClipMesh**, **Copy Pairing Link**, and **Quit ClipMesh**.
- **Quit ClipMesh** from the menu-bar menu is the normal way to completely stop the desktop client and its background sync engine.

### Windows

Opening **ClipMesh-Windows.exe** opens the ClipMesh window and creates a ClipMesh notification-area/system-tray icon.

- Clicking the window **X** hides the ClipMesh window and removes it from the taskbar while synchronization keeps running.
- Left-clicking the ClipMesh tray icon restores the application window.
- Right-clicking the tray icon opens the ClipMesh menu, including **Show ClipMesh**, **Copy Pairing Link**, and **Quit ClipMesh**.
- **Quit ClipMesh** from the tray menu completely stops the desktop client and its background sync engine.

The Windows release remains a single `.exe`: the encrypted Rust sync engine is embedded inside the native tray application and is extracted into ClipMesh's private local runtime directory when needed.

## First-run and secure-key fix

The macOS build is now a real native Cocoa application instead of a shell wrapper around the CLI. On a fresh Mac it automatically creates its configuration and encryption key. The Windows tray application does the equivalent first-run initialization automatically.

Both desktop builds now explicitly use the native secure credential stores:

- macOS - Apple Keychain
- Windows - Windows Credential Manager

This fixes a v0.1.1 alpha configuration mistake where the `keyring` dependency had no native backend feature enabled and therefore fell back to its non-persistent mock credential store. v0.1.2 detects that unusable v0.1.1 state, preserves the old config as a backup, and creates a working secure-key-backed space.

The ClipMesh artwork is used as the native macOS application icon, Windows executable/tray icon, Android launcher icon, Android in-app identity artwork, and notification branding.

> `SHA256SUMS.txt` is optional. You do **not** need it to install or run ClipMesh. It is only there if you want to verify that a downloaded installer is byte-for-byte identical to the CI-produced file.

> This repository is private. Only GitHub accounts with access to the repository can use these GitHub download links. For friends/family who are not repository collaborators, send them the `.dmg`, `.exe`, or `.apk` directly.

## Builds and releases

Every pull request and push to `main` builds and tests macOS, Windows, and Android.

The macOS job performs a clean first-launch smoke test, initializes the secure key, reloads it from Keychain in a separate process, validates the native app bundle, and verifies its ad-hoc signature. The Windows job builds the single-file tray application, starts it in first-run smoke-test mode, verifies that the embedded engine is extracted, and confirms that its configuration and Windows Credential Manager-backed key can be loaded successfully.

Successful workflow runs also expose temporary **Artifacts** under Actions for debugging/testing. A successful `main` build publishes `v0.1.2-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and optional SHA-256 checksum file.
