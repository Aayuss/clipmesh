# ClipMesh v0.2.2

ClipMesh combines encrypted clipboard sync with nearby LAN file transfer across macOS, Windows, and Android.

## v0.2.2 changes

- LocalSend-inspired navigation: desktop left rail; Android bottom navigation for Clipboard, File transfer, Settings.
- macOS/Windows UI rebuilt to match the dark charcoal, warm-white, amber ClipMesh theme.
- File transfer supports drag and drop on desktop plus normal file selection.
- macOS Choose files and favorite/star actions fixed.
- macOS main content is vertically scrollable.
- macOS packages a real `com.apple.share-services` Share extension and registers it when the app launches. Finder controls the exact placement; normally use Right click → Share → ClipMesh.
- Android LAN HTTP transfer policy fixed so direct local transfers are no longer blocked by the cleartext-policy error.
- Android pairing-code clipboard values are excluded from clipboard sync, and rapid clipboard events are coalesced so screenshots are not dropped behind the pairing URI.
- Android switch active states use visible amber/cream colors.
- No permanent Android foreground-service notification was reintroduced.
- CI validates the actual packages plus a LocalSend-v2-style prepare/upload byte-transfer loopback before release.

## Downloads

Release assets are published at:

https://github.com/Aayuss/clipmesh/releases/tag/v0.2.2-alpha

Expected assets:

- `ClipMesh-macOS.dmg`
- `ClipMesh-Windows.exe`
- `ClipMesh-Android.apk`
- `ClipMesh-icon.png`
- `SHA256SUMS.txt`

## macOS Finder Share

ClipMesh includes an actual macOS Share extension. macOS decides whether it appears directly in Finder's Share submenu and whether a newly installed extension is automatically enabled. If it is disabled, enable **ClipMesh** in System Settings → General → Login Items & Extensions → Sharing.

Because the GitHub DMG is ad-hoc signed rather than Developer-ID notarized, macOS can still require the one-time Privacy & Security approval for the application itself.

## Android installation

The GitHub APK is sideloaded and can still trigger Play Protect/Samsung's **Install anyway** flow. Removing that distribution warning reliably requires stable release signing and recognized store distribution; it is separate from ClipMesh's runtime behavior.

## Security model

Clipboard sync and nearby file transfer remain separate:

- Clipboard mesh: paired-space encrypted synchronization.
- Nearby file transfer: direct LAN LocalSend-v2-style discovery/prepare/upload semantics.

The current nearby-file transport is plain HTTP on the local network. Favorites affect automatic file acceptance only and do not grant clipboard-space access.
