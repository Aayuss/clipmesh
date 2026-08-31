#!/usr/bin/env bash
# Audited entrypoint for the full ClipMesh Mac <-> Android physical acceptance run.
# It never edits the checkout: the canonical suite is finalized in four audited
# passes, syntax-checked, then executed in a clean bash.
#
# Final physical acceptance is intentionally strict: by default it only runs from
# a clean checkout whose HEAD exactly matches origin/main. This prevents wasting a
# long hardware run on stale or locally modified harness/product code.

set +e
set +u
set +o pipefail 2>/dev/null
trap - ERR

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

preflight_fail(){
  echo
  echo "PHYSICAL ACCEPTANCE PRECHECK FAILED: $*"
  echo "No build or device tests were started."
  exit 2
}

# Refuse stale/dirty physical certification runs unless explicitly overridden for
# harness development. Untracked files are ignored so logs/temp files do not block
# the suite; tracked source/harness modifications do.
if [ "${CLIPMESH_ACCEPTANCE_ALLOW_DIRTY:-0}" != "1" ]; then
  dirty="$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" || preflight_fail "Could not inspect Git status."
  if [ -n "$dirty" ]; then
    echo "Tracked local changes:"
    printf '%s\n' "$dirty"
    preflight_fail "Checkout has tracked local changes. Commit/stash/restore them first, or set CLIPMESH_ACCEPTANCE_ALLOW_DIRTY=1 only for deliberate harness development."
  fi
fi

if [ "${CLIPMESH_ACCEPTANCE_SKIP_REMOTE_CHECK:-0}" != "1" ]; then
  git -C "$ROOT" remote get-url origin >/dev/null 2>&1 || preflight_fail "Git remote 'origin' is unavailable."
  git -C "$ROOT" fetch --quiet origin main || preflight_fail "Could not refresh origin/main. Check network/GitHub access."
  head_sha="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)" || preflight_fail "Could not resolve local HEAD."
  remote_sha="$(git -C "$ROOT" rev-parse origin/main 2>/dev/null)" || preflight_fail "Could not resolve origin/main."
  if [ "$head_sha" != "$remote_sha" ]; then
    echo "Local HEAD:  $head_sha"
    echo "origin/main: $remote_sha"
    if git -C "$ROOT" merge-base --is-ancestor "$head_sha" "$remote_sha" >/dev/null 2>&1; then
      preflight_fail "Local checkout is behind origin/main. Run: git pull --ff-only"
    elif git -C "$ROOT" merge-base --is-ancestor "$remote_sha" "$head_sha" >/dev/null 2>&1; then
      preflight_fail "Local checkout is ahead of origin/main. Push/resolve it before final physical certification."
    else
      preflight_fail "Local checkout has diverged from origin/main. Resolve Git history before final physical certification."
    fi
  fi
  echo "Physical acceptance Git precheck: PASS ($head_sha)"
fi

TMP_V1="$ROOT/.dev-test-final-v1.$$.sh"
TMP_V2="$ROOT/.dev-test-final-v2.$$.sh"
TMP_V3="$ROOT/.dev-test-final-v3.$$.sh"
TMP="$ROOT/.dev-test-final.$$.sh"
cleanup(){ rm -f -- "$TMP_V1" "$TMP_V2" "$TMP_V3" "$TMP"; }
trap cleanup EXIT INT TERM

python3 "$ROOT/ci/finalize-comprehensive-runner.py" "$ROOT/dev-test-comprehensive.sh" "$TMP_V1"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: could not finalize the comprehensive physical runner."
  exit "$rc"
fi

python3 "$ROOT/ci/finalize-physical-v2.py" "$TMP_V1" "$TMP_V2"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: could not apply deterministic physical hardening v2."
  exit "$rc"
fi

python3 "$ROOT/ci/finalize-physical-v3.py" "$TMP_V2" "$TMP_V3"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: could not apply passwordless/restart physical hardening v3."
  exit "$rc"
fi

python3 "$ROOT/ci/finalize-physical-v4.py" "$TMP_V3" "$TMP"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: could not apply delayed image-echo physical hardening v4."
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
