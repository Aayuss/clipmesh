#!/usr/bin/env python3
"""Static guards for the final reconstructed Android clipboard runtime."""

from pathlib import Path
import os
import platform


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM != "Linux":
    print(f"v052 Android clipboard runtime self-test skipped on {SYSTEM}")
    raise SystemExit(0)

java = PROJECT / "android/app/src/main/java/dev/clipmesh"
aidl_dir = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku"

paths = {
    "runtime": java / "BackgroundRuntime.kt",
    "sync": java / "SyncService.kt",
    "bridge": java / "clipboard/ClipboardBridge.kt",
    "manager": java / "shizuku/ShizukuManager.kt",
    "service": java / "shizuku/ClipboardUserService.kt",
    "accessibility": java / "exclusion/ExclusionAccessibilityService.kt",
    "settings": java / "SettingsActivity.kt",
    "service_aidl": aidl_dir / "IClipboardUserService.aidl",
    "callback_aidl": aidl_dir / "IClipboardChangedCallback.aidl",
}

for label, path in paths.items():
    if not path.is_file():
        raise SystemExit(f"v052 missing final reconstructed {label}: {path}")

text = {label: path.read_text(encoding="utf-8") for label, path in paths.items()}

polling_scope = "\n".join(text[name] for name in ("runtime", "sync", "bridge", "manager"))
for forbidden in (
    "scheduleAtFixedRate",
    "scheduleWithFixedDelay",
    "ClipMesh-ClipboardWatch",
    "clipboardWatchdog",
    "clipboardMonitor",
    "shizukuMonitor",
    "captureNowForWatchdog",
    "captureNowForBackgroundMonitor",
    "delay(650L)",
    "delay(750L)",
    "latch.await",
    "ensureConnected",
):
    if forbidden in polling_scope:
        raise SystemExit(f"v052 forbidden recurring/blocking clipboard path survived: {forbidden}")

required = {
    "runtime": (
        "ShizukuManager.acquireRuntime(app)",
        "listenerRegistrationSucceeded == false",
        "settings.compatibilityWatchdog",
        "power.isInteractive",
        "(network?.peerCount() ?: 0) > 0",
        "captureNowForCompatibilityFallback",
        "ACTION_SCREEN_OFF",
        "@Synchronized fun captureAccessibility()",
        "reconcileClipboardFallback(resetBackoff = true)",
    ),
    "bridge": (
        "private val captureInFlight = AtomicBoolean(false)",
        "private val capturePending = AtomicBoolean(false)",
        "Thread(r, \"ClipMesh-ClipboardCapture\")",
        "shizuku.readSnapshotJson()",
        "if (!ClipMeshUiVisibility.isForeground()) return null",
        "suppressedFingerprint.compareAndSet(fp, null)",
        "lastObservedClipboardEvent.get() == eventKey",
        "registerContentObserver(",
        "captureLatestScreenshot(attempt + 1)",
    ),
    "manager": (
        ".daemon(false)",
        '.tag(if (testConnection) "clipmesh-clipboard-test-v2" else "clipmesh-clipboard-event-v2")',
        ".version(12)",
        "fun acquireRuntime(context: Context)",
        "fun forTest(context: Context)",
        "pendingClipboardCapture",
        "if (clipboardChangeListener != null) pendingClipboardCapture.set(true)",
        "if (pendingClipboardCapture.getAndSet(false)) clipboardChangeListener?.invoke()",
        "Shizuku.unbindUserService(args, connection, true)",
    ),
    "service": (
        "setClipboardChangedCallback",
        "isClipboardListenerRegistered",
        "addPrimaryClipChangedListener",
        "removePrimaryClipChangedListener",
        "listenerRegistrationSucceeded",
        "System.exit(0)",
    ),
    "service_aidl": (
        "void destroy() = 16777114;",
        "void setClipboardChangedCallback",
        "boolean isClipboardListenerRegistered()",
    ),
    "callback_aidl": (
        "oneway interface IClipboardChangedCallback",
        "void onClipboardChanged();",
    ),
}

for label, needles in required.items():
    for needle in needles:
        if needle not in text[label]:
            raise SystemExit(f"v052 {label} guard missing: {needle}")

if "primaryClip" in text["accessibility"] or "getPrimaryClip" in text["accessibility"]:
    raise SystemExit("v052 AccessibilityService still reads the normal app clipboard")

if "ShizukuManager(" in text["settings"]:
    raise SystemExit("v052 SettingsActivity still creates a UserService owner")

if "ShizukuManager(" in text["sync"] or "while (isActive)" in text["sync"]:
    raise SystemExit("v052 legacy SyncService still owns Shizuku or a recurring loop")

if "clipboard.primaryClip" not in text["bridge"]:
    raise SystemExit("v052 foreground-only normal clipboard fallback unexpectedly removed")
foreground_gate = text["bridge"].find("if (!ClipMeshUiVisibility.isForeground()) return null")
normal_read = text["bridge"].find("clipboard.primaryClip", foreground_gate)
if foreground_gate < 0 or normal_read < foreground_gate:
    raise SystemExit("v052 normal ClipboardManager read is not behind the foreground gate")

if "setClipboardChangedCallback(null)" not in text["manager"]:
    raise SystemExit("v052 close does not unregister the callback before removing UserService")

print("v052 Android event-driven clipboard/runtime self-test passed")
