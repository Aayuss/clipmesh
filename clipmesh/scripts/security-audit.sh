#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/4] Protocol vector"
if command -v python3 >/dev/null 2>&1 && python3 -c 'import cryptography' >/dev/null 2>&1; then
  python3 tools/protocol_selftest.py
else
  echo "SKIP: Python cryptography not installed"
fi

echo "[2/4] Forbidden telemetry/ad SDK names"
if grep -RniE 'sentry|posthog|firebase.analytics|google.*ads|appsflyer|amplitude|mixpanel' \
  --include='*.rs' --include='*.kt' --include='*.kts' --include='Cargo.toml' apps crates android; then
  echo "ERROR: telemetry/ad marker found" >&2
  exit 1
else
  echo "PASS: no telemetry/ad SDK markers"
fi

echo "[3/4] Runtime URL/domain literals"
URL_HITS=$(grep -RniE 'https?://|wss?://' --include='*.rs' --include='*.kt' apps crates android/app/src/main/java 2>/dev/null | grep -v 'apple.com/DTDs/PropertyList' || true)
if [ -n "$URL_HITS" ]; then
  echo "$URL_HITS"
  echo "Review URL literals above. Runtime should not need any external endpoint." >&2
  exit 1
else
  echo "PASS: no runtime web endpoints"
fi

echo "[4/4] Cloud/relay markers"
CLOUD_HITS=$(grep -RniE 'relayclient|rendezvousclient|cloud[_-]?(url|host|endpoint)|analyticsclient' --include='*.rs' --include='*.kt' apps crates android/app/src/main/java 2>/dev/null || true)
if [ -n "$CLOUD_HITS" ]; then
  echo "$CLOUD_HITS"
  echo "Review cloud/relay implementation markers above." >&2
  exit 1
else
  echo "PASS: no cloud/relay implementation markers"
fi
