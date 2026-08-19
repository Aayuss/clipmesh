<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.1-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

This repository is used to build the private ClipMesh source package created for personal/family/friends use.

## Download ClipMesh

### Direct downloads - v0.1.1-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.1-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.1-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.1-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

The v0.1.1 alpha uses the ClipMesh artwork as the native macOS application icon, Windows executable icon, Android launcher icon, Android in-app identity artwork, and notification branding.

> `SHA256SUMS.txt` is optional. You do **not** need it to install or run ClipMesh. It is only there if you want to verify that a downloaded installer is byte-for-byte identical to the CI-produced file.

> This repository is private. Only GitHub accounts with access to the repository can use these GitHub download links. For friends/family who are not repository collaborators, send them the `.dmg`, `.exe`, or `.apk` directly.

## Builds and releases

Every pull request and push to `main` builds and tests macOS, Windows, and Android. Successful workflow runs also expose temporary **Artifacts** under Actions for debugging/testing.

A successful `main` build publishes `v0.1.1-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and optional SHA-256 checksum file. Future versions can be published with a new `v*` tag such as `v0.1.2-alpha` or `v0.2.0`.
