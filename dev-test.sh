#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
STATE="${CLIPMESH_DEV_STATE:-$HOME/.clipmesh-dev}"
mkdir -p "$STATE"; chmod 700 "$STATE" 2>/dev/null || true
LOG="$STATE/dev-test.log"; : > "$LOG"
say(){ printf '%s\n' "$*" | tee -a "$LOG"; }
die(){ say "FAIL: $*"; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"; }

on_exit(){
  code=$?
  if [ "$code" -ne 0 ]; then
    say ""; say "--- diagnostics ---"
    if [ -n "${ADB_BIN:-}" ] && [ -n "${SERIAL:-}" ]; then
      "$ADB_BIN" -s "$SERIAL" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tee -a "$LOG" || true
      "$ADB_BIN" -s "$SERIAL" logcat -d -v brief 2>/dev/null | grep -E 'AndroidRuntime|FATAL EXCEPTION|dev\.clipmesh|Shizuku|ClipboardBridge|BackgroundRuntime' | tail -n 250 > "$STATE/android-last-logcat.txt" || true
    fi
    MLOG="$HOME/Library/Application Support/dev.ClipMesh.ClipMesh/clipmesh.log"
    [ ! -f "$MLOG" ] || tail -n 250 "$MLOG" > "$STATE/macos-last-log.txt" || true
    say "Full log: $LOG"
  fi
  exit "$code"
}
trap on_exit EXIT

[ "$(uname -s)" = Darwin ] || die "Run this on the Mac used to test ClipMesh."
for c in python3 curl cargo swiftc security codesign keytool openssl pbcopy pbpaste lsof shasum ditto open xattr route ipconfig; do need "$c"; done

if [ -z "${ANDROID_HOME:-}" ]; then
  [ -z "${ANDROID_SDK_ROOT:-}" ] || ANDROID_HOME="$ANDROID_SDK_ROOT"
  [ -n "${ANDROID_HOME:-}" ] || [ ! -d "$HOME/Library/Android/sdk" ] || ANDROID_HOME="$HOME/Library/Android/sdk"
fi
[ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME" ] || die "Android SDK not found. Set ANDROID_HOME once."
export ANDROID_HOME ANDROID_SDK_ROOT="$ANDROID_HOME"
ADB_BIN="$ANDROID_HOME/platform-tools/adb"; [ -x "$ADB_BIN" ] || ADB_BIN="$(command -v adb || true)"; [ -n "$ADB_BIN" ] || die "adb not found."

choose_android(){
  if [ -n "${ANDROID_SERIAL:-}" ]; then SERIAL="$ANDROID_SERIAL"; "$ADB_BIN" -s "$SERIAL" get-state >/dev/null 2>&1 || die "ANDROID_SERIAL=$SERIAL is not connected."; return; fi
  devices="$($ADB_BIN devices | awk 'NR>1 && $2=="device"{print $1}')"
  if [ -z "$devices" ] && [ -f "$STATE/adb-serial" ]; then "$ADB_BIN" connect "$(cat "$STATE/adb-serial")" >/dev/null 2>&1 || true; devices="$($ADB_BIN devices | awk 'NR>1 && $2=="device"{print $1}')"; fi
  SERIAL="$(printf '%s\n' "$devices" | sed '/^$/d' | head -n1)"
  [ -n "$SERIAL" ] || die "No authorized Android device. Connect once by USB or Wireless debugging."
  printf '%s' "$SERIAL" > "$STATE/adb-serial"
}
choose_android; ADB=("$ADB_BIN" -s "$SERIAL"); say "Android device: $SERIAL"
"${ADB[@]}" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true
"${ADB[@]}" shell wm dismiss-keyguard >/dev/null 2>&1 || true

APKSIGNER="$(find "$ANDROID_HOME/build-tools" -type f -name apksigner 2>/dev/null | sort | tail -n1)"
if [ -z "$APKSIGNER" ]; then
  SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"; [ -x "$SDKMANAGER" ] || die "Android build-tools missing."
  yes | "$SDKMANAGER" "build-tools;35.0.0" "platforms;android-36" "platform-tools" >/dev/null
  APKSIGNER="$(find "$ANDROID_HOME/build-tools" -type f -name apksigner 2>/dev/null | sort | tail -n1)"
fi
[ -x "$APKSIGNER" ] || die "apksigner unavailable."

ANDROID_KEYSTORE="$STATE/android-dev.keystore"; ANDROID_PASS_FILE="$STATE/android-dev.password"
if [ ! -f "$ANDROID_PASS_FILE" ]; then openssl rand -hex 24 > "$ANDROID_PASS_FILE"; chmod 600 "$ANDROID_PASS_FILE"; fi
ANDROID_PASS="$(cat "$ANDROID_PASS_FILE")"
if [ ! -f "$ANDROID_KEYSTORE" ]; then
  say "Creating permanent Android development signing key..."
  keytool -genkeypair -noprompt -keystore "$ANDROID_KEYSTORE" -storepass "$ANDROID_PASS" -keypass "$ANDROID_PASS" -alias clipmesh-dev -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=ClipMesh Local Development,O=ClipMesh Development,C=NP" >/dev/null
  chmod 600 "$ANDROID_KEYSTORE"
fi

MAC_KEYCHAIN_ARGS=()
mac_identity(){
  if [ -n "${CLIPMESH_CODESIGN_IDENTITY:-}" ]; then MAC_SIGN_IDENTITY="$CLIPMESH_CODESIGN_IDENTITY"; return; fi
  line="$(security find-identity -v -p codesigning 2>/dev/null | grep '\"Apple Development:' | head -n1 || true)"
  [ -n "$line" ] || line="$(security find-identity -v -p codesigning 2>/dev/null | grep '\"Developer ID Application:' | head -n1 || true)"
  if [ -n "$line" ]; then MAC_SIGN_IDENTITY="$(printf '%s\n' "$line" | awk '{print $2}')"; say "Using existing Apple code-signing identity."; return; fi
  KEYCHAIN="$STATE/clipmesh-dev.keychain-db"; KCPASS_FILE="$STATE/macos-keychain.password"; P12PASS_FILE="$STATE/macos-p12.password"
  CERT="$STATE/macos-dev-cert.pem"; KEY="$STATE/macos-dev-key.pem"; P12="$STATE/macos-dev.p12"; CN="ClipMesh Local Development"
  [ -f "$KCPASS_FILE" ] || { openssl rand -hex 24 > "$KCPASS_FILE"; chmod 600 "$KCPASS_FILE"; }
  [ -f "$P12PASS_FILE" ] || { openssl rand -hex 24 > "$P12PASS_FILE"; chmod 600 "$P12PASS_FILE"; }
  KCPASS="$(cat "$KCPASS_FILE")"; P12PASS="$(cat "$P12PASS_FILE")"
  if [ ! -f "$KEYCHAIN" ] || [ ! -f "$P12" ]; then
    say "Creating permanent local macOS signing identity..."
    cat > "$STATE/macos-openssl.cnf" <<'EOF'
[req]
prompt=no
distinguished_name=dn
req_extensions=codesign
[dn]
CN=ClipMesh Local Development
O=ClipMesh Development
C=NP
[codesign]
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=codeSigning
EOF
    openssl req -new -newkey rsa:3072 -nodes -keyout "$KEY" -out "$STATE/macos-dev.csr" -config "$STATE/macos-openssl.cnf" >/dev/null 2>&1
    openssl x509 -req -in "$STATE/macos-dev.csr" -signkey "$KEY" -days 3650 -sha256 -extfile "$STATE/macos-openssl.cnf" -extensions codesign -out "$CERT" >/dev/null 2>&1
    openssl pkcs12 -export -inkey "$KEY" -in "$CERT" -name "$CN" -passout "pass:$P12PASS" -out "$P12" >/dev/null 2>&1
    rm -f "$KEYCHAIN"; security create-keychain -p "$KCPASS" "$KEYCHAIN" >/dev/null; security set-keychain-settings -lut 21600 "$KEYCHAIN" >/dev/null
    security unlock-keychain -p "$KCPASS" "$KEYCHAIN" >/dev/null; security import "$P12" -k "$KEYCHAIN" -P "$P12PASS" -T /usr/bin/codesign >/dev/null
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KCPASS" "$KEYCHAIN" >/dev/null 2>&1 || true
  else security unlock-keychain -p "$KCPASS" "$KEYCHAIN" >/dev/null; fi
  MAC_SIGN_IDENTITY="$(security find-certificate -c "$CN" -Z "$KEYCHAIN" 2>/dev/null | awk '/SHA-1 hash:/{print $3;exit}')"
  [ -n "$MAC_SIGN_IDENTITY" ] || die "Could not load persistent local macOS signing identity."
  MAC_KEYCHAIN_ARGS=(--keychain "$KEYCHAIN")
}
mac_identity
sign_mac(){
  app="$1"
  [ -z "${KEYCHAIN:-}" ] || security unlock-keychain -p "$KCPASS" "$KEYCHAIN" >/dev/null
  [ ! -d "$app/Contents/PlugIns/ClipMeshShare.appex" ] || codesign --force --deep --sign "$MAC_SIGN_IDENTITY" "${MAC_KEYCHAIN_ARGS[@]}" "$app/Contents/PlugIns/ClipMeshShare.appex"
  codesign --force --deep --sign "$MAC_SIGN_IDENTITY" "${MAC_KEYCHAIN_ARGS[@]}" "$app"
  codesign --verify --deep --strict "$app"
}

say "Building macOS ClipMesh..."
python3 "$ROOT/ci/reconstruct.py" --platform Darwin >> "$LOG" 2>&1
( cd "$ROOT/clipmesh"; chmod +x scripts/build-macos.sh; ./scripts/build-macos.sh ) >> "$LOG" 2>&1
BUILT_MAC="$ROOT/clipmesh/dist/macos/ClipMesh.app"; [ -d "$BUILT_MAC" ] || die "Mac build missing."
sign_mac "$BUILT_MAC" >> "$LOG" 2>&1
INSTALL_ROOT="${CLIPMESH_INSTALL_DIR:-/Applications}"; if [ ! -w "$INSTALL_ROOT" ]; then INSTALL_ROOT="$HOME/Applications"; mkdir -p "$INSTALL_ROOT"; fi
INSTALL_APP="$INSTALL_ROOT/ClipMesh.app"; APP_EXE="$INSTALL_APP/Contents/MacOS/ClipMesh"; CLI_EXE="$INSTALL_APP/Contents/MacOS/clipmesh-bin"
pkill -x ClipMesh >/dev/null 2>&1 || true; pkill -x clipmesh-bin >/dev/null 2>&1 || true; sleep .4
rm -rf "$INSTALL_APP"; ditto "$BUILT_MAC" "$INSTALL_APP"; xattr -dr com.apple.quarantine "$INSTALL_APP" >/dev/null 2>&1 || true; codesign --verify --deep --strict "$INSTALL_APP"; open "$INSTALL_APP"
wait_mac(){ i=0; while [ "$i" -lt 80 ]; do [ -x "$CLI_EXE" ] && "$CLI_EXE" status >/dev/null 2>&1 && lsof -nP -iTCP:41474 -sTCP:LISTEN >/dev/null 2>&1 && return 0; i=$((i+1)); sleep .25; done; return 1; }
wait_mac || die "Installed Mac runtime did not start."
PAIRING_URI="$($CLI_EXE pairing-uri)"; MAC_FP="$($APP_EXE --dev-test-transfer-fingerprint | tail -n1 | tr -d '\r')"
[ -n "$PAIRING_URI" ] && [ -n "$MAC_FP" ] || die "Could not read Mac pairing/fingerprint state."
say "Fixed Mac install: $INSTALL_APP"

say "Building Android ClipMesh + foreground test driver..."
python3 "$ROOT/ci/reconstruct.py" --platform Linux >> "$LOG" 2>&1
( cd "$ROOT/clipmesh/android"; chmod +x gradlew; ./gradlew :app:assembleDebug :devdriver:assembleDebug --no-daemon ) >> "$LOG" 2>&1
APP_DEBUG="$ROOT/clipmesh/android/app/build/outputs/apk/debug/app-debug.apk"; DRIVER_DEBUG="$ROOT/clipmesh/android/devdriver/build/outputs/apk/debug/devdriver-debug.apk"
[ -s "$APP_DEBUG" ] && [ -s "$DRIVER_DEBUG" ] || die "Android build outputs missing."
sign_apk(){ in="$1"; out="$2"; rm -f "$out"; "$APKSIGNER" sign --ks "$ANDROID_KEYSTORE" --ks-key-alias clipmesh-dev --ks-pass "pass:$ANDROID_PASS" --key-pass "pass:$ANDROID_PASS" --out "$out" "$in"; "$APKSIGNER" verify --print-certs "$out" >/dev/null; }
SIGNED_APP="$STATE/ClipMesh-dev.apk"; SIGNED_DRIVER="$STATE/ClipMesh-e2e-driver.apk"; sign_apk "$APP_DEBUG" "$SIGNED_APP"; sign_apk "$DRIVER_DEBUG" "$SIGNED_DRIVER"
"$APKSIGNER" verify --print-certs "$SIGNED_APP" | awk -F': ' '/Signer #1 certificate SHA-256 digest:/{print $2}' > "$STATE/android-signing.sha256" || true
install_apk(){ package="$1"; apk="$2"; set +e; out="$("${ADB[@]}" install -r -t "$apk" 2>&1)"; code=$?; set -e; printf '%s\n' "$out" >> "$LOG"; [ "$code" -eq 0 ] && return; if printf '%s' "$out" | grep -q INSTALL_FAILED_UPDATE_INCOMPATIBLE; then say "Migrating $package to permanent development signature..."; "${ADB[@]}" uninstall "$package" >/dev/null 2>&1 || true; "${ADB[@]}" install -t "$apk" >> "$LOG" 2>&1; else die "Install failed for $package."; fi; }
install_apk dev.clipmesh "$SIGNED_APP"; install_apk dev.clipmesh.testdriver "$SIGNED_DRIVER"
"${ADB[@]}" shell pm grant dev.clipmesh android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
"${ADB[@]}" shell pm grant dev.clipmesh moe.shizuku.manager.permission.API_V23 >/dev/null 2>&1 || true

if ! "${ADB[@]}" shell 'ps -A | grep -q shizuku_server' >/dev/null 2>&1; then
  say "Starting Shizuku through adb..."
  "${ADB[@]}" shell 'test -f /sdcard/Android/data/moe.shizuku.privileged.api/start.sh && sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh' >> "$LOG" 2>&1 || die "Shizuku is not installed/startable through adb."
  sleep 1
fi
ACCESS="dev.clipmesh/dev.clipmesh.exclusion.ExclusionAccessibilityService"
cur="$("${ADB[@]}" shell settings get secure enabled_accessibility_services 2>/dev/null | tr -d '\r')"
case "$cur" in *"$ACCESS"*) next="$cur";; ""|null) next="$ACCESS";; *) next="$cur:$ACCESS";; esac
"${ADB[@]}" shell settings put secure enabled_accessibility_services "$next" >/dev/null; "${ADB[@]}" shell settings put secure accessibility_enabled 1 >/dev/null

b64(){ printf '%s' "$1" | base64 | tr -d '\n'; }
dev_broadcast(){ action="$1"; shift; "${ADB[@]}" shell am broadcast -n dev.clipmesh/.DevTestReceiver -a "$action" "$@" >/dev/null; }
read_info(){ "${ADB[@]}" shell run-as dev.clipmesh cat files/clipmesh-devtest.txt 2>/dev/null | tr -d '\r'; }
refresh_info(){ dev_broadcast dev.clipmesh.devtest.INFO; sleep .25; read_info; }
dev_broadcast dev.clipmesh.devtest.CONFIGURE --es pairing_b64 "$(b64 "$PAIRING_URI")" --es fingerprint "$MAC_FP"; sleep .5
info="$(refresh_info || true)"
if ! printf '%s\n' "$info" | grep -q shizuku_permission=true; then
  say "Authorizing ClipMesh in Shizuku automatically..."; dev_broadcast dev.clipmesh.devtest.REQUEST_SHIZUKU || true
  i=0; while [ "$i" -lt 30 ]; do sleep .35; info="$(refresh_info || true)"; printf '%s\n' "$info" | grep -q shizuku_permission=true && break; "${ADB[@]}" shell uiautomator dump /sdcard/clipmesh-uia.xml >/dev/null 2>&1 || true; xml="$("${ADB[@]}" shell cat /sdcard/clipmesh-uia.xml 2>/dev/null | tr -d '\r' || true)"; coords="$(printf '%s' "$xml" | python3 "$ROOT/dev/uia-find-allow.py" 2>/dev/null || true)"; if [ -n "$coords" ]; then "${ADB[@]}" shell input tap $(printf '%s' "$coords" | awk '{print $1,$2}') >/dev/null 2>&1 || true; fi; i=$((i+1)); done
fi
info="$(refresh_info || true)"; printf '%s\n' "$info" >> "$LOG"; printf '%s\n' "$info" | grep -q shizuku_available=true || die "ClipMesh cannot see Shizuku."; printf '%s\n' "$info" | grep -q shizuku_permission=true || die "Shizuku authorization could not be automated. Authorize ClipMesh once in Shizuku, then rerun."

"${ADB[@]}" shell am start -W -n dev.clipmesh/.MainActivity >/dev/null; sleep .8; "${ADB[@]}" shell input keyevent KEYCODE_HOME >/dev/null; sleep .5
"${ADB[@]}" shell dumpsys accessibility | grep -F "$ACCESS" >/dev/null || die "Accessibility service is not active."
"${ADB[@]}" shell dumpsys activity services dev.clipmesh | grep -q BackgroundService || die "Android BackgroundService is not running."
ANDROID_IP="$("${ADB[@]}" shell ip route get 1.1.1.1 2>/dev/null | tr -d '\r' | sed -n 's/.* src \([0-9.][0-9.]*\).*/\1/p' | head -n1)"; [ -n "$ANDROID_IP" ] || die "Android LAN IP missing."
MAC_IFACE="$(route -n get "$ANDROID_IP" 2>/dev/null | awk '/interface:/{print $2;exit}')"; MAC_IP="$(ipconfig getifaddr "$MAC_IFACE" 2>/dev/null || true)"; [ -n "$MAC_IP" ] || die "Mac LAN IP missing."
say "Physical LAN: Mac $MAC_IP <-> Android $ANDROID_IP"
"${ADB[@]}" forward tcp:55421 tcp:53421 >/dev/null
ok=0; i=0; while [ "$i" -lt 30 ]; do curl --fail --silent --max-time 2 http://127.0.0.1:55421/api/clipmesh/v1/info > "$STATE/android-transfer-info.json" 2>/dev/null && { ok=1; break; }; i=$((i+1)); sleep .25; done; [ "$ok" -eq 1 ] || die "Android file endpoint unavailable in background."
ANDROID_FP="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["fingerprint"])' "$STATE/android-transfer-info.json")"
PASTE="$STATE/macos-pasteboard-helper"; swiftc "$ROOT/dev/macos-pasteboard-helper.swift" -o "$PASTE" >> "$LOG" 2>&1

start_driver(){ mode="$1"; value="${2:-}"; "${ADB[@]}" shell am force-stop dev.clipmesh.testdriver >/dev/null 2>&1 || true; if [ -n "$value" ]; then "${ADB[@]}" shell am start -W -n dev.clipmesh.testdriver/.MainActivity --es mode "$mode" --es value_b64 "$(b64 "$value")" >/dev/null; else "${ADB[@]}" shell am start -W -n dev.clipmesh.testdriver/.MainActivity --es mode "$mode" >/dev/null; fi; }
driver_result(){ "${ADB[@]}" shell run-as dev.clipmesh.testdriver cat files/result.txt 2>/dev/null | tr -d '\r'; }
wait_driver(){ expected="$1"; i=0; while [ "$i" -lt 100 ]; do r="$(driver_result || true)"; case "$r" in "$expected"*) return 0;; FAIL*) return 1;; esac; i=$((i+1)); sleep .2; done; return 1; }
assert_hidden(){ "${ADB[@]}" shell dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity' | grep -q 'dev\.clipmesh/' && die "ClipMesh became foreground during background clipboard test." || true; }
NONCE="$(date +%s)-$$"; say "Running physical clipboard E2E..."

A2M="clipmesh-android-to-mac-$NONCE"; printf '%s' "sentinel-$NONCE" | pbcopy; start_driver set_text "$A2M"; assert_hidden; ok=0; i=0; while [ "$i" -lt 100 ]; do [ "$(pbpaste 2>/dev/null || true)" = "$A2M" ] && { ok=1; break; }; i=$((i+1)); sleep .2; done; [ "$ok" -eq 1 ] || die "Android -> Mac text failed."; say "PASS Android -> Mac text"
M2A="clipmesh-mac-to-android-$NONCE"; start_driver wait_text "$M2A"; wait_driver READY_TEXT || die "Android driver not ready."; printf '%s' "$M2A" | pbcopy; wait_driver PASS_TEXT || die "Mac -> Android text failed."; assert_hidden; say "PASS Mac -> Android text"
printf '%s' "image-sentinel-$NONCE" | pbcopy; start_driver set_image; assert_hidden; ok=0; i=0; while [ "$i" -lt 120 ]; do [ "$($PASTE image-info 2>/dev/null || true)" = 3x2 ] && { ok=1; break; }; i=$((i+1)); sleep .2; done; [ "$ok" -eq 1 ] || die "Android -> Mac image failed."; say "PASS Android -> Mac image"
start_driver wait_image; wait_driver READY_IMAGE || die "Android image driver not ready."; "$PASTE" set-image >/dev/null; wait_driver PASS_IMAGE || die "Mac -> Android image failed."; assert_hidden; say "PASS Mac -> Android image"

say "Running physical file-transfer E2E..."
dev_broadcast dev.clipmesh.devtest.FAVORITE --es fingerprint "$MAC_FP"; "$APP_EXE" --dev-test-favorite "$ANDROID_FP" >> "$LOG" 2>&1
pkill -x ClipMesh >/dev/null 2>&1 || true; pkill -x clipmesh-bin >/dev/null 2>&1 || true; sleep .4; open "$INSTALL_APP"; wait_mac || die "Mac app restart failed."
i=0; while [ "$i" -lt 40 ] && ! lsof -nP -iTCP:53421 -sTCP:LISTEN >/dev/null 2>&1; do i=$((i+1)); sleep .25; done; lsof -nP -iTCP:53421 -sTCP:LISTEN >/dev/null 2>&1 || die "Mac file receiver not listening."
A2M_FILE="clipmesh-a2m-$NONCE.bin"; A2M_PAYLOAD="android-to-mac-$NONCE-$(openssl rand -hex 32)"; A2M_DEST="$HOME/Downloads/ClipMesh/$A2M_FILE"; rm -f "$A2M_DEST"
dev_broadcast dev.clipmesh.devtest.SEND_FILE --es address "$MAC_IP" --es fingerprint "$MAC_FP" --es file_name "$A2M_FILE" --es payload_b64 "$(b64 "$A2M_PAYLOAD")"
ok=0; i=0; while [ "$i" -lt 120 ]; do [ -f "$A2M_DEST" ] && [ "$(cat "$A2M_DEST")" = "$A2M_PAYLOAD" ] && { ok=1; break; }; printf '%s\n' "$(read_info || true)" | grep -q '^send=FAIL' && break; i=$((i+1)); sleep .25; done; [ "$ok" -eq 1 ] || die "Android -> Mac file failed exact-byte verification."; say "PASS Android -> Mac file"
M2A_FILE="clipmesh-m2a-$NONCE.bin"; M2A_LOCAL="$STATE/$M2A_FILE"; printf '%s' "mac-to-android-$NONCE-$(openssl rand -hex 32)" > "$M2A_LOCAL"; "${ADB[@]}" shell rm -f "/sdcard/Download/ClipMesh/$M2A_FILE" >/dev/null 2>&1 || true
"$APP_EXE" --dev-test-send-file "$M2A_LOCAL" "$ANDROID_IP" "$ANDROID_FP" >> "$LOG" 2>&1
local_hash="$(shasum -a 256 "$M2A_LOCAL" | awk '{print $1}')"; ok=0; i=0; while [ "$i" -lt 120 ]; do if "${ADB[@]}" shell test -f "/sdcard/Download/ClipMesh/$M2A_FILE" >/dev/null 2>&1; then remote_hash="$("${ADB[@]}" exec-out cat "/sdcard/Download/ClipMesh/$M2A_FILE" | shasum -a 256 | awk '{print $1}')"; [ "$remote_hash" = "$local_hash" ] && { ok=1; break; }; fi; i=$((i+1)); sleep .25; done; [ "$ok" -eq 1 ] || die "Mac -> Android file failed exact-byte verification."; say "PASS Mac -> Android file"

"${ADB[@]}" shell dumpsys activity services dev.clipmesh | grep -q BackgroundService || die "Android service stopped during tests."
refresh_info > "$STATE/android-final-info.txt"; grep -q shizuku_permission=true "$STATE/android-final-info.txt" || die "Shizuku permission disappeared."
codesign --verify --deep --strict "$INSTALL_APP"
say ""; say "ALL PHYSICAL CLIPMESH TESTS PASSED"; say "Android permanent signing: $ANDROID_KEYSTORE"; say "macOS fixed install: $INSTALL_APP"; say "Full log: $LOG"
trap - EXIT
