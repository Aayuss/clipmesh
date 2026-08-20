<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.4-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

This repository is used to build the private ClipMesh source package created for personal/family/friends use.

## Download ClipMesh

### Direct downloads - v0.1.4-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.4-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.4-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.4-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

## v0.1.4 - Android sync reliability

v0.1.4 fixes the Android problems discovered during real Mac ↔ Android testing.

### Stable encrypted peer connection

Signed LAN discovery and the encrypted clipboard channel are different things. Earlier builds could show a peer even when both devices had simultaneously opened opposite TCP connections and then replaced/closed each other's active connection.

v0.1.4 assigns connection ownership deterministically: for each pair of device IDs, exactly one side initiates and the other side accepts. A peer is shown as **Online** only after the preferred encrypted connection has completed its authenticated handshake; LAN discovery alone no longer marks it online.

### Shizuku lifecycle fix

The Android client now follows Shizuku's asynchronous binder lifecycle instead of treating one immediate `pingBinder()` call as authoritative. It keeps binder-received, binder-dead, and permission-result listeners registered and binds its clipboard UserService after permission is actually available.

ClipMesh no longer mutates the Shizuku UserService UID/GID, no longer exits the UserService process from a caller-token death callback, and does not request UserService removal when the ClipMesh settings screen closes.

### Background clipboard capture and battery use

Android 10+ restricts ordinary background clipboard reads, so ClipMesh uses Shizuku for reliable background capture when available.

The v0.1.4 monitor is deliberately conditional:

- clipboard snapshot reads happen only while an authenticated ClipMesh peer is connected
- only while the screen is interactive
- only when **Send clipboard** is enabled
- only while Shizuku permission is available
- interval while active: about 750 ms
- no wake lock is held
- when no peer is connected, there is no clipboard snapshot polling and the service backs off
- the separate **Compatibility watchdog (more battery)** remains off by default and is only a fallback when Shizuku is unavailable

This is more conservative than an unconditional polling loop while still allowing automatic background Android → desktop clipboard sync.

### Android accessibility and exclusions

**Choose excluded apps** is fixed and the exclusion activity is now packaged and registered correctly.

The ClipMesh accessibility service is optional for synchronization. It is used only to learn which foreground app generated a clipboard change so excluded apps such as password managers can be ignored. It is configured not to retrieve window content.

Because ClipMesh is sideloaded, Android 13+ / Samsung may block its accessibility service as a restricted setting. If ClipMesh is missing or disabled under Accessibility:

1. Open **Settings → Apps → ClipMesh**.
2. Open the top-right menu and choose **Allow restricted settings** if that option is shown.
3. Return to **Settings → Accessibility → Installed/Downloaded apps**.
4. Enable **ClipMesh app exclusions**.

ClipMesh Settings now includes an **Open ClipMesh app info** shortcut and the same guidance.

### Recommended Android setup

1. Pair once using the pairing code from either existing ClipMesh device. Reciprocal pairing is not required.
2. Turn **Background auto-sync** on.
3. Keep **Send clipboard** and **Receive clipboard** on.
4. Start Shizuku.
5. In ClipMesh Settings tap **Request Shizuku permission** and approve the Shizuku permission dialog.
6. Leave **Compatibility watchdog** off unless your device specifically needs the fallback.
7. Enable the optional ClipMesh accessibility service only if you want source-app exclusions.

On an unrooted device Shizuku itself may need to be started again after a phone reboot.

## Device-focused UI

The normal application window is deliberately simple on macOS, Windows, and Android. The home screen focuses on:

- this device's editable name and short device ID
- known/paired devices, with authenticated recently connected devices marked online
- **Copy Pairing Code**
- **Pair Device**, with pairing-code input, **Join**, **Create New**, and copy-own-code actions
- **View Clipboard**, showing the current local clipboard for testing
- **Settings**, with non-pairing controls kept away from the home screen

Pairing codes include the source device ID and device name while remaining compatible with older v0.1.x codes. The known-device list is local; ClipMesh adds no cloud registry.

### Unified background icon

The compact background-status icon uses the same left/right-arrow concept everywhere:

- macOS menu bar - native `arrow.left.arrow.right`
- Windows notification area/system tray - matching two-way-arrow glyph
- Android foreground-service notification - matching monochrome two-way-arrow glyph

The full ClipMesh artwork remains the normal application/launcher identity.

## Desktop background behavior

### macOS

Double-clicking **ClipMesh.app** opens the ClipMesh window and creates the ClipMesh menu-bar icon. Clipboard sync runs in the background.

- Red close hides the window, removes ClipMesh from the Dock, and keeps synchronization running.
- Left-clicking the menu-bar icon restores the application window and Dock presence.
- Right-clicking the menu-bar icon opens **Show ClipMesh**, **Copy Pairing Code**, and **Quit ClipMesh**.
- **Quit ClipMesh** completely stops the desktop client and background engine.

### Windows

Opening **ClipMesh-Windows.exe** opens the ClipMesh window and creates the system-tray icon.

- X hides the window and removes it from the taskbar while synchronization keeps running.
- Left-clicking the tray icon restores the window.
- Right-clicking the tray icon opens **Show ClipMesh**, **Copy Pairing Code**, and **Quit ClipMesh**.
- **Quit ClipMesh** completely stops the application and background engine.

The Windows release remains a single `.exe`; its encrypted Rust sync engine is embedded and extracted into ClipMesh's private local runtime directory.

## Security and storage

Clipboard payload encryption is mandatory and ClipMesh has no cloud relay, account, analytics service, or clipboard-history database.

Desktop space keys use the operating system credential store:

- macOS - Apple Keychain
- Windows - Windows Credential Manager

Android stores its space key through Android Keystore-backed storage. Pairing codes contain the private space key and should be treated like a password.

v0.1.2 and newer also repair the unusable desktop state that could be left by v0.1.1's temporary/mock keyring configuration.

> `SHA256SUMS.txt` is optional. You do **not** need it to install or run ClipMesh. It is only for verifying downloaded installer bytes.

> This repository is private. Only GitHub accounts with repository access can use the GitHub download links. For friends/family without repository access, send them the `.dmg`, `.exe`, or `.apk` directly.

## Builds and releases

Every pull request and push to `main` builds and tests macOS, Windows, and Android.

CI validates the protocol/core tests, native desktop builds and first-run behavior, secure-key persistence, macOS bundle/signature metadata, Android Shizuku/accessibility/exclusion packaging, Android APK generation, and platform checksums.

Successful `main` builds publish `v0.1.4-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and optional SHA-256 checksum file.
