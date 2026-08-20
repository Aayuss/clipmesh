<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.8-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

This repository builds ClipMesh for personal/family/friends use.

## Download ClipMesh

### Direct downloads - v0.1.8-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.8-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.8-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.8-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

## v0.1.8 - Pairing reset, background sync, macOS shortcuts, and Android image sync

v0.1.8 focuses on real-device usability and cross-platform clipboard reliability.

- **Reset all pairing on every platform** - macOS, Windows, and Android now provide a destructive reset control that creates a new device identity and private space, clears remembered peers, and forces every device to pair again.
- **Live Android Shizuku status** - Settings distinguishes a genuinely bound Shizuku service from a merely authorized/running Shizuku installation. Once bound, ClipMesh reports the connection instead of continuing to show the permission-request action.
- **Background sync enabled by default** - Android now defaults background synchronization to on, matching ClipMesh's always-on synchronization behavior on desktop.
- **Quieter Android receiving** - remote clipboard writes carry Android remote/suppression metadata, including the privileged Shizuku text path, so mirrored clipboard changes do not unnecessarily show the distracting local-copy overlay where Android permits suppression.
- **Normal macOS Command shortcuts** - ClipMesh now installs a proper native application menu and responder chain for standard shortcuts including Cmd-C, Cmd-V, Cmd-X, Cmd-A, Cmd-Z, Cmd-Shift-Z, Cmd-W, Cmd-Q, and Cmd-M.
- **Android image -> desktop synchronization** - ordinary Android clipboard image `content://` URIs are now read and transmitted, and both the normal Android and Shizuku image paths normalize images to PNG before sending them to desktop.
- **Release regression checks** - CI verifies the reset commands/UI, Android Shizuku wiring and status, background-sync default, image path, remote clipboard suppression metadata, macOS menu shortcuts, native package versions, packaged APK components, first-run behavior, and desktop reset behavior.

## v0.1.7 - Shizuku Binder delivery fix

Real-device testing showed a specific Android failure: Shizuku itself could be **running**, and ClipMesh could appear **authorized** in Shizuku's Application management screen, while ClipMesh still reported that Shizuku was not connected.

The cause was the Android client wiring. ClipMesh depended on the Shizuku provider library and requested the Shizuku API permission, but the application manifest did not declare `rikka.shizuku.ShizukuProvider`. Authorization alone is not enough - that provider is the endpoint Shizuku uses to deliver its server Binder into the ClipMesh process. Without it, ClipMesh could remain authorized while `Shizuku.pingBinder()` stayed unavailable.

v0.1.7 therefore:

- declares the required `rikka.shizuku.ShizukuProvider` Binder endpoint in the packaged Android application
- keeps the Shizuku API permission and manager package visibility
- listens for Shizuku Binder arrival/death and immediately binds the clipboard UserService when an already-authorized install reconnects
- gives the clipboard UserService a stable tag and bumps its service version so Shizuku replaces stale service code from older ClipMesh builds
- never asks Shizuku to remove/kill its server; ClipMesh disconnects its own UserService with `remove=false`
- keeps privileged background clipboard reads/writes through the Shizuku UserService
- validates the Shizuku provider, authority, permission, UserService wiring and clipboard bridge in CI and again inside the packaged APK
- retains the v0.1.6 self-capture migration, authenticated transport fallback, canonical text MIME handling, macOS clipboard fallback and Accessibility wake path

### Shizuku setup after updating

1. Install/update to the v0.1.8 Android APK.
2. Start Shizuku normally and confirm **Shizuku is running**.
3. In Shizuku -> **Authorized applications**, keep ClipMesh enabled.
4. Open ClipMesh -> **Settings**. If ClipMesh is already bound, the page reports **Shizuku connected**; otherwise use **Request Shizuku permission** / **Connect Shizuku** as shown.
5. Once the Binder is available and permission is granted, ClipMesh reports that background clipboard access is ready.

Shizuku is **not required** for Mac/Windows -> Android receiving or for Android -> desktop capture while ClipMesh has foreground clipboard access. It is the preferred path for reliable automatic Android -> desktop capture while ClipMesh is in the background on modern Android.

## Foreground synchronization

With both devices showing **Online**, test with new clipboard values:

1. Copy new text or an image on the Mac or Windows PC. Android's clipboard should update automatically.
2. Copy new text or an image on Android. With foreground clipboard access or the Shizuku background path available, the desktop clipboard should update automatically.

One pairing code joins devices to the same private space; pairing is not performed separately in both directions.

## Pairing and device UI

The normal app screen on macOS, Windows, and Android provides:

- editable device name and short device ID
- known/paired devices and authenticated online state
- **Copy Pairing Code**
- **Pair Device** / **Join** / **Create New**
- **View Clipboard** for local clipboard inspection
- **Settings** for synchronization controls and **Reset all pairing**

Pairing codes contain the private space key and must be treated like a password.

## Android background clipboard access

Android 10+ restricts ordinary background clipboard reads. ClipMesh supports:

- Shizuku - preferred privileged background clipboard access
- the optional **ClipMesh app exclusions** Accessibility service as an event-driven fallback where Android/OEM behavior allows it
- the optional compatibility watchdog, which remains off by default because it uses periodic checks

Background sync itself defaults to **on** in v0.1.8. The optional compatibility watchdog is separate and remains off by default.

The Accessibility service is configured with `canRetrieveWindowContent=false`; it is used for foreground-app exclusions and clipboard-change signaling, not screen scraping.

For sideloaded APKs on Android 13+, Android may initially block the Accessibility service as a restricted setting. Open ClipMesh's App info, use the top-right menu -> **Allow restricted settings**, then return to Accessibility and enable **ClipMesh app exclusions** if you want that fallback.

## Background icons and desktop behavior

The compact background-status icon uses the same left/right-arrow concept everywhere.

### macOS

- Opening ClipMesh shows the application window and menu-bar icon.
- Standard application shortcuts such as Cmd-C, Cmd-V, Cmd-W, Cmd-Q, and Cmd-M work through the native macOS menu/responder chain.
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

> The repository may be public during active development. If it is made private later, only GitHub accounts with repository access can use the GitHub release links; installers can also be shared directly with trusted devices.

## Builds and releases

Every pull request and push to `main` builds macOS, Windows, and Android. CI validates protocol/core tests, the authenticated desktop transport roundtrip, self-capture migration guards, native builds, first-run behavior, reset identity behavior, Android Shizuku provider/UserService wiring, Android image synchronization guards, packaged APK components, and checksums.

A successful `main` build publishes `v0.1.8-alpha` with the raw `.dmg`, `.exe`, `.apk`, icon artwork, and checksum file.
