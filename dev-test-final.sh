#!/usr/bin/env bash
# Audited entrypoint for the full ClipMesh Mac <-> Android physical acceptance run.
# It never edits the checkout: the canonical suite is finalized in two audited
# passes, syntax-checked, then executed in a clean bash.

set +e
set +u
set +o pipefail 2>/dev/null
trap - ERR

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TMP_V1="$ROOT/.dev-test-final-v1.$$.sh"
TMP="$ROOT/.dev-test-final.$$.sh"
cleanup(){ rm -f -- "$TMP_V1" "$TMP"; }
trap cleanup EXIT INT TERM

python3 "$ROOT/ci/finalize-comprehensive-runner.py" "$ROOT/dev-test-comprehensive.sh" "$TMP_V1"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: could not finalize the comprehensive physical runner."
  exit "$rc"
fi

python3 "$ROOT/ci/finalize-physical-v2.py" "$TMP_V1" "$TMP"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: could not apply deterministic physical hardening."
  exit "$rc"
fi

chmod +x "$TMP"
/bin/bash -n "$TMP"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: hardened comprehensive runner failed bash syntax validation."
  exit "$rc"
fi

/bin/bash --noprofile --norc "$TMP"
rc=$?
exit "$rc"
