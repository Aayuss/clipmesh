# v063 macOS build integration.
#
# Executed by ci/patch-v063-ember-ui.py with the globals ROOT, PROJECT, LAYER,
# FONTS, replace_once, regex_once, install and build (clipmesh/scripts/build-macos.sh).
#
# 1. Bundle the Sora typeface (Contents/Resources/Fonts + ATSApplicationFontsPath).
# 2. Rebuild the Finder Share extension as a real, sandboxed app extension:
#    MH_EXECUTE with the _NSExtensionMain entry point, complete XPC! Info.plist,
#    signed with its own entitlements before the outer app is signed WITHOUT
#    --deep (which would strip the nested sandbox entitlement).
#
# Release patches bump the version literal in build-macos.sh with an exact
# expected count of 4, so this layer must never add or remove version strings.

_version_literals_before = len(__import__("re").findall(r"0\.2\.\d+", build.read_text(encoding="utf-8")))

replace_once(
    build,
    'iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/ClipMesh.icns"\n',
    'iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/ClipMesh.icns"\n'
    'mkdir -p "$APP/Contents/Resources/Fonts"\n'
    "for font in " + " ".join(FONTS) + "; do\n"
    '  cp "../ci/v063/fonts/$font" "$APP/Contents/Resources/Fonts/$font"\n'
    "done\n",
    "v063 macOS bundled Sora fonts",
)

replace_once(
    build,
    "  <key>NSHighResolutionCapable</key><true/>\n",
    "  <key>NSHighResolutionCapable</key><true/>\n"
    "  <key>ATSApplicationFontsPath</key><string>Fonts</string>\n",
    "v063 macOS font registration key",
)

# The inline Objective-C heredoc becomes a real source file in the layer.
regex_once(
    build,
    r"cat > \"\$OUT/ClipMeshShare\.m\" <<'OBJC'\n.*?\nOBJC\n",
    'SHARE_SRC="../ci/v063/macos/ClipMeshShare.m"\n'
    'SHARE_ENTITLEMENTS="../ci/v063/macos/ClipMeshShare.entitlements"\n'
    'mkdir -p "$APPEX/Contents/Resources"\n'
    'cp "$APP/Contents/Resources/ClipMesh.icns" "$APPEX/Contents/Resources/ClipMesh.icns"\n',
    "v063 macOS share extension source",
)

# Complete the extension bundle metadata. Version keys stay exactly as they are.
replace_once(
    build,
    "<key>CFBundlePackageType</key><string>XPC!</string>",
    "<key>CFBundlePackageType</key><string>XPC!</string>"
    "<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>"
    "<key>CFBundleSupportedPlatforms</key><array><string>MacOSX</string></array>"
    "<key>LSMinimumSystemVersion</key><string>12.0</string>"
    "<key>CFBundleIconFile</key><string>ClipMesh</string>",
    "v063 macOS share extension Info.plist",
)

replace_once(
    build,
    'clang -fobjc-arc -fapplication-extension -framework Cocoa -bundle -o "$APPEX/Contents/MacOS/ClipMeshShare" "$OUT/ClipMeshShare.m"\n',
    'clang -fobjc-arc -fapplication-extension -mmacosx-version-min=12.0 -e _NSExtensionMain -framework Cocoa -framework Foundation -framework QuartzCore -o "$APPEX/Contents/MacOS/ClipMeshShare" "$SHARE_SRC"\n'
    'file "$APPEX/Contents/MacOS/ClipMeshShare" | grep -q "Mach-O.*executable" || { echo "ClipMeshShare must be an MH_EXECUTE app extension"; exit 1; }\n'
    'plutil -lint "$SHARE_ENTITLEMENTS"\n',
    "v063 macOS share extension executable",
)

replace_once(
    build,
    'if command -v codesign >/dev/null 2>&1; then codesign --force --sign - "$APPEX" || true; codesign --force --deep --sign - "$APP" || true; fi\n',
    "if command -v codesign >/dev/null 2>&1; then\n"
    "  # Inside-out, never --deep: the extension keeps its sandbox entitlements.\n"
    '  codesign --force --sign - "$APP/Contents/MacOS/clipmesh-bin"\n'
    '  codesign --force --sign - --entitlements "$SHARE_ENTITLEMENTS" "$APPEX"\n'
    '  codesign --force --sign - "$APP"\n'
    '  codesign -d --entitlements - "$APPEX" 2>/dev/null | grep -q "com.apple.security.app-sandbox" || { echo "ClipMeshShare.appex is missing its sandbox entitlement"; exit 1; }\n'
    "fi\n",
    "v063 macOS inside-out signing",
)

_text = build.read_text(encoding="utf-8")
for _needle in ("-e _NSExtensionMain", "ATSApplicationFontsPath", "--entitlements \"$SHARE_ENTITLEMENTS\"", "XPC!"):
    if _needle not in _text:
        raise SystemExit(f"v063 macOS build guard missing: {_needle}")
if "-bundle -o \"$APPEX" in _text or "codesign --force --deep" in _text:
    raise SystemExit("v063 macOS build still links the extension as a bundle or deep-signs the app")
if len(__import__("re").findall(r"0\.2\.\d+", _text)) != _version_literals_before:
    raise SystemExit("v063 macOS build must not change the number of version literals")
