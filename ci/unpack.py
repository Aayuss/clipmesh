from __future__ import annotations

import base64
import hashlib
import pathlib
import shutil
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CI = ROOT / "ci"
parts = sorted(CI.glob("source.part*.b64"))
if len(parts) != 4:
    raise SystemExit(f"Expected 4 source chunks, found {len(parts)}")

encoded = "".join(p.read_text(encoding="utf-8").strip() for p in parts)
archive_bytes = base64.b64decode(encoded, validate=True)
archive = CI / "clipmesh-source.tar.xz"
archive.write_bytes(archive_bytes)
print(f"source archive sha256={hashlib.sha256(archive_bytes).hexdigest()}")

with tarfile.open(archive, mode="r:xz") as tf:
    tf.extractall(ROOT, filter="data")

project = ROOT / "clipmesh"
if not (project / "Cargo.toml").is_file() or not (project / "android" / "settings.gradle.kts").is_file():
    raise SystemExit("Source archive did not unpack into the expected clipmesh project")

fixed_gradlew = CI / "gradlew-fixed"
android_gradlew = project / "android" / "gradlew"
if fixed_gradlew.is_file():
    shutil.copyfile(fixed_gradlew, android_gradlew)
    android_gradlew.chmod(0o755)

fixed_android_build = CI / "android-app-build.gradle.kts.fixed"
android_build = project / "android" / "app" / "build.gradle.kts"
if fixed_android_build.is_file():
    shutil.copyfile(fixed_android_build, android_build)

fixed_android_props = CI / "android-gradle.properties.fixed"
android_props = project / "android" / "gradle.properties"
if fixed_android_props.is_file():
    shutil.copyfile(fixed_android_props, android_props)

fixed_provider = CI / "ClipFileProvider.kt.fixed"
provider = project / "android" / "app" / "src" / "main" / "java" / "dev" / "clipmesh" / "files" / "ClipFileProvider.kt"
if fixed_provider.is_file():
    provider.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixed_provider, provider)

# Product artwork supplied for ClipMesh.
icon_png_b64 = CI / "clipmesh-icon.png.b64"
icon_ico_b64 = CI / "clipmesh-icon.ico.b64"
if not icon_png_b64.is_file() or not icon_ico_b64.is_file():
    raise SystemExit("ClipMesh icon assets are missing from ci/")

icon_png = base64.b64decode(icon_png_b64.read_text(encoding="utf-8").strip(), validate=True)
icon_ico = base64.b64decode(icon_ico_b64.read_text(encoding="utf-8").strip(), validate=True)

desktop_assets = project / "apps" / "desktop" / "assets"
desktop_assets.mkdir(parents=True, exist_ok=True)
(desktop_assets / "clipmesh.png").write_bytes(icon_png)
(desktop_assets / "clipmesh.ico").write_bytes(icon_ico)

android_drawable = project / "android" / "app" / "src" / "main" / "res" / "drawable-nodpi"
android_drawable.mkdir(parents=True, exist_ok=True)
(android_drawable / "app_icon.png").write_bytes(icon_png)

android_vector_dir = project / "android" / "app" / "src" / "main" / "res" / "drawable"
android_vector_dir.mkdir(parents=True, exist_ok=True)
(android_vector_dir / "ic_clipmesh_notification.xml").write_text('<?xml version="1.0" encoding="utf-8"?>\n<vector xmlns:android="http://schemas.android.com/apk/res/android"\n    android:width="24dp"\n    android:height="24dp"\n    android:viewportWidth="24"\n    android:viewportHeight="24">\n    <path\n        android:fillColor="#FFFFFFFF"\n        android:pathData="M5.2,6.1C3.2,7.5 2,9.6 2,12c0,2.1 0.9,4.1 2.5,5.5L3,19h5v-5l-1.7,1.7C5.2,14.8 4.5,13.5 4.5,12c0,-1.6 0.8,-3.1 2.1,-4L5.2,6.1zM18.8,17.9c2,-1.4 3.2,-3.5 3.2,-5.9 0,-2.1 -0.9,-4.1 -2.5,-5.5L21,5h-5v5l1.7,-1.7c1.1,0.9 1.8,2.2 1.8,3.7 0,1.6 -0.8,3.1 -2.1,4l1.4,1.9zM9.2,11.2a1.2,1.2 0,1 0,0 2.4,1.2 1.2,0 0,0 0,-2.4zM12,10.8a1.2,1.2 0,1 0,0 2.4,1.2 1.2,0 0,0 0,-2.4zM14.8,10.4a1.2,1.2 0,1 0,0 2.4,1.2 1.2,0 0,0 0,-2.4z" />\n</vector>\n', encoding="utf-8")

desktop_cargo = project / "apps" / "desktop" / "Cargo.toml"
cargo_text = desktop_cargo.read_text(encoding="utf-8")
if "winresource" not in cargo_text:
    cargo_text += '\n[target.\'cfg(windows)\'.build-dependencies]\nwinresource = "0.1"\n'
desktop_cargo.write_text(cargo_text, encoding="utf-8")
(project / "apps" / "desktop" / "build.rs").write_text('#[cfg(windows)]\nfn main() {\n    let mut resource = winresource::WindowsResource::new();\n    resource.set_icon("assets/clipmesh.ico");\n    resource.compile().expect("failed to embed ClipMesh Windows icon");\n}\n\n#[cfg(not(windows))]\nfn main() {}\n', encoding="utf-8")

mac_build = project / "scripts" / "build-macos.sh"
mac_build.write_text('#!/usr/bin/env bash\nset -euo pipefail\ncd "$(dirname "$0")/.."\ncommand -v cargo >/dev/null || { echo "Install Rust first from https://rustup.rs"; exit 1; }\ncargo build --release -p clipmesh\n\nOUT="dist/macos"\nAPP="$OUT/ClipMesh.app"\nICON_SRC="apps/desktop/assets/clipmesh.png"\nICONSET="$OUT/ClipMesh.iconset"\n\nrm -rf "$APP" "$ICONSET"\nmkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$ICONSET"\n\ncp target/release/clipmesh "$APP/Contents/MacOS/clipmesh-bin"\ncat > "$APP/Contents/MacOS/ClipMesh" <<\'LAUNCHER\'\n#!/bin/sh\nHERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nexec "$HERE/clipmesh-bin" run\nLAUNCHER\nchmod +x "$APP/Contents/MacOS/clipmesh-bin" "$APP/Contents/MacOS/ClipMesh"\n\nfor spec in \\\n  "16 icon_16x16.png" \\\n  "32 icon_16x16@2x.png" \\\n  "32 icon_32x32.png" \\\n  "64 icon_32x32@2x.png" \\\n  "128 icon_128x128.png" \\\n  "256 icon_128x128@2x.png" \\\n  "256 icon_256x256.png" \\\n  "512 icon_256x256@2x.png" \\\n  "512 icon_512x512.png" \\\n  "1024 icon_512x512@2x.png"\ndo\n  px="${spec%% *}"\n  name="${spec#* }"\n  sips -z "$px" "$px" "$ICON_SRC" --out "$ICONSET/$name" >/dev/null\ndone\niconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/ClipMesh.icns"\nrm -rf "$ICONSET"\ncp "$ICON_SRC" "$OUT/ClipMesh-icon.png"\n\ncat > "$APP/Contents/Info.plist" <<\'PLIST\'\n<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n  <key>CFBundleIdentifier</key><string>dev.clipmesh.private</string>\n  <key>CFBundleName</key><string>ClipMesh</string>\n  <key>CFBundleDisplayName</key><string>ClipMesh</string>\n  <key>CFBundleExecutable</key><string>ClipMesh</string>\n  <key>CFBundlePackageType</key><string>APPL</string>\n  <key>CFBundleShortVersionString</key><string>0.1.1</string>\n  <key>CFBundleIconFile</key><string>ClipMesh.icns</string>\n  <key>LSUIElement</key><true/>\n  <key>NSHighResolutionCapable</key><true/>\n</dict></plist>\nPLIST\ncp target/release/clipmesh "$OUT/clipmesh"\n\nif command -v codesign >/dev/null 2>&1; then\n  codesign --force --deep --sign - "$APP" || true\nfi\n\nif command -v hdiutil >/dev/null 2>&1; then\n  rm -f "$OUT/ClipMesh.dmg"\n  hdiutil create -volname ClipMesh -srcfolder "$APP" -ov -format UDZO "$OUT/ClipMesh.dmg"\n  echo "Built: $OUT/ClipMesh.dmg"\nelse\n  echo "Built app bundle: $APP"\nfi\n', encoding="utf-8")
mac_build.chmod(0o755)

manifest = project / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
manifest_text = manifest.read_text(encoding="utf-8")
old = '        android:label="ClipMesh"\n        android:theme="@style/AppTheme">'
new = '        android:label="ClipMesh"\n        android:icon="@drawable/app_icon"\n        android:roundIcon="@drawable/app_icon"\n        android:theme="@style/AppTheme">'
if old not in manifest_text and 'android:icon="@drawable/app_icon"' not in manifest_text:
    raise SystemExit("Could not patch Android application icon attributes")
manifest_text = manifest_text.replace(old, new)
manifest.write_text(manifest_text, encoding="utf-8")

main_activity = project / "android" / "app" / "src" / "main" / "java" / "dev" / "clipmesh" / "MainActivity.kt"
activity_text = main_activity.read_text(encoding="utf-8")
anchor = """        outer.addView(root)

        root.addView(TextView(this).apply {"""
insertion = """        outer.addView(root)

        root.addView(ImageView(this).apply {
            setImageResource(R.drawable.app_icon)
            adjustViewBounds = true
            scaleType = ImageView.ScaleType.CENTER_INSIDE
            contentDescription = "ClipMesh"
            layoutParams = LinearLayout.LayoutParams(dp(104), dp(104)).apply {
                gravity = android.view.Gravity.CENTER_HORIZONTAL
                bottomMargin = dp(12)
            }
        })

        root.addView(TextView(this).apply {"""
if "setImageResource(R.drawable.app_icon)" not in activity_text:
    if anchor not in activity_text:
        raise SystemExit("Could not patch Android MainActivity icon header")
    activity_text = activity_text.replace(anchor, insertion)
main_activity.write_text(activity_text, encoding="utf-8")

sync_service = project / "android" / "app" / "src" / "main" / "java" / "dev" / "clipmesh" / "SyncService.kt"
service_text = sync_service.read_text(encoding="utf-8")
service_text = service_text.replace(
    ".setSmallIcon(android.R.drawable.ic_menu_share)",
    ".setSmallIcon(R.drawable.ic_clipmesh_notification)\n            .setLargeIcon(android.graphics.BitmapFactory.decodeResource(resources, R.drawable.app_icon))",
)
sync_service.write_text(service_text, encoding="utf-8")

print(f"Extracted and branded project to {project}")
