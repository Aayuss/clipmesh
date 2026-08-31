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

    # The focused retry runner intentionally reuses the exact same finalized
    # physical setup/build/helper code as the full certification suite. It then
    # executes only the scenarios that failed on the stale 518557e hardware run.
    # This keeps debugging fast without creating a second implementation of the
    # product setup or clipboard primitives.
    marker = 'section "PREFLIGHT AND PRIVILEGED CLIPBOARD"'
    if text.count(marker) != 1:
        raise SystemExit(f"focused runner prefix anchor: expected one match, found {text.count(marker)}")

    for needle in (
        "FINAL_COMPREHENSIVE_RUNNER_AUDIT_V1",
        "PHYSICAL_HARDENING_V2",
        "PHYSICAL_HARDENING_V3",
        'm2a-reset-$(nonce)',
        "wait_driver SET_IMAGE",
        "patch-acceptance-chain.py",
        "last_prompt_decision=",
        "CLIPMESH_CODESIGN_IDENTITY=\"-\"",
    ):
        if needle not in text:
            raise SystemExit(f"focused runner requires finalized physical hardening: {needle}")

    # Everything before PREFLIGHT is setup + the finalized shared helper
    # functions. No full-matrix assertion has run yet at this boundary.
    prefix = text.split(marker, 1)[0]

    focused = r'''
section "FOCUSED RETRY - PREVIOUS PHYSICAL FAILURES"
echo "Mode: six previously failing scenarios only"
echo "Final certification still requires ./dev-test-final.sh"

focused_discover_pair_once(){
  acc_sync dev.clipmesh.acceptance.DISCOVER >/dev/null 2>&1
  mac_command discover >/dev/null 2>&1
}
focused_android_has_mac(){
  focused_ai="$(acc_sync dev.clipmesh.acceptance.INFO)"
  contains "$focused_ai" "nearby=$MAC_FP|"
}
focused_wait_android_has_mac(){
  i=0
  while [ "$i" -lt 20 ]; do
    focused_android_has_mac && return 0
    focused_discover_pair_once
    i=$((i+1))
    sleep .25
  done
  return 1
}
focused_mac_file_visible(){
  mac_command file >/dev/null 2>&1 || return 1
  mac_state | awk -F= '/file_nearby_count=/{exit !($2>0)}'
}

# 1) macOS File Transfer must render the already-paired Android receiver.
set_android_favorite "$MAC_FP" false
set_mac_favorite "$ANDROID_FP" false
acc_sync dev.clipmesh.acceptance.CLEAR_NEARBY >/dev/null
mac_command clear-nearby >/dev/null 2>&1
android_file
mac_command file >/dev/null 2>&1
focused_discover_pair_once
wait_until 50 focused_mac_file_visible \
  && pass "Mac File Transfer UI shows paired Android as live target" \
  || fail "Mac File Transfer UI shows paired Android as live target" "$(mac_state)"

# 2) Android discovery must continue when both app UIs are hidden.
set_android_favorite "$MAC_FP" true
set_mac_favorite "$ANDROID_FP" true
android_background
mac_hide
acc_sync dev.clipmesh.acceptance.CLEAR_NEARBY >/dev/null
mac_command clear-nearby >/dev/null 2>&1
focused_discover_pair_once
focused_wait_android_has_mac
adr=$?
ai="$(acc_sync dev.clipmesh.acceptance.INFO)"
[ "$adr" -eq 0 ] && contains "$ai" "nearby=$MAC_FP|" \
  && pass "Android file discovery survives both UIs hidden" \
  || fail "Android file discovery survives both UIs hidden" "$ai"

# 3) The first open/open Mac -> Android text edge must cross cleanly.
set_state open open
focused_text="focused-m2a-open-open-$STAMP"
clipboard_m2a_text open "$focused_text" \
  && pass "Clipboard text Mac -> Android [A-open M-open]" \
  || fail "Clipboard text Mac -> Android [A-open M-open]"

# 4) Android text -> image -> text must preserve final ordering.
set_state open open
order_image_ok=0
clipboard_a2m_image open >/dev/null 2>&1 && order_image_ok=1
sleep .60
focused_order="focused-order-final-$STAMP"
acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$focused_order")" >/dev/null
[ "$order_image_ok" -eq 1 ] && wait_mac_text "$focused_order" \
  && pass "Android text -> image -> text ordering" \
  || fail "Android text -> image -> text ordering"

# 5) Rapid Mac -> Android changes need only guarantee final stable state.
burst_reset="focused-burst-reset-$(nonce)"
burst_ready=1
acc_sync dev.clipmesh.acceptance.SET_TEXT --es expected_b64 "$(b64 "$burst_reset")" >/dev/null || burst_ready=0
[ "$burst_ready" -eq 1 ] && wait_mac_text "$burst_reset" || burst_ready=0
sleep .55
for n in 0 1 2 3 4 5 6 7 8 9; do
  printf '%s' "focused-burst-m2a-$n-$STAMP" | pbcopy
  sleep .10
done
sleep .85
[ "$burst_ready" -eq 1 ] && wait_android_open_text "focused-burst-m2a-9-$STAMP" \
  && pass "Mac -> Android rapid 10-event burst final state" \
  || fail "Mac -> Android rapid 10-event burst final state"

# 6) The real macOS non-favorite prompt must actually click Reject.
set_state open open
set_android_favorite "$MAC_FP" false
set_mac_favorite "$ANDROID_FP" false
"$APP_EXE" --dev-accept-reset-metrics >/dev/null 2>&1
set_mac_policy reject
focused_prefix="focused-prompt-mac-reject-$STAMP"
rm -f "$HOME/Downloads/ClipMesh/$focused_prefix.bin"
acc_broadcast dev.clipmesh.acceptance.SEND_GENERATED \
  --es address "$MAC_IP" \
  --es fingerprint "$MAC_FP" \
  --es file_prefix "$focused_prefix" \
  --es extension bin \
  --ei count 1 \
  --ei size 347
focused_out="$(acc_wait send_generated=)"
focused_ms="$(mac_state)"
focused_pc="$(printf '%s\n' "$focused_ms" | sed -n 's/^prompt_count=//p')"
focused_decision="$(printf '%s\n' "$focused_ms" | sed -n 's/^last_prompt_decision=//p')"
printf '%s\n' "$focused_out" | grep -q '^send_generated=FAIL$' \
  && [ ! -e "$HOME/Downloads/ClipMesh/$focused_prefix.bin" ] \
  && [ "${focused_pc:-0}" -gt 0 ] \
  && [ "$focused_decision" = reject ] \
  && pass "Mac non-favorite real prompt Reject" \
  || fail "Mac non-favorite real prompt Reject" "sender=$(printf '%s' "$focused_out" | tr '\n' ' ') prompts=$focused_pc decision=$focused_decision"

# Do not leave automated rejection enabled after a focused retry.
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
  echo "ALL FOCUSED PREVIOUS-FAILURE TESTS PASSED"
  echo "Next release gate: run the full ./dev-test-final.sh certification once."
  exit 0
fi

echo
echo "FOCUSED RETRY FOUND $FAILURES FAILURE(S). Fix these before rerunning the full matrix."
exit 1

# FOCUSED_PREVIOUS_FAILURES_V1
'''

    out = prefix + focused
    for needle in (
        "Mac File Transfer UI shows paired Android as live target",
        "Android file discovery survives both UIs hidden",
        "Clipboard text Mac -> Android [A-open M-open]",
        "Android text -> image -> text ordering",
        "Mac -> Android rapid 10-event burst final state",
        "Mac non-favorite real prompt Reject",
        "FOCUSED_PREVIOUS_FAILURES_V1",
    ):
        if needle not in out:
            raise SystemExit(f"focused runner guard missing: {needle}")

    dst.write_text(out, encoding="utf-8")
    print(f"Generated focused previous-failure physical runner: {dst}")


if __name__ == "__main__":
    main()
