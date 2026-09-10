#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/dist/macos/clipmesh"
[ -x "$BIN" ] || { echo "Build first with ./scripts/build-macos.sh"; exit 1; }
mkdir -p "$HOME/.local/bin"
cp "$BIN" "$HOME/.local/bin/clipmesh"
echo "Installed $HOME/.local/bin/clipmesh"
echo "Initialize: $HOME/.local/bin/clipmesh init --name 'My Mac'"
