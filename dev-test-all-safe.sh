#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
STATE="${CLIPMESH_DEV_STATE:-$HOME/.clipmesh-dev}"
mkdir -p "$STATE"
ORIGINAL="$ROOT/dev-test-all.sh"
PATCHED="$ROOT/.dev-test-all-safe-wrapper.$$"
RUNTIME="$ROOT/.dev-test-all-runtime.$$"

cleanup(){
  rm -f -- "$PATCHED" "$RUNTIME"
}
trap cleanup EXIT INT TERM

# If the caller supplied a Wireless Debugging endpoint, connect it instead of
# failing just because this adb-server process has not opened that transport yet.
if [ -n "${ANDROID_SERIAL:-}" ]; then
  ADB_BIN="${ANDROID_HOME:-$HOME/Library/Android/sdk}/platform-tools/adb"
  [ -x "$ADB_BIN" ] || ADB_BIN="$(command -v adb || true)"
  if [ -n "$ADB_BIN" ] && ! "$ADB_BIN" -s "$ANDROID_SERIAL" get-state >/dev/null 2>&1; then
    "$ADB_BIN" connect "$ANDROID_SERIAL" >/dev/null 2>&1 || true
    if ! "$ADB_BIN" -s "$ANDROID_SERIAL" get-state >/dev/null 2>&1; then
      host="${ANDROID_SERIAL%%:*}"
      current="$($ADB_BIN mdns services 2>/dev/null | awk -v host="$host" '
        /_adb-tls-connect/ {
          if (match($0, /[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+/)) {
            ep=substr($0,RSTART,RLENGTH)
            if (index(ep, host ":") == 1) { print ep; exit }
          }
        }')"
      if [ -n "$current" ]; then
        "$ADB_BIN" connect "$current" >/dev/null 2>&1 || true
        if "$ADB_BIN" -s "$current" get-state >/dev/null 2>&1; then
          export ANDROID_SERIAL="$current"
          printf 'Wireless Debugging endpoint refreshed: %s\n' "$ANDROID_SERIAL"
        fi
      fi
    fi
  fi
fi

# dev-test-all.sh intentionally generates a runtime copy. Its historical bug was
# placing that copy in ~/.clipmesh-dev, which made dev-test.sh recalculate ROOT
# as ~/.clipmesh-dev and then fail `git -C "$ROOT" archive`. Generate both the
# wrapper and runtime inside the real repository so every relative/repository
# operation remains anchored to the actual checkout.
python3 - "$ORIGINAL" "$PATCHED" "$RUNTIME" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
patched = Path(sys.argv[2])
runtime = Path(sys.argv[3])
old = 'RUNTIME="$STATE/dev-test-all-runtime.sh"'
if source.count(old) != 1:
    raise SystemExit(f"safe harness: expected one runtime anchor, found {source.count(old)}")
source = source.replace(old, f'RUNTIME={str(runtime)!r}', 1)
patched.write_text(source, encoding="utf-8")
PY

chmod +x "$PATCHED"
set +e
/bin/bash "$PATCHED"
code=$?
set -e
exit "$code"
