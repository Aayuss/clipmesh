# ClipMesh Private Clipboard

Private, LAN-only, encrypted clipboard synchronization for **macOS, Windows, and Android**.

> **Status:** private alpha. The protocol, desktop agent, Android client, build automation, test vector, and security controls are included, but the native apps have not been compiled in the Linux environment that generated this archive and the project has not received an independent security audit. Build and test on your own devices before trusting it with high-impact secrets.

## What is included

- macOS <-> Windows automatic clipboard sync.
- macOS/Windows <-> Android automatic clipboard sync.
- Normal Copy/Paste workflow - no "send clipboard" button.
- Desktop: text, HTML, RTF, PNG images, and files.
- Android: text, HTML, images/screenshots, and files.
- No account, cloud, relay, public rendezvous service, ads, analytics, telemetry, or clipboard-history database.
- Strict LAN addressing only.
- **AES-256-GCM always on** for clipboard frames.
- Per-sender keys via HKDF-SHA-256.
- HMAC-SHA-256 authenticated LAN discovery and authenticated peer handshakes.
- Replay UUIDs, timestamp window, deduplication, ACK + retry, and reconnect behavior.
- 64 MiB default clipboard payload cap.
- Password-manager/app exclusions.
- Desktop secret storage through macOS Keychain / Windows Credential Manager.
- Android secret storage wrapped by Android Keystore.
- Android background-sync master toggle and run-at-boot toggle.
- Android foreground service uses no permanent wake lock.
- Preferred Android background-read mode uses **Shizuku**. ClipboardManager's change callback is the wake signal; Shizuku performs the privileged read, avoiding the upstream UniClip module's 500 ms polling loop.
- Optional 5-second compatibility watchdog for OEMs that suppress events; **off by default** and checks only while the screen is interactive.

## Repository layout

```text
clipmesh/
├── crates/clipmesh-core/       # crypto, frame format, payload schema, discovery auth
├── apps/desktop/               # Rust macOS + Windows agent / setup CLI
├── android/                    # native Kotlin Android app
├── scripts/                    # build, install, firewall and audit helpers
├── test-vectors/               # protocol-v1 interoperability vector
├── tools/protocol_selftest.py
├── PROTOCOL.md
├── SECURITY.md
├── BUILDING.md
└── THIRD_PARTY_NOTICES.md
```

## Fastest setup

### 1. Build the first desktop

See `BUILDING.md`, then initialize it:

```bash
clipmesh init --name "My Mac"
clipmesh pairing-code
```

The second command prints a `clipmesh://pair?...` provisioning URI and a QR representation. **The URI contains your private 256-bit space secret. Treat it like a password.**

### 2. Join Windows

```powershell
clipmesh.exe join 'clipmesh://pair?...' --name "My Windows PC"
clipmesh.exe autostart install
clipmesh.exe run
```

### 3. Join Android

Build/install the APK, open ClipMesh, paste the same pairing URI, tap **Join**, grant Shizuku permission, then turn on **Background auto-sync**.

For Android -> desktop background copy capture on modern Android, Shizuku is the recommended mode. Without it, Android's public clipboard API normally returns no clipboard data when the app lacks input focus.

### 4. Start the first desktop automatically

```bash
clipmesh autostart install
clipmesh run
```

Now the intended experience is simply:

```text
Mac: Cmd+C     -> Windows: Ctrl+V
Windows: Ctrl+C -> Mac: Cmd+V
Mac/Windows Copy -> Android Paste
Android Copy -> Mac/Windows Paste
```

## Source-app exclusions

Desktop:

```bash
clipmesh exclude list
clipmesh exclude add "1Password"
clipmesh exclude add "Bitwarden"
```

Android has **Choose excluded apps**. Enable the optional ClipMesh Accessibility exclusion helper if you want source-app detection; it records only the foreground package name and declares `canRetrieveWindowContent=false`.

## Energy strategy on Android

The normal mode is intentionally event-driven:

- no 250/500 ms clipboard polling;
- no wake lock;
- one low-importance foreground-service notification while enabled;
- sockets block while idle;
- LAN discovery every ~12 seconds only while disconnected, backing off to ~45 seconds with a peer;
- a small 30-second encrypted keepalive detects dead connections;
- image/file reads happen only after clipboard events;
- Background auto-sync OFF tears down listeners, sockets, Shizuku binding, and service;
- compatibility watchdog is opt-in, not default.

## Important limitations

Cross-platform "whatever is in the clipboard" cannot preserve every proprietary application-specific clipboard flavor. ClipMesh normalizes portable formats. A Photoshop/Finder/Excel-only private clipboard type may not have an Android/Windows/macOS equivalent.

Files are currently transferred inline and capped at 64 MiB. For multi-gigabyte clipboard file transfer, add a chunked encrypted stream rather than increasing this limit.

Android vendors can still apply aggressive background-process policies. A foreground service plus Shizuku is the strongest practical sideloaded configuration here, but no third-party Android app can promise literal 100% survival under every OEM power manager.

## Before sensitive use

Run:

```bash
./scripts/security-audit.sh
cargo test --workspace
```

Then build from the exact source you reviewed. Keep password managers excluded. Do not use this private alpha for seed phrases, master passwords, signing keys, or similarly catastrophic secrets until you have tested and reviewed your builds.

See `SECURITY.md` and `PROTOCOL.md`.
