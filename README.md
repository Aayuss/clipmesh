# ClipMesh v0.2.15

ClipMesh provides encrypted clipboard sync and direct nearby file transfer across macOS, Windows, and Android.

## Download

Download the current installers directly - there is no need to browse the Releases page:

- [Download ClipMesh for macOS](https://github.com/Aayuss/clipmesh/releases/download/v0.2.15-alpha/ClipMesh-macOS.dmg)
- [Download ClipMesh for Windows](https://github.com/Aayuss/clipmesh/releases/download/v0.2.15-alpha/ClipMesh-Windows.exe)
- [Download ClipMesh for Android](https://github.com/Aayuss/clipmesh/releases/download/v0.2.15-alpha/ClipMesh-Android.apk)
- [Download SHA-256 checksums](https://github.com/Aayuss/clipmesh/releases/download/v0.2.15-alpha/SHA256SUMS.txt)

These links become live after the dedicated `Release ClipMesh v0.2.15` GitHub Action completes and publishes `v0.2.15-alpha`.

Release signing setup and the audited v0.2.9 Android migration are documented in [RELEASE_SIGNING.md](RELEASE_SIGNING.md). Official Android publication fails closed unless the permanent keystore and expected certificate fingerprint are configured; pull-request and local development builds continue to use separate debug/development identities.

## What changed in v0.2.15

- Stops cross-device image ping-pong by carrying remote-image provenance and comparing a stable perceptual identity across PNG/container re-encoding and platform color conversion.
- Prevents adjacent duplicate clipboard writes on both platforms while still allowing the same content to be copied again after a different intervening clipboard event.
- Preserves Android JPEG EXIF orientation when images arrive on macOS, preventing portrait/gallery images from appearing sideways.
- Detects Samsung screenshots added directly to MediaStore even when Gboard receives them without Android's primary clipboard changing, then sends each new screenshot to the paired desktop exactly once.
- Adds physical regression coverage for Android-to-Mac and Mac-to-Android image exact-once delivery, automatic screenshot delivery, orientation, and `A,A,B,A` adjacent-deduplication semantics.
- Physically verified on a Samsung Galaxy S23 Ultra and macOS: all clipboard directions, image echo stability, automatic screenshot sync, adjacent-only deduplication, orientation, and file transfer passed.
- Increments Android to `versionName 0.2.15` and `versionCode 25`, with matching macOS, Windows, and Rust package metadata while retaining the established permanent Android release-signing identity.

## What changed in v0.2.12

- Fixes Samsung/Android background clipboard reads through Shizuku by clearing the inbound Binder identity only for privileged `getPrimaryClip` calls while preserving the previously working clipboard write path.
- Separates macOS file-transfer HTTP callbacks, blocking multicast discovery, announcements, and outgoing sends onto independent queues, preventing the discovery `recvfrom()` loop from starving real file-transfer requests.
- Keeps the macOS file receiver explicitly IPv4-capable on port `53421` for Android LAN peers.
- Hardens physical-device testing so stale Wireless Debugging endpoints and inherited `ANDROID_SERIAL` values are ignored or refreshed safely.
- Adds direct Shizuku read/write probes, runtime clipboard-path observability, ANR checks, and an aggregate physical matrix that continues through all independent text, image, and file directions before reporting failures.
- Physically verified on a Samsung Galaxy S23 Ultra and macOS with `TOTAL FAILURES: 0`: background Shizuku read/write, text both directions, image both directions, file transfer both directions with exact-byte/SHA-256 verification, Android background service, retained Shizuku permission, and no current-run Android ANR.
- Increments Android to `versionName 0.2.12` and `versionCode 22` while retaining the established permanent Android release-signing identity.

The exact physical verification boundary and matrix are recorded in [PHYSICAL_VERIFICATION.md](PHYSICAL_VERIFICATION.md).

## What changed in v0.2.11

- Fixes macOS file receiving for IPv4-only LAN peers, including Android devices: the transfer listener now explicitly binds IPv4 rather than relying on a Network.framework listener that could accept only IPv6.
- Adds the macOS local-network usage description required for ClipMesh LAN discovery and direct transfers.
- Makes the physical development harness self-contained: Java 17 and Cargo are discovered automatically, ADB selects a single canonical transport, and every reconstruction happens in an isolated copy.
- Increments the Android release to `versionName 0.2.11` and `versionCode 21` while retaining the established permanent release-signing identity.

## What changed in v0.2.10

- Establishes ClipMesh's first permanent Android release-signing identity with `versionName 0.2.10` and `versionCode 20`.
- Publishes only the verified release-signed APK; CI/debug receivers, development providers, and test-driver packages are rejected from the release artifact.
- Keeps the physical development harness and its `clipmesh-dev` identity separate from the permanent release key.
- Keeps `v0.2.9-alpha` as the one-time Android signing migration boundary; releases from `v0.2.10-alpha` onward update normally while the permanent key is retained.
- Structures future macOS Developer ID signing inside-out across Mach-O helpers, frameworks, XPC services, extensions, nested apps, and the outer app, with explicit authority and TeamIdentifier verification. Until Apple credentials are configured, GitHub continues to label the macOS artifact as ad-hoc signed and not notarized.

## What changed in v0.2.9

- Clipboard/network reinitialization no longer stops and immediately restarts the independent Android LAN file receiver. This removes the server cleanup race that could make File Transfer requests disappear after a background clipboard lifecycle transition.
- Android 15 CI now proves that the hidden-UI file receiver remains reachable after the production clipboard runtime is rebuilt, before exercising pairing, Accept/Reject notifications, and a complete trusted upload.
- `dev-latest` is refreshed from the same green cross-platform build as the immutable `v0.2.9-alpha` release.

## What changed in v0.2.8

- Restored Android -> desktop clipboard sending when ClipMesh is not open. Accessibility clipboard events now feed the process-level `BackgroundRuntime`/`ClipboardBridge` directly instead of relying on an Activity-era callback handoff that could be missed during lifecycle transitions.
- The Shizuku screen-on clipboard watcher remains the privileged fallback for Android 10+ background clipboard restrictions, so text and image capture do not depend on opening the ClipMesh Activity.
- File Transfer now lists every live ClipMesh LAN receiver on Android, macOS, and Windows. A device is no longer hidden merely because its ClipMesh window is in the background or because it is not a favorite.
- Receiver readiness and expiry remain the availability gates, so a device is not advertised before its transfer server is listening and stale devices still age out.
- Android 15 CI now explicitly hides all ClipMesh Activities, injects a protected debug clipboard event through the same process-level capture path, and verifies that an outgoing clipboard payload reaches the real network callback without reopening the UI.
- The same Android runtime test continues to verify background file receiving, Accept/Reject notifications, trusted automatic receiving, and persistence of transferred bytes.
- Releases are versioned as immutable artifacts. Once `v0.2.8-alpha` exists, later commits will not silently replace its binaries; another release requires a version bump.

## What changed in v0.2.7

- Fixed the macOS startup failure that showed **Background sync stopped (exit 1)** when an older ClipMesh background process still owned clipboard port `41474` after a crash or force-quit.
- macOS now validates the listener executable before replacing it. It will reclaim only an exact `clipmesh-bin` process and will leave unrelated applications untouched.
- A single-instance lock prevents a second ClipMesh window from interrupting a healthy first instance.
- Startup now verifies that the encrypted background engine remains alive before reporting that sync is running.

## What changed in v0.2.6

- Fixed the cross-platform file-transfer deadlock by completing the HTTP `100 Continue` handshake before reading upload bodies. The sender still uses a two-phase request/accept/upload session with per-file tokens, following the reliable state separation used by LocalSend.
- Android background clipboard capture is event-driven again. Accessibility passes the clipboard object immediately to ClipMesh, so copied Samsung screenshots and gallery/image content URIs can be read while their permission grant is valid.
- Remote clipboard retry/reconnect delivery is deduplicated before Android writes to the system clipboard, preventing repeated system “Copied” overlays and echo loops.
- Already-paired devices are hidden from the nearby clipboard and file recipient lists.
- Each paired device has its own Remove action. Removal is enforced by a persistent deny list and authenticated connections from that device are rejected until it is explicitly paired again.
- Android uses a calmer muted gold, custom ClipMesh pairing/file dialogs, and visible press animation plus haptic feedback on app buttons.
- Clipboard/file background work remains socket- and event-driven; no periodic network polling was added.

## What changed in v0.2.5

- Clipboard shows unpaired ClipMesh devices on the same LAN. Select **Pair** instead of copying a long pairing URI between devices.
- The receiver explicitly accepts the request, then types the six-digit code displayed by the sender.
- Pairing uses ephemeral P-256 ECDH, transcript-bound HKDF-SHA256 keys, a short authentication string, encrypted credential delivery and HMAC-SHA256 authentication. The private clipboard-space key is never broadcast or sent in plaintext.
- Pairing sessions expire after two minutes. A wrong code rejects the session, altered ciphertext is refused, and cryptographic work only runs during an active attempt.
- Background discovery remains event-driven. Each platform announces only every two minutes while idle, listens on blocking sockets without polling, and sends an immediate discovery burst when the app becomes visible or the user taps Refresh.

## What changed in v0.2.4

- ClipMesh file transfer now uses its own port (`53421`) and `/api/clipmesh/v1` protocol namespace. It no longer binds LocalSend's port, discovers LocalSend devices, or exposes LocalSend routes.
- The desktop and Android interfaces use neutral black surfaces with gold actions, roomier buttons, and corrected desktop sidebar padding.
- Dropping files anywhere in the macOS or Windows ClipMesh window opens File Transfer and selects the dropped files.
- macOS and Windows have a top-right **Choose file manually** action. Android offers **Image**, **Video**, and **File** choices.
- Selected files render in a horizontal, scrollable visual strip with thumbnails/icons and individual remove buttons.
- Clipboard content remains hidden until **View current clipboard** is selected.
- Clipboard starts with this device's name, paired devices, Refresh, Rename, and **Pair new device**.
- Nearby file discovery starts from every main app section instead of waiting for File Transfer to open.
- Every Android bottom-tab change uses the same fade transition.
- Android has a **Receive files when the app is not opened** switch. When enabled, its foreground service keeps the device discoverable; when disabled, receiving is limited to a visible ClipMesh activity.
- Favorited Android senders can still save automatically. Other senders receive Accept/Reject controls in a blurred bottom sheet while ClipMesh is visible, or in a notification while ClipMesh is in the background.
- macOS packages and refreshes the Finder Share extension. Windows registers **Share with ClipMesh** for files and folders. Shared files open preselected in the recipient chooser.

## Clipboard pairing

Use the nearby-device list for normal pairing. The six-digit code authenticates the ephemeral encrypted connection and must be entered on the receiving device before ClipMesh releases the encrypted clipboard-space credential.

The manual pairing URI remains available as a fallback. It contains the private-space key and should still be treated like a password.

## Android background clipboard sync

Android 10+ restricts ordinary background clipboard reads. ClipMesh uses the optional Accessibility service as the event-driven clipboard signal and Shizuku for privileged background clipboard access where required by Android/OEM behavior.

With **Background sync** enabled, copying text or an image on Android should not require opening ClipMesh. Samsung/OEM battery controls can still stop applications placed in Restricted or deep-sleep modes, so ClipMesh should be allowed to run in the background.

## Android background receiving

Android requires a foreground service for reliable receiving after the visible UI closes. When **Receive files when the app is not opened** is enabled, ClipMesh shows one low-importance ongoing notification and restores the listener after boot or app replacement.

Unknown senders use a separate high-priority Accept/Reject notification when ClipMesh is not visible. Android/OEM battery controls can still override applications placed in Restricted or deep-sleep modes.

## macOS Finder Share

ClipMesh includes a `com.apple.share-services` extension and refreshes its registration when the app opens. macOS controls whether it is shown directly under Finder -> right-click -> Share. If it is hidden, enable ClipMesh in System Settings -> General -> Login Items & Extensions -> Sharing.

The GitHub DMG is currently ad-hoc signed rather than Developer-ID notarized, so macOS may require a one-time approval under Privacy & Security. The release workflow supports a stable Developer ID certificate and optional notarization once the documented GitHub secrets are configured; it reports the ad-hoc mode explicitly until then.

## Android installation

The `v0.2.9-alpha` GitHub APK was debug-signed. Existing GitHub `v0.2.9-alpha` Android users must:

1. Uninstall v0.2.9 once.
2. Install `v0.2.10-alpha`.
3. Pair devices again if uninstalling removed the app data.

`v0.2.10-alpha` to future versions will update normally as long as the permanent release key is retained. The release workflow no longer publishes debug-signed APKs. Sideloading can still trigger Play Protect or Samsung's **Install anyway** flow; avoiding that distribution warning also requires recognized store distribution and is separate from ClipMesh runtime behavior.

## Security model

- Clipboard mesh: paired-space, end-to-end encrypted synchronization.
- Nearby file transfer: direct ClipMesh-only LAN discovery and HTTP transfer on port `53421`.
- Favorites authorize automatic incoming file acceptance only; they do not grant clipboard-space access.
- The current nearby-file transport is plain HTTP on the local network. Do not use it to transmit clipboard pairing secrets.
