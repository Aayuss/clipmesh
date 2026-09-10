#!/usr/bin/env python3
"""Static invariants for the v054 resource-finalization layer."""

from __future__ import annotations

import os
import platform
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"v054 missing final reconstructed source: {path}")
    return path.read_text(encoding="utf-8")


def require(text: str, *needles: str) -> None:
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"v054 guard missing: {needle}")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    network = read(java / "network/NetworkEngine.kt")
    bridge = read(java / "clipboard/ClipboardBridge.kt")
    runtime = read(java / "BackgroundRuntime.kt")
    service = read(java / "shizuku/ClipboardUserService.kt")
    transfer = read(java / "fileshare/LocalTransferEngine.kt")
    diagnostics = read(java / "DebugResourceCounters.kt")
    receiver = read(PROJECT / "android/app/src/debug/java/dev/clipmesh/DevTestReceiver.kt")
    manifest = read(PROJECT / "android/app/src/debug/AndroidManifest.xml")
    retention_test = read(PROJECT / "android/app/src/test/java/dev/clipmesh/network/LatestFrameRetentionTest.kt")

    require(
        network,
        "private const val REPLAY_TTL_MS = 30_000L",
        "internal class LatestFrameRetention(",
        "expiry?.cancel()",
        "val expectedMessage = value.message",
        "expire(expectedGeneration, expectedMessage)",
        "generation == expectedGeneration && current?.message == expectedMessage",
        "latestFrame.clear()",
        "latestFrame.fresh()?.let",
        "private val retryJobs = ConcurrentHashMap<UUID, RetryTask>()",
        "private val retainedStateLock = Any()",
        "retryJobs.put(peerId, RetryTask(messageId, job))?.job?.cancel()",
        "retryJobs.remove(peerId)?.job?.cancel()",
    )
    if "@Volatile private var latestFrame" in network:
        raise SystemExit("v054 unbounded raw latestFrame reference survived")
    require(
        retention_test,
        "fun frameExpiresAtReplayTtl()",
        "scheduler.advanceBy(29_999L)",
        "fun staleExpiryCannotClearNewerFrame()",
        "assertEquals(b, retained.retainedMessageForTest())",
        "assertNull(retained.retainedMessageForTest())",
    )

    for counter in (
        "clipboard_edge_privileged_count",
        "clipboard_edge_secondary_count",
        "clipboard_snapshot_read_count",
        "clipboard_emit_count",
        "clipboard_duplicate_suppressed_count",
        "clipboard_remote_echo_suppressed_count",
        "screenshot_probe_count",
        "screenshot_emit_count",
    ):
        require(bridge, counter)
    require(
        diagnostics,
        "if (BuildConfig.DEBUG)",
        "multicast_lock_acquire_count",
        "multicast_lock_release_count",
        "multicast_lock_total_held_ms",
    )
    require(receiver, "ACTION_RESET_RESOURCE_COUNTERS", "DebugResourceCounters.snapshot()")
    require(manifest, "dev.clipmesh.devtest.RESET_RESOURCE_COUNTERS", "android.permission.DUMP")

    automatic_paths = bridge + "\n" + runtime + "\n" + service
    for forbidden in ("scheduleWithFixedDelay", "scheduleAtFixedRate", "java.util.Timer", "kotlin.concurrent.timer"):
        if forbidden in automatic_paths:
            raise SystemExit(f"v054 routine polling primitive survived: {forbidden}")
    require(
        runtime,
        "listenerRegistrationSucceeded == false",
        "settings.backgroundSync && settings.compatibilityWatchdog && settings.sendEnabled",
        "power.isInteractive && (network?.peerCount() ?: 0) > 0 && shizuku?.hasPermission() == true",
    )
    secondary = bridge[bridge.index("private fun signalSecondaryClipboardEvent"):bridge.index("private fun signalScreenshotProbe")]
    require(secondary, "if (privilegedListenerRegistered == true) return")
    if "readSnapshotJson" in secondary or "primaryClip" in secondary:
        raise SystemExit("v054 secondary edge performs a direct clipboard read")

    require(
        bridge,
        "finally {\n            temp.delete()",
        "temp.length() <= 44L * 1024L * 1024L",
        "openAssetFileDescriptor(uri, \"r\")",
        "runCatching { context.contentResolver.openAssetFileDescriptor(uri, \"r\") }",
        "ByteArray(knownLength.toInt())",
        "isDecodablePng(bytes)",
        "return bytes",
        "debugInjectedClip.set(null)",
        "runCatching {\n                    captureExecutor.schedule(",
        "if (isRemoteClip(clip)) {",
        "if (o.optBoolean(\"remote\", false)) {",
    )
    if "val hash = Crypto.hex(Crypto.sha256(bytes))" in bridge:
        raise SystemExit("v054 image path still computes an unused eager SHA-256")
    require(service, "lastClipUris: Map<Int, Uri> = emptyMap()", "lastClipUris = itemUris.toMap()")
    if "lastClip: ClipData" in service:
        raise SystemExit("v054 UserService still retains full ClipData")

    require(
        transfer,
        "setReferenceCounted(false)",
        "acquire()",
        "DebugResourceCounters.multicastLockAcquired()",
        "DebugResourceCounters.increment(\"multicast_packets_received_count\")",
        "DebugResourceCounters.increment(\"direct_register_count\")",
        "releaseMulticastLock()",
    )
    if "discovery window" in transfer.lower() or "release after" in transfer.lower():
        raise SystemExit("v054 must not introduce unproven multicast discovery windows")

elif SYSTEM == "Darwin":
    read(ROOT / "ci/ClipMeshTransfer.swift")
elif SYSTEM == "Windows":
    read(ROOT / "ci/ClipMeshTransfer.cs")
else:
    raise SystemExit(f"Unsupported CLIPMESH_PLATFORM for v054 self-test: {SYSTEM}")

print(f"v054 resource finalization self-test passed on {SYSTEM}")
