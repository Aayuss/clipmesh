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
