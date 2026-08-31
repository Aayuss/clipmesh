#!/usr/bin/env python3
"""Prevent delayed Android clipboard callbacks from echoing older remote burst items."""

from pathlib import Path
import os
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM != "Linux":
    print(f"Android remote suppression patch skipped on {SYSTEM}")
    raise SystemExit(0)

bridge = PROJECT / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
text = bridge.read_text(encoding="utf-8")

field = "    private val suppressedFingerprint = AtomicReference<String?>(null)\n"
if text.count(field) != 1:
    raise SystemExit(f"Android remote suppressor field: expected one match, found {text.count(field)}")

# The existing implementation intentionally exposes only set() and compareAndSet():
# - applyRemote() marks a fingerprint as remotely written;
# - the clipboard callback consumes that exact fingerprint;
# - a delayed cleanup also compareAndSet()s it away.
# Refuse to patch an unexpected source shape rather than accidentally changing semantics.
methods = re.findall(r"suppressedFingerprint\.([A-Za-z_][A-Za-z0-9_]*)\(", text)
unexpected = sorted(set(methods) - {"set", "compareAndSet"})
if unexpected:
    raise SystemExit(f"Android remote suppressor has unsupported calls: {unexpected}")
if methods.count("set") < 1 or methods.count("compareAndSet") < 2:
    raise SystemExit(f"Android remote suppressor call shape changed: {methods}")

text = text.replace(
    field,
    "    private val suppressedFingerprint = RecentRemoteFingerprintSuppressor()\n",
    1,
)

helper = r'''

/**
 * Tracks multiple recently-applied remote clipboard fingerprints until the
 * corresponding Android clipboard-change callback consumes them.
 *
 * A single AtomicReference is racy during rapid remote bursts: remote N+1 can
 * replace N before Android delivers N's callback, causing N to be mistaken for
 * a local copy and echoed back to the sender. Keeping each pending fingerprint
 * independently prevents that reorder/ping-pong race while retaining the same
 * set()/compareAndSet() contract used by ClipboardBridge.
 */
private class RecentRemoteFingerprintSuppressor(
    private val ttlMs: Long = 15_000L,
    private val maxEntries: Int = 64,
) {
    private val lock = Any()
    private val pendingUntil = LinkedHashMap<String, Long>()

    fun set(value: String?) {
        synchronized(lock) {
            val now = System.currentTimeMillis()
            pruneLocked(now)
            if (value == null) {
                pendingUntil.clear()
                return
            }
            // Refresh insertion order as well as expiry for a repeated value.
            pendingUntil.remove(value)
            pendingUntil[value] = now + ttlMs
            while (pendingUntil.size > maxEntries) {
                val oldest = pendingUntil.entries.iterator()
                if (!oldest.hasNext()) break
                oldest.next()
                oldest.remove()
            }
        }
    }

    fun compareAndSet(expected: String?, update: String?): Boolean {
        if (expected == null) return false
        synchronized(lock) {
            val now = System.currentTimeMillis()
            pruneLocked(now)
            if (!pendingUntil.containsKey(expected)) return false
            pendingUntil.remove(expected)
            if (update != null) pendingUntil[update] = now + ttlMs
            return true
        }
    }

    private fun pruneLocked(now: Long) {
        val iterator = pendingUntil.entries.iterator()
        while (iterator.hasNext()) {
            if (iterator.next().value <= now) iterator.remove()
        }
    }
}
'''

if "private class RecentRemoteFingerprintSuppressor" in text:
    raise SystemExit("Android recent remote suppressor already present before v041")
text = text.rstrip() + helper + "\n"
bridge.write_text(text, encoding="utf-8")

final = bridge.read_text(encoding="utf-8")
for needle in (
    "private val suppressedFingerprint = RecentRemoteFingerprintSuppressor()",
    "private class RecentRemoteFingerprintSuppressor",
    "pendingUntil.containsKey(expected)",
    "maxEntries: Int = 64",
):
    if needle not in final:
        raise SystemExit(f"Android remote suppression guard missing: {needle}")
if "private val suppressedFingerprint = AtomicReference<String?>(null)" in final:
    raise SystemExit("Android one-slot remote suppression remained after v041")

print("Applied Android rapid-burst remote clipboard echo suppression")
