from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
ci = root / "ci"

copies = {
    ci / "config.rs.fixed": project / "apps/desktop/src/config.rs",
    ci / "main.rs.fixed": project / "apps/desktop/src/main.rs",
    ci / "SettingsStore.kt.fixed": project / "android/app/src/main/java/dev/clipmesh/SettingsStore.kt",
    ci / "Pairing.kt.fixed": project / "android/app/src/main/java/dev/clipmesh/Pairing.kt",
    ci / "MainActivity.kt.fixed": project / "android/app/src/main/java/dev/clipmesh/MainActivity.kt",
    ci / "SettingsActivity.kt.fixed": project / "android/app/src/main/java/dev/clipmesh/SettingsActivity.kt",
    ci / "styles.xml.fixed": project / "android/app/src/main/res/values/styles.xml",
    ci / "ic_clipmesh_notification.xml.fixed": project / "android/app/src/main/res/drawable/ic_clipmesh_notification.xml",
}

for source, target in copies.items():
    if not source.is_file():
        raise SystemExit(f"Missing feature source: {source}")
    if not target.parent.is_dir():
        raise SystemExit(f"Missing extracted target directory: {target.parent}")
    shutil.copyfile(source, target)


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Desktop: authenticated discovery already contains a signed peer name. Persist it
# locally so the native app windows can show known/online devices without adding a
# second discovery protocol or any cloud service.
desktop_network = project / "apps/desktop/src/network.rs"
replace_once(
    desktop_network,
    """                if packet.device_id==cfg.device_id || packet.verify(&master,cfg.space_id).is_err() || peers.contains_key(&packet.device_id) { continue; }\n                let target=SocketAddr::new(addr.ip(),packet.port);""",
    """                if packet.device_id==cfg.device_id || packet.verify(&master,cfg.space_id).is_err() { continue; }\n                let _=Config::remember_peer(cfg.space_id,packet.device_id,&packet.name,&addr.ip().to_string(),packet.port);\n                if peers.contains_key(&packet.device_id) { continue; }\n                let target=SocketAddr::new(addr.ip(),packet.port);""",
    "desktop discovery peer persistence",
)
replace_once(
    desktop_network,
    """    let peer_id=remote_hello.device_id;\n    info!(peer=%peer_id,addr=%peer_addr,\"peer authenticated\");""",
    """    let peer_id=remote_hello.device_id;\n    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());\n    info!(peer=%peer_id,addr=%peer_addr,\"peer authenticated\");""",
    "desktop authenticated peer persistence",
)

# Android: same approach, using the existing authenticated discovery packets and
# hello handshake. There is no extra polling or radio wake-up added here.
android_network = project / "android/app/src/main/java/dev/clipmesh/network/NetworkEngine.kt"
replace_once(
    android_network,
    """                    val d = runCatching { Crypto.verifyDiscovery(masterKey, requireNotNull(settings.spaceId), data) }.getOrNull() ?: continue\n                    if (d.deviceId == settings.deviceId || peers.containsKey(d.deviceId)) continue\n                    scope.launch { connect(packet.address, d.port) }""",
    """                    val d = runCatching { Crypto.verifyDiscovery(masterKey, requireNotNull(settings.spaceId), data) }.getOrNull() ?: continue\n                    if (d.deviceId == settings.deviceId) continue\n                    settings.rememberPeer(d.deviceId, d.name, packet.address.hostAddress.orEmpty(), d.port)\n                    if (peers.containsKey(d.deviceId)) continue\n                    scope.launch { connect(packet.address, d.port) }""",
    "Android discovery peer persistence",
)
replace_once(
    android_network,
    """            val peerId = Crypto.verifyHello(masterKey, requireNotNull(settings.spaceId), remoteHello)\n            if (peerId == settings.deviceId) throw IllegalStateException(\"self connection\")\n\n            val connection = PeerConnection""",
    """            val peerId = Crypto.verifyHello(masterKey, requireNotNull(settings.spaceId), remoteHello)\n            if (peerId == settings.deviceId) throw IllegalStateException(\"self connection\")\n            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())\n\n            val connection = PeerConnection""",
    "Android authenticated peer persistence",
)

# Keep the Android foreground notification visually identical to the macOS/Windows
# background icon: only the two-way arrow is used, not the large product artwork.
sync_service = project / "android/app/src/main/java/dev/clipmesh/SyncService.kt"
replace_once(
    sync_service,
    "            .setLargeIcon(android.graphics.BitmapFactory.decodeResource(resources, R.drawable.app_icon))\n",
    "",
    "Android notification large icon removal",
)

manifest = project / "android/app/src/main/AndroidManifest.xml"
replace_once(
    manifest,
    """        </activity>\n\n        <service\n            android:name=\".SyncService\"""",
    """        </activity>\n\n        <activity\n            android:name=\".SettingsActivity\"\n            android:exported=\"false\" />\n\n        <service\n            android:name=\".SyncService\"""",
    "Android SettingsActivity manifest registration",
)

# The macOS wrapper is generated directly from this tracked source. Keep first
# launch quiet until initialization has completed, then refresh when the user
# reopens the window from the menu bar/Dock. The closure form is compatible with
# all Swift versions used by the macOS GitHub runner.
mac_wrapper = ci / "ClipMeshApp.swift"
replace_once(
    mac_wrapper,
    "for line in output.split(whereSeparator: \\ .isNewline) {",
    "for line in output.split(whereSeparator: { $0.isNewline }) {",
    "macOS UI-state line splitting",
)
replace_once(
    mac_wrapper,
    """    private func showWindow() {\n        NSApp.setActivationPolicy(.regular)\n        window?.makeKeyAndOrderFront(nil)\n        NSApp.activate(ignoringOtherApps: true)\n        if window != nil { refreshHome() }\n    }""",
    """    private func showWindow() {\n        NSApp.setActivationPolicy(.regular)\n        window?.makeKeyAndOrderFront(nil)\n        NSApp.activate(ignoringOtherApps: true)\n        if latestState != nil { refreshHome() }\n    }""",
    "macOS avoid pre-initialization UI refresh",
)

print("Applied ClipMesh v0.1.3 cross-platform device UI, peer registry, pairing metadata, and clipboard inspection patches")
