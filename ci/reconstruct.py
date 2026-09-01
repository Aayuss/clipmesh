#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import runpy
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "ci"

PIPELINES = {
    "Darwin": [
        "patch-features.py", "patch-sync-fixes.py", "patch-desktop.py", "patch-macos.py",
        "patch-v014-versions.py", "patch-v015-sync.py", "patch-v016-sync.py", "patch-v017-shizuku.py",
        "patch-v018-features.py", "patch-v019-fixes.py", "patch-v020-fileshare.py", "patch-v020-native.py",
        "patch-v021-final.py", "patch-v021-compile-hotfix.py", "patch-v022-final.py", "patch-v022-hotfix.py",
        "patch-v023-final.py", "patch-v024-repair.py", "patch-v025-nearby-pairing.py", "patch-v026-regressions.py",
        "patch-v027-macos-daemon.py", "patch-v030-finalize.py", "patch-v031-dev-test.py",
        "patch-v032-release.py", "patch-v033-ipv4-transfer.py", "patch-v038-file-transfer-visibility.py",
        "patch-v039-lan-discovery.py", "patch-v040-macos-resilience.py",
        "patch-v043-desktop-image-echo.py",
        "patch-v044-image-provenance.py",
        "patch-v045-screenshot-adjacent-dedupe.py",
        "patch-v047-file-transfer-progress.py",
    ],
    "Linux": [
        "patch-features.py", "patch-sync-fixes.py",
        "patch-v014-versions.py", "patch-v015-sync.py", "patch-v016-sync.py", "patch-v017-shizuku.py",
        "patch-v018-features.py", "patch-v019-fixes.py", "patch-v020-fileshare.py",
        "patch-v021-final.py", "patch-v021-compile-hotfix.py", "patch-v022-final.py", "patch-v022-hotfix.py",
        "patch-v023-final.py", "patch-v023-android-hotfix.py", "patch-v024-repair.py", "patch-v025-nearby-pairing.py",
        "patch-v026-regressions.py", "patch-v027-macos-daemon.py", "patch-v030-finalize.py", "patch-v031-dev-test.py",
        "patch-v032-release.py", "patch-v033-ipv4-transfer.py", "patch-v034-shizuku-clipboard.py",
        "patch-v035-e2e-observability.py", "patch-v038-file-transfer-visibility.py", "patch-v039-lan-discovery.py",
        "patch-v040-macos-resilience.py", "patch-v041-android-remote-suppression.py",
        "patch-v042-android-once-delivery.py", "patch-v043-desktop-image-echo.py",
        "patch-v044-image-provenance.py",
        "patch-v045-screenshot-adjacent-dedupe.py",
        "patch-v047-file-transfer-progress.py",
    ],
    "Windows": [
        "patch-features.py", "patch-sync-fixes.py", "patch-desktop.py", "patch-windows.py",
        "patch-v014-versions.py", "patch-v015-sync.py", "patch-v016-sync.py", "patch-v017-shizuku.py",
        "patch-v018-features.py", "patch-v019-fixes.py", "patch-v020-fileshare.py", "patch-v020-native.py",
        "patch-v021-final.py", "patch-v021-compile-hotfix.py", "patch-v022-final.py", "patch-v022-hotfix.py",
        "patch-v023-windows.py", "patch-v024-repair.py", "patch-v025-nearby-pairing.py", "patch-v026-regressions.py",
        "patch-v027-macos-daemon.py", "patch-v030-finalize.py", "patch-v031-dev-test.py",
        "patch-v032-release.py", "patch-v033-ipv4-transfer.py", "patch-v038-file-transfer-visibility.py",
        "patch-v039-lan-discovery.py", "patch-v040-macos-resilience.py",
        "patch-v043-desktop-image-echo.py",
        "patch-v044-image-provenance.py",
        "patch-v045-screenshot-adjacent-dedupe.py",
        "patch-v047-file-transfer-progress.py",
    ],
}


def run(path: Path) -> None:
    print(f"[reconstruct] {path.name}")
    runpy.run_path(str(path), run_name="__main__")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct ClipMesh for a target platform from the retained source archive.")
    parser.add_argument("--platform", choices=sorted(PIPELINES), required=True)
    parser.add_argument("--keep", action="store_true", help="Do not remove an existing generated clipmesh/ directory first.")
    args = parser.parse_args()

    generated = ROOT / "clipmesh"
    if generated.exists() and not args.keep:
        shutil.rmtree(generated)

    target = args.platform
    os.environ["CLIPMESH_PLATFORM"] = target
    real_platform_system = platform.system
    platform.system = lambda: target  # type: ignore[assignment]
    try:
        run(CI / "prepare-icon-assets.py")
        run(CI / "unpack.py")
        for name in PIPELINES[target]:
            path = CI / name
            if not path.is_file():
                raise SystemExit(f"Missing patch layer: {path}")
            run(path)
    finally:
        platform.system = real_platform_system  # type: ignore[assignment]

    print(f"[reconstruct] ClipMesh v0.2.11 target={target} ready at {generated}")


if __name__ == "__main__":
    main()
