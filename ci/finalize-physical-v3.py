#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one regex match, found {count}")
    return out


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: finalize-physical-v3.py INPUT OUTPUT")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")

    # Physical DEV builds must not enumerate Apple signing identities or touch
    # the production ClipMesh Keychain/config state. v4 acceptance reconstruction
    # uses its own mode-0600 local secret backend. Start every run with a fresh,
    # isolated acceptance identity so there are no password dialogs or stale state.
    text = replace_once(
        text,
        '''section "COMPREHENSIVE ACCEPTANCE PREPARE"
echo "Git:     $(git -C "$ROOT" rev-parse HEAD)"
''',
        '''section "COMPREHENSIVE ACCEPTANCE PREPARE"
export CLIPMESH_CODESIGN_IDENTITY="-"
ACCEPTANCE_MAC_SUPPORT="$HOME/Library/Application Support/dev.ClipMesh.ClipMesh-Acceptance"
rm -rf "$ACCEPTANCE_MAC_SUPPORT" >/dev/null 2>&1 || true
echo "Mac DEV signing: ad-hoc (no Keychain signing identity lookup)"
echo "Mac DEV secrets: isolated acceptance-only store"
echo "Git:     $(git -C "$ROOT" rev-parse HEAD)"
''',
        "acceptance-only passwordless Mac state",
    )

    text = replace_once(
        text,
        '''mac_command(){ "$APP_EXE" --dev-accept-command "$1" >/dev/null 2>&1; sleep .12; }
''',
        '''mac_command(){ "$APP_EXE" --dev-accept-command "$1" >/dev/null 2>&1; rc=$?; [ "$rc" -eq 0 ] || return "$rc"; sleep .05; }
''',
        "Mac command ACK propagation",
    )

    # A reverse text test must start from a positively observed Android->Mac
    # barrier. This drains any prior Android local event and remote-suppression
    # state before macOS becomes the sender. It fixes the one open/open race and
    # makes the restart tests use the exact same deterministic edge.
    text = regex_once(
        text,
        r'''clipboard_m2a_text\(\)\{\n  a="\$1"; expected="\$2"\n  if \[ "\$a" = open \]; then\n    printf '%s' "\$expected" \| pbcopy\n    wait_android_open_text "\$expected"\n  else\n    start_driver wait_text "\$expected"; wait_driver READY_TEXT \|\| return 1\n    sleep \.25\n    printf '%s' "\$expected" \| pbcopy\n    wait_driver PASS_TEXT\n  fi\n\}''',
        r'''clipboard_m2a_text(){
  a="$1"; expected="$2"; reset="m2a-reset-$(nonce)"
  if [ "$a" = open ]; then
    acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$reset")" >/dev/null || return 1
    wait_mac_text "$reset" || return 1
    sleep .55
    printf '%s' "$expected" | pbcopy
    wait_android_open_text "$expected"
  else
    start_driver set_text "$reset"; wait_driver SET_TEXT || return 1
    wait_mac_text "$reset" || return 1
    sleep .55
    start_driver wait_text "$expected"; wait_driver READY_TEXT || return 1
    sleep .20
    printf '%s' "$expected" | pbcopy
    wait_driver PASS_TEXT
  fi
}''',
        "Mac to Android text direction barrier",
    )

    # A 350 ms pasteboard poller cannot promise that every 100 ms intermediate
    # value is observed, but it must converge to the final stable value. Leave the
    # tenth value stable across multiple poll intervals before evaluating it.
    text = regex_once(
        text,
        r'''burst_reset="burst-reset-\$\(nonce\)"; burst_ready=1\nprintf '%s' "\$burst_reset" \| pbcopy\nwait_android_open_text "\$burst_reset" \|\| burst_ready=0\nsleep \.50\nfor n in 0 1 2 3 4 5 6 7 8 9; do printf '%s' "burst-m2a-\$n-\$STAMP" \| pbcopy; sleep \.10; done\n\[ "\$burst_ready" -eq 1 \] && wait_android_open_text "burst-m2a-9-\$STAMP" && pass "Mac -> Android rapid 10-event burst final state" \|\| fail "Mac -> Android rapid 10-event burst final state"''',
        r'''burst_reset="burst-reset-$(nonce)"; burst_ready=1
acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$burst_reset")" >/dev/null || burst_ready=0
[ "$burst_ready" -eq 1 ] && wait_mac_text "$burst_reset" || burst_ready=0
sleep .55
for n in 0 1 2 3 4 5 6 7 8 9; do printf '%s' "burst-m2a-$n-$STAMP" | pbcopy; sleep .10; done
sleep .85
[ "$burst_ready" -eq 1 ] && wait_android_open_text "burst-m2a-9-$STAMP" && pass "Mac -> Android rapid 10-event burst final state" || fail "Mac -> Android rapid 10-event burst final state"''',
        "Mac to Android burst final-state convergence",
    )

    # Commands now ACK only after the real AppDelegate executes them. Re-issue the
    # UI refresh while waiting for discovery so metric checks cannot read a stale
    # renderer snapshot even if the first UDP discovery packet arrived later.
    text = replace_once(
        text,
        '''mac_clipboard_rendered(){ mac_state | awk -F= '/clipboard_nearby_count=/{exit !($2>=0)}'; }
mac_file_visible(){ mac_state | awk -F= '/file_nearby_count=/{exit !($2>0)}'; }
''',
        '''mac_clipboard_rendered(){ mac_command clipboard >/dev/null 2>&1 || return 1; mac_state | awk -F= '/clipboard_nearby_count=/{exit !($2>=0)}'; }
mac_file_visible(){ mac_command file >/dev/null 2>&1 || return 1; mac_state | awk -F= '/file_nearby_count=/{exit !($2>0)}'; }
''',
        "Mac renderer refresh while converging",
    )

    # The real Mac incoming alert is automated by the acceptance build. Prove the
    # Reject button was actually clicked, not merely that the sender happened to
    # fail for another reason.
    text = regex_once(
        text,
        r'''# Mac real prompt Reject leaves no received file\.\nset_mac_policy reject; sleep \.35; prefix="prompt-mac-reject-\$STAMP"; rm -f "\$HOME/Downloads/ClipMesh/\$prefix\.bin"; acc_broadcast dev\.clipmesh\.acceptance\.SEND_GENERATED --es address "\$MAC_IP" --es fingerprint "\$MAC_FP" --es file_prefix "\$prefix" --es extension bin --ei count 1 --ei size 347; out="\$\(acc_wait send_generated=\)"; printf '%s\\n' "\$out" \| grep -q '\^send_generated=FAIL\$' && \[ ! -e "\$HOME/Downloads/ClipMesh/\$prefix\.bin" \] && pass "Mac non-favorite real prompt Reject" \|\| fail "Mac non-favorite real prompt Reject" "\$out"''',
        r'''# Mac real prompt Reject leaves no received file. The acceptance build
# auto-clicks the actual Reject NSAlert button, exactly like Android automation.
"$APP_EXE" --dev-accept-reset-metrics >/dev/null 2>&1
set_mac_policy reject; prefix="prompt-mac-reject-$STAMP"; rm -f "$HOME/Downloads/ClipMesh/$prefix.bin"
acc_broadcast dev.clipmesh.acceptance.SEND_GENERATED --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_prefix "$prefix" --es extension bin --ei count 1 --ei size 347
out="$(acc_wait send_generated=)"; ms_reject="$(mac_state)"; pc_reject="$(printf '%s\n' "$ms_reject" | sed -n 's/^prompt_count=//p')"; decision_reject="$(printf '%s\n' "$ms_reject" | sed -n 's/^last_prompt_decision=//p')"
printf '%s\n' "$out" | grep -q '^send_generated=FAIL$' && [ ! -e "$HOME/Downloads/ClipMesh/$prefix.bin" ] && [ "${pc_reject:-0}" -gt 0 ] && [ "$decision_reject" = reject ] && pass "Mac non-favorite real prompt Reject" || fail "Mac non-favorite real prompt Reject" "sender=$(printf '%s' "$out" | tr '\n' ' ') prompts=$pc_reject decision=$decision_reject"''',
        "Mac real Reject automation assertion",
    )

    # The earlier suite waited only for the independent file receiver after
    # restarting the Mac app, then immediately attempted clipboard sync. Require
    # the Rust clipboard daemon/listener and AppDelegate command mailbox too.
    text = replace_once(
        text,
        '''lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1 && pass "Mac restart restores IPv4 file receiver" || fail "Mac restart restores IPv4 file receiver"
"${ADB[@]}" shell am force-stop dev.clipmesh >/dev/null 2>&1; sleep .5; android_main; android_background
''',
        '''lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1 && pass "Mac restart restores IPv4 file receiver" || fail "Mac restart restores IPv4 file receiver"
mac_clipboard_ready(){ pgrep -x clipmesh-bin >/dev/null 2>&1 && lsof -nP -i4TCP:41474 -sTCP:LISTEN 2>/dev/null | grep -q clipmesh- && "$CLI_EXE" status >/dev/null 2>&1; }
i=0; while [ "$i" -lt 80 ] && ! mac_clipboard_ready; do i=$((i+1)); sleep .15; done
mac_clipboard_ready && pass "Mac restart restores clipboard daemon" || fail "Mac restart restores clipboard daemon"
mac_command snapshot >/dev/null 2>&1 && pass "Mac restart restores acceptance UI command loop" || fail "Mac restart restores acceptance UI command loop"
"${ADB[@]}" shell am force-stop dev.clipmesh >/dev/null 2>&1; sleep .5; android_main; android_background
''',
        "Mac restart clipboard readiness gate",
    )

    text = replace_once(
        text,
        '''pgrep -x ClipMesh >/dev/null 2>&1 && pgrep -x clipmesh-bin >/dev/null 2>&1 && pass "Mac UI and clipboard daemon alive" || fail "Mac UI and clipboard daemon alive"
''',
        '''pgrep -x ClipMesh >/dev/null 2>&1 && mac_clipboard_ready && mac_command snapshot >/dev/null 2>&1 && pass "Mac UI and clipboard daemon alive" || fail "Mac UI and clipboard daemon alive"
''',
        "Mac final UI/clipboard daemon health",
    )

    text += "\n# PHYSICAL_HARDENING_V3\n"
    required = (
        'CLIPMESH_CODESIGN_IDENTITY="-"',
        "dev.ClipMesh.ClipMesh-Acceptance",
        "m2a-reset-$(nonce)",
        "last_prompt_decision=",
        "Mac restart restores clipboard daemon",
        "Mac restart restores acceptance UI command loop",
        "PHYSICAL_HARDENING_V3",
    )
    for needle in required:
        if needle not in text:
            raise SystemExit(f"physical v3 runner guard missing: {needle}")

    dst.write_text(text, encoding="utf-8")
    print(f"Applied passwordless/restart physical hardening: {dst}")


if __name__ == "__main__":
    main()
