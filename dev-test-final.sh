#!/usr/bin/env bash
# Audited entrypoint for the full ClipMesh Mac <-> Android physical acceptance run.
# It never edits the checkout: the large canonical suite is finalized into a
# temporary sibling script, syntax-checked, then executed in a clean bash.

set +e
set +u
set +o pipefail 2>/dev/null
trap - ERR

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TMP="$ROOT/.dev-test-final.$$.sh"
cleanup(){ rm -f -- "$TMP"; }
trap cleanup EXIT INT TERM

python3 "$ROOT/ci/finalize-comprehensive-runner.py" "$ROOT/dev-test-comprehensive.sh" "$TMP"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: could not finalize the comprehensive physical runner."
  exit "$rc"
fi
chmod +x "$TMP"
/bin/bash -n "$TMP"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: finalized comprehensive runner failed bash syntax validation."
  exit "$rc"
fi

/bin/bash --noprofile --norc "$TMP"
rc=$?
exit "$rc"
