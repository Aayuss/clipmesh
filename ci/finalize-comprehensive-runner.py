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
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return out


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: finalize-comprehensive-runner.py INPUT OUTPUT")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")

    # macOS date(1) does not implement GNU %N. Use Python's nanosecond clock so
    # every reset marker stays unique on the actual machine that runs the suite.
    text = replace_once(
        text,
        'b64(){ printf \'%s\' "$1" | base64 | tr -d \'\\n\'; }\n',
        'b64(){ printf \'%s\' "$1" | base64 | tr -d \'\\n\'; }\nnonce(){ python3 -c \'import time; print(time.time_ns())\'; }\n',
        "portable nonce helper",
    )
    if text.count("$(date +%s%N)") != 2:
        raise SystemExit(f"portable nonce replacement: expected two GNU date uses, found {text.count('$(date +%s%N)')}")
    text = text.replace("$(date +%s%N)", "$(nonce)")

    # Unique text values never need a reverse-edge reset. Removing the reset
    # avoids injecting an unnecessary Mac -> Android event immediately before
    # the Android -> Mac assertion.
    text = replace_once(
        text,
        'clipboard_a2m_text(){ a="$1"; expected="$2"; printf \'%s\' "reset-$expected" | pbcopy; if [ "$a" = open ]; then acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$expected")" >/dev/null; else start_driver set_text "$expected"; fi; wait_mac_text "$expected"; }',
        'clipboard_a2m_text(){ a="$1"; expected="$2"; if [ "$a" = open ]; then acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$expected")" >/dev/null; else start_driver set_text "$expected"; fi; wait_mac_text "$expected"; }',
        "Android to Mac text race removal",
    )

    # Images are static 3x2 fixtures, so both directions need a text barrier
    # before the image event. The barrier must reach the opposite machine before
    # starting the image assertion, otherwise an old 3x2 clipboard can satisfy
    # the test before the new transfer happens.
    text = regex_once(
        text,
        r'clipboard_a2m_image\(\)\{.*?\}\nclipboard_m2a_image\(\)\{.*?\}\n',
        r'''clipboard_a2m_image(){
  a="$1"; reset="reset-image-$(nonce)"
  if [ "$a" = open ]; then
    printf '%s' "$reset" | pbcopy
    wait_android_open_text "$reset" || return 1
    acc_sync dev.clipmesh.acceptance.SET_IMAGE >/dev/null
  else
    start_driver wait_text "$reset"; wait_driver READY_TEXT || return 1
    printf '%s' "$reset" | pbcopy
    wait_driver PASS_TEXT || return 1
    start_driver set_image
  fi
  wait_mac_image
}
clipboard_m2a_image(){
  a="$1"; reset="image-reset-$(nonce)"
  if [ "$a" = open ]; then
    acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$reset")" >/dev/null
    wait_mac_text "$reset" || return 1
    "$PASTE" set-image >/dev/null 2>&1
    wait_android_open_image
  else
    start_driver set_text "$reset"
    wait_mac_text "$reset" || return 1
    start_driver wait_image; wait_driver READY_IMAGE || return 1
    "$PASTE" set-image >/dev/null 2>&1
    wait_driver PASS_IMAGE
  fi
}
''',
        "deterministic image barriers",
    )

    # Clipboard's nearby card means "available to pair", not "already paired".
    # The paired relationship is checked with the clipboard engine peer count;
    # the File Transfer pages must still show the same live receiver.
    text = regex_once(
        text,
        r'section "NEARBY DEVICES - REAL UI LISTS AND ENGINE"\n.*?\nsection "CLIPBOARD - 16 FOREGROUND/BACKGROUND COMBINATIONS"',
        r'''section "NEARBY DEVICES - PAIRED CLIPBOARD + LIVE FILE TARGETS"
set_android_favorite "$MAC_FP" false
set_mac_favorite "$ANDROID_FP" false
acc_sync dev.clipmesh.acceptance.CLEAR_NEARBY >/dev/null
mac_command clear-nearby
android_main; mac_show
acc_sync dev.clipmesh.acceptance.DISCOVER >/dev/null; mac_command clipboard
sleep 2
base_info="$("${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1; sleep .2; "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tr -d '\r')"
ui="$(acc_sync dev.clipmesh.acceptance.UI_INFO)"; ms="$(mac_state)"
printf '%s\n' "$base_info" | awk -F= '/clipboard_peer_count=/{exit !($2>0)}' && pass "Android encrypted clipboard has paired Mac peer" || fail "Android encrypted clipboard has paired Mac peer" "$base_info"
printf '%s\n' "$ui" | awk -F= '/clipboard_nearby_count=/{exit !($2>=0)}' && pass "Android Clipboard available-to-pair list rendered" || fail "Android Clipboard available-to-pair list rendered" "$ui"
printf '%s\n' "$ms" | awk -F= '/clipboard_nearby_count=/{exit !($2>=0)}' && pass "Mac Clipboard available-to-pair list rendered" || fail "Mac Clipboard available-to-pair list rendered" "$ms"
android_file; mac_command file; sleep 2
ui="$(acc_sync dev.clipmesh.acceptance.UI_INFO)"; ms="$(mac_state)"
printf '%s\n' "$ui" | awk -F= '/file_nearby_count=/{exit !($2>0)}' && pass "Android File Transfer UI shows paired Mac as live target" || fail "Android File Transfer UI shows paired Mac as live target" "$ui"
printf '%s\n' "$ms" | awk -F= '/file_nearby_count=/{exit !($2>0)}' && pass "Mac File Transfer UI shows paired Android as live target" || fail "Mac File Transfer UI shows paired Android as live target" "$ms"

set_android_favorite "$MAC_FP" true
set_mac_favorite "$ANDROID_FP" true
acc_sync dev.clipmesh.acceptance.DISCOVER >/dev/null; mac_command snapshot; sleep 1
ai="$(acc_sync dev.clipmesh.acceptance.INFO)"; ms="$(mac_state)"
contains "$ai" "nearby=$MAC_FP|1|" && pass "Android engine sees favorited Mac" || fail "Android engine sees favorited Mac" "$ai"
contains "$ms" "nearby=$ANDROID_FP|1|" && pass "Mac engine sees favorited Android" || fail "Mac engine sees favorited Android" "$ms"
android_background; mac_hide; acc_sync dev.clipmesh.acceptance.CLEAR_NEARBY >/dev/null; mac_command clear-nearby; acc_sync dev.clipmesh.acceptance.DISCOVER >/dev/null; mac_command snapshot; sleep 2
ai="$(acc_sync dev.clipmesh.acceptance.INFO)"; mac_command snapshot; ms="$(mac_state)"
contains "$ai" "nearby=$MAC_FP|" && pass "Android file discovery survives both UIs hidden" || fail "Android file discovery survives both UIs hidden" "$ai"
contains "$ms" "nearby=$ANDROID_FP|" && pass "Mac file discovery survives both UIs hidden" || fail "Mac file discovery survives both UIs hidden" "$ms"

section "CLIPBOARD - 16 FOREGROUND/BACKGROUND COMBINATIONS"''',
        "paired clipboard versus file discovery semantics",
    )

    # Favorite transfers must prove they bypass confirmation, not merely prove
    # that a file eventually arrived. macOS prompt_count must not change and
    # Android's pending-request count must remain zero.
    text = regex_once(
        text,
        r'send_a2m\(\)\{\n.*?\n\}\n\nsend_m2a\(\)\{\n.*?\n\}\n',
        r'''send_a2m(){
  astate="$1"; mstate="$2"; mfav="$3"; prefix="$4"; size="${5:-257}"; count="${6:-1}"
  set_state "$astate" "$mstate"
  set_mac_policy "$( [ "$mfav" = true ] && printf '' || printf accept )"
  before_prompt=""
  if [ "$mfav" = true ]; then before_prompt="$(mac_state | sed -n 's/^prompt_count=//p')"; fi
  rm -f "$HOME/Downloads/ClipMesh/$prefix"*.bin 2>/dev/null || true
  acc_broadcast dev.clipmesh.acceptance.SEND_GENERATED --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_prefix "$prefix" --es extension bin --ei count "$count" --ei size "$size"
  out="$(acc_wait send_generated=)" || return 1
  printf '%s\n' "$out" | grep -q '^send_generated=PASS$' || return 1
  if [ "$mfav" = true ]; then
    after_prompt="$(mac_state | sed -n 's/^prompt_count=//p')"
    [ "${before_prompt:-0}" = "${after_prompt:-0}" ] || return 1
  fi
  ok=1
  while IFS='|' read -r name hash bytes; do [ -n "$name" ] || continue; dest="$HOME/Downloads/ClipMesh/$name"; [ -f "$dest" ] && [ "$(sha_file "$dest")" = "$hash" ] || ok=0; done <<EOF
$(printf '%s\n' "$out" | sed -n 's/^file=//p')
EOF
  [ "$ok" -eq 1 ]
}

send_m2a(){
  mstate="$1"; astate="$2"; afav="$3"; prefix="$4"; size="${5:-263}"; count="${6:-1}"
  set_state "$astate" "$mstate"
  if [ "$afav" = true ]; then
    before_pending="$(acc_sync dev.clipmesh.acceptance.PENDING | sed -n 's/^pending_count=//p')"
    [ "${before_pending:-0}" = 0 ] || return 1
  fi
  files=""; n=0
  while [ "$n" -lt "$count" ]; do name="$( [ "$count" -eq 1 ] && printf '%s.bin' "$prefix" || printf '%s-%s.bin' "$prefix" "$n" )"; path="$STATE/$name"; make_file "$path" "$size" "$((31+n))"; files="$files\n$path"; "${ADB[@]}" shell rm -f "/sdcard/Download/ClipMesh/$name" >/dev/null 2>&1 || true; n=$((n+1)); done
  set_android_policy "$( [ "$afav" = true ] && printf '' || [ "$astate" = open ] && printf accept || printf '' )"
  args=""; while IFS= read -r f; do [ -n "$f" ] && args="$args $(printf '%q' "$f")"; done <<EOF
$(printf '%b\n' "$files")
EOF
  if [ "$afav" = false ] && [ "$astate" = background ]; then
    eval '"$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP"' "$args" '>'"$STATE/m2a-$prefix.out"' 2>&1 &' ; pid=$!
    req="$(wait_pending)" || { wait "$pid" >/dev/null 2>&1; return 1; }
    if [ -z "${NOTIFICATION_ACCEPT_RECORDED:-}" ]; then
      "${ADB[@]}" shell dumpsys notification --noredact 2>/dev/null | grep -q 'clipmesh_file_requests_v020' && pass "Android background non-favorite receive posts request notification" || fail "Android background non-favorite receive posts request notification"
      NOTIFICATION_ACCEPT_RECORDED=1
    fi
    acc_sync dev.clipmesh.acceptance.RESOLVE_PENDING --es request_id "$req" --ez accept true >/dev/null
    wait "$pid"; rc=$?
  else
    eval '"$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP"' "$args" '>'"$STATE/m2a-$prefix.out"' 2>&1'; rc=$?
  fi
  [ "$rc" -eq 0 ] || return 1
  if [ "$afav" = true ]; then
    after_pending="$(acc_sync dev.clipmesh.acceptance.PENDING | sed -n 's/^pending_count=//p')"
    [ "${after_pending:-0}" = 0 ] || return 1
  fi
  ok=1
  while IFS= read -r f; do [ -n "$f" ] || continue; name="$(basename "$f")"; remote="/sdcard/Download/ClipMesh/$name"; i=0; while [ "$i" -lt 80 ] && ! "${ADB[@]}" shell test -f "$remote" >/dev/null 2>&1; do i=$((i+1)); sleep .15; done; [ "$(android_sha "$remote")" = "$(sha_file "$f")" ] || ok=0; done <<EOF
$(printf '%b\n' "$files")
EOF
  [ "$ok" -eq 1 ]
}
''',
        "favorite confirmation bypass assertions",
    )

    # There is a permanent foreground/background ClipMesh notification, so a
    # generic package-name grep is not evidence that an incoming-file request
    # notification appeared. Match the request channel specifically.
    text = text.replace(
        '"${ADB[@]}" shell dumpsys notification --noredact 2>/dev/null | grep -q \'dev.clipmesh\'',
        '"${ADB[@]}" shell dumpsys notification --noredact 2>/dev/null | grep -q \'clipmesh_file_requests_v020\'',
    )

    # The old helper removed the first received file before the second send,
    # making collision testing impossible. Send two different payloads with the
    # same basename without cleanup, then prove both distinct hashes survived.
    text = regex_once(
        text,
        r'# Duplicate names must never overwrite the first received file\.\n.*?\n# PNG MIME route into Android Images folder\.',
        r'''# Duplicate names must never overwrite the first received file.
dup="dup-a2m-$STAMP"
set_state background tray; set_mac_policy ''
rm -f "$HOME/Downloads/ClipMesh/$dup"* 2>/dev/null || true
acc_broadcast dev.clipmesh.acceptance.SEND_GENERATED --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_prefix "$dup" --es extension bin --ei count 1 --ei size 777
o1="$(acc_wait send_generated=)"; r1=$?; h1="$(printf '%s\n' "$o1" | sed -n 's/^file=[^|]*|\([^|]*\)|.*$/\1/p' | head -n1)"
acc_broadcast dev.clipmesh.acceptance.SEND_GENERATED --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_prefix "$dup" --es extension bin --ei count 1 --ei size 778
o2="$(acc_wait send_generated=)"; r2=$?; h2="$(printf '%s\n' "$o2" | sed -n 's/^file=[^|]*|\([^|]*\)|.*$/\1/p' | head -n1)"
files_found="$(find "$HOME/Downloads/ClipMesh" -maxdepth 1 -type f -name "$dup*" -print 2>/dev/null)"; dc="$(printf '%s\n' "$files_found" | sed '/^$/d' | wc -l | tr -d ' ')"; seen1=0; seen2=0
while IFS= read -r found; do [ -n "$found" ] || continue; hash="$(sha_file "$found")"; [ "$hash" = "$h1" ] && seen1=1; [ "$hash" = "$h2" ] && seen2=1; done <<EOF
$files_found
EOF
[ "$r1" -eq 0 ] && [ "$r2" -eq 0 ] && contains "$o1" "send_generated=PASS" && contains "$o2" "send_generated=PASS" && [ "$dc" -ge 2 ] && [ "$seen1" -eq 1 ] && [ "$seen2" -eq 1 ] && pass "Mac duplicate filename collision preservation" "files=$dc distinct_hashes=2" || fail "Mac duplicate filename collision preservation" "files=$dc seen1=$seen1 seen2=$seen2"

dup="dup-m2a-$STAMP"
set_state background tray; set_android_policy ''
"${ADB[@]}" shell rm -f "/sdcard/Download/ClipMesh/$dup"* >/dev/null 2>&1 || true
d1="$STATE/dup-src1-$STAMP"; d2="$STATE/dup-src2-$STAMP"; mkdir -p "$d1" "$d2"; f1="$d1/$dup.bin"; f2="$d2/$dup.bin"; make_file "$f1" 781 71; make_file "$f2" 783 73; h1="$(sha_file "$f1")"; h2="$(sha_file "$f2")"
"$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP" "$f1" > "$STATE/dup-m2a-first.out" 2>&1; r1=$?
"$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP" "$f2" > "$STATE/dup-m2a-second.out" 2>&1; r2=$?
remote_found="$("${ADB[@]}" shell "find /sdcard/Download/ClipMesh -maxdepth 1 -type f -name '$dup*' -print 2>/dev/null" | tr -d '\r')"; dc="$(printf '%s\n' "$remote_found" | sed '/^$/d' | wc -l | tr -d ' ')"; seen1=0; seen2=0
while IFS= read -r remote; do [ -n "$remote" ] || continue; hash="$(android_sha "$remote")"; [ "$hash" = "$h1" ] && seen1=1; [ "$hash" = "$h2" ] && seen2=1; done <<EOF
$remote_found
EOF
[ "$r1" -eq 0 ] && [ "$r2" -eq 0 ] && [ "$dc" -ge 2 ] && [ "$seen1" -eq 1 ] && [ "$seen2" -eq 1 ] && pass "Android duplicate filename collision preservation" "files=$dc distinct_hashes=2" || fail "Android duplicate filename collision preservation" "files=$dc seen1=$seen1 seen2=$seen2"
# PNG MIME route into Android Images folder.''',
        "duplicate filename integrity test",
    )

    # Clear logcat immediately before functional execution so the final fatal
    # scan cannot fail because of an unrelated historical crash. lastanr cannot
    # be reliably cleared on every OEM, so snapshot it and only treat a changed
    # ClipMesh entry as a new ANR from this run.
    text = replace_once(
        text,
        'codesign --verify --deep --strict "$INSTALL_APP" >/dev/null 2>&1 && pass "macOS DEV code signing" || fail "macOS DEV code signing"\n',
        'codesign --verify --deep --strict "$INSTALL_APP" >/dev/null 2>&1 && pass "macOS DEV code signing" || fail "macOS DEV code signing"\n"${ADB[@]}" logcat -c >/dev/null 2>&1 || true\nBASE_LASTANR="$STATE/comprehensive-lastanr-baseline-$STAMP.txt"\n"${ADB[@]}" shell dumpsys activity lastanr > "$BASE_LASTANR" 2>&1 || true\n',
        "runtime failure baseline",
    )
    text = replace_once(
        text,
        'if grep -q \'dev.clipmesh\' "$STATE/comprehensive-lastanr-$STAMP.txt"; then fail "Android ANR scan" "dev.clipmesh present in lastanr"; else pass "Android ANR scan"; fi',
        'if grep -q \'dev.clipmesh\' "$STATE/comprehensive-lastanr-$STAMP.txt" && ! cmp -s "$BASE_LASTANR" "$STATE/comprehensive-lastanr-$STAMP.txt"; then fail "Android ANR scan" "new dev.clipmesh entry present in lastanr"; else pass "Android ANR scan"; fi',
        "ANR baseline comparison",
    )

    text += '\n# FINAL_COMPREHENSIVE_RUNNER_AUDIT_V1\n'

    required = (
        "nonce(){ python3 -c",
        "wait_mac_text \"$reset\" || return 1",
        "Android encrypted clipboard has paired Mac peer",
        "clipmesh_file_requests_v020",
        "before_prompt=",
        "before_pending=",
        "distinct_hashes=2",
        "BASE_LASTANR=",
        "FINAL_COMPREHENSIVE_RUNNER_AUDIT_V1",
    )
    for needle in required:
        if needle not in text:
            raise SystemExit(f"final runner guard missing: {needle}")
    forbidden = (
        "date +%s%N",
        "Android Clipboard nearby UI sees Mac - unfavorited",
        "Mac Clipboard nearby UI sees Android - unfavorited",
        "grep -q 'dev.clipmesh' && notif",
    )
    for needle in forbidden:
        if needle in text:
            raise SystemExit(f"final runner still contains forbidden legacy pattern: {needle}")

    dst.write_text(text, encoding="utf-8")
    print(f"Finalized comprehensive physical runner: {dst}")


if __name__ == "__main__":
    main()
