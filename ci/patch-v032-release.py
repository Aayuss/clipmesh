#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
from pathlib import Path

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
    replace_exact(gradle, "versionCode = 19", "versionCode = 20", "Android v0.2.10 versionCode")
    replace_exact(
        gradle,
        'versionName = "0.2.9"',
        'versionName = "0.2.10"',
        "Android v0.2.10 versionName",
    )
elif system == "Darwin":
    build = project / "scripts/build-macos.sh"
    replace_exact(
        build,
        "CFBundleShortVersionString</key><string>0.2.9",
        "CFBundleShortVersionString</key><string>0.2.10",
        "macOS v0.2.10 short version",
        expected=2,
    )
    replace_exact(
        build,
        "CFBundleVersion</key><string>0.2.9",
        "CFBundleVersion</key><string>0.2.10",
        "macOS v0.2.10 bundle version",
        expected=2,
    )
elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    replace_exact(
        ui,
        'private const string Version = "0.2.9";',
        'private const string Version = "0.2.10";',
        "Windows v0.2.10 runtime version",
    )
else:
    raise SystemExit(f"unsupported platform: {system}")

cargo = project / "Cargo.toml"
replace_exact(
    cargo,
    'version = "0.1.0"',
    'version = "0.2.10"',
    f"{system} Cargo package version",
)

print(f"Applied canonical ClipMesh v0.2.10 release version metadata on {system}")
