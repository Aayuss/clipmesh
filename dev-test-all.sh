#!/usr/bin/env bash
# Runs the canonical dev-test setup/build, then replaces only the functional
# E2E tail with a non-stop matrix runner. Environment/build prerequisites may
# still hard-fail, but once physical tests begin every independent check runs.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
STATE="${CLIPMESH_DEV_STATE:-$HOME/.clipmesh-dev}"
mkdir -p "$STATE"
RUNTIME="$STATE/dev-test-all-runtime.sh"

python3 - "$ROOT/dev-test.sh" "$RUNTIME" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")
marker = 'NONCE="$(date +%s)-$$"; say "Running physical clipboard E2E..."'
pos = src.find(marker)
if pos < 0:
    raise SystemExit("dev-test-all: canonical functional-test marker not found")

head = src[:pos]
tail = r'''NONCE="$(date +%s)-$$"
MATRIX="$STATE/physical-test-matrix.txt"
: > "$MATRIX"
FAILURES=0

record_pass(){
  name="$1"; detail="${2:-}"
  printf 'PASS|%s|%s\n' "$name" "$detail" >> "$MATRIX"
  say "PASS $name${detail:+ - $detail}"
}
record_fail(){
  name="$1"; detail="${2:-}"
  printf 'FAIL|%s|%s\n' "$name" "$detail" >> "$MATRIX"
  FAILURES=$((FAILURES + 1))
  say "FAIL $name${detail:+ - $detail}"
}
wait_file_contains(){
  needle="$1"; i=0
  while [ "$i" -lt 120 ]; do
    value="$(read_info || true)"
    printf '%s\n' "$value" | grep -q "$needle" && return 0
    printf '%s\n' "$value" | grep -q '^.*=FAIL' && return 1
    i=$((i+1)); sleep .15
  done
  return 1
}
clipmesh_is_hidden(){
  ! "${ADB[@]}" shell dumpsys activity activities 2>/dev/null \
    | grep -E 'mResumedActivity|topResumedActivity' \
    | grep -q 'dev\.clipmesh/'
}
wait_mac_text(){
  expected="$1"; i=0
  while [ "$i" -lt 120 ]; do
    [ "$(pbpaste 2>/dev/null || true)" = "$expected" ] && return 0
    i=$((i+1)); sleep .15
  done
  return 1
}

say ""
say "============================================================"
say " PHYSICAL E2E - RUN ALL CHECKS BEFORE EXITING"
say "============================================================"
"${ADB[@]}" logcat -c >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Primitive 0A: prove Shizuku can READ while another app is foreground.
# ---------------------------------------------------------------------------
say "Running direct Shizuku background-read probe..."
READ_PROBE="clipmesh-shizuku-read-$NONCE"
if start_driver set_text "$READ_PROBE"; then
  sleep .35
  dev_broadcast dev.clipmesh.devtest.READ_SHIZUKU --es expected_b64 "$(b64 "$READ_PROBE")" || true
  if wait_file_contains '^shizuku_read=PASS'; then
    record_pass "Shizuku background read"
  else
    printf '%s\n' "$(read_info || true)" >> "$LOG"
    record_fail "Shizuku background read" "privileged read did not return expected text"
  fi
else
  record_fail "Shizuku background read" "test driver could not seed clipboard"
fi

# ---------------------------------------------------------------------------
# Primitive 0B: prove the pre-v034 Shizuku WRITE behavior still works.
# ---------------------------------------------------------------------------
say "Running direct Shizuku write probe..."
WRITE_PROBE="clipmesh-shizuku-write-$NONCE"
write_ready=0
if start_driver wait_text "$WRITE_PROBE" && wait_driver READY_TEXT; then
  write_ready=1
fi
if [ "$write_ready" -eq 1 ]; then
  dev_broadcast dev.clipmesh.devtest.WRITE_SHIZUKU --es expected_b64 "$(b64 "$WRITE_PROBE")" || true
  write_control=0; write_clip=0; i=0
  while [ "$i" -lt 150 ]; do
    info_now="$(read_info || true)"
    printf '%s\n' "$info_now" | grep -q '^shizuku_write=PASS' && write_control=1
    result_now="$(driver_result || true)"
    case "$result_now" in PASS_TEXT*) write_clip=1;; esac
    [ "$write_control" -eq 1 ] && [ "$write_clip" -eq 1 ] && break
    printf '%s\n' "$info_now" | grep -q '^shizuku_write=FAIL' && break
    i=$((i+1)); sleep .12
  done
  if [ "$write_control" -eq 1 ] && [ "$write_clip" -eq 1 ]; then
    record_pass "Shizuku clipboard write"
  else
    printf 'write-control=%s driver=%s\n' "$(read_info || true)" "$(driver_result || true)" >> "$LOG"
    record_fail "Shizuku clipboard write" "control=$write_control observed=$write_clip"
  fi
else
  record_fail "Shizuku clipboard write" "test driver never became ready"
fi

say "Running physical clipboard E2E..."

# ---------------------------------------------------------------------------
# 1/6 Android -> Mac text
# ---------------------------------------------------------------------------
A2M="clipmesh-android-to-mac-$NONCE"
if start_driver set_text "$A2M" && wait_mac_text "$A2M"; then
  if clipmesh_is_hidden; then
    record_pass "Android -> Mac text"
  else
    record_fail "Android -> Mac text" "ClipMesh became foreground"
  fi
else
  record_fail "Android -> Mac text" "Mac pasteboard did not receive expected nonce"
fi

# ---------------------------------------------------------------------------
# 2/6 Mac -> Android text
# Unique nonce means polling actual foreground clipboard is deterministic.
# ---------------------------------------------------------------------------
M2A="clipmesh-mac-to-android-$NONCE"
m2a_ready=0
if start_driver wait_text "$M2A" && wait_driver READY_TEXT; then m2a_ready=1; fi
if [ "$m2a_ready" -eq 1 ]; then
  sleep .4
  printf '%s' "$M2A" | pbcopy
  if wait_driver PASS_TEXT; then
    record_pass "Mac -> Android text"
  else
    refresh_info > "$STATE/m2a-text-runtime-info.txt" 2>/dev/null || true
    "$CLI_EXE" status > "$STATE/m2a-text-mac-status.txt" 2>&1 || true
    record_fail "Mac -> Android text" "Android foreground clipboard never matched expected nonce"
  fi
else
  record_fail "Mac -> Android text" "test driver never became ready"
fi

# ---------------------------------------------------------------------------
# 3/6 Android -> Mac image
# Reset Mac clipboard so a stale 3x2 image cannot produce a false pass.
# ---------------------------------------------------------------------------
printf '%s' "mac-image-reset-$NONCE" | pbcopy
sleep .25
A2M_IMAGE_OK=0
if start_driver set_image; then
  i=0
  while [ "$i" -lt 150 ]; do
    [ "$($PASTE image-info 2>/dev/null || true)" = "3x2" ] && { A2M_IMAGE_OK=1; break; }
    i=$((i+1)); sleep .15
  done
fi
if [ "$A2M_IMAGE_OK" -eq 1 ]; then
  record_pass "Android -> Mac image"
else
  record_fail "Android -> Mac image" "Mac did not receive 3x2 image"
fi

# ---------------------------------------------------------------------------
# 4/6 Mac -> Android image
# First replace Android's prior 3x2 image with unique text. This removes stale
# image state before arming the image receiver.
# ---------------------------------------------------------------------------
IMAGE_RESET="clipmesh-image-reset-$NONCE"
reset_seeded=0
if start_driver set_text "$IMAGE_RESET"; then
  reset_seeded=1
  wait_mac_text "$IMAGE_RESET" || true
fi
M2A_IMAGE_OK=0
if [ "$reset_seeded" -eq 1 ] && start_driver wait_image && wait_driver READY_IMAGE; then
  sleep .4
  "$PASTE" set-image >/dev/null 2>>"$LOG" || true
  wait_driver PASS_IMAGE && M2A_IMAGE_OK=1
fi
if [ "$M2A_IMAGE_OK" -eq 1 ]; then
  record_pass "Mac -> Android image"
else
  record_fail "Mac -> Android image" "new image was not observed after explicit text reset"
fi

say "Running physical file-transfer E2E..."

# Shared file-transfer preparation. Failures here are recorded, not terminal.
FILE_SETUP_OK=1
dev_broadcast dev.clipmesh.devtest.FAVORITE --es fingerprint "$MAC_FP" || FILE_SETUP_OK=0
"$APP_EXE" --dev-test-favorite "$ANDROID_FP" >> "$LOG" 2>&1 || FILE_SETUP_OK=0
pkill -x ClipMesh >/dev/null 2>&1 || true
pkill -x clipmesh-bin >/dev/null 2>&1 || true
sleep .4
open "$INSTALL_APP" || FILE_SETUP_OK=0
wait_mac || FILE_SETUP_OK=0
i=0
while [ "$i" -lt 40 ] && ! lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1; do i=$((i+1)); sleep .25; done
lsof -nP -i4TCP:53421 -sTCP:LISTEN >/dev/null 2>&1 || FILE_SETUP_OK=0
if [ "$FILE_SETUP_OK" -eq 1 ]; then
  record_pass "File-transfer setup" "peers favorited and Mac IPv4 listener active"
else
  record_fail "File-transfer setup" "one or more shared prerequisites failed"
fi

# ---------------------------------------------------------------------------
# 5/6 Android -> Mac file, exact bytes
# ---------------------------------------------------------------------------
A2M_FILE="clipmesh-a2m-$NONCE.bin"
A2M_PAYLOAD="android-to-mac-$NONCE-$(openssl rand -hex 32)"
A2M_DEST="$HOME/Downloads/ClipMesh/$A2M_FILE"
rm -f "$A2M_DEST"
A2M_FILE_OK=0
if dev_broadcast dev.clipmesh.devtest.SEND_FILE --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_name "$A2M_FILE" --es payload_b64 "$(b64 "$A2M_PAYLOAD")"; then
  i=0
  while [ "$i" -lt 180 ]; do
    if [ -f "$A2M_DEST" ] && [ "$(cat "$A2M_DEST" 2>/dev/null || true)" = "$A2M_PAYLOAD" ]; then
      A2M_FILE_OK=1; break
    fi
    send_state="$(read_info || true)"
    printf '%s\n' "$send_state" | grep -q '^send=FAIL' && break
    i=$((i+1)); sleep .2
  done
fi
if [ "$A2M_FILE_OK" -eq 1 ]; then
  record_pass "Android -> Mac file" "exact bytes verified"
else
  printf '%s\n' "$(read_info || true)" > "$STATE/a2m-file-result.txt"
  record_fail "Android -> Mac file" "exact-byte transfer failed"
fi

# ---------------------------------------------------------------------------
# 6/6 Mac -> Android file, SHA256
# ---------------------------------------------------------------------------
M2A_FILE="clipmesh-m2a-$NONCE.bin"
M2A_LOCAL="$STATE/$M2A_FILE"
M2A_REMOTE="/sdcard/Download/ClipMesh/$M2A_FILE"
printf '%s' "mac-to-android-$NONCE-$(openssl rand -hex 32)" > "$M2A_LOCAL"
"${ADB[@]}" shell rm -f "$M2A_REMOTE" >/dev/null 2>&1 || true
M2A_FILE_OK=0
if "$APP_EXE" --dev-test-send-file "$M2A_LOCAL" "$ANDROID_IP" "$ANDROID_FP" >> "$LOG" 2>&1; then
  local_hash="$(shasum -a 256 "$M2A_LOCAL" | awk '{print $1}')"
  i=0
  while [ "$i" -lt 180 ]; do
    if "${ADB[@]}" shell test -f "$M2A_REMOTE" >/dev/null 2>&1; then
      remote_hash="$("${ADB[@]}" exec-out cat "$M2A_REMOTE" 2>/dev/null | shasum -a 256 | awk '{print $1}')"
      [ "$remote_hash" = "$local_hash" ] && { M2A_FILE_OK=1; break; }
    fi
    i=$((i+1)); sleep .2
  done
fi
if [ "$M2A_FILE_OK" -eq 1 ]; then
  record_pass "Mac -> Android file" "SHA256 verified"
else
  record_fail "Mac -> Android file" "SHA256 transfer verification failed"
fi

# ---------------------------------------------------------------------------
# Postconditions + comprehensive diagnostics. Always collect them.
# ---------------------------------------------------------------------------
if "${ADB[@]}" shell dumpsys activity services dev.clipmesh 2>/dev/null | grep -q BackgroundService; then
  record_pass "Android background service"
else
  record_fail "Android background service" "service stopped during E2E"
fi

refresh_info > "$STATE/android-final-info.txt" 2>/dev/null || true
if grep -q '^shizuku_permission=true' "$STATE/android-final-info.txt" 2>/dev/null; then
  record_pass "Shizuku permission retained"
else
  record_fail "Shizuku permission retained" "permission unavailable after E2E"
fi

"${ADB[@]}" logcat -d -v threadtime > "$STATE/android-all-e2e-logcat.txt" 2>&1 || true
"${ADB[@]}" shell dumpsys activity lastanr > "$STATE/android-all-e2e-lastanr.txt" 2>&1 || true
"${ADB[@]}" shell dumpsys activity services dev.clipmesh > "$STATE/android-all-e2e-services.txt" 2>&1 || true
{
  echo '--- CLI status ---'
  "$CLI_EXE" status 2>&1 || true
  echo '--- Mac processes ---'
  pgrep -alf 'ClipMesh|clipmesh-bin' || true
  echo '--- Mac listeners ---'
  lsof -nP -iTCP:41474 -sTCP:LISTEN || true
  lsof -nP -i4TCP:53421 -sTCP:LISTEN || true
  lsof -nP -i6TCP:53421 -sTCP:LISTEN || true
} > "$STATE/macos-all-e2e-state.txt" 2>&1
MLOG="$HOME/Library/Application Support/dev.ClipMesh.ClipMesh/clipmesh.log"
[ ! -f "$MLOG" ] || tail -n 1000 "$MLOG" > "$STATE/macos-all-e2e-log.txt" 2>&1 || true

# Current-run ANRs are visible in the cleared logcat even if dumpsys lastanr has
# historical data. Count a new ClipMesh ANR as a matrix failure.
if grep -E 'ANR in dev\.clipmesh|ANR.*dev\.clipmesh|Input dispatching timed out.*dev\.clipmesh' "$STATE/android-all-e2e-logcat.txt" >/dev/null 2>&1; then
  record_fail "Android ANR check" "current-run ANR found in cleared logcat"
else
  record_pass "Android ANR check"
fi

codesign --verify --deep --strict "$INSTALL_APP" >> "$LOG" 2>&1 || record_fail "macOS code signature" "installed development app failed verification"

say ""
say "============================================================"
say " PHYSICAL TEST MATRIX"
say "============================================================"
while IFS='|' read -r status name detail; do
  printf '%-5s  %-31s %s\n' "$status" "$name" "$detail" | tee -a "$LOG"
done < "$MATRIX"
say "------------------------------------------------------------"
say "TOTAL FAILURES: $FAILURES"
say ""
say "Android runtime info: $STATE/android-final-info.txt"
say "Android logcat:       $STATE/android-all-e2e-logcat.txt"
say "Android last ANR:     $STATE/android-all-e2e-lastanr.txt"
say "Mac runtime state:    $STATE/macos-all-e2e-state.txt"
say "Mac log:              $STATE/macos-all-e2e-log.txt"
say "Full harness log:     $LOG"

trap - EXIT
if [ "$FAILURES" -eq 0 ]; then
  say ""
  say "ALL PHYSICAL CLIPMESH TESTS PASSED"
  say "Android permanent signing: $ANDROID_KEYSTORE"
  say "macOS fixed install: $INSTALL_APP"
  exit 0
fi

say ""
say "PHYSICAL CLIPMESH TESTS FINISHED WITH $FAILURES FAILURE(S)"
exit 1
'''

Path(sys.argv[2]).write_text(head + tail, encoding="utf-8")
PY

chmod +x "$RUNTIME"
exec /bin/bash "$RUNTIME"
