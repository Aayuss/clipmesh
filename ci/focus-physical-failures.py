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
    # but exercise only the real-world image echo regression currently under
    # investigation. Do not make the user rerun already-green scenarios.
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
section "FOCUSED RETRY - IMAGE ECHO REGRESSION"
echo "Mode: two targeted image echo regression scenarios only"
echo "Final certification still requires ./dev-test-final.sh"

focused_android_remote_apply_at(){
  "${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1
  sleep .18
  "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null \
    | tr -d '\r' | sed -n 's/^last_remote_apply_at=//p' | tail -n1
}

set_android_favorite "$MAC_FP" true
set_mac_favorite "$ANDROID_FP" true
set_state background tray

# 1) Reproduce the user's Android -> Mac image loop exactly. A local Android
# image may arrive on Mac, but Mac must not mistake its re-encoded pasteboard
# representation for a fresh local copy and send it back to Android.
focused_a2m_reset="focused-image-a2m-reset-$(nonce)"
printf '%s' "$focused_a2m_reset" | pbcopy
focused_a2m_ready=1
wait_android_open_text "$focused_a2m_reset" >/dev/null 2>&1 || focused_a2m_ready=0
sleep 1
focused_a2m_before="$(focused_android_remote_apply_at)"
start_driver set_image
wait_driver SET_IMAGE || focused_a2m_ready=0
[ "$focused_a2m_ready" -eq 1 ] && wait_mac_image || focused_a2m_ready=0
sleep 10
focused_a2m_after="$(focused_android_remote_apply_at)"
[ "$focused_a2m_ready" -eq 1 ] \
  && [ -n "$focused_a2m_before" ] \
  && [ "$focused_a2m_before" = "$focused_a2m_after" ] \
  && pass "Android -> Mac image does not echo back to Android" "remote_apply_at $focused_a2m_before -> $focused_a2m_after" \
  || fail "Android -> Mac image does not echo back to Android" "ready=$focused_a2m_ready remote_apply_at $focused_a2m_before -> $focused_a2m_after"

# 2) A Mac-local image must be applied to Android once, then remain quiet. The
# timestamp is captured immediately after the first proven remote application
# and must not move again during the observation window.
focused_m2a_reset="focused-image-m2a-reset-$(nonce)"
start_driver set_text "$focused_m2a_reset"
focused_m2a_ready=1
wait_driver SET_TEXT || focused_m2a_ready=0
[ "$focused_m2a_ready" -eq 1 ] && wait_mac_text "$focused_m2a_reset" || focused_m2a_ready=0
sleep .60
focused_m2a_before="$(focused_android_remote_apply_at)"
start_driver wait_image
wait_driver READY_IMAGE || focused_m2a_ready=0
sleep .25
"$PASTE" set-image >/dev/null 2>&1
wait_driver PASS_IMAGE || focused_m2a_ready=0
sleep 1
focused_m2a_first="$(focused_android_remote_apply_at)"
sleep 10
focused_m2a_after="$(focused_android_remote_apply_at)"
[ "$focused_m2a_ready" -eq 1 ] \
  && [ -n "$focused_m2a_before" ] \
  && [ -n "$focused_m2a_first" ] \
  && [ "$focused_m2a_first" -gt "$focused_m2a_before" ] \
  && [ "$focused_m2a_first" = "$focused_m2a_after" ] \
  && pass "Mac -> Android image applies only once" "remote_apply_at $focused_m2a_before -> $focused_m2a_first -> $focused_m2a_after" \
  || fail "Mac -> Android image applies only once" "ready=$focused_m2a_ready remote_apply_at $focused_m2a_before -> $focused_m2a_first -> $focused_m2a_after"

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
  echo "ALL TARGETED IMAGE ECHO REGRESSION TESTS PASSED"
  echo "Next release gate: run the full ./dev-test-final.sh certification once."
  exit 0
fi

echo
echo "FOCUSED IMAGE ECHO RETRY FOUND $FAILURES FAILURE(S). Fix these before rerunning the full matrix."
exit 1

# FOCUSED_IMAGE_ECHO_V4
'''

    out = prefix + focused
    for needle in (
        "two targeted image echo regression scenarios only",
        "Android -> Mac image does not echo back to Android",
        "Mac -> Android image applies only once",
        "last_remote_apply_at=",
        "FOCUSED_IMAGE_ECHO_V4",
        "patch-acceptance-chain.py",
        'CLIPMESH_CODESIGN_IDENTITY="-"',
    ):
        if needle not in out:
            raise SystemExit(f"focused image runner guard missing: {needle}")

    # A focused retry must not grow back into the complete matrix.
    for forbidden in (
        "1 MiB Android -> Mac SHA integrity",
        "3-file Mac -> Android batch",
        'section "RESTART, REDISCOVERY AND PERSISTENCE"',
        'section "FINAL STABILITY AND FAILURE SCAN"',
        "Mac non-favorite real prompt Reject",
    ):
        if forbidden in focused:
            raise SystemExit(f"focused image runner unexpectedly contains full-matrix test: {forbidden}")

    dst.write_text(out, encoding="utf-8")
    print(f"Generated focused image echo regression runner: {dst}")


if __name__ == "__main__":
    main()
