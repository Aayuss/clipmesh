# ClipMesh protocol v1

Ports:

- UDP 41473: authenticated LAN discovery.
- TCP 41474: persistent peer channel.

All integer fields are big-endian.

## Discovery datagram

UTF-8 JSON:

```json
{
  "v": 1,
  "space_id": "uuid",
  "device_id": "uuid",
  "name": "Laptop",
  "port": 41474,
  "timestamp_ms": 0,
  "mac": "base64url"
}
```

`mac` is HMAC-SHA-256 over the canonical byte sequence:

```text
v || 0x00 || space_id || 0x00 || device_id || 0x00 || name || 0x00 || port || 0x00 || timestamp_ms
```

The discovery key is derived independently from the clipboard AEAD keys.

Datagrams with the wrong space ID, invalid HMAC or timestamp skew greater than 120 seconds are ignored.

## TCP hello

Immediately after connecting, both sides send a `Hello` record:

```text
"CMH1"                     4 bytes
space_id                    16 bytes
sender_device_id            16 bytes
timestamp_ms                 8 bytes
random_nonce                16 bytes
HMAC-SHA256(previous bytes) 32 bytes
```

The connection is closed unless the HMAC and space ID are valid.

## Encrypted frame

A TCP frame is prefixed with a 4-byte length. The encrypted frame itself is:

```text
magic            4   "CM01"
version          1   0x01
kind             1   1=clipboard, 2=ack, 3=ping, 4=pong
flags            2
sender_id       16
message_id      16
timestamp_ms     8
nonce           12   AES-GCM nonce
ciphertext_len   4
ciphertext       N   plaintext + 16-byte GCM tag
```

All fixed header bytes including nonce and `ciphertext_len` are AEAD associated data.

The receiver derives the decrypt key from the advertised `sender_id`. Because the sender ID is authenticated as associated data, it cannot be changed without failing authentication.

## Clipboard payload

Clipboard plaintext is UTF-8 JSON. Binary representations are base64 encoded to keep the Android/Rust implementations simple and deterministic.

```json
{
  "schema": 1,
  "source_app": "Visual Studio Code",
  "representations": [
    {"mime": "text/plain", "data_b64": "..."},
    {"mime": "text/html", "data_b64": "..."}
  ],
  "files": [
    {"name": "photo.png", "sha256": "hex", "data_b64": "..."}
  ]
}
```

Portable MIME names used by v1:

- `text/plain; charset=utf-8`
- `text/html; charset=utf-8`
- `text/rtf`
- `image/png`

## ACK/retry

An ACK frame uses `kind=2` and places the acknowledged clipboard message UUID in the frame `message_id`. It has an empty encrypted plaintext.

Senders retry an unacknowledged clipboard frame after 750 ms with exponential backoff, up to 3 retries. Duplicate message IDs are ignored but ACKed again.

## Limits

- Max encrypted TCP frame: 72 MiB.
- Default clipboard payload: 64 MiB.
- Max discovery JSON: 4 KiB.
- Timestamp window: 120 seconds.
