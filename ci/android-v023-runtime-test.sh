#!/usr/bin/env bash
set -euo pipefail

APK=clipmesh/dist/android/ClipMesh-debug.apk
adb install -r "$APK"
adb shell pm grant dev.clipmesh android.permission.POST_NOTIFICATIONS

adb shell am start -W -n dev.clipmesh/.MainActivity | tee /tmp/activity-start.txt
grep -q 'Status: ok' /tmp/activity-start.txt
sleep 3
adb shell dumpsys package dev.clipmesh | grep -q 'versionName=0.2.3'

# Close the visible UI. The persistent connected-device foreground service must
# continue owning the clipboard runtime and the LocalTransferEngine listener.
adb shell input keyevent KEYCODE_BACK
sleep 3
adb shell dumpsys activity services dev.clipmesh > /tmp/services.txt
cat /tmp/services.txt
grep -q 'BackgroundService' /tmp/services.txt

# Prove the actual Android LocalTransferEngine is reachable after the UI closes.
adb forward tcp:54321 tcp:53317
for i in $(seq 1 15); do
  if curl --fail --silent --max-time 2 http://127.0.0.1:54321/api/localsend/v2/info > /tmp/info.json; then
    break
  fi
  sleep 1
done
python - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/info.json')
assert p.exists() and p.stat().st_size, 'Android LocalTransferEngine /info never became reachable'
info = json.loads(p.read_text())
assert info['protocol'] == 'http'
assert int(info['port']) == 53317
assert info['fingerprint']
print('Android background LocalTransferEngine endpoint is live after UI close')
PY

# Exercise an unknown-sender request against the Android implementation while
# there is no visible ClipMesh activity. prepare-upload intentionally waits for
# a decision, so run it in the background while inspecting the system notification.
cat > /tmp/prepare.json <<'JSON'
{"info":{"alias":"CI Sender","fingerprint":"ci-unknown-sender","port":53317,"protocol":"http","deviceModel":"CI","deviceType":"desktop"},"files":{"proof":{"id":"proof","fileName":"proof.txt","size":5,"fileType":"text/plain"}}}
JSON
curl --silent --max-time 12 -H 'Content-Type: application/json' --data-binary @/tmp/prepare.json http://127.0.0.1:54321/api/localsend/v2/prepare-upload >/tmp/prepare.out 2>/tmp/prepare.err &
REQUEST_PID=$!
sleep 3
(adb shell dumpsys notification --noredact || adb shell dumpsys notification) > /tmp/notifications.txt
cat /tmp/notifications.txt
grep -q 'CI Sender wants to send you proof.txt' /tmp/notifications.txt
# The source gate already requires the high-importance incoming channel and both
# actions. Runtime additionally proves the live notification carries the request.
grep -q 'dev.clipmesh' /tmp/notifications.txt
kill "$REQUEST_PID" 2>/dev/null || true
wait "$REQUEST_PID" 2>/dev/null || true

# After handling a live request, the service and listener must still be alive.
curl --fail --silent --max-time 3 http://127.0.0.1:54321/api/localsend/v2/info > /tmp/info-after.json
adb shell dumpsys activity services dev.clipmesh > /tmp/services-after.txt
grep -q 'BackgroundService' /tmp/services-after.txt

echo 'Android v0.2.3 emulator runtime smoke test: PASS'
