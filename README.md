<p align="center">
  <img src="https://github.com/Aayuss/clipmesh/releases/download/v0.1.9-alpha/ClipMesh-icon.png" width="180" alt="ClipMesh icon">
</p>

<h1 align="center">ClipMesh</h1>

<p align="center">
  Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.
</p>

ClipMesh synchronizes text, images, and files directly between your paired devices over the local network. Clipboard payload encryption is mandatory and there is no cloud relay, account, analytics service, or clipboard-history database.

## Download ClipMesh

### Direct downloads - v0.1.9-alpha

- [Download ClipMesh for macOS (.dmg)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.9-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows (.exe)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.9-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android (.apk)](https://github.com/Aayuss/clipmesh/releases/download/v0.1.9-alpha/ClipMesh-Android.apk)

**[Open all ClipMesh releases](https://github.com/Aayuss/clipmesh/releases)**

## v0.1.9 - Android image reliability and quieter background sync

v0.1.9 focuses on the Android -> desktop image path and removing distracting Android clipboard/background UI.

- **Android -> macOS/Windows image fix** - Android clipboard entries are no longer required to contain exactly one item before an image is promoted to a real `image/png` clipboard representation. ClipMesh now scans ordinary Android clipboard items and prioritizes the first real image item in Shizuku snapshots even when Android/Samsung adds extra metadata or clip items.
- **Remote-copy popup setting** - Android Settings now includes **Show remote copy popup**. It defaults to **off**. With it off, mirrored text uses ClipMesh's Shizuku/shell clipboard write with Android's clipboard-overlay suppression metadata. Turn it on if you prefer Android's normal local "Copied" popup.
- **Quieter foreground sync notification** - the Android foreground-service channel is now minimum-importance and silent, uses a new quiet channel for upgrades, and no longer advertises `Connected peers: N`. Android still requires a foreground-service notification for reliable always-on sync; ClipMesh does not fake-remove the OS-required service indicator at the cost of background reliability.
- **v0.1.9 package metadata** - Android, macOS, Windows, the sync engine, CI checks, and release assets are aligned to v0.1.9.

## Pairing

One pairing code joins devices to the same encrypted private space. Pairing is not performed separately in both directions.

The macOS, Windows, and Android apps provide:

- editable device name and short device ID
- known/paired devices and authenticated online state
- **Copy Pairing Code**
- **Pair Device** / **Join** / **Create New**
- **View Clipboard**
- synchronization settings
- **Reset all pairing**

Pairing codes contain the private space key and should be treated like a password.

## Android background clipboard access

Android 10+ restricts ordinary background clipboard reads. ClipMesh supports:

- **Shizuku** - preferred for reliable Android -> desktop background clipboard capture
- the optional **ClipMesh app exclusions** Accessibility service as an event-driven fallback where Android/OEM behavior allows it
- an optional compatibility watchdog, off by default

Background sync defaults to **on**.

### Shizuku setup

1. Install/update the v0.1.9 Android APK.
2. Start Shizuku and confirm it is running.
3. In Shizuku -> **Authorized applications**, keep ClipMesh enabled.
4. Open ClipMesh -> **Settings**.
5. If needed, use **Request Shizuku permission** / **Connect Shizuku**.
6. Once bound, ClipMesh reports that background clipboard access is ready.

Shizuku is not required for Mac/Windows -> Android receiving or when Android has ordinary foreground clipboard access. It is the preferred path for reliable automatic Android -> desktop capture while ClipMesh is in the background.

## Testing synchronization

With both devices online, copy a fresh clipboard value each time:

1. Copy text or an image on macOS/Windows. Android should receive it automatically.
2. Copy text or an image on Android. With foreground clipboard access or Shizuku available, the desktop clipboard should update automatically.

## Android clipboard popup behavior

**Settings -> Show remote copy popup** controls whether mirrored text should intentionally use Android's visible local-copy UI.

- **Off (default)** - ClipMesh uses the quiet Shizuku/shell path and asks SystemUI to suppress the clipboard overlay.
- **On** - ClipMesh allows Android's normal copied popup.

The exact visual behavior is ultimately controlled by the Android/OEM SystemUI implementation.

## Background icons and desktop behavior

### macOS

- Opening ClipMesh shows the application window and menu-bar icon.
- Standard shortcuts such as Cmd-C, Cmd-V, Cmd-W, Cmd-Q, and Cmd-M work through the native macOS menu/responder chain.
- Red close hides the window and keeps synchronization running.
- Use the menu-bar icon to restore or quit ClipMesh.

### Windows

- Opening ClipMesh shows the application window and system-tray icon.
- X hides the window/taskbar entry while synchronization keeps running.
- Use the tray icon to restore or quit ClipMesh.

## macOS Gatekeeper and Android install warnings

The current GitHub builds are suitable for direct personal testing, but operating-system trust prompts cannot be removed just by changing application code.

### macOS

The GitHub build is ad-hoc code-signed. To eliminate the normal Gatekeeper **Open Anyway / Privacy & Security** flow for downloaded builds, ClipMesh needs:

1. an Apple Developer Program **Developer ID Application** certificate,
2. signing with that certificate,
3. Apple notarization of the finished app/DMG,
4. stapling the notarization ticket to the distributed build.

Without those Apple-issued credentials, CI cannot legitimately make macOS treat the downloaded app as notarized.

### Android

The current GitHub workflow produces a sideloaded debug APK. Android/Play Protect may therefore require an **Install anyway** confirmation. The proper production path is a release APK/AAB signed with a stable private release key, ideally distributed through Google Play (including an internal-testing track if the app is private).

A private signing key should not be committed to this public repository. It should be stored as a protected GitHub Actions secret before switching the public release workflow to stable release signing.

## Security and storage

Desktop space keys use the operating-system credential store:

- macOS - Apple Keychain
- Windows - Windows Credential Manager

Android stores its space key through Android Keystore-backed storage.

The Accessibility service is configured with `canRetrieveWindowContent=false`; it is used for foreground-app exclusions and clipboard-change signaling, not screen scraping.

For sideloaded APKs on Android 13+, Android may initially block an Accessibility service as a restricted setting. If you use that optional fallback, open ClipMesh App info -> top-right menu -> **Allow restricted settings**, then enable **ClipMesh app exclusions** in Accessibility.

## Builds and releases

Every pull request and push to `main` builds macOS, Windows, and Android. CI validates protocol/core tests, authenticated desktop transport, Android Shizuku wiring, image synchronization guards, package metadata, native builds, packaged APK components, first-run behavior, reset behavior, and checksums.

A successful `main` build publishes `v0.1.9-alpha` with:

- `ClipMesh-macOS.dmg`
- `ClipMesh-Windows.exe`
- `ClipMesh-Android.apk`
- `ClipMesh-icon.png`
- `SHA256SUMS.txt`
