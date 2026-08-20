from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_if_present(path: Path, old: str, new: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Native wrappers and package metadata have their own version strings in addition
# to Cargo.toml. The v0.1.5 reliability patch owns peer-status/transport semantics;
# this script is intentionally version-only.
replace_if_present(root / "ci" / "ClipMeshWindows.cs", 'private const string Version = "0.1.3";', 'private const string Version = "0.1.5";')
replace_if_present(root / "ci" / "ClipMeshWindows.cs", 'private const string Version = "0.1.4";', 'private const string Version = "0.1.5";')
replace_if_present(project / "scripts" / "build-macos.sh", '<key>CFBundleShortVersionString</key><string>0.1.3</string>', '<key>CFBundleShortVersionString</key><string>0.1.5</string>')
replace_if_present(project / "scripts" / "build-macos.sh", '<key>CFBundleShortVersionString</key><string>0.1.4</string>', '<key>CFBundleShortVersionString</key><string>0.1.5</string>')
replace_if_present(project / "scripts" / "build-macos.sh", '<key>CFBundleVersion</key><string>0.1.3</string>', '<key>CFBundleVersion</key><string>0.1.5</string>')
replace_if_present(project / "scripts" / "build-macos.sh", '<key>CFBundleVersion</key><string>0.1.4</string>', '<key>CFBundleVersion</key><string>0.1.5</string>')

android_gradle = project / "android" / "app" / "build.gradle.kts"
text = android_gradle.read_text(encoding="utf-8")
for old_code in ('versionCode = 3', 'versionCode = 4'):
    if old_code in text:
        text = text.replace(old_code, 'versionCode = 5', 1)
        break
for old_name in ('versionName = "0.1.3"', 'versionName = "0.1.4"'):
    if old_name in text:
        text = text.replace(old_name, 'versionName = "0.1.5"', 1)
        break
android_gradle.write_text(text, encoding="utf-8")

print("Aligned ClipMesh v0.1.5 native package metadata")
