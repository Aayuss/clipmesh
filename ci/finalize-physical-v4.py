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
    # back to Android repeatedly. Exact debug counters are sampled before the
    # first image event so even an immediate first bounce cannot hide behind a
    # later stable clipboard sample. Also exercise an EXIF-oriented Android JPEG.
    old = r'''printf '%s' "echo-stability-$STAMP" | pbcopy; wait_android_open_text "echo-stability-$STAMP" >/dev/null 2>&1
sleep 1; c1="$($PASTE change-count)"; sleep 2; c2="$($PASTE change-count)"; sleep 2; c3="$($PASTE change-count)"
[ "$c2" = "$c3" ] && pass "Clipboard echo/ping-pong settles" "changeCount $c1 -> $c2 -> $c3" || fail "Clipboard echo/ping-pong settles" "changeCount $c1 -> $c2 -> $c3"
'''
    new = old + r'''
android_ci_value(){
  key="$1"
  "${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a dev.clipmesh.devtest.INFO >/dev/null 2>&1
  sleep .18
  "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null \
    | tr -d '\r' | sed -n "s/^${key}=//p" | tail -n1
}

# Android -> Mac image: first establish a deterministic Mac -> Android TEXT
# barrier while ClipMesh itself is backgrounded. The foreground test driver owns
# the clipboard check, so this proves the encrypted clipboard connection is ready
# without incorrectly relying on a foreground-only acceptance receiver. Android
# then performs a LOCAL image copy. It must add exactly one outgoing event,
# with no remote apply and no later macOS pasteboard change.
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
image_a2m_outgoing_before="$(android_ci_value outgoing_clip_count)"
image_a2m_remote_before="$(android_ci_value remote_apply_count)"
start_driver set_image
wait_driver SET_IMAGE || { image_a2m_ready=0; image_a2m_reason="android-local-image-not-set"; }
if [ "$image_a2m_ready" -eq 1 ]; then
  wait_mac_image || { image_a2m_ready=0; image_a2m_reason="mac-image-not-received"; }
fi
image_a2m_mac_first="$($PASTE change-count)"
sleep 10
image_a2m_outgoing_after="$(android_ci_value outgoing_clip_count)"
image_a2m_remote_after="$(android_ci_value remote_apply_count)"
image_a2m_mac_after="$($PASTE change-count)"
[ "$image_a2m_ready" -eq 1 ] \
  && [ "$image_a2m_outgoing_after" -eq $((image_a2m_outgoing_before + 1)) ] \
  && [ "$image_a2m_remote_after" -eq "$image_a2m_remote_before" ] \
  && [ "$image_a2m_mac_after" -eq "$image_a2m_mac_first" ] \
  && pass "Android -> Mac image sends exactly once with no echo" "outgoing $image_a2m_outgoing_before -> $image_a2m_outgoing_after; remote applies $image_a2m_remote_before -> $image_a2m_remote_after; Mac changeCount $image_a2m_mac_first -> $image_a2m_mac_after" \
  || fail "Android -> Mac image sends exactly once with no echo" "ready=$image_a2m_ready reason=$image_a2m_reason outgoing $image_a2m_outgoing_before -> $image_a2m_outgoing_after remote applies $image_a2m_remote_before -> $image_a2m_remote_after Mac changeCount $image_a2m_mac_first -> $image_a2m_mac_after"

# Android JPEG with an EXIF 90-degree transform: a 2x3 encoded bitmap must
# arrive on macOS as 3x2. This directly covers sideways camera/gallery images.
image_orientation_reset="image-orientation-reset-$(nonce)"
image_orientation_ready=1
start_driver wait_text "$image_orientation_reset"
wait_driver READY_TEXT || image_orientation_ready=0
if [ "$image_orientation_ready" -eq 1 ]; then
  sleep .25
  printf '%s' "$image_orientation_reset" | pbcopy
  wait_driver PASS_TEXT || image_orientation_ready=0
fi
sleep .60
start_driver set_oriented_image
wait_driver SET_ORIENTED_IMAGE || image_orientation_ready=0
[ "$image_orientation_ready" -eq 1 ] && wait_mac_image \
  && pass "Android EXIF image orientation preserved" "2x3 JPEG plus rotate-90 EXIF arrived 3x2" \
  || fail "Android EXIF image orientation preserved" "expected oriented 3x2 image on Mac"

# Mac -> Android image: establish Android-local text first, then require exactly
# one remote apply, zero Android outgoing events, and an unchanged Mac pasteboard
# for 10 seconds. This catches repeated resend/toast loops in either direction.
image_m2a_reset="image-echo-m2a-reset-$(nonce)"
start_driver set_text "$image_m2a_reset"
image_m2a_ready=1
wait_driver SET_TEXT || image_m2a_ready=0
[ "$image_m2a_ready" -eq 1 ] && wait_mac_text "$image_m2a_reset" || image_m2a_ready=0
sleep .60
image_m2a_outgoing_before="$(android_ci_value outgoing_clip_count)"
image_m2a_remote_before="$(android_ci_value remote_apply_count)"
start_driver wait_image
wait_driver READY_IMAGE || image_m2a_ready=0
sleep .25
"$PASTE" set-image >/dev/null 2>&1
image_m2a_mac_first="$($PASTE change-count)"
wait_driver PASS_IMAGE || image_m2a_ready=0
sleep 10
image_m2a_outgoing_after="$(android_ci_value outgoing_clip_count)"
image_m2a_remote_after="$(android_ci_value remote_apply_count)"
image_m2a_mac_after="$($PASTE change-count)"
[ "$image_m2a_ready" -eq 1 ] \
  && [ "$image_m2a_remote_after" -eq $((image_m2a_remote_before + 1)) ] \
  && [ "$image_m2a_outgoing_after" -eq "$image_m2a_outgoing_before" ] \
  && [ "$image_m2a_mac_after" -eq "$image_m2a_mac_first" ] \
  && pass "Mac -> Android image applies exactly once with no echo" "remote applies $image_m2a_remote_before -> $image_m2a_remote_after; outgoing $image_m2a_outgoing_before -> $image_m2a_outgoing_after; Mac changeCount $image_m2a_mac_first -> $image_m2a_mac_after" \
  || fail "Mac -> Android image applies exactly once with no echo" "ready=$image_m2a_ready remote applies $image_m2a_remote_before -> $image_m2a_remote_after outgoing $image_m2a_outgoing_before -> $image_m2a_outgoing_after Mac changeCount $image_m2a_mac_first -> $image_m2a_mac_after"
'''
    text = replace_once(text, old, new, "delayed image echo physical coverage")

    text += "\n# PHYSICAL_HARDENING_V4_IMAGE_ECHO\n"
    for needle in (
        "Android -> Mac image sends exactly once with no echo",
        "Mac -> Android image applies exactly once with no echo",
        "Android EXIF image orientation preserved",
        "outgoing_clip_count",
        "remote_apply_count",
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
