<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.5-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

This repository builds the private ClipMesh package for personal/family/friends use.

## Download ClipMesh

### Direct downloads - v0.1.5-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.5-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.5-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.5-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

## v0.1.5 - foreground sync and transport reliability

v0.1.5 is based on real-device testing where v0.1.4 could discover a Mac and Android phone but still fail to move clipboard data in either direction.

### Encrypted connection fallback

ClipMesh still prefers one deterministic connection direction to avoid duplicate-connection races, but it no longer depends exclusively on that direction. If the preferred direction has not established an authenticated channel after about 2.5 seconds, the other device attempts the reverse direction.

The first successfully authenticated encrypted TCP connection wins. This makes ClipMesh tolerate asymmetric host firewall/network behavior while keeping a single active connection per device pair.

**Online now means an authenticated clipboard connection is actually alive.** Signed UDP discovery updates a known device's LAN address/name, but discovery alone does not mark it Online. Authenticated encrypted traffic refreshes the online timestamp.

### Android ↔ desktop text interoperability

Android text payloads are now emitted using the canonical `text/plain; charset=utf-8` MIME form. Desktop receiving is also tolerant of text MIME parameters/casing, so older `text/plain;charset=utf-8` payloads are accepted instead of silently ignored.

### macOS clipboard capture

The native clipboard watcher remains the primary mechanism. macOS additionally has a 350 ms content-fingerprint fallback that only emits when the clipboard actually changes. The watcher and fallback share deduplication, so they do not double-send the same copy event.

The fallback sleeps between checks and does no network work for an unchanged clipboard.

### Android foreground capture without Shizuku

Shizuku is **not required for the encrypted network connection or for Mac → Android receiving**.

When ClipMesh is foregrounded/resumed on Android, it performs an immediate clipboard capture through normal Android APIs. This makes the following test possible without Shizuku:

1. Copy text on Android.
2. Return to the ClipMesh window.
3. ClipMesh captures the foreground-accessible clipboard and sends it to the connected desktop.

Mac → Android remote clipboard writes use normal Android clipboard APIs when Shizuku is unavailable.

### Optional Accessibility background fallback

If **ClipMesh app exclusions** Accessibility is enabled, the same privacy-minimized service now also receives Android clipboard-change callbacks and uses them only as an event signal to ClipMesh. There is no added polling loop.

- `canRetrieveWindowContent` remains disabled.
- It still tracks the foreground package only for source-app exclusions.
- Clipboard content is handled by the normal ClipMesh clipboard bridge and encrypted transport.
- Shizuku remains the preferred mechanism for the most reliable automatic Android background clipboard capture across Android/OEM versions.

Because ClipMesh is sideloaded, Android 13+ / Samsung may initially block its Accessibility service under Restricted Settings. If needed:

1. Open **Settings → Apps → ClipMesh**.
2. Open the top-right menu and choose **Allow restricted settings**.
3. Return to **Settings → Accessibility → Installed/Downloaded apps**.
4. Enable **ClipMesh app exclusions**.

### Shizuku

ClipMesh follows Shizuku's asynchronous binder/permission lifecycle and does not ask Shizuku to kill/remove its global service. ClipMesh's own Shizuku UserService no longer terminates its process from caller-death callbacks.

For Shizuku background capture, the low-power monitor is active only while:

- an authenticated peer is connected
- the screen is interactive
- **Send clipboard** is enabled
- Shizuku is authorized

The active interval is about 750 ms, no wake lock is held, and when no peer is connected the clipboard snapshot polling stops. **Compatibility watchdog** remains off by default.

On some Samsung/One UI builds Shizuku itself can be stopped by the OS independently of ClipMesh; if Shizuku stops even when ClipMesh is not running, that is outside ClipMesh's process lifecycle.

### Real transport test in CI

CI now includes a bidirectional authenticated TCP test using ClipMesh's actual Rust network handler, hello authentication, AES-GCM clipboard frames, length-prefix framing and receive path. It sends a clipboard payload A → B and another B → A rather than only testing cryptographic helper vectors.

## Pairing and device UI

Pairing is one-way to establish a shared private space: copy one existing device's pairing code and join from the new device. You do **not** pair back in the opposite direction.

The normal app screen on macOS, Windows, and Android provides:

- editable device name and short device ID
- known/paired devices and authenticated online state
- **Copy Pairing Code**
- **Pair Device** / **Join** / **Create New**
- **View Clipboard** for local clipboard inspection
- **Settings** for non-pairing controls

Pairing codes contain the private space key and must be treated like a password.

## Background icons and desktop behavior

The compact background-status icon uses the same left/right-arrow concept everywhere:

- macOS menu bar - native `arrow.left.arrow.right`
- Windows notification area/system tray - matching two-way-arrow glyph
- Android foreground-service notification - matching monochrome two-way-arrow glyph

The full ClipMesh artwork remains the normal application/launcher identity.

### macOS

Double-clicking **ClipMesh.app** opens its window and creates the menu-bar icon.

- Red close hides the window, removes ClipMesh from the Dock, and keeps sync running.
- Left-click the menu-bar icon to restore the window/Dock presence.
- Right-click the menu-bar icon for **Show ClipMesh**, **Copy Pairing Code**, and **Quit ClipMesh**.
- **Quit ClipMesh** completely stops the app and background engine.

### Windows

Opening **ClipMesh-Windows.exe** opens its window and system-tray icon.

- X hides the window/taskbar entry while sync keeps running.
- Left-click the tray icon to restore the window.
- Right-click the tray icon for **Show ClipMesh**, **Copy Pairing Code**, and **Quit ClipMesh**.
- **Quit ClipMesh** completely stops the app and background engine.

The Windows release is a single `.exe`; its Rust sync engine is embedded and extracted into ClipMesh's private local runtime directory.

## Security and storage

Clipboard payload encryption is mandatory. ClipMesh has no cloud relay, account, analytics service, or clipboard-history database.

Desktop space keys use the operating-system credential store:

- macOS - Apple Keychain
- Windows - Windows Credential Manager

Android stores its space key through Android Keystore-backed storage.

> `SHA256SUMS.txt` is optional. It is not required to install or run ClipMesh; it is only for verifying installer bytes.

> This repository is private. Only GitHub accounts with repository access can use these GitHub download links. For friends/family without repository access, send them the `.dmg`, `.exe`, or `.apk` directly.

## Builds and releases

Every pull request and push to `main` builds and tests macOS, Windows, and Android.

CI validates protocol/core tests, the real desktop transport roundtrip, native desktop builds and first-run behavior, secure-key persistence, macOS bundle/signature metadata, Android Shizuku/accessibility/exclusion packaging, APK generation, and platform checksums.

Successful `main` builds publish `v0.1.5-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and optional SHA-256 checksum file.
