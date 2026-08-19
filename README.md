# ClipMesh

Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.

This repository is used to build the private ClipMesh source package created for personal/family/friends use.

## Download ClipMesh

The first verified private alpha release is published on the GitHub **Releases** page after the native macOS, Windows, and Android builds all pass.

### Direct downloads

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.0-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.0-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.0-alpha/ClipMesh-Android.apk)
- [Optional SHA-256 checksums](https://github.com/Aayuss/clipmesh/releases/download/v0.1.0-alpha/SHA256SUMS.txt)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

> `SHA256SUMS.txt` is optional. You do **not** need it to install or run ClipMesh. It is only provided if you want to verify that a downloaded installer is byte-for-byte identical to the file produced by CI.

> This repository is private. Only GitHub accounts with access to the repository can use these GitHub download links. For friends/family who are not repository collaborators, send them the `.dmg`, `.exe`, or `.apk` directly.

## Builds and releases

Every pull request and push to `main` builds and tests macOS, Windows, and Android. Successful workflow runs also expose temporary **Artifacts** under Actions for debugging/testing.

After this verified build PR is merged, the first successful `main` build automatically creates `v0.1.0-alpha` and attaches the raw `.dmg`, `.exe`, and `.apk` installers. Future versions can be published by pushing a new `v*` tag such as `v0.1.1-alpha` or `v0.2.0`.
