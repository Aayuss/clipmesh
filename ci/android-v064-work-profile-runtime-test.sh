#!/usr/bin/env bash
set -euo pipefail

PACKAGE=dev.clipmesh
COMPONENT=dev.clipmesh/.MainActivity

adb shell am force-stop --user 0 "$PACKAGE" || true

create_output=$(adb shell pm create-user --profileOf 0 --managed ClipMeshWork 2>&1 || true)
if ! grep -q 'Success:' <<<"$create_output"; then
  create_output=$(adb shell pm create-user --profileOf 0 --user-type android.os.usertype.profile.MANAGED ClipMeshWork 2>&1 || true)
fi
printf '%s\n' "$create_output"
WORK_USER=$(grep -oE '[0-9]+' <<<"$create_output" | tail -n1)
test -n "$WORK_USER"

adb shell am start-user -w "$WORK_USER"
adb shell pm install-existing --user "$WORK_USER" "$PACKAGE" | tee /tmp/work-install.txt
grep -Eq 'installed|Package .* installed' /tmp/work-install.txt

adb shell pm grant --user "$WORK_USER" "$PACKAGE" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

adb logcat -c
adb shell am start --user "$WORK_USER" -W -n "$COMPONENT" | tee /tmp/work-start.txt
grep -q 'Status: ok' /tmp/work-start.txt
sleep 3

adb shell dumpsys activity activities > /tmp/work-activities.txt
cat /tmp/work-activities.txt
grep -Eq "u${WORK_USER}.*dev\.clipmesh|dev\.clipmesh.*u${WORK_USER}" /tmp/work-activities.txt

adb shell dumpsys activity services "$PACKAGE" > /tmp/work-services.txt || true
cat /tmp/work-services.txt
if grep -q 'BackgroundService' /tmp/work-services.txt; then
  echo "Fresh managed-profile launch unexpectedly started ClipMesh BackgroundService"
  exit 1
fi

adb logcat -d -v brief > /tmp/work-logcat.txt
if grep -A12 -B3 -E 'FATAL EXCEPTION|Process: dev\.clipmesh' /tmp/work-logcat.txt | grep -q 'dev.clipmesh'; then
  echo "--- managed-profile crash log ---"
  grep -A20 -B5 -E 'FATAL EXCEPTION|Process: dev\.clipmesh' /tmp/work-logcat.txt | tail -n 200
  exit 1
fi

adb shell input keyevent KEYCODE_HOME
sleep 1
adb shell am start --user "$WORK_USER" -W -n "$COMPONENT" | tee /tmp/work-resume.txt
grep -q 'Status: ok' /tmp/work-resume.txt

echo "Android managed-work-profile launch smoke test: PASS (user $WORK_USER)"
