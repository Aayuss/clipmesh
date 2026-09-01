#!/usr/bin/env bash
# ClipMesh comprehensive Mac <-> Android physical acceptance suite.
# Functional checks never abort the run. Setup/build failures do, because no
# meaningful physical matrix can run without a valid instrumented environment.

set +e
set +u
set +o pipefail 2>/dev/null
trap - ERR

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
STATE="${CLIPMESH_DEV_STATE:-$HOME/.clipmesh-dev}"
mkdir -p "$STATE"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$STATE/comprehensive-$STAMP.log"
MATRIX="$STATE/comprehensive-matrix-$STAMP.tsv"
: > "$LOG"
: > "$MATRIX"
exec > >(tee -a "$LOG") 2>&1

FAILURES=0
PASSES=0

section(){ printf '\n============================================================\n %s\n============================================================\n' "$*"; }
record(){
  status="$1"; name="$2"; detail="${3:-}"
  printf '%s\t%s\t%s\n' "$status" "$name" "$detail" >> "$MATRIX"
  if [ "$status" = PASS ]; then PASSES=$((PASSES+1)); printf 'PASS %s%s\n' "$name" "${detail:+ - $detail}"; else FAILURES=$((FAILURES+1)); printf 'FAIL %s%s\n' "$name" "${detail:+ - $detail}"; fi
}
pass(){ record PASS "$1" "${2:-}"; }
fail(){ record FAIL "$1" "${2:-}"; }
setup_fail(){ printf '\nSETUP FAILURE: %s\nFull log: %s\n' "$*" "$LOG"; exit 2; }
contains(){ printf '%s\n' "$1" | grep -Fq "$2"; }
wait_until(){
  timeout="$1"; shift
  i=0
  while [ "$i" -lt "$timeout" ]; do "$@" >/dev/null 2>&1 && return 0; i=$((i+1)); sleep .2; done
  return 1
}
b64(){ printf '%s' "$1" | base64 | tr -d '\n'; }

[ "$(uname -s)" = Darwin ] || setup_fail "Run this on the Mac physically paired with the Android device."
[ -d "$ROOT/.git" ] || setup_fail "Run from the ClipMesh Git checkout."

export ADB_MDNS_AUTO_CONNECT=0
if [ -z "${ANDROID_HOME:-}" ]; then ANDROID_HOME="${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}"; fi
ADB_BIN="$ANDROID_HOME/platform-tools/adb"
[ -x "$ADB_BIN" ] || ADB_BIN="$(command -v adb 2>/dev/null)"
[ -n "$ADB_BIN" ] && [ -x "$ADB_BIN" ] || setup_fail "adb not found."

ENDPOINT="${CLIPMESH_ANDROID_ENDPOINT:-${ANDROID_SERIAL:-}}"
if [ -n "$ENDPOINT" ]; then
  "$ADB_BIN" connect "$ENDPOINT" >/dev/null 2>&1 || true
  "$ADB_BIN" -s "$ENDPOINT" get-state >/dev/null 2>&1 && export ANDROID_SERIAL="$ENDPOINT"
fi
if [ -z "${ANDROID_SERIAL:-}" ]; then
  devices="$("$ADB_BIN" devices | awk 'NR>1 && $2=="device"{print $1}')"
  count="$(printf '%s\n' "$devices" | sed '/^$/d' | wc -l | tr -d ' ')"
  [ "$count" = 1 ] || setup_fail "Connect exactly one Android device or set CLIPMESH_ANDROID_ENDPOINT."
  ANDROID_SERIAL="$(printf '%s\n' "$devices" | sed '/^$/d' | head -n1)"
  export ANDROID_SERIAL
fi
"$ADB_BIN" -s "$ANDROID_SERIAL" get-state >/dev/null 2>&1 || setup_fail "Android endpoint $ANDROID_SERIAL is not connected."

section "COMPREHENSIVE ACCEPTANCE PREPARE"
echo "Git:     $(git -C "$ROOT" rev-parse HEAD)"
echo "Android: $ANDROID_SERIAL"

# Reuse the already proven dev-test setup/build/pairing code, but patch a runtime
# copy so it applies the acceptance layer to isolated builds and exits before its
# legacy smoke tests. The canonical dev-test.sh is never modified.
PREP="$ROOT/.dev-test-comprehensive-prepare.$$"
PREP_STATE="$STATE/comprehensive-prepare-$STAMP.env"
python3 - "$ROOT/dev-test.sh" "$PREP" "$PREP_STATE" <<'PY'
from pathlib import Path
import sys
src = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])
state = sys.argv[3]
mac = 'python3 "$MAC_BUILD_ROOT/ci/reconstruct.py" --platform Darwin >> "$LOG" 2>&1\n'
linux = 'python3 "$ANDROID_BUILD_ROOT/ci/reconstruct.py" --platform Linux >> "$LOG" 2>&1\n'
marker = 'NONCE="$(date +%s)-$$"; say "Running physical clipboard E2E..."\n'
for needle, label in ((mac,"mac reconstruct"),(linux,"android reconstruct"),(marker,"test marker")):
    if src.count(needle) != 1:
        raise SystemExit(f"prepare patch: expected one {label}, found {src.count(needle)}")
src = src.replace(mac, mac + 'CLIPMESH_PLATFORM=Darwin python3 "$MAC_BUILD_ROOT/ci/patch-acceptance-v2.py" >> "$LOG" 2>&1\n', 1)
src = src.replace(linux, linux + 'CLIPMESH_PLATFORM=Linux python3 "$ANDROID_BUILD_ROOT/ci/patch-acceptance-v2.py" >> "$LOG" 2>&1\n', 1)
injected = f'''cat > {state!r} <<EOF\nSERIAL=\"$SERIAL\"\nMAC_IP=\"$MAC_IP\"\nANDROID_IP=\"$ANDROID_IP\"\nMAC_FP=\"$MAC_FP\"\nANDROID_FP=\"$ANDROID_FP\"\nINSTALL_APP=\"$INSTALL_APP\"\nAPP_EXE=\"$APP_EXE\"\nCLI_EXE=\"$CLI_EXE\"\nPASTE=\"$PASTE\"\nADB_BIN=\"$ADB_BIN\"\nEOF\nsay "Acceptance-instrumented physical environment ready."\nexit 0\n'''
src = src.replace(marker, injected, 1)
out.write_text(src, encoding="utf-8")
PY
[ "$?" -eq 0 ] || setup_fail "Could not generate acceptance prepare runner."
chmod +x "$PREP"
/bin/bash --noprofile --norc "$PREP"
PREP_RC=$?
rm -f "$PREP"
[ "$PREP_RC" -eq 0 ] || setup_fail "Acceptance-instrumented DEV build/setup failed."
[ -s "$PREP_STATE" ] || setup_fail "Prepare state was not written."
. "$PREP_STATE"
ADB=("$ADB_BIN" -s "$SERIAL")
[ -x "$APP_EXE" ] || setup_fail "Instrumented Mac app missing."
[ -x "$PASTE" ] || setup_fail "Pasteboard helper missing."

acc_broadcast(){ action="$1"; shift; "${ADB[@]}" shell run-as dev.clipmesh rm -f files/clipmesh-acceptance.txt >/dev/null 2>&1 || true; "${ADB[@]}" shell am broadcast -n dev.clipmesh/.AcceptanceReceiver -a "$action" "$@" >/dev/null 2>&1; }
acc_result(){ "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-acceptance.txt 2>/dev/null | tr -d '\r'; }
acc_wait(){ prefix="$1"; i=0; while [ "$i" -lt 400 ]; do r="$(acc_result)"; printf '%s\n' "$r" | grep -q "^$prefix" && { printf '%s\n' "$r"; return 0; }; i=$((i+1)); sleep .15; done; return 1; }
acc_sync(){ action="$1"; shift; acc_broadcast "$action" "$@"; i=0; while [ "$i" -lt 80 ]; do r="$(acc_result)"; [ -n "$r" ] && { printf '%s\n' "$r"; return 0; }; i=$((i+1)); sleep .1; done; return 1; }

start_driver(){ mode="$1"; value="${2:-}"; "${ADB[@]}" shell am force-stop dev.clipmesh.testdriver >/dev/null 2>&1 || true; "${ADB[@]}" shell run-as dev.clipmesh.testdriver rm -f files/result.txt >/dev/null 2>&1 || true; if [ -n "$value" ]; then "${ADB[@]}" shell am start -W -n dev.clipmesh.testdriver/.MainActivity --es mode "$mode" --es value_b64 "$(b64 "$value")" >/dev/null 2>&1; else "${ADB[@]}" shell am start -W -n dev.clipmesh.testdriver/.MainActivity --es mode "$mode" >/dev/null 2>&1; fi; }
driver_result(){ "${ADB[@]}" shell run-as dev.clipmesh.testdriver cat files/result.txt 2>/dev/null | tr -d '\r'; }
wait_driver(){ prefix="$1"; i=0; while [ "$i" -lt 180 ]; do r="$(driver_result)"; case "$r" in "$prefix"*) return 0;; FAIL*) return 1;; esac; i=$((i+1)); sleep .15; done; return 1; }

android_main(){ "${ADB[@]}" shell am start -W -n dev.clipmesh/.MainActivity >/dev/null 2>&1; sleep .5; }
android_file(){ acc_sync dev.clipmesh.acceptance.OPEN_FILE >/dev/null; sleep .5; }
android_background(){ "${ADB[@]}" shell input keyevent KEYCODE_HOME >/dev/null 2>&1; sleep .5; }
android_is_hidden(){ ! "${ADB[@]}" shell dumpsys activity activities 2>/dev/null | grep -E 'mResumedActivity|topResumedActivity' | grep -q 'dev\.clipmesh/'; }
mac_command(){ "$APP_EXE" --dev-accept-command "$1" >/dev/null 2>&1; sleep .3; }
mac_state(){ "$APP_EXE" --dev-accept-state 2>/dev/null; }
mac_show(){ mac_command show; }
mac_hide(){ mac_command hide; }
mac_is_visible(){ mac_state | grep -q '^window_visible=true$'; }
mac_is_hidden(){ mac_state | grep -q '^window_visible=false$'; }

set_android_favorite(){ acc_sync dev.clipmesh.acceptance.SET_FAVORITE --es fingerprint "$1" --ez favorite "$2" >/dev/null; }
check_android_favorite(){ acc_sync dev.clipmesh.acceptance.CHECK_FAVORITE --es fingerprint "$1" | grep -q "^value=$2$"; }
set_mac_favorite(){ "$APP_EXE" --dev-accept-set-favorite "$1" "$2" >/dev/null 2>&1; }
set_android_policy(){ acc_sync dev.clipmesh.acceptance.SET_POLICY --es policy "$1" >/dev/null; }
set_mac_policy(){ "$APP_EXE" --dev-accept-policy "$1" >/dev/null 2>&1; }

wait_mac_text(){ expected="$1"; i=0; while [ "$i" -lt 120 ]; do [ "$(pbpaste 2>/dev/null)" = "$expected" ] && return 0; i=$((i+1)); sleep .15; done; return 1; }
wait_mac_image(){ i=0; while [ "$i" -lt 140 ]; do [ "$($PASTE image-info 2>/dev/null)" = "3x2" ] && return 0; i=$((i+1)); sleep .15; done; return 1; }
wait_android_open_text(){ expected="$1"; i=0; while [ "$i" -lt 120 ]; do out="$(acc_sync dev.clipmesh.acceptance.CHECK_TEXT --es expected_b64 "$(b64 "$expected")")"; printf '%s\n' "$out" | grep -q '^check_text=PASS$' && return 0; i=$((i+1)); sleep .15; done; return 1; }
wait_android_open_image(){ i=0; while [ "$i" -lt 140 ]; do out="$(acc_sync dev.clipmesh.acceptance.CHECK_IMAGE)"; printf '%s\n' "$out" | grep -q '^check_image=PASS$' && return 0; i=$((i+1)); sleep .15; done; return 1; }

set_state(){
  a="$1"; m="$2"
  if [ "$a" = open ]; then android_main; else android_background; fi
  if [ "$m" = open ]; then mac_show; else mac_hide; fi
}

clipboard_a2m_text(){ a="$1"; expected="$2"; printf '%s' "reset-$expected" | pbcopy; if [ "$a" = open ]; then acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$expected")" >/dev/null; else start_driver set_text "$expected"; fi; wait_mac_text "$expected"; }
clipboard_m2a_text(){ a="$1"; expected="$2"; if [ "$a" = open ]; then printf '%s' "$expected" | pbcopy; wait_android_open_text "$expected"; else start_driver wait_text "$expected"; wait_driver READY_TEXT || return 1; printf '%s' "$expected" | pbcopy; wait_driver PASS_TEXT; fi; }
clipboard_a2m_image(){ a="$1"; printf '%s' "reset-image-$(date +%s%N)" | pbcopy; if [ "$a" = open ]; then acc_sync dev.clipmesh.acceptance.SET_IMAGE >/dev/null; else start_driver set_image; fi; wait_mac_image; }
clipboard_m2a_image(){ a="$1"; if [ "$a" = open ]; then acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "image-reset-$(date +%s%N)")" >/dev/null; "$PASTE" set-image >/dev/null 2>&1; wait_android_open_image; else start_driver wait_image; wait_driver READY_IMAGE || return 1; "$PASTE" set-image >/dev/null 2>&1; wait_driver PASS_IMAGE; fi; }

section "PREFLIGHT AND PRIVILEGED CLIPBOARD"
info="$(acc_sync dev.clipmesh.acceptance.INFO)"
contains "$info" "fingerprint=$ANDROID_FP" && pass "Android acceptance control plane" || fail "Android acceptance control plane" "$info"
base_info="$("${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1; sleep .2; "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tr -d '\r')"
contains "$base_info" "shizuku_permission=true" && pass "Shizuku permission" || fail "Shizuku permission" "$base_info"
contains "$base_info" "background_status=Sync active" && pass "Android background clipboard runtime" || fail "Android background clipboard runtime" "$base_info"
lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1 && pass "Mac IPv4 file listener" || fail "Mac IPv4 file listener"
"${ADB[@]}" shell toybox nc -z -w 3 "$MAC_IP" 53421 >/dev/null 2>&1 && pass "Android reaches Mac file receiver" || fail "Android reaches Mac file receiver"
codesign --verify --deep --strict "$INSTALL_APP" >/dev/null 2>&1 && pass "macOS DEV code signing" || fail "macOS DEV code signing"

# Re-run direct Shizuku primitives.
SHI="acceptance-shizuku-$STAMP"
start_driver set_text "$SHI"; android_background
"${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.READ_SHIZUKU --es expected_b64 "$(b64 "$SHI")" >/dev/null 2>&1
sleep .4; shiout="$("${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tr -d '\r')"
contains "$shiout" "shizuku_read=PASS" && pass "Shizuku background read" || fail "Shizuku background read" "$shiout"
SHW="acceptance-shizuku-write-$STAMP"
"${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.WRITE_SHIZUKU --es expected_b64 "$(b64 "$SHW")" >/dev/null 2>&1
sleep .4; shwout="$("${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tr -d '\r')"
contains "$shwout" "shizuku_write=PASS" && pass "Shizuku clipboard write" || fail "Shizuku clipboard write" "$shwout"

section "NEARBY DEVICES - REAL UI LISTS AND ENGINE"
set_android_favorite "$MAC_FP" false
set_mac_favorite "$ANDROID_FP" false
acc_sync dev.clipmesh.acceptance.CLEAR_NEARBY >/dev/null
mac_command clear-nearby
android_main; mac_show
acc_sync dev.clipmesh.acceptance.DISCOVER >/dev/null; mac_command clipboard
sleep 2
ui="$(acc_sync dev.clipmesh.acceptance.UI_INFO)"; ms="$(mac_state)"
printf '%s\n' "$ui" | awk -F= '/clipboard_nearby_count=/{exit !($2>0)}' && pass "Android Clipboard nearby UI sees Mac - unfavorited" || fail "Android Clipboard nearby UI sees Mac - unfavorited" "$ui"
printf '%s\n' "$ms" | awk -F= '/clipboard_nearby_count=/{exit !($2>0)}' && pass "Mac Clipboard nearby UI sees Android - unfavorited" || fail "Mac Clipboard nearby UI sees Android - unfavorited" "$ms"
android_file; mac_command file; sleep 2
ui="$(acc_sync dev.clipmesh.acceptance.UI_INFO)"; ms="$(mac_state)"
printf '%s\n' "$ui" | awk -F= '/file_nearby_count=/{exit !($2>0)}' && pass "Android File Transfer nearby UI sees Mac - unfavorited" || fail "Android File Transfer nearby UI sees Mac - unfavorited" "$ui"
printf '%s\n' "$ms" | awk -F= '/file_nearby_count=/{exit !($2>0)}' && pass "Mac File Transfer nearby UI sees Android - unfavorited" || fail "Mac File Transfer nearby UI sees Android - unfavorited" "$ms"

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

section "CLIPBOARD - 16 FOREGROUND/BACKGROUND COMBINATIONS"
for astate in open background; do
  for mstate in open tray; do
    set_state "$astate" "$mstate"
    tag="A-$astate M-$mstate"
    v="clip-a2m-$astate-$mstate-$STAMP"
    clipboard_a2m_text "$astate" "$v" && pass "Clipboard text Android -> Mac [$tag]" || fail "Clipboard text Android -> Mac [$tag]"
    v="clip-m2a-$astate-$mstate-$STAMP"
    clipboard_m2a_text "$astate" "$v" && pass "Clipboard text Mac -> Android [$tag]" || fail "Clipboard text Mac -> Android [$tag]"
    set_state "$astate" "$mstate"
    clipboard_a2m_image "$astate" && pass "Clipboard image Android -> Mac [$tag]" || fail "Clipboard image Android -> Mac [$tag]"
    set_state "$astate" "$mstate"
    clipboard_m2a_image "$astate" && pass "Clipboard image Mac -> Android [$tag]" || fail "Clipboard image Mac -> Android [$tag]"
  done
done

section "CLIPBOARD ORDERING, BURST, DEDUPE AND ECHO"
android_main; mac_show
for value in "order-a-$STAMP" "order-b-$STAMP" "order-c-$STAMP"; do acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$value")" >/dev/null; sleep .25; done
wait_mac_text "order-c-$STAMP" && pass "Android -> Mac text ordering" || fail "Android -> Mac text ordering"
clipboard_a2m_image open >/dev/null 2>&1; acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "order-final-$STAMP")" >/dev/null
wait_mac_text "order-final-$STAMP" && pass "Android text -> image -> text ordering" || fail "Android text -> image -> text ordering"
for n in 0 1 2 3 4 5 6 7 8 9; do printf '%s' "burst-m2a-$n-$STAMP" | pbcopy; sleep .08; done
wait_android_open_text "burst-m2a-9-$STAMP" && pass "Mac -> Android rapid 10-event burst final state" || fail "Mac -> Android rapid 10-event burst final state"
for n in 0 1 2 3 4 5 6 7 8 9; do acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "burst-a2m-$n-$STAMP")" >/dev/null; sleep .08; done
wait_mac_text "burst-a2m-9-$STAMP" && pass "Android -> Mac rapid 10-event burst final state" || fail "Android -> Mac rapid 10-event burst final state"
printf '%s' "echo-stability-$STAMP" | pbcopy; wait_android_open_text "echo-stability-$STAMP" >/dev/null 2>&1
sleep 1; c1="$($PASTE change-count)"; sleep 2; c2="$($PASTE change-count)"; sleep 2; c3="$($PASTE change-count)"
[ "$c2" = "$c3" ] && pass "Clipboard echo/ping-pong settles" "changeCount $c1 -> $c2 -> $c3" || fail "Clipboard echo/ping-pong settles" "changeCount $c1 -> $c2 -> $c3"

# Helpers for deterministic file verification.
sha_file(){ shasum -a 256 "$1" | awk '{print $1}'; }
android_sha(){ "${ADB[@]}" exec-out cat "$1" 2>/dev/null | shasum -a 256 | awk '{print $1}'; }
make_file(){ path="$1"; size="$2"; seed="$3"; python3 - "$path" "$size" "$seed" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); n=int(sys.argv[2]); seed=int(sys.argv[3]); p.parent.mkdir(parents=True,exist_ok=True)
p.write_bytes(bytes(((i+seed)%251 for i in range(n))))
PY
}
wait_pending(){ i=0; while [ "$i" -lt 160 ]; do out="$(acc_sync dev.clipmesh.acceptance.PENDING)"; id="$(printf '%s\n' "$out" | sed -n 's/^pending=//p' | head -n1)"; [ -n "$id" ] && { printf '%s' "$id"; return 0; }; i=$((i+1)); sleep .15; done; return 1; }

send_a2m(){
  astate="$1"; mstate="$2"; mfav="$3"; prefix="$4"; size="${5:-257}"; count="${6:-1}"
  set_state "$astate" "$mstate"
  set_mac_policy "$( [ "$mfav" = true ] && printf '' || printf accept )"
  rm -f "$HOME/Downloads/ClipMesh/$prefix"*.bin 2>/dev/null || true
  acc_broadcast dev.clipmesh.acceptance.SEND_GENERATED --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_prefix "$prefix" --es extension bin --ei count "$count" --ei size "$size"
  out="$(acc_wait send_generated=)" || return 1
  printf '%s\n' "$out" | grep -q '^send_generated=PASS$' || return 1
  ok=1
  while IFS='|' read -r name hash bytes; do [ -n "$name" ] || continue; dest="$HOME/Downloads/ClipMesh/$name"; [ -f "$dest" ] && [ "$(sha_file "$dest")" = "$hash" ] || ok=0; done <<EOF
$(printf '%s\n' "$out" | sed -n 's/^file=//p')
EOF
  [ "$ok" -eq 1 ]
}

send_m2a(){
  mstate="$1"; astate="$2"; afav="$3"; prefix="$4"; size="${5:-263}"; count="${6:-1}"
  set_state "$astate" "$mstate"
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
      "${ADB[@]}" shell dumpsys notification --noredact 2>/dev/null | grep -q 'dev.clipmesh' && pass "Android background non-favorite receive posts notification" || fail "Android background non-favorite receive posts notification"
      NOTIFICATION_ACCEPT_RECORDED=1
    fi
    acc_sync dev.clipmesh.acceptance.RESOLVE_PENDING --es request_id "$req" --ez accept true >/dev/null
    wait "$pid"; rc=$?
  else
    eval '"$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP"' "$args" '>'"$STATE/m2a-$prefix.out"' 2>&1'; rc=$?
  fi
  [ "$rc" -eq 0 ] || return 1
  ok=1
  while IFS= read -r f; do [ -n "$f" ] || continue; name="$(basename "$f")"; remote="/sdcard/Download/ClipMesh/$name"; i=0; while [ "$i" -lt 80 ] && ! "${ADB[@]}" shell test -f "$remote" >/dev/null 2>&1; do i=$((i+1)); sleep .15; done; [ "$(android_sha "$remote")" = "$(sha_file "$f")" ] || ok=0; done <<EOF
$(printf '%b\n' "$files")
EOF
  [ "$ok" -eq 1 ]
}

section "FILE TRANSFER - COMPLETE FAVORITE/STATE MATRIX"
combo=0
for afav in false true; do
  for mfav in false true; do
    set_android_favorite "$MAC_FP" "$afav"
    set_mac_favorite "$ANDROID_FP" "$mfav"
    check_android_favorite "$MAC_FP" "$afav" && pass "Favorite state Android -> Mac [$afav/$mfav]" || fail "Favorite state Android -> Mac [$afav/$mfav]"
    for astate in open background; do
      for mstate in open tray; do
        combo=$((combo+1)); tag="A-fav-M=$afav M-fav-A=$mfav A=$astate M=$mstate"
        send_a2m "$astate" "$mstate" "$mfav" "fm-a2m-$combo-$STAMP" 257 1 && pass "File Android -> Mac [$tag]" || fail "File Android -> Mac [$tag]"
        send_m2a "$mstate" "$astate" "$afav" "fm-m2a-$combo-$STAMP" 263 1 && pass "File Mac -> Android [$tag]" || fail "File Mac -> Android [$tag]"
      done
    done
  done
done

section "FILE TRANSFER - EXPLICIT PROMPT, NOTIFICATION, ACCEPT AND REJECT"
set_android_favorite "$MAC_FP" false; set_mac_favorite "$ANDROID_FP" false
# Mac real non-favorite prompt Accept.
set_mac_policy accept; "$APP_EXE" --dev-accept-reset-metrics >/dev/null 2>&1; send_a2m open open false "prompt-mac-accept-$STAMP" 333 1
rc=$?; pc="$(mac_state | sed -n 's/^prompt_count=//p')"; [ "$rc" -eq 0 ] && [ "${pc:-0}" -gt 0 ] && pass "Mac foreground non-favorite real prompt Accept" || fail "Mac foreground non-favorite real prompt Accept" "prompt_count=$pc"
# Mac real prompt Reject leaves no received file.
set_mac_policy reject; prefix="prompt-mac-reject-$STAMP"; rm -f "$HOME/Downloads/ClipMesh/$prefix.bin"; acc_broadcast dev.clipmesh.acceptance.SEND_GENERATED --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_prefix "$prefix" --es extension bin --ei count 1 --ei size 347; out="$(acc_wait send_generated=)"; printf '%s\n' "$out" | grep -q '^send_generated=FAIL$' && [ ! -e "$HOME/Downloads/ClipMesh/$prefix.bin" ] && pass "Mac non-favorite real prompt Reject" || fail "Mac non-favorite real prompt Reject" "$out"
# Android foreground real dialog Reject.
android_main; set_android_policy reject; f="$STATE/android-fg-reject-$STAMP.bin"; make_file "$f" 359 51; "${ADB[@]}" shell rm -f "/sdcard/Download/ClipMesh/$(basename "$f")" >/dev/null 2>&1; "$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP" "$f" > "$STATE/android-fg-reject.out" 2>&1; rc=$?; [ "$rc" -ne 0 ] && ! "${ADB[@]}" shell test -f "/sdcard/Download/ClipMesh/$(basename "$f")" >/dev/null 2>&1 && pass "Android foreground non-favorite real dialog Reject" || fail "Android foreground non-favorite real dialog Reject"
# Android background notification Reject through real TransferActionReceiver.
android_background; set_android_policy ''; f="$STATE/android-bg-reject-$STAMP.bin"; make_file "$f" 367 57; "$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP" "$f" > "$STATE/android-bg-reject.out" 2>&1 & pid=$!; req="$(wait_pending)"; if [ -n "$req" ]; then "${ADB[@]}" shell dumpsys notification --noredact 2>/dev/null | grep -q 'dev.clipmesh' && notif=1 || notif=0; acc_sync dev.clipmesh.acceptance.RESOLVE_PENDING --es request_id "$req" --ez accept false >/dev/null; wait "$pid"; rc=$?; [ "$notif" -eq 1 ] && [ "$rc" -ne 0 ] && pass "Android background non-favorite notification Reject" || fail "Android background non-favorite notification Reject"; else kill "$pid" >/dev/null 2>&1 || true; fail "Android background non-favorite notification Reject" "no pending request"; fi

section "FILE TRANSFER - INTEGRITY, SIZE, MULTI-FILE, DUPLICATES AND MIME"
set_android_favorite "$MAC_FP" true; set_mac_favorite "$ANDROID_FP" true; set_android_policy ''; set_mac_policy ''
send_a2m background tray true "large-a2m-$STAMP" 1048576 1 && pass "1 MiB Android -> Mac SHA integrity" || fail "1 MiB Android -> Mac SHA integrity"
send_m2a tray background true "large-m2a-$STAMP" 1048576 1 && pass "1 MiB Mac -> Android SHA integrity" || fail "1 MiB Mac -> Android SHA integrity"
send_a2m background tray true "multi-a2m-$STAMP" 4096 3 && pass "3-file Android -> Mac batch" || fail "3-file Android -> Mac batch"
send_m2a tray background true "multi-m2a-$STAMP" 4096 3 && pass "3-file Mac -> Android batch" || fail "3-file Mac -> Android batch"
# Duplicate names must never overwrite the first received file.
dup="dup-a2m-$STAMP"; rm -f "$HOME/Downloads/ClipMesh/$dup"* 2>/dev/null; send_a2m background tray true "$dup" 777 1; r1=$?; send_a2m background tray true "$dup" 777 1; r2=$?; dc="$(find "$HOME/Downloads/ClipMesh" -maxdepth 1 -type f -name "$dup*" 2>/dev/null | wc -l | tr -d ' ')"; [ "$r1" -eq 0 ] && [ "$r2" -eq 0 ] && [ "$dc" -ge 2 ] && pass "Mac duplicate filename collision preservation" "files=$dc" || fail "Mac duplicate filename collision preservation" "files=$dc"
dup="dup-m2a-$STAMP"; "${ADB[@]}" shell rm -f "/sdcard/Download/ClipMesh/$dup"* >/dev/null 2>&1 || true; send_m2a tray background true "$dup" 781 1; r1=$?; send_m2a tray background true "$dup" 781 1; r2=$?; dc="$("${ADB[@]}" shell "find /sdcard/Download/ClipMesh -maxdepth 1 -type f -name '$dup*' 2>/dev/null | wc -l" | tr -d '\r ' )"; [ "$r1" -eq 0 ] && [ "$r2" -eq 0 ] && [ "${dc:-0}" -ge 2 ] && pass "Android duplicate filename collision preservation" "files=$dc" || fail "Android duplicate filename collision preservation" "files=$dc"
# PNG MIME route into Android Images folder.
png="$STATE/file-image-$STAMP.png"; python3 - "$png" <<'PY'
from pathlib import Path
import base64,sys
Path(sys.argv[1]).write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAYAAACddGYaAAAAFUlEQVR42mP8z8Dwn4GBgYGJAQoAHg0CAO3pP+0AAAAASUVORK5CYII='))
PY
android_background; "${ADB[@]}" shell rm -f "/sdcard/Download/ClipMesh/Images/$(basename "$png")" >/dev/null 2>&1; "$APP_EXE" --dev-accept-send-files "$ANDROID_IP" "$ANDROID_FP" "$png" >/dev/null 2>&1; rc=$?; [ "$rc" -eq 0 ] && "${ADB[@]}" shell test -f "/sdcard/Download/ClipMesh/Images/$(basename "$png")" >/dev/null 2>&1 && pass "Android image-file MIME routing" || fail "Android image-file MIME routing"

section "RESTART, REDISCOVERY AND PERSISTENCE"
set_android_favorite "$MAC_FP" true; set_mac_favorite "$ANDROID_FP" true
pkill -x ClipMesh >/dev/null 2>&1 || true; pkill -x clipmesh-bin >/dev/null 2>&1 || true; sleep .6; open -n "$INSTALL_APP"
i=0; while [ "$i" -lt 80 ] && ! lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1; do i=$((i+1)); sleep .2; done
lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1 && pass "Mac restart restores IPv4 file receiver" || fail "Mac restart restores IPv4 file receiver"
"${ADB[@]}" shell am force-stop dev.clipmesh >/dev/null 2>&1; sleep .5; android_main; android_background
sleep 1
check_android_favorite "$MAC_FP" true && pass "Android favorite persists across app restart" || fail "Android favorite persists across app restart"
mac_command snapshot; contains "$(mac_state)" "nearby=$ANDROID_FP|1|" && pass "Mac favorite/discovery persists after restart" || fail "Mac favorite/discovery persists after restart"
acc_sync dev.clipmesh.acceptance.DISCOVER >/dev/null; mac_command snapshot; sleep 2
contains "$(acc_sync dev.clipmesh.acceptance.INFO)" "nearby=$MAC_FP|" && pass "Android rediscovers Mac after restart" || fail "Android rediscovers Mac after restart"
contains "$(mac_state)" "nearby=$ANDROID_FP|" && pass "Mac rediscovers Android after restart" || fail "Mac rediscovers Android after restart"
set_state background tray
clipboard_a2m_text background "restart-a2m-$STAMP" && pass "Clipboard Android -> Mac after restart" || fail "Clipboard Android -> Mac after restart"
clipboard_m2a_text background "restart-m2a-$STAMP" && pass "Clipboard Mac -> Android after restart" || fail "Clipboard Mac -> Android after restart"
send_a2m background tray true "restart-file-a2m-$STAMP" 521 1 && pass "File Android -> Mac after restart" || fail "File Android -> Mac after restart"
send_m2a tray background true "restart-file-m2a-$STAMP" 523 1 && pass "File Mac -> Android after restart" || fail "File Mac -> Android after restart"

section "FINAL STABILITY AND FAILURE SCAN"
final_info="$("${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1; sleep .2; "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tr -d '\r')"
contains "$final_info" "shizuku_permission=true" && pass "Shizuku permission retained after full suite" || fail "Shizuku permission retained after full suite" "$final_info"
contains "$final_info" "background_status=Sync active" && pass "Android background sync active after full suite" || fail "Android background sync active after full suite" "$final_info"
"${ADB[@]}" shell dumpsys activity services dev.clipmesh 2>/dev/null | grep -q BackgroundService && pass "Android BackgroundService alive after full suite" || fail "Android BackgroundService alive after full suite"
"${ADB[@]}" shell dumpsys activity lastanr > "$STATE/comprehensive-lastanr-$STAMP.txt" 2>&1 || true
if grep -q 'dev.clipmesh' "$STATE/comprehensive-lastanr-$STAMP.txt"; then fail "Android ANR scan" "dev.clipmesh present in lastanr"; else pass "Android ANR scan"; fi
"${ADB[@]}" logcat -d -v threadtime > "$STATE/comprehensive-logcat-$STAMP.txt" 2>&1 || true
if grep -E 'FATAL EXCEPTION.*|Process: dev\.clipmesh|ANR in dev\.clipmesh' "$STATE/comprehensive-logcat-$STAMP.txt" >/dev/null 2>&1; then fail "Android fatal/ANR logcat scan"; else pass "Android fatal/ANR logcat scan"; fi
pgrep -x ClipMesh >/dev/null 2>&1 && pgrep -x clipmesh-bin >/dev/null 2>&1 && pass "Mac UI and clipboard daemon alive" || fail "Mac UI and clipboard daemon alive"
lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1 && pass "Mac file receiver alive at end" || fail "Mac file receiver alive at end"
codesign --verify --deep --strict "$INSTALL_APP" >/dev/null 2>&1 && pass "macOS code signature intact at end" || fail "macOS code signature intact at end"

section "COMPREHENSIVE PHYSICAL ACCEPTANCE MATRIX"
printf '%-7s  %-72s  %s\n' STATUS TEST DETAIL
printf '%-7s  %-72s  %s\n' '-------' '------------------------------------------------------------------------' '------'
while IFS=$'\t' read -r status name detail; do printf '%-7s  %-72s  %s\n' "$status" "$name" "$detail"; done < "$MATRIX"
printf '\nTOTAL PASSES:   %s\nTOTAL FAILURES: %s\n' "$PASSES" "$FAILURES"
printf 'Full log:       %s\nMatrix:         %s\n' "$LOG" "$MATRIX"
printf 'Android logcat: %s\n' "$STATE/comprehensive-logcat-$STAMP.txt"

if [ "$FAILURES" -eq 0 ]; then
  echo
  echo "ALL COMPREHENSIVE PHYSICAL CLIPMESH ACCEPTANCE TESTS PASSED"
  exit 0
fi

echo
echo "COMPREHENSIVE ACCEPTANCE FOUND $FAILURES FAILURE(S) - all independent scenarios were still executed."
exit 1
