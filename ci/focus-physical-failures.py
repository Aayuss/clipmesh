#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: focus-physical-failures.py FINALIZED_FULL_RUNNER OUTPUT")

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")

    # Reuse the exact finalized build/setup/helpers from the full physical suite,
    # but exercise only the five clipboard regressions affected by the scoped
    # desktop remote-write suppression change. Do not make the user rerun the
    # already-green file-transfer/discovery/prompt matrix while debugging.
    marker = 'section "PREFLIGHT AND PRIVILEGED CLIPBOARD"'
    if text.count(marker) != 1:
        raise SystemExit(f"focused runner prefix anchor: expected one match, found {text.count(marker)}")

    for needle in (
        "FINAL_COMPREHENSIVE_RUNNER_AUDIT_V1",
        "PHYSICAL_HARDENING_V2",
        "PHYSICAL_HARDENING_V3",
        "PHYSICAL_HARDENING_V4_IMAGE_ECHO",
        "wait_driver SET_IMAGE",
        "patch-acceptance-chain.py",
        'CLIPMESH_CODESIGN_IDENTITY="-"',
    ):
        if needle not in text:
            raise SystemExit(f"focused runner requires finalized physical hardening: {needle}")

    prefix = text.split(marker, 1)[0]

    focused = r'''
section "FOCUSED RETRY - ORDERING, BURST AND IMAGE ECHO"
echo "Mode: five targeted clipboard regression scenarios only"
echo "Final certification still requires ./dev-test-final.sh"

focused_android_ci_value(){
  key="$1"
  "${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1
  sleep .18
  "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null \
    | tr -d '\r' | sed -n "s/^${key}=//p" | tail -n1
}

set_android_favorite "$MAC_FP" true
set_mac_favorite "$ANDROID_FP" true
set_state open open

# 1) Reproduce the exact full-suite Android text -> image -> text sequence.
# Several Android text writes converge first, then the image edge is proven, then
# a fresh Android text must still reach the Mac after remote-write suppression.
focused_order_ready=1
for value in "focused-order-a-$STAMP" "focused-order-b-$STAMP" "focused-order-c-$STAMP"; do
  acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$value")" >/dev/null 2>&1 || focused_order_ready=0
  sleep .25
done
[ "$focused_order_ready" -eq 1 ] && wait_mac_text "focused-order-c-$STAMP" || focused_order_ready=0
clipboard_a2m_image open >/dev/null 2>&1 || focused_order_ready=0
sleep .60
focused_order_final="focused-order-final-$(nonce)"
acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$focused_order_final")" >/dev/null 2>&1 || focused_order_ready=0
[ "$focused_order_ready" -eq 1 ] \
  && wait_mac_text "$focused_order_final" \
  && pass "Android text -> image -> text ordering" \
  || fail "Android text -> image -> text ordering"

# 2) Prove a genuine Mac copy immediately after a reverse-direction barrier is
# never swallowed. The final burst value is left stable across several poller
# intervals, matching the full-suite convergence contract.
focused_burst_reset="focused-burst-reset-$(nonce)"; focused_burst_ready=1
acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$focused_burst_reset")" >/dev/null 2>&1 || focused_burst_ready=0
[ "$focused_burst_ready" -eq 1 ] && wait_mac_text "$focused_burst_reset" || focused_burst_ready=0
sleep .55
for n in 0 1 2 3 4 5 6 7 8 9; do printf '%s' "focused-burst-m2a-$n-$STAMP" | pbcopy; sleep .10; done
sleep .85
[ "$focused_burst_ready" -eq 1 ] \
  && wait_android_open_text "focused-burst-m2a-9-$STAMP" \
  && pass "Mac -> Android rapid 10-event burst final state" \
  || fail "Mac -> Android rapid 10-event burst final state"

set_state background tray

# 3) Reproduce the user's Android -> Mac image loop exactly. Establish the
# reverse-direction reset with the foreground test driver because ClipMesh itself
# is intentionally backgrounded here. Only after that barrier is proven do we
# perform the Android-local image copy and watch for a Mac echo.
focused_a2m_reset="focused-image-a2m-reset-$(nonce)"
focused_a2m_ready=1
focused_a2m_reason="ready"
start_driver wait_text "$focused_a2m_reset"
wait_driver READY_TEXT || { focused_a2m_ready=0; focused_a2m_reason="reset-driver-not-ready"; }
if [ "$focused_a2m_ready" -eq 1 ]; then
  sleep .25
  printf '%s' "$focused_a2m_reset" | pbcopy
  wait_driver PASS_TEXT || { focused_a2m_ready=0; focused_a2m_reason="reset-text-not-received"; }
fi
sleep 1
focused_a2m_outgoing_before="$(focused_android_ci_value outgoing_clip_count)"
focused_a2m_remote_before="$(focused_android_ci_value remote_apply_count)"
start_driver set_image
wait_driver SET_IMAGE || { focused_a2m_ready=0; focused_a2m_reason="android-local-image-not-set"; }
if [ "$focused_a2m_ready" -eq 1 ]; then
  wait_mac_image || { focused_a2m_ready=0; focused_a2m_reason="mac-image-not-received"; }
fi
focused_a2m_mac_first="$($PASTE change-count)"
sleep 10
focused_a2m_outgoing_after="$(focused_android_ci_value outgoing_clip_count)"
focused_a2m_remote_after="$(focused_android_ci_value remote_apply_count)"
focused_a2m_mac_after="$($PASTE change-count)"
[ "$focused_a2m_ready" -eq 1 ] \
  && [ "$focused_a2m_outgoing_after" -eq $((focused_a2m_outgoing_before + 1)) ] \
  && [ "$focused_a2m_remote_after" -eq "$focused_a2m_remote_before" ] \
  && [ "$focused_a2m_mac_after" -eq "$focused_a2m_mac_first" ] \
  && pass "Android -> Mac image sends exactly once with no echo" "outgoing $focused_a2m_outgoing_before -> $focused_a2m_outgoing_after; remote applies $focused_a2m_remote_before -> $focused_a2m_remote_after; Mac changeCount $focused_a2m_mac_first -> $focused_a2m_mac_after" \
  || fail "Android -> Mac image sends exactly once with no echo" "ready=$focused_a2m_ready reason=$focused_a2m_reason outgoing $focused_a2m_outgoing_before -> $focused_a2m_outgoing_after remote applies $focused_a2m_remote_before -> $focused_a2m_remote_after Mac changeCount $focused_a2m_mac_first -> $focused_a2m_mac_after"

# 4) A 2x3 JPEG with rotate-90 EXIF must arrive on the Mac as 3x2.
focused_orientation_reset="focused-orientation-reset-$(nonce)"
focused_orientation_ready=1
start_driver wait_text "$focused_orientation_reset"
wait_driver READY_TEXT || focused_orientation_ready=0
if [ "$focused_orientation_ready" -eq 1 ]; then
  sleep .25
  printf '%s' "$focused_orientation_reset" | pbcopy
  wait_driver PASS_TEXT || focused_orientation_ready=0
fi
sleep .60
start_driver set_oriented_image
wait_driver SET_ORIENTED_IMAGE || focused_orientation_ready=0
[ "$focused_orientation_ready" -eq 1 ] \
  && wait_mac_image \
  && pass "Android EXIF image orientation preserved" "2x3 JPEG plus rotate-90 EXIF arrived 3x2" \
  || fail "Android EXIF image orientation preserved" "expected oriented 3x2 image on Mac"

# 5) A Mac-local image must be applied to Android exactly once and must never
# become an Android outgoing event or cause another Mac pasteboard write.
focused_m2a_reset="focused-image-m2a-reset-$(nonce)"
start_driver set_text "$focused_m2a_reset"
focused_m2a_ready=1
wait_driver SET_TEXT || focused_m2a_ready=0
[ "$focused_m2a_ready" -eq 1 ] && wait_mac_text "$focused_m2a_reset" || focused_m2a_ready=0
sleep .60
focused_m2a_outgoing_before="$(focused_android_ci_value outgoing_clip_count)"
focused_m2a_remote_before="$(focused_android_ci_value remote_apply_count)"
start_driver wait_image
wait_driver READY_IMAGE || focused_m2a_ready=0
sleep .25
"$PASTE" set-image >/dev/null 2>&1
focused_m2a_mac_first="$($PASTE change-count)"
wait_driver PASS_IMAGE || focused_m2a_ready=0
sleep 10
focused_m2a_outgoing_after="$(focused_android_ci_value outgoing_clip_count)"
focused_m2a_remote_after="$(focused_android_ci_value remote_apply_count)"
focused_m2a_mac_after="$($PASTE change-count)"
[ "$focused_m2a_ready" -eq 1 ] \
  && [ "$focused_m2a_remote_after" -eq $((focused_m2a_remote_before + 1)) ] \
  && [ "$focused_m2a_outgoing_after" -eq "$focused_m2a_outgoing_before" ] \
  && [ "$focused_m2a_mac_after" -eq "$focused_m2a_mac_first" ] \
  && pass "Mac -> Android image applies exactly once with no echo" "remote applies $focused_m2a_remote_before -> $focused_m2a_remote_after; outgoing $focused_m2a_outgoing_before -> $focused_m2a_outgoing_after; Mac changeCount $focused_m2a_mac_first -> $focused_m2a_mac_after" \
  || fail "Mac -> Android image applies exactly once with no echo" "ready=$focused_m2a_ready remote applies $focused_m2a_remote_before -> $focused_m2a_remote_after outgoing $focused_m2a_outgoing_before -> $focused_m2a_outgoing_after Mac changeCount $focused_m2a_mac_first -> $focused_m2a_mac_after"

set_mac_policy '' >/dev/null 2>&1 || true
set_android_policy '' >/dev/null 2>&1 || true
rm -f "$PREP_STATE" >/dev/null 2>&1 || true

section "FOCUSED PHYSICAL RETRY MATRIX"
printf '%-7s  %-72s  %s\n' STATUS TEST DETAIL
printf '%-7s  %-72s  %s\n' '-------' '------------------------------------------------------------------------' '------'
while IFS=$'\t' read -r status name detail; do
  printf '%-7s  %-72s  %s\n' "$status" "$name" "$detail"
done < "$MATRIX"
printf '\nFOCUSED PASSES:   %s\nFOCUSED FAILURES: %s\n' "$PASSES" "$FAILURES"
printf 'Full log:         %s\nMatrix:           %s\n' "$LOG" "$MATRIX"

if [ "$FAILURES" -eq 0 ]; then
  echo
  echo "ALL FIVE TARGETED CLIPBOARD REGRESSION TESTS PASSED"
  echo "Next release gate: run the full ./dev-test-final.sh certification once."
  exit 0
fi

echo
echo "FOCUSED CLIPBOARD RETRY FOUND $FAILURES FAILURE(S). Fix these before rerunning the full matrix."
exit 1

# FOCUSED_SCOPED_REMOTE_WRITE_V5
'''

    out = prefix + focused
    for needle in (
        "five targeted clipboard regression scenarios only",
        "Android text -> image -> text ordering",
        "Mac -> Android rapid 10-event burst final state",
        "Android -> Mac image sends exactly once with no echo",
        "Android EXIF image orientation preserved",
        "Mac -> Android image applies exactly once with no echo",
        "outgoing_clip_count",
        "remote_apply_count",
        'start_driver wait_text "$focused_a2m_reset"',
        "reset-driver-not-ready",
        "FOCUSED_SCOPED_REMOTE_WRITE_V5",
        "patch-acceptance-chain.py",
        'CLIPMESH_CODESIGN_IDENTITY="-"',
    ):
        if needle not in out:
            raise SystemExit(f"focused clipboard runner guard missing: {needle}")

    # A focused retry must not grow back into the complete matrix.
    for forbidden in (
        "1 MiB Android -> Mac SHA integrity",
        "3-file Mac -> Android batch",
        'section "RESTART, REDISCOVERY AND PERSISTENCE"',
        'section "FINAL STABILITY AND FAILURE SCAN"',
        "Mac non-favorite real prompt Reject",
    ):
        if forbidden in focused:
            raise SystemExit(f"focused clipboard runner unexpectedly contains full-matrix test: {forbidden}")

    dst.write_text(out, encoding="utf-8")
    print(f"Generated focused five-scenario clipboard regression runner: {dst}")


if __name__ == "__main__":
    main()
