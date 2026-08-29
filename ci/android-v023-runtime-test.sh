#!/usr/bin/env bash
set -euo pipefail

APK=clipmesh/dist/android/ClipMesh-debug.apk
EXPECTED_VERSION=$("$ANDROID_HOME/cmdline-tools/latest/bin/apkanalyzer" manifest version-name "$APK")
test -n "$EXPECTED_VERSION"
adb install -r "$APK"
adb shell pm grant dev.clipmesh android.permission.POST_NOTIFICATIONS
adb shell rm -f /sdcard/Download/ClipMesh/ci-proof.txt 2>/dev/null || true

# Seed one trusted sender through a DEBUG-only hook. This lets CI exercise the
# same no-confirmation path used when the receiver has favorited the sender.
adb shell am start -W -n dev.clipmesh/.MainActivity --es clipmesh_ci_favorite ci-favorite-sender | tee /tmp/activity-start.txt
grep -q 'Status: ok' /tmp/activity-start.txt
sleep 3
adb shell dumpsys package dev.clipmesh | grep -Fq "versionName=$EXPECTED_VERSION"

# Prove the actual LocalTransferEngine is reachable while the UI is visible and
# that its discovery record advertises the visibility bit.
adb forward tcp:54321 tcp:53421
for i in $(seq 1 15); do
  if curl --fail --silent --max-time 2 http://127.0.0.1:54321/api/clipmesh/v1/info > /tmp/info-visible.json; then
    break
  fi
  sleep 1
done
python - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/info-visible.json')
assert p.exists() and p.stat().st_size, 'Android LocalTransferEngine /info never became reachable'
info = json.loads(p.read_text())
assert info['protocol'] == 'http'
assert int(info['port']) == 53421
assert info['fingerprint']
assert info.get('visible') is True, info
print('Android visible LocalTransferEngine endpoint is live')
PY

# Put ClipMesh definitively in the background. HOME is used instead of BACK so
# an incidental modal/dialog cannot consume the key and leave the Activity on
# screen. The persistent connected-device foreground service must keep clipboard
# sync and the file receiver alive while discovery advertises visible=false.
adb shell input keyevent KEYCODE_HOME
sleep 3
adb shell dumpsys activity activities > /tmp/activities.txt
cat /tmp/activities.txt
if grep -E 'mResumedActivity|topResumedActivity' /tmp/activities.txt | grep -q 'dev.clipmesh'; then
  echo 'ClipMesh Activity is still resumed after HOME'
  exit 1
fi
adb shell dumpsys activity services dev.clipmesh > /tmp/services.txt
cat /tmp/services.txt
grep -q 'BackgroundService' /tmp/services.txt
curl --fail --silent --max-time 3 http://127.0.0.1:54321/api/clipmesh/v1/info > /tmp/info-background.json
python - <<'PY'
import json
info = json.load(open('/tmp/info-background.json'))
assert info.get('visible') is False, info
print('Android receiver remains live with UI hidden and advertises visible=false')
PY

# Regression for the Android -> desktop bug: while every ClipMesh Activity is
# hidden, inject a DEBUG-only clipboard event through the same process-level
# BackgroundRuntime/ClipboardBridge path used by Accessibility. The outgoing
# callback records a debug marker immediately before the real network send.
CI_TEXT="clipmesh-ci-background-outgoing-$(date +%s%N)"
adb shell am broadcast \
  -a dev.clipmesh.action.CI_BACKGROUND_CAPTURE \
  --es text "$CI_TEXT" | tee /tmp/background-capture-broadcast.txt
OUTGOING_OK=0
for i in $(seq 1 30); do
  adb shell run-as dev.clipmesh cat shared_prefs/clipmesh_ci.xml > /tmp/clipmesh-ci-prefs.xml 2>/dev/null || true
  if grep -q 'last_outgoing_at' /tmp/clipmesh-ci-prefs.xml && \
     grep -Eq 'last_outgoing_representation_count[^>]*value="[1-9][0-9]*"' /tmp/clipmesh-ci-prefs.xml; then
    OUTGOING_OK=1
    break
  fi
  sleep 0.2
done
cat /tmp/clipmesh-ci-prefs.xml || true
test "$OUTGOING_OK" = 1
adb shell dumpsys activity activities > /tmp/activities-after-capture.txt
if grep -E 'mResumedActivity|topResumedActivity' /tmp/activities-after-capture.txt | grep -q 'dev.clipmesh'; then
  echo 'Background clipboard probe incorrectly opened ClipMesh UI'
  exit 1
fi
echo 'Android hidden-UI outgoing clipboard capture reached the network callback'

# The event-driven encrypted pairing listener shares the file receiver lifecycle.
# Its startup runs the on-device P-256/HKDF/encryption self-test first.
adb forward tcp:54322 tcp:53422
PAIR_STATUS=000
for i in $(seq 1 15); do
  PAIR_STATUS=$(curl --silent --max-time 2 -o /tmp/pair-invalid.json -w '%{http_code}' \
    -H 'Content-Type: application/json' --data '{}' \
    http://127.0.0.1:54322/api/clipmesh/v1/pair/start || true)
  if [ "$PAIR_STATUS" = 400 ]; then
    break
  fi
  sleep 1
done
test "$PAIR_STATUS" = 400
grep -q 'invalid request' /tmp/pair-invalid.json

# Exercise an unknown-sender request while there is no visible ClipMesh activity.
# prepare-upload waits for the user, so keep it open while checking the system
# notification. The notification must expose Accept and Reject actions.
cat > /tmp/prepare-unknown.json <<'JSON'
{"info":{"alias":"CI Sender","fingerprint":"ci-unknown-sender","port":53421,"protocol":"http","deviceModel":"CI","deviceType":"desktop","visible":true},"files":{"proof":{"id":"proof","fileName":"proof.txt","size":5,"fileType":"text/plain"}}}
JSON
curl --silent --max-time 12 -H 'Content-Type: application/json' --data-binary @/tmp/prepare-unknown.json http://127.0.0.1:54321/api/clipmesh/v1/prepare-upload >/tmp/prepare-unknown.out 2>/tmp/prepare-unknown.err &
REQUEST_PID=$!
sleep 3
(adb shell dumpsys notification --noredact || adb shell dumpsys notification) > /tmp/notifications.txt
cat /tmp/notifications.txt
grep -q 'CI Sender wants to send you proof.txt' /tmp/notifications.txt
grep -q 'dev.clipmesh' /tmp/notifications.txt
grep -q 'Accept' /tmp/notifications.txt
grep -q 'Reject' /tmp/notifications.txt
kill "$REQUEST_PID" 2>/dev/null || true
wait "$REQUEST_PID" 2>/dev/null || true

# Now perform a complete transfer from the sender that this Android device has
# favorited. It must prepare immediately without confirmation, accept actual file
# bytes while the UI is closed, and persist them into Downloads/ClipMesh.
printf 'hello' > /tmp/ci-proof.txt
cat > /tmp/prepare-favorite.json <<'JSON'
{"info":{"alias":"CI Favorite","fingerprint":"ci-favorite-sender","port":53421,"protocol":"http","deviceModel":"CI","deviceType":"desktop","visible":true},"files":{"proof":{"id":"proof","fileName":"ci-proof.txt","size":5,"fileType":"text/plain"}}}
JSON
FAVORITE_STATUS=$(curl --silent --max-time 10 -o /tmp/prepare-favorite.out -w '%{http_code}' \
  -H 'Content-Type: application/json' --data-binary @/tmp/prepare-favorite.json \
  http://127.0.0.1:54321/api/clipmesh/v1/prepare-upload)
test "$FAVORITE_STATUS" = 200
python - <<'PY' > /tmp/upload-path.txt
import json, urllib.parse
response = json.load(open('/tmp/prepare-favorite.out'))
sid = response['sessionId']
token = response['files']['proof']
print('/api/clipmesh/v1/upload?' + urllib.parse.urlencode({'sessionId': sid, 'fileId': 'proof', 'token': token}))
PY
UPLOAD_PATH=$(cat /tmp/upload-path.txt)
UPLOAD_STATUS=$(curl --silent --max-time 15 -o /tmp/upload.out -w '%{http_code}' \
  -H 'Content-Type: application/octet-stream' --data-binary @/tmp/ci-proof.txt \
  "http://127.0.0.1:54321${UPLOAD_PATH}")
case "$UPLOAD_STATUS" in 2??) ;; *) echo "favorite upload failed: HTTP $UPLOAD_STATUS"; cat /tmp/upload.out; exit 1;; esac
sleep 2
adb shell find /sdcard/Download/ClipMesh -type f -name 'ci-proof.txt' | tee /tmp/downloaded-files.txt
grep -q 'ci-proof.txt' /tmp/downloaded-files.txt
adb shell cat /sdcard/Download/ClipMesh/ci-proof.txt | tr -d '\r' | grep -qx 'hello'

echo 'Android background favorite transfer persisted successfully'

# After outgoing capture, an unknown request, and a full trusted upload, the
# service/listener must still be alive.
curl --fail --silent --max-time 3 http://127.0.0.1:54321/api/clipmesh/v1/info > /tmp/info-after.json
adb shell dumpsys activity services dev.clipmesh > /tmp/services-after.txt
grep -q 'BackgroundService' /tmp/services-after.txt

echo "Android $EXPECTED_VERSION emulator runtime smoke test: PASS"
