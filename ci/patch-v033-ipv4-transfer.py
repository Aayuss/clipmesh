#!/usr/bin/env python3
"""ClipMesh v0.2.11: reliable macOS IPv4 LAN file receiving."""

from pathlib import Path
import os
import platform


root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} match(es) in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: Path, old: str, new: str, label: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} match(es) in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


if system == "Darwin":
    transfer = root / "ci/ClipMeshTransfer.swift"
    build = project / "scripts/build-macos.sh"
    replace_once(
        transfer,
        '''        do {
            let listener = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: Self.port)!)
''',
        '''        do {
            // File sharing is discovered over IPv4 multicast and Android LAN
            // clients connect to an IPv4 address.  On some macOS versions the
            // default Network.framework listener presents as IPv6-only and
            // never acknowledges those SYNs.  Pin this endpoint to IPv4.
            let parameters = NWParameters.tcp
            guard let ip = parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options else {
                throw NSError(domain: "ClipMesh", code: -1, userInfo: [NSLocalizedDescriptionKey: "Network.framework has no IP options"])
            }
            ip.version = .v4
            let listener = try NWListener(using: parameters, on: NWEndpoint.Port(rawValue: Self.port)!)
''',
        "macOS IPv4 file listener",
    )
    replace_once(
        build,
        '  <key>NSHighResolutionCapable</key><true/>',
        '''  <key>NSHighResolutionCapable</key><true/>
  <key>NSLocalNetworkUsageDescription</key><string>ClipMesh uses your local network to discover paired devices and transfer clipboard content and files between them.</string>''',
        "macOS local network privacy description",
    )
    replace_all(build, "0.2.10", "0.2.11", "macOS v0.2.11 version", expected=4)
elif system == "Linux":
    gradle = project / "android/app/build.gradle.kts"
    replace_once(gradle, "versionCode = 20", "versionCode = 21", "Android v0.2.11 versionCode")
    replace_once(gradle, 'versionName = "0.2.10"', 'versionName = "0.2.11"', "Android v0.2.11 versionName")
elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    replace_once(ui, 'private const string Version = "0.2.10";', 'private const string Version = "0.2.11";', "Windows v0.2.11 version")
else:
    raise SystemExit(f"unsupported platform: {system}")

cargo = project / "Cargo.toml"
replace_once(cargo, 'version = "0.2.10"', 'version = "0.2.11"', f"{system} Cargo package version")

print(f"Applied ClipMesh v0.2.11 IPv4 file-transfer patch on {system}")
