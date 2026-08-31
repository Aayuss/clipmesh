#!/usr/bin/env bash
# Fast physical retry loop for only the scenarios that currently fail.
# Uses the exact same finalized setup/helpers as dev-test-final.sh, but does not
# execute the already-green full matrix. Final release certification must still
# use dev-test-final.sh once all focused failures are green.

set +e
set +u
set +o pipefail 2>/dev/null
trap - ERR

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

preflight_fail(){
  echo
  echo "FOCUSED PHYSICAL RETRY PRECHECK FAILED: $*"
  echo "No build or device tests were started."
  exit 2
}

if [ "${CLIPMESH_ACCEPTANCE_ALLOW_DIRTY:-0}" != "1" ]; then
  dirty="$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" || preflight_fail "Could not inspect Git status."
  if [ -n "$dirty" ]; then
    echo "Tracked local changes:"
    printf '%s\n' "$dirty"
    preflight_fail "Checkout has tracked local changes. Commit/stash/restore them first."
  fi
fi

if [ "${CLIPMESH_ACCEPTANCE_SKIP_REMOTE_CHECK:-0}" != "1" ]; then
  git -C "$ROOT" remote get-url origin >/dev/null 2>&1 || preflight_fail "Git remote 'origin' is unavailable."
  git -C "$ROOT" fetch --quiet origin main || preflight_fail "Could not refresh origin/main."
  head_sha="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)" || preflight_fail "Could not resolve local HEAD."
  remote_sha="$(git -C "$ROOT" rev-parse origin/main 2>/dev/null)" || preflight_fail "Could not resolve origin/main."
  if [ "$head_sha" != "$remote_sha" ]; then
    echo "Local HEAD:  $head_sha"
    echo "origin/main: $remote_sha"
    if git -C "$ROOT" merge-base --is-ancestor "$head_sha" "$remote_sha" >/dev/null 2>&1; then
      preflight_fail "Local checkout is behind origin/main. Run: git pull --ff-only"
    elif git -C "$ROOT" merge-base --is-ancestor "$remote_sha" "$head_sha" >/dev/null 2>&1; then
      preflight_fail "Local checkout is ahead of origin/main. Push/resolve it first."
    else
      preflight_fail "Local checkout has diverged from origin/main. Resolve Git history first."
    fi
  fi
  echo "Focused physical retry Git precheck: PASS ($head_sha)"
fi

TMP_V1="$ROOT/.dev-test-focused-v1.$$.sh"
TMP_V2="$ROOT/.dev-test-focused-v2.$$.sh"
TMP_V3="$ROOT/.dev-test-focused-v3.$$.sh"
TMP_FULL="$ROOT/.dev-test-focused-full.$$.sh"
TMP="$ROOT/.dev-test-focused.$$.sh"
cleanup(){ rm -f -- "$TMP_V1" "$TMP_V2" "$TMP_V3" "$TMP_FULL" "$TMP"; }
trap cleanup EXIT INT TERM

python3 "$ROOT/ci/finalize-comprehensive-runner.py" "$ROOT/dev-test-comprehensive.sh" "$TMP_V1"
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: could not finalize comprehensive physical runner."; exit "$rc"; }

python3 "$ROOT/ci/finalize-physical-v2.py" "$TMP_V1" "$TMP_V2"
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: could not apply physical hardening v2."; exit "$rc"; }

python3 "$ROOT/ci/finalize-physical-v3.py" "$TMP_V2" "$TMP_V3"
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: could not apply physical hardening v3."; exit "$rc"; }

python3 "$ROOT/ci/finalize-physical-v4.py" "$TMP_V3" "$TMP_FULL"
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: could not apply image-echo hardening v4."; exit "$rc"; }

python3 "$ROOT/ci/focus-physical-failures.py" "$TMP_FULL" "$TMP"
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: could not generate focused image-echo runner."; exit "$rc"; }

chmod +x "$TMP"
/bin/bash -n "$TMP"
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: focused physical runner failed bash syntax validation."; exit "$rc"; }

/bin/bash --noprofile --norc "$TMP"
rc=$?
exit "$rc"
