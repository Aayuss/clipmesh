# v054 resource audit

This pass preserves the v052/v053 runtime architecture and protocol. It changes only bounded retention, equivalent image handling, cleanup, and debug-only observability.

## Clipboard frame ownership

| Owner | Maximum retained clipboard frames | Maximum lifetime | Release condition |
| --- | ---: | --- | --- |
| Reconnect replay | 1 process-wide | 30 seconds | TTL expiry, newer clipboard state, or network stop |
| Pending retransmission | 1 per connected peer | Existing 0.75 + 1.5 + 3 second retry sequence | Matching ACK, newer state for that peer, retry exhaustion, disconnect, or stop |
| Peer writer queue | 1 conflated clipboard state per peer | Until written, superseded, connection close, or stop | Write/dequeue, newer state, disconnect, or stop |

The retry coroutine registry is also bounded to one job per peer. Control frames retain the existing bounded capacity of 64 per peer.

## Android image allocation catalogue

Before v054, a normal content URI with a known size could be held once inside `ByteArrayOutputStream` and again after `toByteArray()`. Image normalization then held the encoded input, a decoded ARGB bitmap, and a second PNG byte array. A screenshot used a temporary file, a source byte array, a decoded bitmap, a PNG output array, payload JSON/base64 data, and the encrypted frame. Remote apply retained the received protocol payload while calculating its perceptual identity, then streamed that same byte array to the cache file.

After v054:

- Known-size content URIs allocate one exact encoded byte array. Providers without a reliable size keep the prior bounded-stream fallback.
- Valid PNG input with normal or undefined EXIF orientation passes through unchanged after PNG signature and decode-bounds validation, removing the full normalization bitmap and second encoded array. JPEG, HEIC, other formats, and oriented images keep the existing decode/orient/PNG path.
- Image-only payloads no longer compute an unused SHA-256 over source bytes; hashing remains unchanged when bytes are actually emitted as a portable file.
- Screenshot temporary files are size-checked and deleted in `finally` before image handling continues.
- The Shizuku UserService retains only clipboard item index-to-URI metadata between snapshot and copy calls, not the full `ClipData` and its text/image objects.
- Remote apply is unchanged because its payload bytes are required by the protocol and echo-suppression behavior.

The 44 MiB item/payload limit is unchanged. Base64 JSON and encrypted-frame allocations are protocol-required and intentionally unchanged.

## Idle and multicast conclusions

No routine clipboard polling was added. The only compatibility capture scheduler remains gated on an actually failed privileged listener registration, background sync, the compatibility setting, sending enabled, screen interactive, at least one peer, and Shizuku permission.

### Final Android clipboard-work classification

| Match | Classification |
| --- | --- |
| `ClipboardBridge.readSnapshotJson` | One privileged snapshot per coalesced clipboard edge; never scheduled routinely while the hidden listener is healthy |
| `ClipboardUserService.getPrimaryClip` | Binder work performed only for the explicit snapshot AIDL call; the fallback inside item copy is used only if its preceding snapshot URI map is unavailable |
| `ClipboardBridge.primaryClip` | Normal-UID fallback gated by a foreground ClipMesh activity and reached only after the event-driven privileged attempt |
| `MainActivity.primaryClip` | User-visible clipboard preview construction while the app UI is open, not background work |
| `captureNowForSystemEvent` | Authoritative privileged event edge |
| `captureNowForAccessibilityEvent` and normal listener | Secondary metadata/fallback edge; returns before scheduling a read while the privileged listener is healthy |
| `captureNowForCompatibilityFallback` | One-shot backoff task created only after privileged listener registration is confirmed failed and every existing compatibility gate passes |
| `captureNowForUserAction` | Explicit user/debug action only |
| Screenshot `schedule`/`delay` | Existing bounded one-shot copy retry; no clipboard read |
| Network, pairing, discovery, and transfer delays | Existing protocol health/retry/discovery/progress behavior; no clipboard read and unchanged by v054 |

There is no `scheduleWithFixedDelay`, `scheduleAtFixedRate`, `Timer`, or routine `postDelayed` clipboard snapshot path in the final reconstructed runtime. The 60 ms edge coalescer retains one serialized clipboard worker.

### Executor lifecycle conclusion

`ClipboardBridge` owns one scheduled worker per runtime instance and clears pending debug/edge state before `shutdownNow`. The production `ShizukuManager`, its bind scheduler, and the UserService watchdog retain their existing one-process/one-manager cleanup. Network scope cancellation now also clears replay and per-peer retry ownership. `LocalTransferEngine` remains a process-wide singleton whose executor is reused across start/stop cycles; socket closure and the `started` gate terminate its discovery/server loops. Replacing that working pool or discovery mechanism was not justified without physical reliability/load evidence.

The continuous `WifiManager.MulticastLock` is intentionally unchanged because the required Samsung/macOS/Windows, screen-off, Wi-Fi reconnect, and VPN reliability matrix is not available in CI. Debug builds now count lock acquisition/release/held time, packets received by the existing shared multicast-capable discovery socket, and direct HTTP registrations. Android's existing single socket can receive multicast and broadcast on the same port but does not expose the destination address through `DatagramPacket`, so broadcast receives are reported as unclassified instead of changing socket architecture merely for measurement.
