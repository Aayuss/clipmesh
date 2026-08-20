from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_required(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Native wrappers and package metadata have their own version strings in addition
# to Cargo.toml. Keep all of them aligned so update/runtime paths are deterministic.
replace_required(root / "ci" / "ClipMeshWindows.cs", 'private const string Version = "0.1.3";', 'private const string Version = "0.1.4";', "Windows wrapper version")
replace_required(project / "scripts" / "build-macos.sh", '<key>CFBundleShortVersionString</key><string>0.1.3</string>', '<key>CFBundleShortVersionString</key><string>0.1.4</string>', "macOS short version")
replace_required(project / "scripts" / "build-macos.sh", '<key>CFBundleVersion</key><string>0.1.3</string>', '<key>CFBundleVersion</key><string>0.1.4</string>', "macOS bundle version")

android_gradle = project / "android" / "app" / "build.gradle.kts"
text = android_gradle.read_text(encoding="utf-8")
if 'versionCode = 3' in text:
    text = text.replace('versionCode = 3', 'versionCode = 4', 1)
if 'versionName = "0.1.3"' in text:
    text = text.replace('versionName = "0.1.3"', 'versionName = "0.1.4"', 1)
android_gradle.write_text(text, encoding="utf-8")

# Discovery proves that a trusted device is present on the LAN, but it does not prove
# that the encrypted TCP clipboard channel is established. Keep peer metadata from
# discovery while reserving last_seen_ms for a successful authenticated handshake.
desktop_config = project / "apps" / "desktop" / "src" / "config.rs"
replace_required(
    desktop_config,
    """        let now = now_ms();\n        let safe_name = peer_name(name, device_id);\n        if let Some(peer) = peers.iter_mut().find(|p| p.device_id == device_id) {\n            peer.name = safe_name;\n            peer.address = address.trim().chars().take(128).collect();\n            peer.port = port;\n            peer.last_seen_ms = now;\n        } else {\n            peers.push(KnownPeer {\n                device_id,\n                name: safe_name,\n                address: address.trim().chars().take(128).collect(),\n                port,\n                last_seen_ms: now,\n            });\n        }""",
    """        let safe_name = peer_name(name, device_id);\n        if let Some(peer) = peers.iter_mut().find(|p| p.device_id == device_id) {\n            peer.name = safe_name;\n            peer.address = address.trim().chars().take(128).collect();\n            peer.port = port;\n        } else {\n            peers.push(KnownPeer {\n                device_id,\n                name: safe_name,\n                address: address.trim().chars().take(128).collect(),\n                port,\n                last_seen_ms: 0,\n            });\n        }""",
    "desktop authenticated online-state semantics",
)

android_settings = project / "android" / "app" / "src" / "main" / "java" / "dev" / "clipmesh" / "SettingsStore.kt"
replace_required(
    android_settings,
    """        val now = System.currentTimeMillis()\n        val index = peers.indexOfFirst { it.deviceId == deviceId }\n        val peer = KnownPeer(deviceId, safeName, safeAddress, port.coerceIn(0, 65535), now)\n        if (index >= 0) peers[index] = peer else peers += peer""",
    """        val index = peers.indexOfFirst { it.deviceId == deviceId }\n        if (index >= 0) {\n            val old = peers[index]\n            peers[index] = old.copy(name = safeName, address = safeAddress, port = port.coerceIn(0, 65535))\n        } else {\n            peers += KnownPeer(deviceId, safeName, safeAddress, port.coerceIn(0, 65535), 0L)\n        }""",
    "Android authenticated online-state semantics",
)

# Only the single deterministic encrypted channel is allowed to mark a peer Online.
# A duplicate simultaneous connection may complete the cryptographic hello before it
# is rejected; touching lastSeen before that rejection made the UI misleading.
desktop_network = project / "apps" / "desktop" / "src" / "network.rs"
replace_required(
    desktop_network,
    """    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());\n    let preferred_outgoing = cfg.device_id.as_bytes() < peer_id.as_bytes();\n    if outgoing != preferred_outgoing {\n        debug!(peer=%peer_id,addr=%peer_addr,\"closing non-preferred duplicate connection\");\n        return Ok(());\n    }\n    info!(peer=%peer_id,addr=%peer_addr,\"peer authenticated\");""",
    """    let preferred_outgoing = cfg.device_id.as_bytes() < peer_id.as_bytes();\n    if outgoing != preferred_outgoing {\n        debug!(peer=%peer_id,addr=%peer_addr,\"closing non-preferred duplicate connection\");\n        return Ok(());\n    }\n    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());\n    info!(peer=%peer_id,addr=%peer_addr,\"peer authenticated\");""",
    "desktop preferred-channel online marker",
)

android_network = project / "android" / "app" / "src" / "main" / "java" / "dev" / "clipmesh" / "network" / "NetworkEngine.kt"
replace_required(
    android_network,
    """            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())\n            val preferredOutgoing = shouldInitiate(settings.deviceId, peerId)\n            if (outgoing != preferredOutgoing) {\n                socket.close()\n                return@withContext\n            }\n\n            val connection = PeerConnection""",
    """            val preferredOutgoing = shouldInitiate(settings.deviceId, peerId)\n            if (outgoing != preferredOutgoing) {\n                socket.close()\n                return@withContext\n            }\n            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())\n\n            val connection = PeerConnection""",
    "Android preferred-channel online marker",
)

print("Aligned ClipMesh v0.1.4 package metadata and authenticated peer-status semantics")
