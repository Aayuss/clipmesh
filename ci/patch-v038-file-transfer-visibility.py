#!/usr/bin/env python3
from pathlib import Path
import os
import platform
import re

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_function(path: Path, start_pattern: str, end_pattern: str, transform, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    match = re.search(f"({start_pattern})(.*?)({end_pattern})", text, re.S)
    if not match:
        raise SystemExit(f"{label}: function block not found in {path}")
    body = match.group(2)
    new_body = transform(body)
    if new_body == body:
        raise SystemExit(f"{label}: expected paired-device filter was not found in function")
    path.write_text(text[:match.start(2)] + new_body + text[match.end(2):], encoding="utf-8")


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

elif system == "Darwin":
    app = root / "ci/ClipMeshApp.swift"

    def repair_mac(body: str) -> str:
        # v026 intentionally filters paired peers from Clipboard's AVAILABLE TO
        # PAIR list. The same broad rewrite accidentally reached File Transfer.
        # File Transfer is a separate trust/favorite surface and must expose every
        # live LAN receiver, including a device already paired for clipboard.
        patterns = (
            r'''\s*let pairedNames = Set\(\(latestState\?\.peers \?\? \[\]\)\.map \{ \$0\.name\.trimmingCharacters\(in: \.whitespacesAndNewlines\)\.lowercased\(\) \}\)\s*\n\s*let devices = LocalTransferManager\.shared\.nearbyDevices\(\)\.filter \{ !pairedNames\.contains\(\$0\.alias\.trimmingCharacters\(in: \.whitespacesAndNewlines\)\.lowercased\(\)\) \}''',
            r'''\s*let pairedNames=Set\(\(latestState\?\.peers \?\? \[\]\)\.map\{\$0\.name\.trimmingCharacters\(in:\.whitespacesAndNewlines\)\.lowercased\(\)\}\);let devices=LocalTransferManager\.shared\.nearbyDevices\(\)\.filter\{!pairedNames\.contains\(\$0\.alias\.trimmingCharacters\(in:\.whitespacesAndNewlines\)\.lowercased\(\)\)\}''',
        )
        for pattern in patterns:
            repaired, count = re.subn(pattern, '\n        let devices = LocalTransferManager.shared.nearbyDevices()', body, count=1)
            if count == 1:
                return repaired
        return body

    replace_function(
        app,
        r"private\s+func\s+refreshTransferDevices\s*\(\)\s*\{",
        r"\n\s*private\s+func\s+",
        repair_mac,
        "macOS File Transfer paired-device visibility",
    )
    final = app.read_text(encoding="utf-8")
    transfer = re.search(r"private\s+func\s+refreshTransferDevices\s*\(\)\s*\{(.*?)(?=\n\s*private\s+func\s+)", final, re.S)
    pairing = re.search(r"private\s+func\s+refreshNearbyPairDevices\s*\(\)\s*\{(.*?)(?=\n\s*private\s+func\s+)", final, re.S)
    if not transfer or "LocalTransferManager.shared.nearbyDevices()" not in transfer.group(1) or "pairedNames" in transfer.group(1):
        raise SystemExit("macOS File Transfer does not use the complete live LAN receiver list")
    if not pairing or "pairedNames" not in pairing.group(1):
        raise SystemExit("macOS Clipboard available-to-pair list lost its paired-device filter")

elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    text = ui.read_text(encoding="utf-8")
    match = re.search(r"private\s+void\s+RefreshTransferDevices\s*\(\)\s*\{(.*?)(?=\n\s*private\s+)", text, re.S)
    if not match:
        raise SystemExit("Windows RefreshTransferDevices function not found")
    body = match.group(1)
    # Some historical Windows generations never inherited the paired-name filter.
    # If it is present, remove it only from File Transfer. Clipboard pairing keeps
    # its own filtering semantics.
    repaired = re.sub(
        r'''(?:List<string>\s+pairedNames[^;]*;\s*)?List<TransferDeviceC>\s+devices\s*=\s*LocalTransferManagerC\.Shared\.Nearby\(\)\.Where\([^;]*\)\.ToList\(\);''',
        'List<TransferDeviceC> devices = LocalTransferManagerC.Shared.Nearby();',
        body,
        count=1,
    )
    if repaired != body:
        ui.write_text(text[:match.start(1)] + repaired + text[match.end(1):], encoding="utf-8")
    final = ui.read_text(encoding="utf-8")
    block = re.search(r"private\s+void\s+RefreshTransferDevices\s*\(\)\s*\{(.*?)(?=\n\s*private\s+)", final, re.S)
    if not block or "LocalTransferManagerC.Shared.Nearby()" not in block.group(1):
        raise SystemExit("Windows File Transfer live-device source missing")
else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh file-transfer visibility repair on {system}")
