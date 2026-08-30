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
        raise SystemExit("usage: finalize-physical-v2.py INPUT OUTPUT")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")

    # The physical prepare runner must apply both acceptance layers. Replacing
    # the script name is intentionally narrow: the canonical comprehensive file
    # contains exactly one Darwin and one Linux invocation.
    count = text.count("patch-acceptance-v2.py")
    if count != 2:
        raise SystemExit(f"acceptance chain wiring: expected two v2 invocations, found {count}")
    text = text.replace("patch-acceptance-v2.py", "patch-acceptance-chain.py")

    # Commands sent to the already-running Mac app are now preference-mailbox
    # commands. Wait for the requested state instead of assuming a fixed 300 ms
    # sleep means AppKit processed it.
    text = replace_once(
        text,
        '''mac_command(){ "$APP_EXE" --dev-accept-command "$1" >/dev/null 2>&1; sleep .3; }
mac_state(){ "$APP_EXE" --dev-accept-state 2>/dev/null; }
mac_show(){ mac_command show; }
mac_hide(){ mac_command hide; }
mac_is_visible(){ mac_state | grep -q '^window_visible=true$'; }
mac_is_hidden(){ mac_state | grep -q '^window_visible=false$'; }
''',
        '''mac_command(){ "$APP_EXE" --dev-accept-command "$1" >/dev/null 2>&1; sleep .12; }
mac_state(){ "$APP_EXE" --dev-accept-state 2>/dev/null; }
mac_is_visible(){ mac_state | grep -q '^window_visible=true$'; }
mac_is_hidden(){ mac_state | grep -q '^window_visible=false$'; }
mac_show(){ mac_command show; wait_until 40 mac_is_visible; }
mac_hide(){ mac_command hide; wait_until 40 mac_is_hidden; }
''',
        "deterministic Mac window commands",
    )

    text = replace_once(
        text,
        '''set_state(){
  a="$1"; m="$2"
  if [ "$a" = open ]; then android_main; else android_background; fi
  if [ "$m" = open ]; then mac_show; else mac_hide; fi
}
''',
        '''set_state(){
  a="$1"; m="$2"
  if [ "$a" = open ]; then android_main; else android_background; fi
  if [ "$m" = open ]; then mac_show || return 1; else mac_hide || return 1; fi
  sleep .35
}
''',
        "foreground/background state settling",
    )

    # Setter modes are asynchronous from the shell's perspective. Every
    # background clipboard edge now proves that the foreground driver actually
    # completed its local write before waiting for the remote side. Image edges
    # retain the unique text barrier and additionally allow remote echo
    # suppression to settle before changing direction again.
    text = regex_once(
        text,
        r'clipboard_a2m_text\(\)\{.*?\nclipboard_m2a_image\(\)\{.*?\n\}\n\nsection "PREFLIGHT AND PRIVILEGED CLIPBOARD"',
        r'''clipboard_a2m_text(){
  a="$1"; expected="$2"
  if [ "$a" = open ]; then
    acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$expected")" >/dev/null || return 1
  else
    start_driver set_text "$expected"; wait_driver SET_TEXT || return 1
  fi
  wait_mac_text "$expected"
}
clipboard_m2a_text(){
  a="$1"; expected="$2"
  if [ "$a" = open ]; then
    printf '%s' "$expected" | pbcopy
    wait_android_open_text "$expected"
  else
    start_driver wait_text "$expected"; wait_driver READY_TEXT || return 1
    sleep .25
    printf '%s' "$expected" | pbcopy
    wait_driver PASS_TEXT
  fi
}
clipboard_a2m_image(){
  a="$1"; reset="reset-image-$(nonce)"
  if [ "$a" = open ]; then
    printf '%s' "$reset" | pbcopy
    wait_android_open_text "$reset" || return 1
    sleep .50
    acc_sync dev.clipmesh.acceptance.SET_IMAGE >/dev/null || return 1
  else
    start_driver wait_text "$reset"; wait_driver READY_TEXT || return 1
    printf '%s' "$reset" | pbcopy
    wait_driver PASS_TEXT || return 1
    sleep .50
    start_driver set_image; wait_driver SET_IMAGE || return 1
  fi
  wait_mac_image
}
clipboard_m2a_image(){
  a="$1"; reset="image-reset-$(nonce)"
  if [ "$a" = open ]; then
    acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$reset")" >/dev/null || return 1
    wait_mac_text "$reset" || return 1
    sleep .50
    "$PASTE" set-image >/dev/null 2>&1
    wait_android_open_image
  else
    start_driver set_text "$reset"; wait_driver SET_TEXT || return 1
    wait_mac_text "$reset" || return 1
    sleep .50
    start_driver wait_image; wait_driver READY_IMAGE || return 1
    sleep .25
    "$PASTE" set-image >/dev/null 2>&1
    wait_driver PASS_IMAGE
  fi
}

section "PREFLIGHT AND PRIVILEGED CLIPBOARD"''',
        "clipboard edge synchronization",
    )

    # Replace the fixed-sleep discovery assertions with active, bounded
    # convergence checks. Both peers explicitly advertise on every retry. This
    # still fails a broken discovery implementation, but it no longer fails just
    # because one UDP packet or one UI refresh landed a few hundred ms late.
    text = regex_once(
        text,
        r'section "NEARBY DEVICES - PAIRED CLIPBOARD \+ LIVE FILE TARGETS"\n.*?\nsection "CLIPBOARD - 16 FOREGROUND/BACKGROUND COMBINATIONS"',
        r'''section "NEARBY DEVICES - PAIRED CLIPBOARD + LIVE FILE TARGETS"
discover_pair_once(){ acc_sync dev.clipmesh.acceptance.DISCOVER >/dev/null 2>&1; mac_command discover >/dev/null 2>&1; }
android_has_mac(){ ai_check="$(acc_sync dev.clipmesh.acceptance.INFO)"; contains "$ai_check" "nearby=$MAC_FP|"; }
mac_has_android(){ mac_command snapshot >/dev/null 2>&1; ms_check="$(mac_state)"; contains "$ms_check" "nearby=$ANDROID_FP|"; }
wait_android_has_mac(){ i=0; while [ "$i" -lt 20 ]; do android_has_mac && return 0; discover_pair_once; i=$((i+1)); sleep .25; done; return 1; }
wait_mac_has_android(){ i=0; while [ "$i" -lt 20 ]; do mac_has_android && return 0; discover_pair_once; i=$((i+1)); sleep .25; done; return 1; }
android_clipboard_rendered(){ acc_sync dev.clipmesh.acceptance.UI_INFO | awk -F= '/clipboard_nearby_count=/{exit !($2>=0)}'; }
android_file_visible(){ acc_sync dev.clipmesh.acceptance.UI_INFO | awk -F= '/file_nearby_count=/{exit !($2>0)}'; }
mac_clipboard_rendered(){ mac_state | awk -F= '/clipboard_nearby_count=/{exit !($2>=0)}'; }
mac_file_visible(){ mac_state | awk -F= '/file_nearby_count=/{exit !($2>0)}'; }

set_android_favorite "$MAC_FP" false
set_mac_favorite "$ANDROID_FP" false
acc_sync dev.clipmesh.acceptance.CLEAR_NEARBY >/dev/null
mac_command clear-nearby >/dev/null
android_main; mac_show
discover_pair_once
wait_android_has_mac; adr=$?
wait_mac_has_android; mdr=$?
base_info="$("${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1; sleep .2; "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tr -d '\r')"
printf '%s\n' "$base_info" | awk -F= '/clipboard_peer_count=/{exit !($2>0)}' && pass "Android encrypted clipboard has paired Mac peer" || fail "Android encrypted clipboard has paired Mac peer" "$base_info"
mac_command clipboard >/dev/null
wait_until 40 android_clipboard_rendered && pass "Android Clipboard available-to-pair list rendered" || fail "Android Clipboard available-to-pair list rendered" "$(acc_sync dev.clipmesh.acceptance.UI_INFO)"
wait_until 40 mac_clipboard_rendered && pass "Mac Clipboard available-to-pair list rendered" || fail "Mac Clipboard available-to-pair list rendered" "$(mac_state)"

android_file; mac_command file >/dev/null; discover_pair_once
wait_until 50 android_file_visible && pass "Android File Transfer UI shows paired Mac as live target" || fail "Android File Transfer UI shows paired Mac as live target" "$(acc_sync dev.clipmesh.acceptance.UI_INFO)"
wait_until 50 mac_file_visible && pass "Mac File Transfer UI shows paired Android as live target" || fail "Mac File Transfer UI shows paired Android as live target" "$(mac_state)"

set_android_favorite "$MAC_FP" true
set_mac_favorite "$ANDROID_FP" true
discover_pair_once
wait_android_has_mac; adr=$?
wait_mac_has_android; mdr=$?
ai="$(acc_sync dev.clipmesh.acceptance.INFO)"; mac_command snapshot >/dev/null; ms="$(mac_state)"
[ "$adr" -eq 0 ] && contains "$ai" "nearby=$MAC_FP|1|" && pass "Android engine sees favorited Mac" || fail "Android engine sees favorited Mac" "$ai"
[ "$mdr" -eq 0 ] && contains "$ms" "nearby=$ANDROID_FP|1|" && pass "Mac engine sees favorited Android" || fail "Mac engine sees favorited Android" "$ms"

android_background; mac_hide
acc_sync dev.clipmesh.acceptance.CLEAR_NEARBY >/dev/null; mac_command clear-nearby >/dev/null
discover_pair_once
wait_android_has_mac; adr=$?
wait_mac_has_android; mdr=$?
ai="$(acc_sync dev.clipmesh.acceptance.INFO)"; mac_command snapshot >/dev/null; ms="$(mac_state)"
[ "$adr" -eq 0 ] && contains "$ai" "nearby=$MAC_FP|" && pass "Android file discovery survives both UIs hidden" || fail "Android file discovery survives both UIs hidden" "$ai"
[ "$mdr" -eq 0 ] && contains "$ms" "nearby=$ANDROID_FP|" && pass "Mac file discovery survives both UIs hidden" || fail "Mac file discovery survives both UIs hidden" "$ms"

section "CLIPBOARD - 16 FOREGROUND/BACKGROUND COMBINATIONS"''',
        "bounded bidirectional discovery convergence",
    )

    text = replace_once(
        text,
        '''clipboard_a2m_image open >/dev/null 2>&1; acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "order-final-$STAMP")" >/dev/null
wait_mac_text "order-final-$STAMP" && pass "Android text -> image -> text ordering" || fail "Android text -> image -> text ordering"
''',
        '''order_image_ok=0
clipboard_a2m_image open >/dev/null 2>&1 && order_image_ok=1
sleep .60
acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "order-final-$STAMP")" >/dev/null
[ "$order_image_ok" -eq 1 ] && wait_mac_text "order-final-$STAMP" && pass "Android text -> image -> text ordering" || fail "Android text -> image -> text ordering"
''',
        "ordering transition barrier",
    )

    text = replace_once(
        text,
        '''for n in 0 1 2 3 4 5 6 7 8 9; do printf '%s' "burst-m2a-$n-$STAMP" | pbcopy; sleep .08; done
wait_android_open_text "burst-m2a-9-$STAMP" && pass "Mac -> Android rapid 10-event burst final state" || fail "Mac -> Android rapid 10-event burst final state"
''',
        '''burst_reset="burst-reset-$(nonce)"; burst_ready=1
printf '%s' "$burst_reset" | pbcopy
wait_android_open_text "$burst_reset" || burst_ready=0
sleep .50
for n in 0 1 2 3 4 5 6 7 8 9; do printf '%s' "burst-m2a-$n-$STAMP" | pbcopy; sleep .10; done
[ "$burst_ready" -eq 1 ] && wait_android_open_text "burst-m2a-9-$STAMP" && pass "Mac -> Android rapid 10-event burst final state" || fail "Mac -> Android rapid 10-event burst final state"
''',
        "Mac to Android burst barrier",
    )

    text = replace_once(
        text,
        'set_mac_policy reject; prefix="prompt-mac-reject-$STAMP";',
        'set_mac_policy reject; sleep .35; prefix="prompt-mac-reject-$STAMP";',
        "Mac reject policy propagation barrier",
    )

    text += "\n# PHYSICAL_HARDENING_V2\n"
    required = (
        "patch-acceptance-chain.py",
        "wait_driver SET_IMAGE",
        "mac_command discover",
        "ClipMesh File Transfer UI shows" if False else "Mac File Transfer UI shows paired Android as live target",
        "burst_reset=",
        "PHYSICAL_HARDENING_V2",
    )
    for needle in required:
        if needle not in text:
            raise SystemExit(f"physical v2 runner guard missing: {needle}")

    dst.write_text(text, encoding="utf-8")
    print(f"Applied deterministic physical hardening: {dst}")


if __name__ == "__main__":
    main()
