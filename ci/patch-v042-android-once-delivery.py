#!/usr/bin/env python3
"""Make Android remote clipboard delivery idempotent by transport message ID."""

from pathlib import Path
import os
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM != "Linux":
    print(f"Android once-delivery patch skipped on {SYSTEM}")
    raise SystemExit(0)

settings = PROJECT / "android/app/src/main/java/dev/clipmesh/SettingsStore.kt"
network = PROJECT / "android/app/src/main/java/dev/clipmesh/network/NetworkEngine.kt"
bridge = PROJECT / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"

# ---------------------------------------------------------------------------
# Durable transport-message ledger.
#
# NetworkEngine already ACKs every CLIPBOARD frame and keeps an in-memory `seen`
# map keyed by frame.messageId. That map is intentionally pruned, so an outbox
# retry that survives longer than the in-memory TTL can look new again. Persist a
# bounded recent ledger in the existing settings store so the same sender/message
# pair cannot rewrite Android's clipboard after the TTL or a runtime restart.
# ---------------------------------------------------------------------------
settings_text = settings.read_text(encoding="utf-8")
anchor = "    companion object {\n"
if settings_text.count(anchor) != 1:
    raise SystemExit(
        f"Android SettingsStore companion anchor: expected one match, found {settings_text.count(anchor)}"
    )

ledger = r'''    @Synchronized
    fun markClipboardMessageDelivered(peerId: UUID, messageId: UUID): Boolean {
        val key = "${peerId}|${messageId}"
        val entries = prefs.getString(DELIVERED_CLIPBOARD_MESSAGES_KEY, "")
            .orEmpty()
            .lineSequence()
            .filter { it.isNotBlank() }
            .toMutableList()
        if (entries.contains(key)) return false

        entries += key
        // A sender whose ACK was lost only needs its recent outstanding IDs to
        // remain remembered. Keep the ledger bounded so clipboard use cannot
        // grow SharedPreferences forever while still spanning far more messages
        // than the transport can reasonably leave pending.
        val bounded = entries.takeLast(MAX_DELIVERED_CLIPBOARD_MESSAGES)
        prefs.edit()
            .putString(DELIVERED_CLIPBOARD_MESSAGES_KEY, bounded.joinToString("\n"))
            .commit()
        return true
    }

'''
settings_text = settings_text.replace(anchor, ledger + anchor, 1)

const_anchor = "    companion object {\n"
const_replacement = '''    companion object {
        private const val DELIVERED_CLIPBOARD_MESSAGES_KEY = "delivered_clipboard_messages_v1"
        private const val MAX_DELIVERED_CLIPBOARD_MESSAGES = 2048
'''
if settings_text.count(const_anchor) != 1:
    raise SystemExit("Android SettingsStore companion anchor changed after ledger insertion")
settings_text = settings_text.replace(const_anchor, const_replacement, 1)
settings.write_text(settings_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Extend the existing message-ID gate instead of deduplicating clipboard bytes.
#
# The existing receive path has the correct ordering: determine whether the
# message ID is new, send ACK regardless, then skip payload application for a
# duplicate. Keep that ACK behavior intact and make "new" require both the
# in-memory seen-map check and the durable sender/message ledger.
# ---------------------------------------------------------------------------
network_text = network.read_text(encoding="utf-8")
pattern = re.compile(
    r'(?m)^(?P<indent>[ \t]*)val[ \t]+(?P<flag>[A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*'
    r'seen\.putIfAbsent\(frame\.messageId,[ \t]*System\.currentTimeMillis\(\)\)[ \t]*==[ \t]*null[ \t]*$'
)
match = pattern.search(network_text)
if match is None:
    raise SystemExit("Android CLIPBOARD seen/messageId gate was not found")
if pattern.search(network_text, match.end()) is not None:
    raise SystemExit("Android CLIPBOARD seen/messageId gate was unexpectedly ambiguous")

indent = match.group("indent")
flag = match.group("flag")
replacement = (
    f"{indent}val {flag} = seen.putIfAbsent(frame.messageId, System.currentTimeMillis()) == null &&\n"
    f"{indent}    settings.markClipboardMessageDelivered(peerId, frame.messageId)"
)
network_text = network_text[:match.start()] + replacement + network_text[match.end():]

# Refuse to alter a transport shape where duplicate frames would stop being ACKed.
# The ACK construction/send must remain before the branch that skips a duplicate.
gate_at = network_text.index("settings.markClipboardMessageDelivered(peerId, frame.messageId)")
window = network_text[gate_at:gate_at + 2600]
skip_match = re.search(
    rf'if\s*\(\s*!\s*{re.escape(flag)}\s*\)\s*(?:\{{\s*)?continue',
    window,
    flags=re.S,
)
if skip_match is None:
    raise SystemExit(f"Android duplicate-skip branch for {flag} was not found after durable gate")
ack_at = window.find("ACK")
if ack_at < 0 or ack_at > skip_match.start():
    raise SystemExit("Android ACK is no longer sent before duplicate CLIPBOARD frames are skipped")

network.write_text(network_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Remove the older content-fingerprint time gate. Once transport message IDs are
# durable, suppressing by bytes is incorrect: a user must be able to intentionally
# copy the exact same text/image again and have that new event (new messageId)
# arrive normally. v041's RecentRemoteFingerprintSuppressor remains in place only
# to consume Android callbacks caused by the remote write and prevent echo loops.
# ---------------------------------------------------------------------------
bridge_text = bridge.read_text(encoding="utf-8")
old_fields = '''    private val lastRemoteFingerprint = AtomicReference<String?>(null)
    @Volatile private var lastRemoteAppliedAt = 0L
'''
if bridge_text.count(old_fields) != 1:
    raise SystemExit(
        f"Android legacy content-dedupe fields: expected one match, found {bridge_text.count(old_fields)}"
    )
bridge_text = bridge_text.replace(old_fields, "", 1)

old_gate = '''        val remoteFingerprint = payload.stableFingerprint()
        val now = System.currentTimeMillis()
        // Retries and reconnect outbox delivery must ACK at the network layer but
        // must never rewrite Android's clipboard (or trigger SystemUI) repeatedly.
        if (lastRemoteFingerprint.get() == remoteFingerprint && now - lastRemoteAppliedAt < 30_000L) return
        lastRemoteFingerprint.set(remoteFingerprint)
        lastRemoteAppliedAt = now
        suppressedFingerprint.set(remoteFingerprint)
'''
new_gate = '''        val remoteFingerprint = payload.stableFingerprint()
        suppressedFingerprint.set(remoteFingerprint)
'''
if bridge_text.count(old_gate) != 1:
    raise SystemExit(
        f"Android legacy content-dedupe gate: expected one match, found {bridge_text.count(old_gate)}"
    )
bridge_text = bridge_text.replace(old_gate, new_gate, 1)
bridge.write_text(bridge_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Reconstruction-time semantic guards.
# ---------------------------------------------------------------------------
final_settings = settings.read_text(encoding="utf-8")
for needle in (
    'fun markClipboardMessageDelivered(peerId: UUID, messageId: UUID): Boolean',
    'val key = "${peerId}|${messageId}"',
    'DELIVERED_CLIPBOARD_MESSAGES_KEY = "delivered_clipboard_messages_v1"',
    'MAX_DELIVERED_CLIPBOARD_MESSAGES = 2048',
    '.takeLast(MAX_DELIVERED_CLIPBOARD_MESSAGES)',
    '.commit()',
):
    if needle not in final_settings:
        raise SystemExit(f"Android durable message ledger guard missing: {needle}")

final_network = network.read_text(encoding="utf-8")
for needle in (
    'seen.putIfAbsent(frame.messageId, System.currentTimeMillis()) == null &&',
    'settings.markClipboardMessageDelivered(peerId, frame.messageId)',
):
    if needle not in final_network:
        raise SystemExit(f"Android message-level once-delivery guard missing: {needle}")

final_bridge = bridge.read_text(encoding="utf-8")
for forbidden in (
    'lastRemoteFingerprint',
    'lastRemoteAppliedAt',
    'last_remote_fingerprint',
    'clipmesh_remote_dedupe',
):
    if forbidden in final_bridge:
        raise SystemExit(f"Android content-level once-delivery suppression remained: {forbidden}")
for required in (
    'private val suppressedFingerprint = RecentRemoteFingerprintSuppressor()',
    'val remoteFingerprint = payload.stableFingerprint()',
    'suppressedFingerprint.set(remoteFingerprint)',
):
    if required not in final_bridge:
        raise SystemExit(f"Android echo-suppression guard missing after v042: {required}")

print(
    "Applied Android once-per-transport-message clipboard delivery: durable sender/message IDs, "
    "ACK-preserving duplicate handling, and same-content new-event support"
)
