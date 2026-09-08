#!/usr/bin/env python3
from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def require(path: Path, *needles: str) -> str:
    text = path.read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, f"missing {needle!r} in {path}"
    return text


if system == "Linux":
    java = root / "clipmesh/android/app/src/main/java/dev/clipmesh"
    runtime = require(java / "BackgroundRuntime.kt", "Clipboard capture is event-driven through the Shizuku UserService")
    assert "clipboardWatchdog" not in runtime
    assert "scheduleWithFixedDelay" not in runtime
    assert "650L" not in runtime

    sync = (java / "SyncService.kt").read_text(encoding="utf-8")
    assert "shizukuMonitor = scope.launch" not in sync
    assert "bridge.captureNowForBackgroundMonitor()" not in sync

    bridge = require(
        java / "clipboard/ClipboardBridge.kt",
        "shizuku.setEventListeners(",
        "clipboard = { captureAsync(fromWatchdog = true) }",
        "screenshot = { probeLatestScreenshotIfDue() }",
    )
    assert "Reuse the already-running interactive watchdog" not in bridge

    aidl = root / "clipmesh/android/app/src/main/aidl/dev/clipmesh/shizuku"
    require(aidl / "IClipboardChangeCallback.aidl", "onClipboardChanged", "onScreenshotChanged")
    require(aidl / "IClipboardUserService.aidl", "registerClipboardChangeCallback", "unregisterClipboardChangeCallback")
    require(
        java / "shizuku/ClipboardUserService.kt",
        "RemoteCallbackList<IClipboardChangeCallback>",
        "addPrimaryClipChangedListener",
        "registerContentObserver",
        "broadcastClipboardChanged",
        "broadcastScreenshotChanged",
    )
    require(java / "shizuku/ShizukuManager.kt", "setEventListeners", ".version(12)")

elif system == "Darwin":
    transfer = require(
        root / "ci/ClipMeshTransfer.swift",
        "URLSessionTaskDelegate",
        "didSendBodyData",
        "NSApp.dockTile.badgeLabel",
        "UNUserNotificationCenter",
        "CMTransferPresentation",
    )
    assert "while sem.wait(timeout: .now() + 0.1)" not in transfer
    assert "countOfBytesSent" not in transfer
    require(root / "clipmesh/scripts/build-macos.sh", "-framework UserNotifications")

elif system == "Windows":
    transfer = require(
        root / "ci/ClipMeshTransfer.cs",
        "ClipMeshTaskbarProgress",
        "SetProgressValue",
        "SetProgressState",
        "lastProgressValue",
        "value - lastProgressValue >= 5",
    )
    require(
        root / "ci/ClipMeshWindows.cs",
        "ShowTransferNotification",
        "ClipMeshTaskbarProgress.Set",
        "ClipMeshTaskbarProgress.Clear",
        "ShowBalloonTip",
    )
else:
    raise AssertionError(f"unsupported CLIPMESH_PLATFORM={system!r}")

print(f"v049 event-driven/performance self-test passed on {system}")
