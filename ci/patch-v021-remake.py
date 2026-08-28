from pathlib import Path
import base64
import hashlib
import io
import lzma
import platform
import shutil
import tarfile

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
ci = root / "ci"
system = platform.system()
unpacked = project / ".v021"

parts = [ci / f"v021s.part{i:02d}.b64" for i in range(9)]
missing = [str(p) for p in parts if not p.is_file()]
if missing:
    raise SystemExit(f"v0.2.1 source bundle chunks missing: {missing}")
chunks = [p.read_text(encoding="ascii").strip() for p in parts]
encoded = "".join(chunk.rstrip("=") for chunk in chunks)
encoded += "=" * ((4 - len(encoded) % 4) % 4)
raw = base64.b64decode(encoded, validate=True)
expected_sha = "93c3dec963163912995c262e8cbb0a42c41af846f766c2b116b73720c9eada3c"
actual_sha = hashlib.sha256(raw).hexdigest()
if actual_sha != expected_sha:
    details = ", ".join(f"p{i}={len(c)}" for i, c in enumerate(chunks))
    raise SystemExit(f"v0.2.1 source bundle checksum mismatch: {actual_sha}; {details}")

if unpacked.exists():
    shutil.rmtree(unpacked)
unpacked.mkdir(parents=True)
try:
    unpacked_tar = lzma.decompress(raw)
except lzma.LZMAError as exc:
    raise SystemExit(f"v0.2.1 XZ bundle invalid despite checksum {actual_sha}: {exc}") from exc
with tarfile.open(fileobj=io.BytesIO(unpacked_tar), mode="r:") as tar:
    tar.extractall(unpacked, filter="data")


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
    for name in ("ClipMeshApp.swift", "ClipMeshTransfer.swift", "ClipMeshClipboardPreview.swift", "ClipMeshShareExtension.swift", "ClipMeshShare.m", "ClipMeshShare-Info.plist", "ClipMeshShare.entitlements"):
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

print(f"Applied ClipMesh v0.2.1 remake for {system}; source sha256={actual_sha}")
