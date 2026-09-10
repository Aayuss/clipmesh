# Project status

## Implemented

- Shared encrypted protocol for macOS, Windows, and Android.
- AES-256-GCM authenticated encryption is mandatory.
- HKDF-SHA-256 per-sender key separation.
- HMAC-SHA-256 discovery and authenticated peer hello.
- LAN/private-address enforcement; no cloud, relay, account, analytics, ads, or runtime updater.
- Replay protection, duplicate/echo suppression, ACK/retry, reconnect, keepalive, and a 30-second RAM-only latest-frame outbox.
- Desktop native clipboard watcher for text, HTML, RTF, images, and files.
- Desktop app exclusions and secure OS keyring storage.
- Native Kotlin Android app with Android Keystore-wrapped space secret.
- Android foreground background-sync service, boot start option, send/receive toggles, per-content toggles, and app exclusions.
- Shizuku privileged clipboard bridge for background Android reads/writes.
- Event-triggered Android capture; no permanent high-frequency polling.
- Optional 5-second screen-on-only compatibility watchdog, disabled by default.
- Sensitive-clipboard flag rejection on Android.
- Protocol interoperability test vector and independent Python self-test.
- macOS/Windows/Android build scripts and GitHub Actions build workflow.

## Verified in the generation environment

- Protocol-v1 independent AES-GCM/HKDF/HMAC self-test: PASS.
- Security audit script: PASS.
- Shell script syntax: PASS.
- Android XML parsing: PASS.
- Source scan for TODO/FIXME/unimplemented markers: PASS.
- No telemetry/ad SDK markers in runtime source: PASS.
- No runtime web endpoint literals: PASS.
- No cloud/relay implementation markers: PASS.

## Not verified here

The generation environment does not contain Rust, Cargo, the Android SDK, Gradle, macOS/Xcode, or Windows/MSVC. Therefore:

- Rust desktop/core compilation was not executed here.
- Android Kotlin/Gradle compilation was not executed here.
- macOS `.app`/`.dmg` was not produced here.
- Windows `.exe` was not produced here.
- Android `.apk` was not produced here.
- Cross-device latency, sleep/wake behavior, OEM battery behavior, and clipboard-format fidelity have not yet been tested on the owner's actual hardware.
- No independent security audit has been performed.

This is source-complete private-alpha engineering work, not a claim of a production-audited or literally flawless release.
