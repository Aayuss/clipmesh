#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: finalize-physical-v4.py INPUT OUTPUT")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")

    # The previous full matrix only checked a TEXT ping-pong and only for four
    # seconds. A real-device regression proved that an IMAGE copied onto macOS
    # could be re-encoded, mistaken for a fresh local clipboard event, and sent
    # back to Android repeatedly. Use Android's existing debug apply timestamp to
    # prove both image directions remain quiet for a full 10-second observation.
    old = r'''printf '%s' "echo-stability-$STAMP" | pbcopy; wait_android_open_text "echo-stability-$STAMP" >/dev/null 2>&1
sleep 1; c1="$($PASTE change-count)"; sleep 2; c2="$($PASTE change-count)"; sleep 2; c3="$($PASTE change-count)"
[ "$c2" = "$c3" ] && pass "Clipboard echo/ping-pong settles" "changeCount $c1 -> $c2 -> $c3" || fail "Clipboard echo/ping-pong settles" "changeCount $c1 -> $c2 -> $c3"
'''
    new = old + r'''
android_remote_apply_at(){
  "${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1
  sleep .18
  "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null \
    | tr -d '\r' | sed -n 's/^last_remote_apply_at=//p' | tail -n1
}

# Android -> Mac image: first establish a deterministic Mac -> Android TEXT
# barrier while ClipMesh itself is backgrounded. The foreground test driver owns
# the clipboard check, so this proves the encrypted clipboard connection is ready
# without incorrectly relying on a foreground-only acceptance receiver. Android
# then performs a LOCAL image copy. Nothing should be remotely applied back to
# Android. Any change to last_remote_apply_at proves the Mac echoed it.
set_state background tray
image_a2m_reset="image-echo-a2m-reset-$(nonce)"
image_a2m_ready=1
image_a2m_reason="ready"
start_driver wait_text "$image_a2m_reset"
wait_driver READY_TEXT || { image_a2m_ready=0; image_a2m_reason="reset-driver-not-ready"; }
if [ "$image_a2m_ready" -eq 1 ]; then
  sleep .25
  printf '%s' "$image_a2m_reset" | pbcopy
  wait_driver PASS_TEXT || { image_a2m_ready=0; image_a2m_reason="reset-text-not-received"; }
fi
sleep 1
image_a2m_before="$(android_remote_apply_at)"
start_driver set_image
wait_driver SET_IMAGE || { image_a2m_ready=0; image_a2m_reason="android-local-image-not-set"; }
if [ "$image_a2m_ready" -eq 1 ]; then
  wait_mac_image || { image_a2m_ready=0; image_a2m_reason="mac-image-not-received"; }
fi
sleep 10
image_a2m_after="$(android_remote_apply_at)"
[ "$image_a2m_ready" -eq 1 ] \
  && [ -n "$image_a2m_before" ] \
  && [ "$image_a2m_before" = "$image_a2m_after" ] \
  && pass "Android -> Mac image does not echo back to Android" "remote_apply_at $image_a2m_before -> $image_a2m_after" \
  || fail "Android -> Mac image does not echo back to Android" "ready=$image_a2m_ready reason=$image_a2m_reason remote_apply_at $image_a2m_before -> $image_a2m_after"

# Mac -> Android image: establish Android-local text first, then wait for one
# remote image application. Once the first apply is observed, its timestamp must
# remain unchanged for 10 seconds. This catches repeated Mac resend/toast loops.
image_m2a_reset="image-echo-m2a-reset-$(nonce)"
start_driver set_text "$image_m2a_reset"
image_m2a_ready=1
wait_driver SET_TEXT || image_m2a_ready=0
[ "$image_m2a_ready" -eq 1 ] && wait_mac_text "$image_m2a_reset" || image_m2a_ready=0
sleep .60
image_m2a_before="$(android_remote_apply_at)"
start_driver wait_image
wait_driver READY_IMAGE || image_m2a_ready=0
sleep .25
"$PASTE" set-image >/dev/null 2>&1
wait_driver PASS_IMAGE || image_m2a_ready=0
sleep 1
image_m2a_first="$(android_remote_apply_at)"
sleep 10
image_m2a_after="$(android_remote_apply_at)"
[ "$image_m2a_ready" -eq 1 ] \
  && [ -n "$image_m2a_before" ] \
  && [ -n "$image_m2a_first" ] \
  && [ "$image_m2a_first" -gt "$image_m2a_before" ] \
  && [ "$image_m2a_first" = "$image_m2a_after" ] \
  && pass "Mac -> Android image applies only once" "remote_apply_at $image_m2a_before -> $image_m2a_first -> $image_m2a_after" \
  || fail "Mac -> Android image applies only once" "ready=$image_m2a_ready remote_apply_at $image_m2a_before -> $image_m2a_first -> $image_m2a_after"
'''
    text = replace_once(text, old, new, "delayed image echo physical coverage")

    text += "\n# PHYSICAL_HARDENING_V4_IMAGE_ECHO\n"
    for needle in (
        "Android -> Mac image does not echo back to Android",
        "Mac -> Android image applies only once",
        "last_remote_apply_at=",
        "start_driver wait_text",
        "reset-driver-not-ready",
        "sleep 10",
        "PHYSICAL_HARDENING_V4_IMAGE_ECHO",
    ):
        if needle not in text:
            raise SystemExit(f"physical v4 image-echo guard missing: {needle}")

    dst.write_text(text, encoding="utf-8")
    print(f"Applied delayed image-echo physical hardening: {dst}")


if __name__ == "__main__":
    main()
