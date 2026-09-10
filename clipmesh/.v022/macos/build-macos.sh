#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

command -v cargo >/dev/null || { echo "Rust is required"; exit 1; }
command -v swiftc >/dev/null || { echo "Swift compiler is required"; exit 1; }

cargo build --release -p clipmesh

OUT="dist/macos"
APP="$OUT/ClipMesh.app"
ICON_SRC="apps/desktop/assets/clipmesh.png"
ICONSET="$OUT/ClipMesh.iconset"
LAUNCHER_SRC="../ci/ClipMeshApp.swift"
TRANSFER_SRC="../ci/ClipMeshTransfer.swift"
DMG_ROOT="$OUT/dmg-root"

rm -rf "$APP" "$ICONSET" "$DMG_ROOT"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$ICONSET" "$DMG_ROOT"

cp target/release/clipmesh "$APP/Contents/MacOS/clipmesh-bin"
chmod +x "$APP/Contents/MacOS/clipmesh-bin"

MAIN_SRC="$OUT/main.swift"
cp "$LAUNCHER_SRC" "$MAIN_SRC"
swiftc -O "$MAIN_SRC" "$TRANSFER_SRC" -o "$APP/Contents/MacOS/ClipMesh" -framework Cocoa -framework Network -framework UniformTypeIdentifiers
rm -f "$MAIN_SRC"
chmod +x "$APP/Contents/MacOS/ClipMesh"

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
  <key>CFBundleShortVersionString</key><string>0.2.2</string>
  <key>CFBundleVersion</key><string>0.2.2</string>
  <key>CFBundleIconFile</key><string>ClipMesh.icns</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>CFBundleURLTypes</key><array><dict><key>CFBundleURLName</key><string>ClipMesh Share</string><key>CFBundleURLSchemes</key><array><string>clipmesh-share</string></array></dict></array>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key><dict><key>default</key><string>Share with ClipMesh</string></dict>
      <key>NSMessage</key><string>shareFiles</string>
      <key>NSPortName</key><string>ClipMesh</string>
      <key>NSSendTypes</key>
      <array><string>public.file-url</string><string>NSFilenamesPboardType</string></array>
    </dict>
  </array>
</dict></plist>
PLIST

plutil -lint "$APP/Contents/Info.plist"
cp target/release/clipmesh "$OUT/clipmesh"

APPEX="$APP/Contents/PlugIns/ClipMeshShare.appex"
mkdir -p "$APPEX/Contents/MacOS"
cat > "$OUT/ClipMeshShare.m" <<'OBJC'
#import <Cocoa/Cocoa.h>
@interface ClipMeshShareController : NSViewController
@property(nonatomic,strong) NSMutableArray<NSURL *> *files;
@end
@implementation ClipMeshShareController
- (void)loadView { NSView *v=[[NSView alloc]initWithFrame:NSMakeRect(0,0,380,150)];NSTextField*t=[NSTextField labelWithString:@"Send with ClipMesh"];t.font=[NSFont systemFontOfSize:20 weight:NSFontWeightSemibold];t.frame=NSMakeRect(22,102,330,30);[v addSubview:t];NSTextField*s=[NSTextField labelWithString:@"Choose the nearby device in ClipMesh."];s.textColor=NSColor.secondaryLabelColor;s.frame=NSMakeRect(22,73,330,24);[v addSubview:s];NSButton*b=[NSButton buttonWithTitle:@"Open ClipMesh" target:self action:@selector(send:)];b.bezelStyle=NSBezelStyleRounded;b.frame=NSMakeRect(22,24,150,38);[v addSubview:b];self.view=v;self.files=[NSMutableArray array]; }
- (void)viewDidAppear { [super viewDidAppear];for(NSExtensionItem*i in self.extensionContext.inputItems)for(NSItemProvider*p in i.attachments)if([p hasItemConformingToTypeIdentifier:@"public.file-url"])[p loadItemForTypeIdentifier:@"public.file-url" options:nil completionHandler:^(id value,NSError*e){if([value isKindOfClass:NSURL.class]&&[(NSURL*)value isFileURL])@synchronized(self.files){[self.files addObject:(NSURL*)value];}}]; }
- (void)send:(id)sender { if(self.files.count==0)return;NSString*path=[NSTemporaryDirectory() stringByAppendingPathComponent:[NSString stringWithFormat:@"clipmesh-share-%@.txt",NSUUID.UUID.UUIDString]];NSMutableString*body=[NSMutableString string];for(NSURL*u in self.files)[body appendFormat:@"%@\n",u.path];[body writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];NSURLComponents*c=[NSURLComponents componentsWithString:@"clipmesh-share://send"];c.queryItems=@[[NSURLQueryItem queryItemWithName:@"manifest" value:path]];[self.extensionContext openURL:c.URL completionHandler:^(BOOL ok){[self.extensionContext completeRequestReturningItems:@[] completionHandler:nil];}]; }
@end
OBJC
cat > "$APPEX/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>dev.clipmesh.private.Share</string><key>CFBundleName</key><string>ClipMesh</string><key>CFBundleDisplayName</key><string>ClipMesh</string><key>CFBundleExecutable</key><string>ClipMeshShare</string><key>CFBundlePackageType</key><string>XPC!</string><key>CFBundleShortVersionString</key><string>0.2.2</string><key>CFBundleVersion</key><string>0.2.2</string><key>NSExtension</key><dict><key>NSExtensionPointIdentifier</key><string>com.apple.share-services</string><key>NSExtensionPrincipalClass</key><string>ClipMeshShareController</string><key>NSExtensionAttributes</key><dict><key>NSExtensionActivationRule</key><dict><key>NSExtensionActivationDictionaryVersion</key><integer>2</integer><key>NSExtensionActivationSupportsAttachmentsWithMaxCount</key><integer>999</integer><key>NSExtensionActivationSupportsFileWithMaxCount</key><integer>999</integer><key>NSExtensionActivationSupportsImageWithMaxCount</key><integer>999</integer><key>NSExtensionActivationSupportsMovieWithMaxCount</key><integer>999</integer></dict></dict></dict></dict></plist>
PLIST
clang -fobjc-arc -fapplication-extension -framework Cocoa -bundle -o "$APPEX/Contents/MacOS/ClipMeshShare" "$OUT/ClipMeshShare.m"
plutil -lint "$APPEX/Contents/Info.plist"
if command -v codesign >/dev/null 2>&1; then codesign --force --sign - "$APPEX" || true; codesign --force --deep --sign - "$APP" || true; fi
codesign --verify --deep --strict --verbose=2 "$APP"

cp -R "$APP" "$DMG_ROOT/ClipMesh.app"
ln -s /Applications "$DMG_ROOT/Applications"
rm -f "$OUT/ClipMesh.dmg"
hdiutil create -volname ClipMesh -srcfolder "$DMG_ROOT" -ov -format UDZO "$OUT/ClipMesh.dmg"
rm -rf "$DMG_ROOT"

echo "Built native macOS app: $APP"
echo "Built installer: $OUT/ClipMesh.dmg"
