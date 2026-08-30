#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ANDROID="$ROOT/clipmesh/android"
DIST="$ROOT/clipmesh/dist/android"
EXPECTED_PACKAGE="${CLIPMESH_ANDROID_EXPECTED_PACKAGE:-dev.clipmesh}"
EXPECTED_VERSION_NAME="${CLIPMESH_ANDROID_EXPECTED_VERSION_NAME:-0.2.10}"
EXPECTED_VERSION_CODE="${CLIPMESH_ANDROID_EXPECTED_VERSION_CODE:-20}"

required=(
  CLIPMESH_ANDROID_KEYSTORE_B64
  CLIPMESH_ANDROID_KEYSTORE_PASSWORD
  CLIPMESH_ANDROID_KEY_ALIAS
  CLIPMESH_ANDROID_KEY_PASSWORD
  CLIPMESH_ANDROID_SIGNING_CERT_SHA256
)
missing=()
for name in "${required[@]}"; do
  [ -n "${!name:-}" ] || missing+=("$name")
done
if [ "${#missing[@]}" -ne 0 ]; then
  printf 'ERROR: official Android release signing is not configured. Missing: %s\n' "${missing[*]}" >&2
  exit 1
fi

[ -d "$ANDROID" ] || { echo "ERROR: reconstruct clipmesh/android before signing." >&2; exit 1; }

temp_root="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
KEYSTORE_PATH="$(mktemp "$temp_root/clipmesh-android-release.XXXXXX.jks")"
cleanup() {
  rm -f "$KEYSTORE_PATH"
}
trap cleanup EXIT INT TERM
chmod 600 "$KEYSTORE_PATH"

if ! printf '%s' "$CLIPMESH_ANDROID_KEYSTORE_B64" | base64 --decode > "$KEYSTORE_PATH" 2>/dev/null; then
  printf '%s' "$CLIPMESH_ANDROID_KEYSTORE_B64" | base64 -D > "$KEYSTORE_PATH"
fi
[ -s "$KEYSTORE_PATH" ] || { echo "ERROR: decoded Android keystore is empty." >&2; exit 1; }

find_android_tool() {
  local tool="$1"
  local candidate=""
  if [ -n "${ANDROID_HOME:-}" ]; then
    if [ "$tool" = apkanalyzer ] && [ -x "$ANDROID_HOME/cmdline-tools/latest/bin/apkanalyzer" ]; then
      candidate="$ANDROID_HOME/cmdline-tools/latest/bin/apkanalyzer"
    elif [ "$tool" = apksigner ]; then
      candidate="$(find "$ANDROID_HOME/build-tools" -type f -name apksigner 2>/dev/null | sort | tail -n 1)"
    fi
  fi
  if [ -n "$candidate" ]; then
    printf '%s\n' "$candidate"
  else
    command -v "$tool"
  fi
}

APKSIGNER="$(find_android_tool apksigner)"
APKANALYZER="$(find_android_tool apkanalyzer)"
[ -x "$APKSIGNER" ] || { echo "ERROR: apksigner is unavailable." >&2; exit 1; }
[ -x "$APKANALYZER" ] || { echo "ERROR: apkanalyzer is unavailable." >&2; exit 1; }

export CLIPMESH_ANDROID_KEYSTORE_PATH="$KEYSTORE_PATH"
(
  cd "$ANDROID"
  chmod +x gradlew
  ./gradlew :app:assembleRelease --no-daemon
)

APK="$ANDROID/app/build/outputs/apk/release/app-release.apk"
[ -s "$APK" ] || { echo "ERROR: signed release APK was not produced." >&2; exit 1; }

verification="$($APKSIGNER verify --verbose --print-certs "$APK")"
printf '%s\n' "$verification"
printf '%s\n' "$verification" | grep -q '^Number of signers: 1$' || {
  echo "ERROR: the Android release APK must have exactly one signer." >&2
  exit 1
}
printf '%s\n' "$verification" | grep -q '^Verified using v2 scheme (APK Signature Scheme v2): true$' || {
  echo "ERROR: the Android release APK is missing an APK Signature Scheme v2 signature." >&2
  exit 1
}
actual_cert="$(printf '%s\n' "$verification" | sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | head -n 1 | tr -d '[:space:]:' | tr '[:upper:]' '[:lower:]')"
expected_cert="$(printf '%s' "$CLIPMESH_ANDROID_SIGNING_CERT_SHA256" | tr -d '[:space:]:' | tr '[:upper:]' '[:lower:]')"
[ -n "$actual_cert" ] || { echo "ERROR: apksigner did not report a signer certificate." >&2; exit 1; }
if [ "$actual_cert" != "$expected_cert" ]; then
  echo "ERROR: Android signing certificate SHA-256 does not match CLIPMESH_ANDROID_SIGNING_CERT_SHA256." >&2
  echo "Actual certificate SHA-256: $actual_cert" >&2
  exit 1
fi

actual_package="$($APKANALYZER manifest application-id "$APK")"
actual_version_name="$($APKANALYZER manifest version-name "$APK")"
actual_version_code="$($APKANALYZER manifest version-code "$APK")"
manifest="$($APKANALYZER manifest print "$APK")"
[ "$actual_package" = "$EXPECTED_PACKAGE" ] || { echo "ERROR: package is $actual_package, expected $EXPECTED_PACKAGE." >&2; exit 1; }
[ "$actual_version_name" = "$EXPECTED_VERSION_NAME" ] || { echo "ERROR: versionName is $actual_version_name, expected $EXPECTED_VERSION_NAME." >&2; exit 1; }
[ "$actual_version_code" = "$EXPECTED_VERSION_CODE" ] || { echo "ERROR: versionCode is $actual_version_code, expected $EXPECTED_VERSION_CODE." >&2; exit 1; }
for debug_component in \
  dev.clipmesh.CiBackgroundCaptureReceiver \
  dev.clipmesh.DevTestReceiver \
  dev.clipmesh.DevTestFileProvider \
  dev.clipmesh.testdriver; do
  if printf '%s\n' "$manifest" | grep -q "$debug_component"; then
    echo "ERROR: debug-only Android component leaked into the release APK: $debug_component" >&2
    exit 1
  fi
done

mkdir -p "$DIST"
cp "$APK" "$DIST/ClipMesh-release.apk"
(
  cd "$DIST"
  sha256sum ClipMesh-release.apk > SHA256SUMS.txt
)
echo "Verified release-signed Android APK: package=$actual_package versionName=$actual_version_name versionCode=$actual_version_code certSHA256=$actual_cert"
