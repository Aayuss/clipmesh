#!/usr/bin/env python3
"""Apply ClipMesh v0.2.24 release metadata after patch-v062-release.py."""

from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

def replace_exact(path: Path, old: str, new: str, label: str, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} match(es) in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")

if system == "Linux":
    gradle = project / "android/app/build.gradle.kts"
    replace_exact(gradle, "versionCode = 33", "versionCode = 34", "Android v0.2.24 versionCode")
    replace_exact(gradle, 'versionName = "0.2.23"', 'versionName = "0.2.24"', "Android v0.2.24 versionName")
elif system == "Darwin":
    replace_exact(project / "scripts/build-macos.sh", "0.2.23", "0.2.24", "macOS v0.2.24 version metadata", expected=4)
elif system == "Windows":
    replace_exact(
        root / "ci/ClipMeshWindows.cs",
        'private const string Version = "0.2.23";',
        'private const string Version = "0.2.24";',
        "Windows v0.2.24 runtime version",
    )
else:
    raise SystemExit(f"unsupported platform: {system}")

replace_exact(project / "Cargo.toml", 'version = "0.2.23"', 'version = "0.2.24"', f"{system} Cargo package version")
print(f"Applied ClipMesh v0.2.24 release metadata on {system}")
