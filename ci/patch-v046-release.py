#!/usr/bin/env python3
"""ClipMesh v0.2.15 release-only metadata bump.

Apply this after patch-v036-release.py. The product/runtime code remains the
physically verified generation at commit ce8dae678e8cd3f7bc40613c4ea317d9a9598ff4;
this layer changes only cross-platform version metadata.
"""

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
    replace_exact(gradle, "versionCode = 22", "versionCode = 25", "Android v0.2.15 versionCode")
    replace_exact(
        gradle,
        'versionName = "0.2.12"',
        'versionName = "0.2.15"',
        "Android v0.2.15 versionName",
    )
elif system == "Darwin":
    build = project / "scripts/build-macos.sh"
    replace_exact(
        build,
        "0.2.12",
        "0.2.15",
        "macOS v0.2.15 version metadata",
        expected=4,
    )
elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    replace_exact(
        ui,
        'private const string Version = "0.2.12";',
        'private const string Version = "0.2.15";',
        "Windows v0.2.15 runtime version",
    )
else:
    raise SystemExit(f"unsupported platform: {system}")

cargo = project / "Cargo.toml"
replace_exact(
    cargo,
    'version = "0.2.12"',
    'version = "0.2.15"',
    f"{system} Cargo package version",
)

print(f"Applied ClipMesh v0.2.15 release metadata on {system}")
