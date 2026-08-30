#!/usr/bin/env python3
"""Debug-only observability for the physical ClipMesh E2E harness."""

from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    bridge = java / "clipboard/ClipboardBridge.kt"

    replace_once(
        runtime,
        '''        val net = NetworkEngine(settings, key, { payload -> bridge.applyRemote(payload) }, { text -> status = text })\n''',
        '''        val net = NetworkEngine(settings, key, { payload ->\n            if (BuildConfig.DEBUG) {\n                app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()\n                    .putLong("last_remote_received_at", System.currentTimeMillis())\n                    .putString("last_remote_received_fingerprint", payload.stableFingerprint())\n                    .apply()\n            }\n            bridge.applyRemote(payload)\n        }, { text -> status = text })\n''',
        "record incoming clipboard frame",
    )

    replace_once(
        runtime,
        '''    fun captureNow() { clipboard?.captureNowForForeground() }\n''',
        '''    fun captureNow() { clipboard?.captureNowForForeground() }\n    fun debugPeerCount(): Int = network?.peerCount() ?: 0\n''',
        "debug clipboard peer count",
    )

    replace_once(
        bridge,
        '''        lastRemoteFingerprint.set(remoteFingerprint)\n        lastRemoteAppliedAt = now\n        suppressedFingerprint.set(remoteFingerprint)\n''',
        '''        lastRemoteFingerprint.set(remoteFingerprint)\n        lastRemoteAppliedAt = now\n        if (dev.clipmesh.BuildConfig.DEBUG) {\n            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()\n                .putLong("last_remote_apply_at", now)\n                .putString("last_remote_apply_fingerprint", remoteFingerprint)\n                .apply()\n        }\n        suppressedFingerprint.set(remoteFingerprint)\n''',
        "record remote clipboard apply",
    )

    replace_once(
        bridge,
        '''        if (plain != null && html == null && shizuku.hasPermission() && !settings.showRemoteCopyOverlay) {\n            val text = plain.data.toString(Charsets.UTF_8)\n            if (shizuku.setText(text)) return\n        }\n        main.post {\n''',
        '''        if (plain != null && html == null && shizuku.hasPermission() && !settings.showRemoteCopyOverlay) {\n            val text = plain.data.toString(Charsets.UTF_8)\n            val wrote = shizuku.setText(text)\n            if (dev.clipmesh.BuildConfig.DEBUG) {\n                context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()\n                    .putLong("last_remote_shizuku_write_at", System.currentTimeMillis())\n                    .putBoolean("last_remote_shizuku_write_ok", wrote)\n                    .apply()\n            }\n            if (wrote) return\n        }\n        if (dev.clipmesh.BuildConfig.DEBUG) {\n            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()\n                .putLong("last_remote_fallback_at", System.currentTimeMillis())\n                .apply()\n        }\n        main.post {\n''',
        "record remote clipboard write path",
    )

    final_runtime = runtime.read_text(encoding="utf-8")
    final_bridge = bridge.read_text(encoding="utf-8")
    for value in (
        'putLong("last_remote_received_at"',
        'fun debugPeerCount(): Int = network?.peerCount() ?: 0',
    ):
        if value not in final_runtime:
            raise SystemExit(f"runtime E2E observability guard missing: {value}")
    for value in (
        'putLong("last_remote_apply_at"',
        'putLong("last_remote_shizuku_write_at"',
        'putBoolean("last_remote_shizuku_write_ok", wrote)',
        'putLong("last_remote_fallback_at"',
    ):
        if value not in final_bridge:
            raise SystemExit(f"clipboard E2E observability guard missing: {value}")

print(f"Applied ClipMesh debug E2E observability on {system}")
