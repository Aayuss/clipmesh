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
# Extend the EXISTING receive duplicate-skip, after its ACK.
#
# We intentionally do not rewrite the source expression that computes the
# in-memory "is new" flag. Its exact formatting has changed across reconstructed
# versions, but the protocol invariant is stable: CLIPBOARD branch -> messageId
# putIfAbsent -> ACK -> `if (!isNew) continue` -> payload application.
#
# By adding the durable ledger to that existing skip condition:
# - in-memory duplicates are still ACKed and skipped exactly as before;
# - a retry after the in-memory TTL/restart is ACKed, then rejected by the ledger;
# - a genuinely new copy of identical bytes has a new messageId and is accepted.
# ---------------------------------------------------------------------------
network_text = network.read_text(encoding="utf-8")


def matching_brace(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        ch = text[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return index
    raise SystemExit("Android CLIPBOARD branch closing brace was not found")


branch_candidates = []
for branch_match in re.finditer(r"\bCLIPBOARD\b\s*->\s*\{", network_text):
    open_index = network_text.find("{", branch_match.start(), branch_match.end())
    close_index = matching_brace(network_text, open_index)
    branch = network_text[branch_match.start():close_index + 1]
    msg_match = re.search(
        r"\.putIfAbsent\(\s*(?P<frame>[A-Za-z_][A-Za-z0-9_]*)\.messageId\b",
        branch,
    )
    if msg_match is not None and re.search(r"\bACK\b", branch):
        branch_candidates.append((branch_match.start(), close_index + 1, branch, msg_match))

if len(branch_candidates) != 1:
    hints = []
    for match in re.finditer(r"putIfAbsent", network_text):
        start = max(0, match.start() - 220)
        end = min(len(network_text), match.end() + 420)
        hints.append(network_text[start:end].replace("\n", "\\n"))
    raise SystemExit(
        "Android CLIPBOARD messageId branch: expected one candidate, found "
        f"{len(branch_candidates)}; putIfAbsent snippets={hints[:4]}"
    )

branch_start, branch_end, branch, msg_match = branch_candidates[0]
frame_var = msg_match.group("frame")
ack_match = re.search(r"\bACK\b", branch)
if ack_match is None:
    raise SystemExit("Android CLIPBOARD ACK marker disappeared")

# Find the existing duplicate continue AFTER ACK. Replace only its boolean
# condition, preserving braces/formatting and therefore preserving ACK ordering.
after_ack = branch[ack_match.end():]
skip_pattern = re.compile(
    r"if\s*\(\s*(?P<cond>!\s*(?P<flag>[A-Za-z_][A-Za-z0-9_]*))\s*\)"
    r"\s*(?:\{\s*)?continue\b",
    flags=re.S,
)
skip_match = skip_pattern.search(after_ack)
if skip_match is None:
    raise SystemExit(
        "Android CLIPBOARD duplicate continue after ACK was not found; branch="
        + branch[:2600].replace("\n", "\\n")
    )

flag = skip_match.group("flag")
cond_rel_start = ack_match.end() + skip_match.start("cond")
cond_rel_end = ack_match.end() + skip_match.end("cond")
cond_abs_start = branch_start + cond_rel_start
cond_abs_end = branch_start + cond_rel_end
new_condition = (
    f"!{flag} || !settings.markClipboardMessageDelivered(peerId, {frame_var}.messageId)"
)
network_text = network_text[:cond_abs_start] + new_condition + network_text[cond_abs_end:]
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
final_branch_match = re.search(r"\bCLIPBOARD\b\s*->\s*\{", final_network)
if final_branch_match is None:
    raise SystemExit("Android final CLIPBOARD branch guard missing")
final_branch_open = final_network.find("{", final_branch_match.start(), final_branch_match.end())
final_branch_close = matching_brace(final_network, final_branch_open)
final_branch = final_network[final_branch_match.start():final_branch_close + 1]
for needle in (
    ".putIfAbsent(",
    ".messageId",
    "ACK",
    "settings.markClipboardMessageDelivered(peerId,",
):
    if needle not in final_branch:
        raise SystemExit(f"Android message-level once-delivery guard missing: {needle}")
ack_pos = final_branch.find("ACK")
durable_pos = final_branch.find("settings.markClipboardMessageDelivered(peerId,")
if ack_pos < 0 or durable_pos < 0 or ack_pos > durable_pos:
    raise SystemExit("Android duplicate ledger moved before ACK - refusing unsafe transport semantics")

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
