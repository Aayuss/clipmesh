#!/usr/bin/env python3
"""Make Android remote clipboard delivery idempotent by transport message ID."""

from pathlib import Path
import os
import platform

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
# NetworkEngine already ACKs every CLIPBOARD frame and keeps an in-memory seen
# map keyed by messageId. That map is deliberately pruned, so a sender retry that
# survives longer than its TTL (or a receiver runtime restart) can otherwise look
# new and rewrite Android's clipboard. Persist a bounded sender/message ledger in
# the existing settings store so re-delivery stays idempotent across both cases.
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
        // Keep this bounded so normal clipboard use cannot grow preferences
        // forever. 4096 IDs spans vastly more deliveries than the sender should
        // ever retain pending while preserving restart/long-retry protection.
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
        private const val MAX_DELIVERED_CLIPBOARD_MESSAGES = 4096
'''
if settings_text.count(const_anchor) != 1:
    raise SystemExit("Android SettingsStore companion anchor changed after ledger insertion")
settings_text = settings_text.replace(const_anchor, const_replacement, 1)
settings.write_text(settings_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Extend the exact existing receive gate AFTER ACK.
#
# Current reconstructed source is:
#   duplicate = seen.putIfAbsent(messageId, now) != null
#   send ACK
#   if (!duplicate && receiveEnabled) apply payload
#
# Add the durable sender/message ledger between the duplicate check and the
# receive-enabled check. Kotlin && evaluates left-to-right, so duplicates never
# touch storage, every new message is durably recorded after its ACK is sent, and
# receive-disabled messages are still consumed rather than resurfacing later.
# A fresh copy of identical bytes has a fresh messageId and remains valid.
# ---------------------------------------------------------------------------
network_text = network.read_text(encoding="utf-8")
required_branch = '''                        Crypto.Kind.CLIPBOARD -> {
                            val duplicate = seen.putIfAbsent(frame.messageId, System.currentTimeMillis()) != null
                            val ack = Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.ACK, 0, settings.deviceId, frame.messageId, ByteArray(0))
                            connection.send(ack)
                            if (!duplicate && settings.receiveEnabled) {
                                runCatching { ClipPayload.fromJsonBytes(frame.plaintext) }.getOrNull()?.let(onRemoteClip)
                            }
                        }'''
replacement_branch = '''                        Crypto.Kind.CLIPBOARD -> {
                            val duplicate = seen.putIfAbsent(frame.messageId, System.currentTimeMillis()) != null
                            val ack = Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.ACK, 0, settings.deviceId, frame.messageId, ByteArray(0))
                            connection.send(ack)
                            if (!duplicate && settings.markClipboardMessageDelivered(peerId, frame.messageId) && settings.receiveEnabled) {
                                runCatching { ClipPayload.fromJsonBytes(frame.plaintext) }.getOrNull()?.let(onRemoteClip)
                            }
                        }'''
if network_text.count(required_branch) != 1:
    raise SystemExit(
        "Android exact CLIPBOARD receive branch changed; refusing to weaken once-delivery semantics"
    )
network_text = network_text.replace(required_branch, replacement_branch, 1)
network.write_text(network_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Remove the older CONTENT-fingerprint time gate.
#
# v041's RecentRemoteFingerprintSuppressor stays: it consumes Android callbacks
# caused by a remote write and prevents echo/ping-pong. What must go is v026's
# 30-second content gate, because two intentional copies of the same bytes are two
# distinct clipboard events and therefore two distinct transport message IDs.
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
    'MAX_DELIVERED_CLIPBOARD_MESSAGES = 4096',
    '.takeLast(MAX_DELIVERED_CLIPBOARD_MESSAGES)',
    '.commit()',
):
    if needle not in final_settings:
        raise SystemExit(f"Android durable message ledger guard missing: {needle}")

final_network = network.read_text(encoding="utf-8")
for needle in (
    'val duplicate = seen.putIfAbsent(frame.messageId, System.currentTimeMillis()) != null',
    'connection.send(ack)',
    'if (!duplicate && settings.markClipboardMessageDelivered(peerId, frame.messageId) && settings.receiveEnabled)',
):
    if needle not in final_network:
        raise SystemExit(f"Android message-level once-delivery guard missing: {needle}")
branch_start = final_network.index("Crypto.Kind.CLIPBOARD -> {")
branch_end = final_network.index("\n                        }", branch_start) + len("\n                        }")
final_branch = final_network[branch_start:branch_end]
ack_pos = final_branch.find("connection.send(ack)")
durable_pos = final_branch.find("settings.markClipboardMessageDelivered(peerId, frame.messageId)")
apply_pos = final_branch.find("onRemoteClip")
if ack_pos < 0 or durable_pos < 0 or apply_pos < 0 or not (ack_pos < durable_pos < apply_pos):
    raise SystemExit("Android ACK/durable/apply ordering guard failed")

final_bridge = bridge.read_text(encoding="utf-8")
for forbidden in (
    "lastRemoteFingerprint",
    "lastRemoteAppliedAt",
    "last_remote_fingerprint",
    "clipmesh_remote_dedupe",
):
    if forbidden in final_bridge:
        raise SystemExit(f"Android content-level once-delivery suppression remained: {forbidden}")
for required in (
    "private val suppressedFingerprint = RecentRemoteFingerprintSuppressor()",
    "val remoteFingerprint = payload.stableFingerprint()",
    "suppressedFingerprint.set(remoteFingerprint)",
):
    if required not in final_bridge:
        raise SystemExit(f"Android echo-suppression guard missing after v042: {required}")

print(
    "Applied Android once-per-transport-message clipboard delivery: durable sender/message IDs, "
    "ACK-preserving duplicate handling, and same-content new-event support"
)
