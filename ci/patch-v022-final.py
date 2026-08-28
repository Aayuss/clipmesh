from pathlib import Path
import hashlib, io, lzma, platform, shutil, tarfile

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
ci = root / "ci"
system = platform.system()
parts = [ci / f"v022_sources.part{i:02d}" for i in range(7)] + [
    ci / "v022_sources.part07a", ci / "v022_sources.part07b", ci / "v022_sources.part07c", ci / "v022_sources.part07d",
    ci / "v022_sources.part08a", ci / "v022_sources.part08b", ci / "v022_sources.part08c",
]
missing = [str(path) for path in parts if not path.is_file()]
if missing:
    raise SystemExit(f"missing v0.2.2 source bundle parts: {missing}")
raw = b"".join(path.read_bytes() for path in parts)
expected = "3dacca9a346d9411bef7c231355f56abb809973531637974641a5735373ea29a"
actual = hashlib.sha256(raw).hexdigest()
if actual != expected:
    raise SystemExit(f"v0.2.2 bundle checksum mismatch: {actual}")

unpacked = project / ".v022"
if unpacked.exists(): shutil.rmtree(unpacked)
unpacked.mkdir(parents=True)
with tarfile.open(fileobj=io.BytesIO(lzma.decompress(raw)), mode="r:") as tar:
    tar.extractall(unpacked, filter="data")

def cp(src: str, dst: Path):
    source = unpacked / src
    if not source.is_file(): raise SystemExit(f"v0.2.2 source missing: {source}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dst)

def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1: raise SystemExit(f"{label}: expected one match in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    cp("android/MainActivity.kt", java / "MainActivity.kt")
    cp("android/SettingsActivity.kt", java / "SettingsActivity.kt")
    cp("android/SettingsStore.kt", java / "SettingsStore.kt")
    cp("android/ClipboardBridge.kt", java / "clipboard/ClipboardBridge.kt")
    cp("android/FileShareActivity.kt", java / "fileshare/FileShareActivity.kt")
    cp("android/LocalTransferEngine.kt", java / "fileshare/LocalTransferEngine.kt")
    cp("android/AndroidManifest.xml", project / "android/app/src/main/AndroidManifest.xml")
    gradle = project / "android/app/build.gradle.kts"
    replace_once(gradle, 'versionCode = 11', 'versionCode = 12', 'Android versionCode')
    replace_once(gradle, 'versionName = "0.2.1"', 'versionName = "0.2.2"', 'Android versionName')
    manifest = (project / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    required = [
        'android:usesCleartextTraffic="true"',
        'dev.clipmesh.fileshare.FileShareActivity',
        'dev.clipmesh.fileshare.TransferActionReceiver',
    ]
    for value in required:
        if value not in manifest: raise SystemExit(f"Android v0.2.2 manifest guard missing: {value}")
    bridge = (java / "clipboard/ClipboardBridge.kt").read_text(encoding="utf-8")
    for value in ('capturePending', 'clipmesh://pair?', 'main.postDelayed({ captureAsync(fromWatchdog = false) }, 90L)'):
        if value not in bridge: raise SystemExit(f"Android clipboard guard missing: {value}")
    for file, values in {
        java / "MainActivity.kt": ('bottomNav(0)', 'Current clipboard', 'Type + actual content'),
        java / "fileshare/FileShareActivity.kt": ('bottomNav()', 'ACTION_DROP', 'Rescan'),
        java / "SettingsActivity.kt": ('bottomNav(2)', 'thumbTintList', 'Auto-save from favorited devices'),
    }.items():
        text = file.read_text(encoding="utf-8")
        for value in values:
            if value not in text: raise SystemExit(f"Android UI guard missing in {file.name}: {value}")

elif system == "Darwin":
    cp("macos/ClipMeshApp.swift", root / "ci/ClipMeshApp.swift")
    cp("macos/ClipMeshTransfer.swift", root / "ci/ClipMeshTransfer.swift")
    cp("macos/clipboard.rs", project / "apps/desktop/src/clipboard.rs")
    cp("macos/build-macos.sh", project / "scripts/build-macos.sh")
    app = (root / "ci/ClipMeshApp.swift").read_text(encoding="utf-8")
    transfer = (root / "ci/ClipMeshTransfer.swift").read_text(encoding="utf-8")
    build = (project / "scripts/build-macos.sh").read_text(encoding="utf-8")
    for value in ('buildClipboardPage()', 'buildTransferPage()', 'buildSettingsPage()', 'CMFileDropView', 'hasVerticalScroller = true', 'registerShareExtension', 'dev.clipmesh.private.Share'):
        if value not in app: raise SystemExit(f"macOS UI guard missing: {value}")
    for value in ('convenience init(title: String, handler:', 'TransferSelfTest', 'setFavorite(fp, true)'):
        if value not in transfer: raise SystemExit(f"macOS transfer guard missing: {value}")
    for value in ('<string>0.2.2</string>', 'com.apple.share-services', 'dev.clipmesh.private.Share', 'NSExtensionActivationSupportsImageWithMaxCount'):
        if value not in build: raise SystemExit(f"macOS package guard missing: {value}")

elif system == "Windows":
    cp("windows/ClipMeshWindows.cs", root / "ci/ClipMeshWindows.cs")
    cp("windows/ClipMeshTransfer.cs", root / "ci/ClipMeshTransfer.cs")
    cp("windows/build-windows.ps1", project / "scripts/build-windows.ps1")
    ui = (root / "ci/ClipMeshWindows.cs").read_text(encoding="utf-8")
    transfer = (root / "ci/ClipMeshTransfer.cs").read_text(encoding="utf-8")
    for value in ('"Clipboard", "File transfer", "Settings"', 'AllowDrop = true', 'RefreshClipboardPreview()', 'ChooseTransferFiles()', 'SwitchTab(1)'):
        if value not in ui: raise SystemExit(f"Windows UI guard missing: {value}")
    for value in ('public void DiscoverNow()', 'AddSeconds(-180)', 'i < 1200 && Running', 'Share with ClipMesh'):
        if value not in transfer: raise SystemExit(f"Windows transfer guard missing: {value}")
else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh v0.2.2 final patch on {system}; bundle sha256={actual}")
