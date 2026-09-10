# Security model

## Goals

ClipMesh is designed for a single owner running trusted devices on a trusted or partially trusted LAN. An attacker may be able to sniff, inject, replay or alter LAN packets. The attacker should not be able to recover clipboard plaintext or forge valid clipboard messages without the 256-bit space key.

## Deliberately absent

- No internet relay.
- No cloud backend.
- No analytics or telemetry.
- No account system.
- No web dashboard.
- No remote update channel in the runtime.
- No persistent clipboard-content history.
- No plaintext network compatibility mode.

## Cryptography

- Master secret: 32 random bytes from the OS CSPRNG.
- AEAD: AES-256-GCM.
- KDF: HKDF-SHA-256.
- Discovery authentication: HMAC-SHA-256.
- Message IDs: UUID v4.
- Nonces: independent 96-bit random values from the OS CSPRNG.
- Per-device sender key separation prevents nonce collisions on different devices from sharing an AEAD key.

The encryption key is derived as:

```text
HKDF-SHA256(
  ikm  = space_key,
  salt = space_id_bytes,
  info = "clipmesh/aead/v1" || sender_device_id_bytes,
  len  = 32
)
```

Discovery uses a separate key:

```text
HKDF-SHA256(
  ikm  = space_key,
  salt = space_id_bytes,
  info = "clipmesh/discovery/v1",
  len  = 32
)
```

## Secret storage

Desktop uses the OS keyring through the Rust `keyring` crate (macOS Keychain / Windows Credential Manager backends). Android stores the space secret encrypted with an AES key generated inside Android Keystore. The raw space secret is not stored in normal SharedPreferences.

## Pairing

The private-alpha provisioning URI contains the space key. This makes setup simple and removes a network pairing attack surface, but means the URI/QR must be protected like a password. Never send it through email/chat/cloud notes. Import it locally and discard screenshots afterwards.

A production/public version should replace this with an expiring PAKE/invite handshake (for example SPAKE2 or Noise XX with an authenticated out-of-band secret).

## LAN boundary

Discovery uses local UDP broadcast only. Runtime TCP peers are rejected unless their IP address is private, loopback or link-local. The desktop also refuses non-LAN static peers by default.

This is defense-in-depth, not a firewall. Use the supplied OS firewall scripts as well.

## Replay and loops

Each clipboard message has a UUID. Receivers keep a bounded in-memory replay set. Messages outside the timestamp acceptance window are discarded. Applying a remote clipboard also records its content fingerprint so the local watcher does not immediately re-broadcast the same content.

## Source exclusions

Desktop checks the frontmost application when a clipboard event arrives. Android can optionally enable an accessibility helper that records only `event.packageName`; it does not request window content. If the source matches an exclusion, nothing is serialized or sent.

Android also refuses to sync a local clipboard when its `ClipDescription` is marked sensitive (`EXTRA_IS_SENSITIVE` / legacy sensitive extra), providing a second defense for password managers and other apps that correctly mark sensitive clipboard content.

## Remaining risks

- A compromised endpoint can read the clipboard before or after encryption. E2EE cannot protect against malware/root/admin on an endpoint.
- Pairing-code leakage gives access to the shared space key. In this private alpha, reinitialize all devices into a fresh space if the provisioning URI is exposed.
- Clipboard APIs are inherently privileged/sensitive.
- AES-GCM requires nonce uniqueness; this implementation uses 96-bit CSPRNG nonces and a per-sender key. For the expected personal clipboard volume, collision probability is negligible, but a formal high-assurance product could persist deterministic counters or use a nonce-misuse-resistant AEAD.
- The project has not received an independent cryptographic or application security audit.
- Android Shizuku executes the clipboard helper with shell/root-like privileges supplied by Shizuku. Only install builds you compiled yourself and keep Shizuku access limited.

## Recommended local hardening

1. Build binaries yourself from a reviewed commit.
2. Turn on OS full-disk encryption.
3. Keep password-manager/app exclusions enabled.
4. Restrict the desktop executable to LocalSubnet in Windows Firewall / macOS firewall tooling.
5. Do not expose TCP port 41474 or UDP 41473 on your router.
6. If a device or pairing code is lost/exposed, reinitialize all devices into a fresh ClipMesh space.
7. Keep Android background sync off when you do not need it.
