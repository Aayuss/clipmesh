#!/usr/bin/env python3
"""ClipMesh v063: shared "Ember" UI layer for Android, macOS and Windows.

This is the final reconstruction layer. It installs the redesigned platform UI
sources kept under ci/v063/, bundles the Sora typeface, clears sent files after
a successful desktop transfer, renders clipboard images instead of raw pasteboard
type identifiers, and rebuilds the macOS Finder Share extension as a sandboxed,
properly linked app extension so macOS lists it under Share.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "ci"
LAYER = CI / "v063"
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())
FONTS = ("sora_regular.ttf", "sora_medium.ttf", "sora_semibold.ttf", "sora_bold.ttf")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one regex match in {path}, found {count}")
    path.write_text(updated, encoding="utf-8")


def install(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"v063 missing layer source: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def install_tree(source_root: Path, target_root: Path) -> None:
    for source in sorted(source_root.rglob("*")):
        if source.is_file():
            install(source, target_root / source.relative_to(source_root))


def run_layer(path: Path, **extra) -> None:
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"),
         {"__name__": "__v063__", "ROOT": ROOT, "PROJECT": PROJECT, "LAYER": LAYER, "FONTS": FONTS,
          "replace_once": replace_once, "regex_once": regex_once, "install": install, **extra})


if SYSTEM in ("Darwin", "Windows"):
    run_layer(LAYER / "desktop/patch_daemon.py")

if SYSTEM == "Darwin":
    from_dir = LAYER / "macos"
    for name in ("ClipMeshApp.swift", "ClipMeshTransfer.swift"):
        install(from_dir / name, CI / name)
    build = PROJECT / "scripts/build-macos.sh"
    # Applied by the macOS section below once the layer sources exist.
    exec(compile((LAYER / "macos/patch_build.py").read_text(encoding="utf-8"), str(LAYER / "macos/patch_build.py"), "exec"),
         {"__name__": "__v063__", "ROOT": ROOT, "PROJECT": PROJECT, "LAYER": LAYER, "FONTS": FONTS,
          "replace_once": replace_once, "regex_once": regex_once, "install": install, "build": build})
    print("Applied ClipMesh v063 Ember UI on Darwin")

elif SYSTEM == "Windows":
    from_dir = LAYER / "windows"
    for name in ("ClipMeshWindows.cs", "ClipMeshTransfer.cs"):
        install(from_dir / name, CI / name)
    exec(compile((LAYER / "windows/patch_build.py").read_text(encoding="utf-8"), str(LAYER / "windows/patch_build.py"), "exec"),
         {"__name__": "__v063__", "ROOT": ROOT, "PROJECT": PROJECT, "LAYER": LAYER, "FONTS": FONTS,
          "replace_once": replace_once, "regex_once": regex_once, "install": install})
    print("Applied ClipMesh v063 Ember UI on Windows")

elif SYSTEM == "Linux":
    app = PROJECT / "android/app"
    install_tree(LAYER / "android/src", app / "src")
    for font in FONTS:
        install(LAYER / "fonts" / font, app / "src/main/res/font" / font)
    exec(compile((LAYER / "android/patch_build.py").read_text(encoding="utf-8"), str(LAYER / "android/patch_build.py"), "exec"),
         {"__name__": "__v063__", "ROOT": ROOT, "PROJECT": PROJECT, "LAYER": LAYER, "FONTS": FONTS,
          "replace_once": replace_once, "regex_once": regex_once, "install": install})
    print("Applied ClipMesh v063 Ember UI on Linux")

else:
    raise SystemExit(f"Unsupported CLIPMESH_PLATFORM: {SYSTEM}")
