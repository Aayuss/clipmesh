#!/usr/bin/env bash
set -euo pipefail
for f in \
  clipmesh/android/app/src/main/java/dev/clipmesh/network/NetworkEngine.kt \
  clipmesh/android/app/src/main/java/dev/clipmesh/crypto/Crypto.kt \
  clipmesh/android/app/src/main/java/dev/clipmesh/model/Payload.kt \
  clipmesh/android/app/build.gradle.kts \
  clipmesh/android/build.gradle.kts \
  clipmesh/apps/desktop/src/network.rs \
  clipmesh/crates/core/src/lib.rs \
  clipmesh/crates/core/src/protocol.rs \
  clipmesh/crates/core/src/crypto.rs; do
  if [[ -f "$f" ]]; then
    echo "=== $f ==="
    sed -n '1,520p' "$f"
  fi
done
