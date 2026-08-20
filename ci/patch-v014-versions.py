from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_required(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Native wrappers and package metadata have their own version strings in addition
# to Cargo.toml. Keep all of them aligned so update/runtime paths are deterministic.
replace_required(root / "ci" / "ClipMeshWindows.cs", 'private const string Version = "0.1.3";', 'private const string Version = "0.1.4";', "Windows wrapper version")
replace_required(project / "scripts" / "build-macos.sh", '<key>CFBundleShortVersionString</key><string>0.1.3</string>', '<key>CFBundleShortVersionString</key><string>0.1.4</string>', "macOS short version")
replace_required(project / "scripts" / "build-macos.sh", '<key>CFBundleVersion</key><string>0.1.3</string>', '<key>CFBundleVersion</key><string>0.1.4</string>', "macOS bundle version")

android_gradle = project / "android" / "app" / "build.gradle.kts"
text = android_gradle.read_text(encoding="utf-8")
if 'versionCode = 3' in text:
    text = text.replace('versionCode = 3', 'versionCode = 4', 1)
if 'versionName = "0.1.3"' in text:
    text = text.replace('versionName = "0.1.3"', 'versionName = "0.1.4"', 1)
android_gradle.write_text(text, encoding="utf-8")

print("Aligned ClipMesh native package/runtime metadata to v0.1.4")
