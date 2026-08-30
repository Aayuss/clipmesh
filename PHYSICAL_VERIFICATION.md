# ClipMesh physical verification

Verified product-code boundary: `9faf1b8b1baffa2c2a8aee78938ba9d9acf7fe74`

Date: 2026-08-30

Hardware used:
- Samsung Galaxy S23 Ultra (`SM-S918B`)
- macOS development machine on the same physical LAN
- Shizuku authorized on Android
- Android background sync enabled

The aggregate physical harness completed with `TOTAL FAILURES: 0`.

## Physical matrix

- PASS - Shizuku background read
- PASS - Shizuku clipboard write
- PASS - Android -> Mac text
- PASS - Mac -> Android text
- PASS - Android -> Mac image
- PASS - Mac -> Android image
- PASS - File-transfer setup - peers favorited and macOS IPv4 listener active
- PASS - Android -> Mac file - exact bytes verified
- PASS - Mac -> Android file - SHA-256 verified
- PASS - Android background service
- PASS - Shizuku permission retained
- PASS - Android ANR check

The run ended with `ALL PHYSICAL CLIPMESH TESTS PASSED`.

## Release boundary

`v0.2.12-alpha` must descend from the verified commit above. After this physical verification, runtime/product code must not change before release. Only release metadata, documentation, and release workflow files may differ.
