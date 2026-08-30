#!/usr/bin/env python3
from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if system == "Darwin":
    transfer = (root / "ci/ClipMeshTransfer.swift").read_text(encoding="utf-8")
    build = (root / "clipmesh/scripts/build-macos.sh").read_text(encoding="utf-8")

    # IPv4 reachability.
    assert "ip.version = .v4" in transfer
    assert "NWListener(using: parameters" in transfer

    # Blocking multicast discovery must never share the HTTP callback queue.
    for required in (
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
    ):
        assert required in transfer, required

    for forbidden in (
        'private let queue = DispatchQueue(label: "dev.clipmesh.fileshare"',
        'listener.start(queue: queue)',
        'connection.start(queue: queue)',
        'func discoverNow() { queue.async',
        'self.queue.asyncAfter',
    ):
        assert forbidden not in transfer, forbidden

    assert "NSLocalNetworkUsageDescription" in build
    assert "CFBundleShortVersionString</key><string>0.2.11" in build
elif system == "Linux":
    gradle = (root / "clipmesh/android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert "versionCode = 21" in gradle
    assert 'versionName = "0.2.11"' in gradle
elif system == "Windows":
    ui = (root / "ci/ClipMeshWindows.cs").read_text(encoding="utf-8")
    assert 'private const string Version = "0.2.11";' in ui
else:
    raise AssertionError(f"unsupported platform: {system}")

cargo = (root / "clipmesh/Cargo.toml").read_text(encoding="utf-8")
assert 'version = "0.2.11"' in cargo
print(f"ClipMesh v0.2.11 IPv4/nonblocking transfer self-test passed on {system}")
