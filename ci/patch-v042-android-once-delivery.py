#!/usr/bin/env python3
# Make repeated delivery of the same remote Android clipboard payload idempotent.

from pathlib import Path
import os
import platform

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM != "Linux":
    print(f"Android once-delivery patch skipped on {SYSTEM}")
    raise SystemExit(0)

bridge = PROJECT / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
text = bridge.read_text(encoding="utf-8")

old_fields = '''    private val lastRemoteFingerprint = AtomicReference<String?>(null)
    @Volatile private var lastRemoteAppliedAt = 0L
'''
new_fields = '''    private val remoteDedupePrefs =
        context.getSharedPreferences("clipmesh_remote_dedupe", Context.MODE_PRIVATE)
    private val lastRemoteFingerprint = AtomicReference(
        remoteDedupePrefs.getString("last_remote_fingerprint", null)
    )
    @Volatile private var lastRemoteAppliedAt = 0L
'''
if text.count(old_fields) != 1:
    raise SystemExit(
        f"Android durable remote dedupe fields: expected one match, found {text.count(old_fields)}"
    )
text = text.replace(old_fields, new_fields, 1)

old_gate = '''        val remoteFingerprint = payload.stableFingerprint()
        val now = System.currentTimeMillis()
        // Retries and reconnect outbox delivery must ACK at the network layer but
        // must never rewrite Android's clipboard (or trigger SystemUI) repeatedly.
        if (lastRemoteFingerprint.get() == remoteFingerprint && now - lastRemoteAppliedAt < 30_000L) return
        lastRemoteFingerprint.set(remoteFingerprint)
        lastRemoteAppliedAt = now
'''
new_gate = '''        val remoteFingerprint = payload.stableFingerprint()
        // Transport retries/reconnects may legally re-deliver the newest frame.
        // Never apply identical remote clipboard bytes more than once. Persisting
        // the fingerprint also prevents an app/runtime restart from replaying the
        // same old Mac clipboard and causing another Android "Copied" toast.
        if (lastRemoteFingerprint.get() == remoteFingerprint) return
        val now = System.currentTimeMillis()
        lastRemoteFingerprint.set(remoteFingerprint)
        lastRemoteAppliedAt = now
        remoteDedupePrefs.edit()
            .putString("last_remote_fingerprint", remoteFingerprint)
            .apply()
'''
if text.count(old_gate) != 1:
    raise SystemExit(
        f"Android durable remote dedupe gate: expected one match, found {text.count(old_gate)}"
    )
text = text.replace(old_gate, new_gate, 1)

bridge.write_text(text, encoding="utf-8")

final = bridge.read_text(encoding="utf-8")
for needle in (
    'getSharedPreferences("clipmesh_remote_dedupe", Context.MODE_PRIVATE)',
    'remoteDedupePrefs.getString("last_remote_fingerprint", null)',
    'if (lastRemoteFingerprint.get() == remoteFingerprint) return',
    '.putString("last_remote_fingerprint", remoteFingerprint)',
):
    if needle not in final:
        raise SystemExit(f"Android durable remote dedupe guard missing: {needle}")
if "now - lastRemoteAppliedAt < 30_000L" in final:
    raise SystemExit("Android 30-second remote dedupe expiry remained after v042")

print("Applied durable Android once-per-clipboard remote delivery suppression")
