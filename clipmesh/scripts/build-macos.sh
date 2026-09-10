#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v cargo >/dev/null || { echo "Install Rust first from https://rustup.rs"; exit 1; }
cargo build --release -p clipmesh

OUT="dist/macos"
APP="$OUT/ClipMesh.app"
ICON_SRC="apps/desktop/assets/clipmesh.png"
ICONSET="$OUT/ClipMesh.iconset"

rm -rf "$APP" "$ICONSET"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$ICONSET"

cp target/release/clipmesh "$APP/Contents/MacOS/clipmesh-bin"
cat > "$APP/Contents/MacOS/ClipMesh" <<'LAUNCHER'
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/clipmesh-bin" run
LAUNCHER
chmod +x "$APP/Contents/MacOS/clipmesh-bin" "$APP/Contents/MacOS/ClipMesh"

for spec in \
  "16 icon_16x16.png" \
  "32 icon_16x16@2x.png" \
  "32 icon_32x32.png" \
  "64 icon_32x32@2x.png" \
  "128 icon_128x128.png" \
  "256 icon_128x128@2x.png" \
  "256 icon_256x256.png" \
  "512 icon_256x256@2x.png" \
  "512 icon_512x512.png" \
  "1024 icon_512x512@2x.png"
do
  px="${spec%% *}"
  name="${spec#* }"
  sips -z "$px" "$px" "$ICON_SRC" --out "$ICONSET/$name" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/ClipMesh.icns"
rm -rf "$ICONSET"
cp "$ICON_SRC" "$OUT/ClipMesh-icon.png"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>dev.clipmesh.private</string>
  <key>CFBundleName</key><string>ClipMesh</string>
  <key>CFBundleDisplayName</key><string>ClipMesh</string>
  <key>CFBundleExecutable</key><string>ClipMesh</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.1</string>
  <key>CFBundleIconFile</key><string>ClipMesh.icns</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cp target/release/clipmesh "$OUT/clipmesh"

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP" || true
fi

if command -v hdiutil >/dev/null 2>&1; then
  rm -f "$OUT/ClipMesh.dmg"
  hdiutil create -volname ClipMesh -srcfolder "$APP" -ov -format UDZO "$OUT/ClipMesh.dmg"
  echo "Built: $OUT/ClipMesh.dmg"
else
  echo "Built app bundle: $APP"
fi
