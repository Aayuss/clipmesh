#!/usr/bin/env python3
"""Apply ClipMesh v0.2.22 release metadata after patch-v058-release.py."""

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
    replace_exact(gradle, "versionCode = 31", "versionCode = 32", "Android v0.2.22 versionCode")
    replace_exact(gradle, 'versionName = "0.2.21"', 'versionName = "0.2.22"', "Android v0.2.22 versionName")
elif system == "Darwin":
    replace_exact(project / "scripts/build-macos.sh", "0.2.21", "0.2.22", "macOS v0.2.22 version metadata", expected=4)
elif system == "Windows":
    replace_exact(
        root / "ci/ClipMeshWindows.cs",
        'private const string Version = "0.2.21";',
        'private const string Version = "0.2.22";',
        "Windows v0.2.22 runtime version",
    )
else:
    raise SystemExit(f"unsupported platform: {system}")

replace_exact(project / "Cargo.toml", 'version = "0.2.21"', 'version = "0.2.22"', f"{system} Cargo package version")
print(f"Applied ClipMesh v0.2.22 release metadata on {system}")
