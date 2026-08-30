#!/usr/bin/env python3
"""ClipMesh v0.2.12 release-only metadata bump.

Apply this after the canonical reconstructed v0.2.11 source has passed the
physical E2E matrix. It changes version metadata only - no runtime behavior.
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
    replace_exact(gradle, "versionCode = 21", "versionCode = 22", "Android v0.2.12 versionCode")
    replace_exact(
        gradle,
        'versionName = "0.2.11"',
        'versionName = "0.2.12"',
        "Android v0.2.12 versionName",
    )
elif system == "Darwin":
    build = project / "scripts/build-macos.sh"
    replace_exact(
        build,
        "0.2.11",
        "0.2.12",
        "macOS v0.2.12 version metadata",
        expected=4,
    )
elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    replace_exact(
        ui,
        'private const string Version = "0.2.11";',
        'private const string Version = "0.2.12";',
        "Windows v0.2.12 runtime version",
    )
else:
    raise SystemExit(f"unsupported platform: {system}")

cargo = project / "Cargo.toml"
replace_exact(
    cargo,
    'version = "0.2.11"',
    'version = "0.2.12"',
    f"{system} Cargo package version",
)

print(f"Applied ClipMesh v0.2.12 release metadata on {system}")
