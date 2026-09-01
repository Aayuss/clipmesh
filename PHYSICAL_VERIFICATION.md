# ClipMesh physical verification

Verified product-code boundary: `ce8dae678e8cd3f7bc40613c4ea317d9a9598ff4`

Date: 2026-09-01

Hardware used:
- Samsung Galaxy S23 Ultra (`SM-S918B`)
- macOS development machine on the same physical LAN
- Shizuku authorized on Android
- Android background sync enabled

The physical development harness and exact-final targeted screenshot probe completed with `TOTAL FAILURES: 0`.

## Physical matrix

- PASS - Shizuku background read
- PASS - Shizuku clipboard write
- PASS - Android -> Mac text
- PASS - Mac -> Android text
- PASS - Android -> Mac image exactly once with no echo
- PASS - Android EXIF image orientation preserved
- PASS - Mac -> Android image exactly once with no echo
- PASS - Automatic Android screenshot -> Mac exactly once
- PASS - Adjacent duplicate suppressed; separated same-content recopy allowed
- PASS - Ten-second passive clipboard stability - no outgoing, remote-apply, or macOS change-count growth
- PASS - File-transfer setup - peers favorited and macOS IPv4 listener active
- PASS - Android -> Mac file - exact bytes verified
- PASS - Mac -> Android file - SHA-256 verified
- PASS - Android background service
- PASS - Shizuku permission retained
- PASS - Android ANR check

The run ended with `ALL PHYSICAL CLIPMESH TESTS PASSED`.

## Release boundary

`v0.2.15-alpha` must descend from the verified commit above. After this physical verification, runtime/product code must not change before release. Only the v0.2.15 metadata patch, release-policy checks, documentation, and build/release workflow files may differ.
