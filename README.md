<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.6-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

This repository builds the private ClipMesh package for personal/family/friends use.

## Download ClipMesh

### Direct downloads - v0.1.6-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.6-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.6-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.6-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

## v0.1.6 - foreground/self-capture synchronization fix

Real-device testing of v0.1.5 proved that Mac and Android could establish the authenticated encrypted connection and both show **Online**, while local clipboard changes still failed to leave the originating device.

The remaining cause was source-app exclusion. Earlier versions included ClipMesh itself in the default exclusion list. That was redundant because remote clipboard echoes are already prevented using content fingerprints, and it could suppress a legitimate local copy when the ClipMesh window became foreground before the watcher/capture path observed the change.

v0.1.6 therefore:

- removes `clipmesh` from desktop default exclusions
- removes `dev.clipmesh` from Android default exclusions
- migrates the obsolete self-exclusion out of existing installs at runtime - updating does not require clearing data or re-pairing
- explicitly allows capture while the ClipMesh UI itself is foreground
- keeps password-manager and other sensitive-app exclusions intact
- keeps fingerprint-based remote-echo suppression intact
- makes Android **View clipboard** request an immediate foreground capture in addition to the automatic clipboard listener
- retains the v0.1.5 authenticated TCP fallback, canonical text MIME handling, macOS 350 ms deduplicated pasteboard fallback, and Android foreground/Accessibility/Shizuku capture paths

### Expected foreground test

With both devices showing **Online**, Shizuku is not required for this test:

1. Copy new text on the Mac. Android's clipboard should update automatically.
2. Copy new text on Android while ClipMesh is foreground, or return to ClipMesh after copying. The Mac clipboard should update automatically.

You do not pair in both directions. One pairing code joins the devices to the same private space.

## Pairing and device UI

The normal app screen on macOS, Windows, and Android provides:

- editable device name and short device ID
- known/paired devices and authenticated online state
- **Copy Pairing Code**
- **Pair Device** / **Join** / **Create New**
- **View Clipboard** for local clipboard inspection
- **Settings** for non-pairing controls

Pairing codes contain the private space key and must be treated like a password.

## Android background clipboard access

Mac/Windows → Android receiving does not require Shizuku. Android → desktop foreground capture also does not require Shizuku.

Android 10+ restricts ordinary background clipboard reads. For automatic Android → desktop capture while ClipMesh is not foreground, ClipMesh supports:

- Shizuku - preferred privileged background clipboard access
- the optional **ClipMesh app exclusions** Accessibility service as an event-driven fallback where Android/OEM behavior allows it
- the optional compatibility watchdog, which remains off by default because it uses periodic checks

The Accessibility service is configured with `canRetrieveWindowContent=false`; it is used for foreground-app exclusions and clipboard-change signaling, not screen scraping.

## Background icons and desktop behavior

The compact background-status icon uses the same left/right-arrow concept everywhere.

### macOS

- Opening ClipMesh shows the application window and menu-bar icon.
- Red close hides the window, removes ClipMesh from the Dock, and keeps synchronization running.
- Left-click the menu-bar icon to restore the window.
- Right-click the menu-bar icon and choose **Quit ClipMesh** to terminate the app completely.

### Windows

- Opening ClipMesh shows the application window and system-tray icon.
- X hides the window/taskbar entry while synchronization keeps running.
- Left-click the tray icon to restore the window.
- Right-click the tray icon and choose **Quit ClipMesh** to terminate the app completely.

## Security and storage

Clipboard payload encryption is mandatory. ClipMesh has no cloud relay, account, analytics service, or clipboard-history database.

Desktop space keys use the operating-system credential store:

- macOS - Apple Keychain
- Windows - Windows Credential Manager

Android stores its space key through Android Keystore-backed storage.

> `SHA256SUMS.txt` is optional. It is only for verifying installer bytes.

> This repository is private. Only GitHub accounts with repository access can use these GitHub download links.

## Builds and releases

Every pull request and push to `main` builds macOS, Windows, and Android. CI validates the protocol/core tests, authenticated desktop transport roundtrip, v0.1.6 self-capture migration guards, native builds, first-run behavior, secure-key persistence, Android packaged components, and checksums.

A successful `main` build publishes `v0.1.6-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and optional checksum file.
