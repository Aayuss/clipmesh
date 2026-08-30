#!/usr/bin/env bash
set -euo pipefail

[ "$(uname -s)" = Darwin ] || { echo "This setup script is for macOS."; exit 1; }

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ZSHENV="${ZDOTDIR:-$HOME}/.zshenv"
MARKER="# ClipMesh: keep explicit Wireless Debugging endpoints canonical"
LINE="export ADB_MDNS_AUTO_CONNECT=0"
AGENT_DIR="$HOME/Library/LaunchAgents"
AGENT="$AGENT_DIR/dev.clipmesh.adb-mdns.plist"
UID_VALUE="$(id -u)"

mkdir -p "$AGENT_DIR"
if [ ! -f "$ZSHENV" ]; then
  : > "$ZSHENV"
  chmod 600 "$ZSHENV"
fi
if ! grep -Fqx "$MARKER" "$ZSHENV"; then
  cp -p "$ZSHENV" "$ZSHENV.clipmesh-backup-$(date +%Y%m%d%H%M%S)"
  printf '\n%s\n%s\n' "$MARKER" "$LINE" >> "$ZSHENV"
elif ! grep -Fqx "$LINE" "$ZSHENV"; then
  cp -p "$ZSHENV" "$ZSHENV.clipmesh-backup-$(date +%Y%m%d%H%M%S)"
  printf '%s\n' "$LINE" >> "$ZSHENV"
fi

install -m 644 "$ROOT/scripts/dev.clipmesh.adb-mdns.plist" "$AGENT"
launchctl bootout "gui/$UID_VALUE/dev.clipmesh.adb-mdns" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID_VALUE" "$AGENT"
launchctl setenv ADB_MDNS_AUTO_CONNECT 0

echo "Configured ADB_MDNS_AUTO_CONNECT=0 for zsh and the current login session."
echo "Future harness runs discover the changing mDNS endpoint and connect one explicit transport."
