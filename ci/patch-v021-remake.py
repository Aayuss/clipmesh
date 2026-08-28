from pathlib import Path
import base64
import io
import lzma
import platform
import shutil
import tarfile

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = platform.system()
payload = root / "ci/v021_sources.b64"
unpacked = project / ".v021"

if unpacked.exists():
    shutil.rmtree(unpacked)
unpacked.mkdir(parents=True)
raw = base64.b64decode(payload.read_text(encoding="ascii"))
with tarfile.open(fileobj=io.BytesIO(lzma.decompress(raw)), mode="r:") as tar:
    tar.extractall(unpacked)


def copy(src: str, dst: Path):
    source = unpacked / src
    if not source.is_file():
        raise SystemExit(f"v0.2.1 source missing: {source}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dst)


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if system == "Linux":
    android = project / "android/app/src/main/java/dev/clipmesh"
    copy("android/MainActivity.kt", android / "MainActivity.kt")
    copy("android/SettingsActivity.kt", android / "SettingsActivity.kt")
    copy("android/ClipboardBridge.kt", android / "clipboard/ClipboardBridge.kt")
    copy("android/FileShareActivity.kt", android / "fileshare/FileShareActivity.kt")
    copy("android/ClipboardUserService.kt", android / "shizuku/ClipboardUserService.kt")
    shizuku = android / "shizuku/ShizukuManager.kt"
    replace_once(shizuku, ".version(3)", ".version(4)", "Shizuku UserService generation")
    gradle = project / "android/app/build.gradle.kts"
    replace_once(gradle, "versionCode = 10", "versionCode = 11", "Android versionCode")
    replace_once(gradle, 'versionName = "0.2.0"', 'versionName = "0.2.1"', "Android versionName")
    user_service = (android / "shizuku/ClipboardUserService.kt").read_text(encoding="utf-8")
    for required in ('ProcessBuilder("/system/bin/content", "read", "--uri"', 'constructor(context: Context)', 'readUriAsShell(uri)'):
        if required not in user_service:
            raise SystemExit(f"v0.2.1 missing Android image-copy fix: {required}")
    main = (android / "MainActivity.kt").read_text(encoding="utf-8")
    for required in ("Clipboard", "File Transfer", "renderClipboardPreview", "View.GONE", "IMAGE", "NEARBY DEVICES"):
        if required not in main:
            raise SystemExit(f"v0.2.1 missing Android UI guard: {required}")

elif system == "Darwin":
    copy("macos/build-macos.sh", project / "scripts/build-macos.sh")
    target = root / "ci/v021"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("ClipMeshApp.swift", "ClipMeshTransfer.swift", "ClipMeshClipboardPreview.swift", "ClipMeshShareExtension.swift"):
        copy(f"macos/{name}", target / name)

elif system == "Windows":
    copy("windows/ClipMeshWindows.cs", root / "ci/ClipMeshWindows.cs")
    copy("windows/ClipMeshTransfer.cs", root / "ci/ClipMeshTransfer.cs")
    win_build = project / "scripts/build-windows.ps1"
    text = win_build.read_text(encoding="utf-8")
    if "0.2.0" not in text:
        raise SystemExit("Windows v0.2.0 runtime anchor missing")
    win_build.write_text(text.replace("0.2.0", "0.2.1"), encoding="utf-8")

else:
    raise SystemExit(f"v0.2.1 platform patch unsupported on {system}")

print(f"Applied ClipMesh v0.2.1 remake for {system}")
