#!/usr/bin/env bash
set -euo pipefail

command_name="${1:-}"
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
APP="$ROOT/clipmesh/dist/macos/ClipMesh.app"
DMG="$ROOT/clipmesh/dist/macos/ClipMesh.dmg"

append_env() {
  printf '%s=%s\n' "$1" "$2" >> "$GITHUB_ENV"
}

setup() {
  : "${GITHUB_ENV:?GITHUB_ENV is required}"
  : "${RUNNER_TEMP:?RUNNER_TEMP is required}"
  local cert="${CLIPMESH_MACOS_CERTIFICATE_P12_B64:-}"
  local password="${CLIPMESH_MACOS_CERTIFICATE_PASSWORD:-}"
  local identity="${CLIPMESH_MACOS_SIGNING_IDENTITY:-}"
  if [ -z "$cert$password$identity" ]; then
    append_env CLIPMESH_MACOS_SIGNING_MODE adhoc
    echo "No Apple release certificate is configured; the macOS artifact will remain explicitly ad-hoc signed."
    return
  fi
  if [ -z "$cert" ] || [ -z "$password" ] || [ -z "$identity" ]; then
    echo "ERROR: macOS release signing is partially configured; set all three certificate secrets." >&2
    exit 1
  fi

  local p12="$RUNNER_TEMP/clipmesh-macos-release.p12"
  local keychain="$RUNNER_TEMP/clipmesh-release-signing.keychain-db"
  local keychain_password
  keychain_password="$(openssl rand -hex 32)"
  trap 'rm -f "$RUNNER_TEMP/clipmesh-macos-release.p12"' EXIT INT TERM
  if ! printf '%s' "$cert" | base64 --decode > "$p12" 2>/dev/null; then
    printf '%s' "$cert" | base64 -D > "$p12"
  fi
  chmod 600 "$p12"
  security create-keychain -p "$keychain_password" "$keychain"
  append_env CLIPMESH_MACOS_SIGNING_KEYCHAIN "$keychain"
  security set-keychain-settings -lut 21600 "$keychain"
  security unlock-keychain -p "$keychain_password" "$keychain"
  security import "$p12" -k "$keychain" -P "$password" -T /usr/bin/codesign -T /usr/bin/security
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$keychain_password" "$keychain"
  security find-identity -v -p codesigning "$keychain" | grep -F "$identity" >/dev/null || {
    echo "ERROR: CLIPMESH_MACOS_SIGNING_IDENTITY is not present in the imported certificate." >&2
    exit 1
  }
  rm -f "$p12"
  trap - EXIT INT TERM
  append_env CLIPMESH_MACOS_SIGNING_MODE developer-id
  echo "Apple release certificate imported into a temporary keychain."
}

sign_package() {
  [ -d "$APP" ] || { echo "ERROR: macOS app bundle is missing." >&2; exit 1; }
  if [ "${CLIPMESH_MACOS_SIGNING_MODE:-adhoc}" = adhoc ]; then
    codesign --verify --deep --strict --verbose=2 "$APP"
    codesign -dv --verbose=4 "$APP" 2>&1 | grep -q 'Signature=adhoc' || {
      echo "ERROR: expected an explicitly ad-hoc signed macOS app." >&2
      exit 1
    }
    echo "Verified macOS signing mode: ad-hoc (not Developer ID and not notarized)."
    return
  fi

  : "${CLIPMESH_MACOS_SIGNING_IDENTITY:?Signing identity is required}"
  : "${CLIPMESH_MACOS_SIGNING_KEYCHAIN:?Temporary signing keychain is required}"
  local extension="$APP/Contents/PlugIns/ClipMeshShare.appex"
  [ -d "$extension" ] || { echo "ERROR: Finder Share extension is missing." >&2; exit 1; }
  codesign --force --options runtime --timestamp --sign "$CLIPMESH_MACOS_SIGNING_IDENTITY" --keychain "$CLIPMESH_MACOS_SIGNING_KEYCHAIN" "$extension"
  codesign --force --options runtime --timestamp --sign "$CLIPMESH_MACOS_SIGNING_IDENTITY" --keychain "$CLIPMESH_MACOS_SIGNING_KEYCHAIN" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
  codesign -dv --verbose=4 "$APP" 2>&1 | grep -F "Authority=$CLIPMESH_MACOS_SIGNING_IDENTITY" >/dev/null

  local dmg_root="$ROOT/clipmesh/dist/macos/dmg-release-root"
  rm -rf "$dmg_root"
  mkdir -p "$dmg_root"
  cp -R "$APP" "$dmg_root/ClipMesh.app"
  ln -s /Applications "$dmg_root/Applications"
  rm -f "$DMG"
  hdiutil create -volname ClipMesh -srcfolder "$dmg_root" -ov -format UDZO "$DMG"
  rm -rf "$dmg_root"
  codesign --force --timestamp --sign "$CLIPMESH_MACOS_SIGNING_IDENTITY" --keychain "$CLIPMESH_MACOS_SIGNING_KEYCHAIN" "$DMG"
  codesign --verify --verbose=2 "$DMG"
  echo "Verified macOS signing mode: Developer ID. Notarization is a separate optional step."
}

notarize() {
  local apple_id="${CLIPMESH_MACOS_NOTARY_APPLE_ID:-}"
  local team_id="${CLIPMESH_MACOS_NOTARY_TEAM_ID:-}"
  local password="${CLIPMESH_MACOS_NOTARY_PASSWORD:-}"
  if [ -z "$apple_id$team_id$password" ]; then
    echo "No Apple notarization credentials are configured; notarization was skipped."
    return
  fi
  if [ -z "$apple_id" ] || [ -z "$team_id" ] || [ -z "$password" ]; then
    echo "ERROR: macOS notarization is partially configured; set all three notarization secrets." >&2
    exit 1
  fi
  [ "${CLIPMESH_MACOS_SIGNING_MODE:-adhoc}" = developer-id ] || {
    echo "ERROR: notarization credentials require Developer ID signing credentials." >&2
    exit 1
  }
  xcrun notarytool submit "$DMG" --apple-id "$apple_id" --team-id "$team_id" --password "$password" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  echo "Apple notarization and stapling verified."
}

cleanup() {
  local keychain="${CLIPMESH_MACOS_SIGNING_KEYCHAIN:-}"
  if [ -n "$keychain" ] && [ -f "$keychain" ]; then
    security delete-keychain "$keychain" || true
  fi
  [ -z "${RUNNER_TEMP:-}" ] || rm -f "$RUNNER_TEMP/clipmesh-macos-release.p12"
}

case "$command_name" in
  setup) setup ;;
  sign) sign_package ;;
  notarize) notarize ;;
  cleanup) cleanup ;;
  *) echo "Usage: $0 {setup|sign|notarize|cleanup}" >&2; exit 2 ;;
esac
