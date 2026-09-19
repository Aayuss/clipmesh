#!/usr/bin/env python3
"""Static invariants for v053 final reconstructed platform sources."""

from __future__ import annotations

import os
import platform
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"v053 missing final reconstructed source: {path}")
    return path.read_text(encoding="utf-8")


def require(text: str, *needles: str) -> None:
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"v053 guard missing: {needle}")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    bridge = read(java / "clipboard/ClipboardBridge.kt")
    runtime = read(java / "BackgroundRuntime.kt")
    manager = read(java / "shizuku/ShizukuManager.kt")
    service = read(java / "shizuku/ClipboardUserService.kt")
    network = read(java / "network/NetworkEngine.kt")
    network_test = read(PROJECT / "android/app/src/test/java/dev/clipmesh/network/PeerOutgoingQueueTest.kt")
    transfer = read(java / "fileshare/LocalTransferEngine.kt")
    notifications = read(java / "fileshare/TransferNotifications.kt")
    activity = read(java / "fileshare/FileShareActivity.kt")
    boot = read(java / "BootReceiver.kt")

    require(
        bridge,
        "private val clipboardCapturePending = AtomicBoolean(false)",
        "private val screenshotProbePending = AtomicBoolean(false)",
        "private val captureInFlight = AtomicBoolean(false)",
        "const val EDGE_COALESCE_MS = 60L",
        "signalSecondaryClipboardEvent()",
        "if (privilegedListenerRegistered == true) return",
        "copyScreenshotCandidate(candidate, attempt = 0)",
        "copyScreenshotCandidate(candidate, attempt + 1)",
    )
    screenshot_handler = bridge[bridge.index("private fun signalScreenshotProbe"):bridge.index("private fun signalClipboardEvent")]
    if "readCurrent(" in screenshot_handler or "clipboardCapturePending.set" in screenshot_handler:
        raise SystemExit("v053 screenshot-only edge can request a clipboard snapshot")
    clipboard_worker = bridge[bridge.index("private fun captureClipboardSnapshot"):bridge.index("private fun recordObservedEvent")]
    if "latestScreenshot(" in clipboard_worker or "screenshotProbePending" in clipboard_worker:
        raise SystemExit("v053 clipboard-only capture can query screenshots")
    screenshot_copy = bridge[bridge.index("private fun probeLatestScreenshotIfDue"):bridge.index("private fun isPairingPayload")]
    if screenshot_copy.count("latestScreenshot()") != 1:
        raise SystemExit("v053 one coalesced screenshot edge must query exactly one candidate")
    if ".commit()" in bridge:
        raise SystemExit("v053 production ClipboardBridge still performs synchronous preference writes")
    require(bridge, "temp.length() <= 44L * 1024L * 1024L", "finally {\n                    temp.delete()")

    require(runtime, "bridge.setPrivilegedListenerRegistered(registered)")
    require(
        manager,
        "BIND_TIMEOUT_SECONDS = 8L",
        "BIND_RETRY_DELAYS_MS = longArrayOf(1_000L, 2_000L, 4_000L, 8_000L)",
        "armBindTimeout()",
        "scheduleBindingRetry()",
        "cancelBindTimers(resetAttempt = true)",
        "if (closed) {",
        "runCatching { connectionExecutor.execute {",
        "private val connection: ServiceConnection",
        "Detach in-process callbacks before any remote Binder cleanup can stall.",
        ".daemon(false)",
        ".version(12)",
    )
    require(service, "armProcessTimeout(process)", "process.destroyForcibly()", "processWatchdog.shutdownNow()")

    if "Channel.UNLIMITED" in network:
        raise SystemExit("v053 unbounded per-peer queue survived")
    require(
        network,
        "ConcurrentHashMap<UUID, PendingFrame>()",
        "controlCapacity: Int = 64",
        "Channel<ByteArray>(capacity = controlCapacity)",
        "Channel<ByteArray>(capacity = Channel.CONFLATED)",
        "suspend fun sendControl",
        "fun sendLatest",
        "pending.computeIfPresent(peerId)",
    )
    require(network_test, "repeat(100)", "delay(1L)", "assertEquals(99, latest)", "assertEquals((0 until 100).toList(), controls)")
    require(transfer, "data class IncomingProgress", "val failed: Boolean = false", "session.receivedBytes.addAndGet", "publishIncoming(session, meta.fileName, complete = true)", "publishIncoming(session, meta.fileName, failed = true)")
    require(notifications, "File receiving progress", "fun showReceiving", "fun showReceiveFailed", ".setProgress(100, percent, false)")
    require(activity, "setIncomingProgressListener(incomingProgressListener)", "value.failed", "Receiving ${value.fileName}")
    require(boot, "BackgroundService::class.java")
    if (java / "SyncService.kt").exists() or "SyncService" in boot:
        raise SystemExit("v053 obsolete undeclared SyncService survived")

elif SYSTEM == "Darwin":
    transfer = read(ROOT / "ci/ClipMeshTransfer.swift")
    app = read(ROOT / "ci/ClipMeshApp.swift")
    require(
        transfer,
        "var incomingProgress: ((String, String, Double, Bool) -> Void)?",
        "onProgress: @escaping (Int) -> Void",
        "publishIncomingProgress(session: session",
        "refreshDownloadsFolderRecency()",
        "let folder = TransferPrefs.outputFolder",
        ".modificationDate: Date()",
        "publishIncomingFailure(session: session",
        "percent - session.lastNotifiedPercent >= 10",
        "identifier: \"clipmesh-receive-",
    )
    recency = transfer[transfer.index("private func refreshDownloadsFolderRecency"):transfer.index("private func destinationURL")]
    if "copyItem(" in recency or "removeItem(" in recency or "contentsOfDirectory" in recency:
        raise SystemExit("macOS recency refresh must never copy/remove/enumerate files inside the receive folder")
    require(app, "showIncomingTransferProgress", "fraction < 0", "NSStatusItem.variableLength", "Receiving \\(file) from \\(sender)")

elif SYSTEM == "Windows":
    transfer = read(ROOT / "ci/ClipMeshTransfer.cs")
    app = read(ROOT / "ci/ClipMeshWindows.cs")
    require(
        transfer,
        "Action<string, string, int, bool> IncomingProgress",
        "Interlocked.Add(ref session.ReceivedBytes, read)",
        "Interlocked.Read(ref session.ReceivedBytes)",
        "PublishIncoming(session, meta.Name, true)",
    )
    require(
        app,
        "IncomingProgress = ShowIncomingTransferProgress",
        "CMTaskbarProgress.Set(Handle, value)",
        "tray.BalloonTipTitle = \"Receiving from \"",
        "transferStatus.Text = \"Receiving \"",
        "Downloads\\\\ClipMesh",
    )
else:
    raise SystemExit(f"Unsupported CLIPMESH_PLATFORM for v053 self-test: {SYSTEM}")

print(f"v053 second-pass runtime self-test passed on {SYSTEM}")
