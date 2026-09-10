# Third-party notices

ClipMesh is an independent private project assembled from open-source building blocks and ideas.

## UniClipboard / UniClip

The Android Shizuku clipboard bridge in `android/app/src/main/java/dev/clipmesh/shizuku/` is adapted from UniClipboard's `UniClip` mobile project, especially its MIT-licensed `modules/shizuku-clipboard` implementation.

Upstream copyright notice:

```text
MIT License
Copyright (c) 2026 JericX
Copyright (c) 2026 mkdir700 (UniClip)
```

The full MIT grant is reproduced in `licenses/UNICLIP-MIT.txt`.

UniClipboard desktop informed the local-first/P2P threat model, but this repository does not include a copied UniClipboard desktop source tree. UniClipboard desktop is AGPL-3.0-only; if you later copy code from that repository into this project, preserve its AGPL obligations for the resulting derivative work.

## clipboard-rs

Desktop clipboard access uses `clipboard-rs`, MIT licensed, for native macOS/Windows clipboard read/write/watch support.

## Shizuku API

Android Shizuku integration uses the Shizuku API, MIT licensed.

All third-party dependencies remain subject to their own licenses. Cargo/Gradle dependency manifests are the authoritative package list.
