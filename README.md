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

### v0.1.2 macOS first-run fix

The macOS build is now a real native Cocoa application instead of a shell wrapper around the CLI. Double-clicking **ClipMesh.app** opens a ClipMesh window, starts encrypted clipboard sync in the background, and exposes a menu-bar control. On a fresh Mac it automatically creates its configuration and encryption key. It also repairs the unusable config left behind by v0.1.1, preserving that old config as a backup before creating a working space.

The desktop builds now explicitly use the native secure credential stores:

- macOS - Apple Keychain
- Windows - Windows Credential Manager

This fixes a v0.1.1 alpha configuration mistake where the `keyring` dependency had no native backend feature enabled and therefore fell back to its non-persistent mock credential store.

The ClipMesh artwork is used as the native macOS application icon, Windows executable icon, Android launcher icon, Android in-app identity artwork, and notification branding.

> `SHA256SUMS.txt` is optional. You do **not** need it to install or run ClipMesh. It is only there if you want to verify that a downloaded installer is byte-for-byte identical to the CI-produced file.

> This repository is private. Only GitHub accounts with access to the repository can use these GitHub download links. For friends/family who are not repository collaborators, send them the `.dmg`, `.exe`, or `.apk` directly.

## Builds and releases

Every pull request and push to `main` builds and tests macOS, Windows, and Android. The macOS job additionally performs a first-launch smoke test that starts with no configuration, initializes the secure key, reloads it from Keychain in a separate process, validates the app bundle, and verifies its ad-hoc signature.

Successful workflow runs also expose temporary **Artifacts** under Actions for debugging/testing. A successful `main` build publishes `v0.1.2-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and optional SHA-256 checksum file.
