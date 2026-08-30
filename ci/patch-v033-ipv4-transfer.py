#!/usr/bin/env python3
"""ClipMesh v0.2.11: reliable macOS IPv4 LAN file receiving."""

from pathlib import Path
import os
import platform
import runpy


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

    # The original LocalTransferManager used one serial DispatchQueue for:
    #   - an infinite blocking multicast recvfrom() loop,
    #   - Network.framework HTTP callbacks,
    #   - outgoing file sends,
    #   - discovery announcements.
    # Once recvfrom() occupied that queue, TCP could be accepted by the kernel
    # while /prepare-upload and /upload callbacks never ran. Keep blocking
    # discovery isolated from HTTP and sending work.
    replace_once(
        transfer,
        '    private let queue = DispatchQueue(label: "dev.clipmesh.fileshare", qos: .utility)\n',
        '''    private let httpQueue = DispatchQueue(label: "dev.clipmesh.fileshare.http", qos: .utility)\n    private let discoveryQueue = DispatchQueue(label: "dev.clipmesh.fileshare.discovery", qos: .utility)\n    private let announceQueue = DispatchQueue(label: "dev.clipmesh.fileshare.announce", qos: .utility)\n    private let sendQueue = DispatchQueue(label: "dev.clipmesh.fileshare.send", qos: .utility)\n''',
        "macOS file-transfer queue separation",
    )
    replace_once(
        transfer,
        '''    func send(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, completion: @escaping (Result<Void, Error>) -> Void) {\n        queue.async {\n''',
        '''    func send(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, completion: @escaping (Result<Void, Error>) -> Void) {\n        sendQueue.async {\n''',
        "macOS outgoing transfer queue",
    )
    replace_once(
        transfer,
        '''    private func startDiscovery() {\n        queue.async {\n''',
        '''    private func startDiscovery() {\n        discoveryQueue.async {\n''',
        "macOS blocking discovery queue",
    )
    replace_once(
        transfer,
        '        let source = DispatchSource.makeTimerSource(queue: queue)\n',
        '        let source = DispatchSource.makeTimerSource(queue: announceQueue)\n',
        "macOS announcement queue",
    )
    replace_once(
        transfer,
        '    func discoverNow() { queue.async { [weak self] in guard let self else { return }; self.sendAnnouncement(announce:true);self.queue.asyncAfter(deadline:.now()+0.18){self.sendAnnouncement(announce:true)};self.queue.asyncAfter(deadline:.now()+0.36){self.sendAnnouncement(announce:true)} } }\n',
        '''    func discoverNow() {\n        announceQueue.async { [weak self] in\n            guard let self else { return }\n            self.sendAnnouncement(announce: true)\n            self.announceQueue.asyncAfter(deadline: .now() + 0.18) { [weak self] in self?.sendAnnouncement(announce: true) }\n            self.announceQueue.asyncAfter(deadline: .now() + 0.36) { [weak self] in self?.sendAnnouncement(announce: true) }\n        }\n    }\n''',
        "macOS immediate discovery queue",
    )

    # File sharing is discovered over IPv4 multicast and Android LAN clients
    # connect to an IPv4 address. Pin Network.framework to IPv4 explicitly.
    replace_once(
        transfer,
        '''        do {\n            let listener = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: Self.port)!)\n''',
        '''        do {\n            let parameters = NWParameters.tcp\n            guard let ip = parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options else {\n                throw NSError(domain: "ClipMesh", code: -1, userInfo: [NSLocalizedDescriptionKey: "Network.framework has no IP options"])\n            }\n            ip.version = .v4\n            let listener = try NWListener(using: parameters, on: NWEndpoint.Port(rawValue: Self.port)!)\n''',
        "macOS IPv4 file listener",
    )
    replace_once(
        transfer,
        '            listener.start(queue: queue)\n',
        '            listener.start(queue: httpQueue)\n',
        "macOS HTTP listener queue",
    )
    replace_once(
        transfer,
        '        connection.start(queue: queue)\n',
        '        connection.start(queue: httpQueue)\n',
        "macOS HTTP connection queue",
    )

    final_transfer = transfer.read_text(encoding="utf-8")
    required = (
        'private let httpQueue = DispatchQueue(label: "dev.clipmesh.fileshare.http"',
        'private let discoveryQueue = DispatchQueue(label: "dev.clipmesh.fileshare.discovery"',
        'private let announceQueue = DispatchQueue(label: "dev.clipmesh.fileshare.announce"',
        'private let sendQueue = DispatchQueue(label: "dev.clipmesh.fileshare.send"',
        'discoveryQueue.async {',
        'sendQueue.async {',
        'DispatchSource.makeTimerSource(queue: announceQueue)',
        'func discoverNow()',
        'announceQueue.async { [weak self] in',
        'self.announceQueue.asyncAfter',
        'listener.start(queue: httpQueue)',
        'connection.start(queue: httpQueue)',
        'ip.version = .v4',
    )
    for value in required:
        if value not in final_transfer:
            raise SystemExit(f"macOS v0.2.11 transfer guard missing after patch: {value}")
    forbidden = (
        'private let queue = DispatchQueue(label: "dev.clipmesh.fileshare"',
        'listener.start(queue: queue)',
        'connection.start(queue: queue)',
        'func discoverNow() { queue.async',
        'self.queue.asyncAfter',
    )
    for value in forbidden:
        if value in final_transfer:
            raise SystemExit(f"macOS v0.2.11 still contains starvation-prone shared queue reference: {value}")

    replace_once(
        build,
        '  <key>NSHighResolutionCapable</key><true/>',
        '''  <key>NSHighResolutionCapable</key><true/>\n  <key>NSLocalNetworkUsageDescription</key><string>ClipMesh uses your local network to discover paired devices and transfer clipboard content and files between them.</string>''',
        "macOS local network privacy description",
    )
    replace_all(build, "0.2.10", "0.2.11", "macOS v0.2.11 version", expected=4)
elif system == "Linux":
    gradle = project / "android/app/build.gradle.kts"
    replace_once(gradle, "versionCode = 20", "versionCode = 21", "Android v0.2.11 versionCode")
    replace_once(gradle, 'versionName = "0.2.10"', 'versionName = "0.2.11"', "Android v0.2.11 versionName")
    # build.yml still invokes the historical patch stack explicitly instead of
    # reconstruct.py. Chain the Android-only v034 repair here as well so release,
    # dev-latest, CI and the physical harness all compile identical source.
    runpy.run_path(str(root / "ci/patch-v034-shizuku-clipboard.py"), run_name="__main__")
elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    replace_once(ui, 'private const string Version = "0.2.10";', 'private const string Version = "0.2.11";', "Windows v0.2.11 version")
else:
    raise SystemExit(f"unsupported platform: {system}")

cargo = project / "Cargo.toml"
replace_once(cargo, 'version = "0.2.10"', 'version = "0.2.11"', f"{system} Cargo package version")

print(f"Applied ClipMesh v0.2.11 IPv4 + nonblocking file-transfer patch on {system}")
