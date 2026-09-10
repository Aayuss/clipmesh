#!/usr/bin/env bash
set -euo pipefail
command -v adb >/dev/null || { echo "adb not found"; exit 1; }
CLIPMESH_BIN="${CLIPMESH_BIN:-clipmesh}"
command -v "$CLIPMESH_BIN" >/dev/null || { echo "clipmesh executable not found; set CLIPMESH_BIN=/path/to/clipmesh"; exit 1; }
URI="$($CLIPMESH_BIN pairing-uri)"
adb shell am start -a android.intent.action.VIEW -d "$URI" dev.clipmesh/.MainActivity >/dev/null
echo "Pairing URI delivered directly to ClipMesh over ADB. Unlock Android and tap Join."
