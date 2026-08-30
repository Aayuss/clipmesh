#!/usr/bin/env python3
from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if system == "Linux":
    share = project / "android/app/src/main/java/dev/clipmesh/fileshare/FileShareActivity.kt"
    text = share.read_text(encoding="utf-8")
    old = '''        val pairedNames = dev.clipmesh.SettingsStore(this).knownPeers().map { it.name.trim().lowercase() }.toSet()
        val devices = runCatching { LocalTransferEngine.nearbyDevices().filterNot { pairedNames.contains(it.alias.trim().lowercase()) } }.getOrDefault(emptyList())'''
    new = '''        // File Transfer trust/favorites are independent from encrypted clipboard pairing.
        // A clipboard-paired device must remain visible here as long as its live
        // LAN file receiver is discoverable.
        val devices = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())'''
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Android File Transfer paired-device visibility: expected one match, found {count}")
    share.write_text(text.replace(old, new, 1), encoding="utf-8")
    final = share.read_text(encoding="utf-8")
    if "LocalTransferEngine.nearbyDevices().filterNot" in final:
        raise SystemExit("Android File Transfer still filters clipboard-paired devices")
    if "val devices = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())" not in final:
        raise SystemExit("Android File Transfer live-device source missing")

elif system in ("Darwin", "Windows"):
    # Desktop File Transfer already uses the complete live LAN receiver list.
    pass
else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh file-transfer visibility repair on {system}")
