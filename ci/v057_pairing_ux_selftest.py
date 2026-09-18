#!/usr/bin/env python3
"""Static guards for v057 pairing UX and Android first-run initialization."""

from __future__ import annotations
import os, platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"v057 missing source: {path}")
    return path.read_text(encoding="utf-8")

def require(text: str, *needles: str) -> None:
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"v057 guard missing: {needle}")

if SYSTEM == "Darwin":
    app = read(ROOT / "ci/ClipMeshApp.swift")
    require(app,
        "private var nearbyCodePanel: NSPanel?",
        'NSTextField(labelWithString: "Verification code")',
        'NSTextField(wrappingLabelWithString: "Enter this code on \\(device).")',
        "codeBox.widthAnchor.constraint(equalToConstant: 404)",
        ".monospacedDigitSystemFont(ofSize: 46, weight: .bold)",
        'NSTextField(labelWithString: "Waiting for confirmation…")',
        "window.beginSheet(panel)",
        "parent.endSheet(panel)",
        'input.placeholderString = "6-digit code"',
    )
    if "nearbyCodeAlert" in app:
        raise SystemExit("v057 old NSAlert verification panel survived")
elif SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    main = read(java / "MainActivity.kt")
    dialog = read(java / "ClipMeshDialog.kt")
    require(main,
        "ensureLocalClipboardSpace()",
        "val data = Pairing.createSpace(settings.deviceName, settings.deviceId)",
        "secrets.saveSpaceKey(data.key)",
        'toast("ClipMesh could not prepare pairing")',
    )
    if "Create or join a clipboard space first" in main:
        raise SystemExit("v057 manual Android space prerequisite survived")
    require(dialog,
        "Color.argb(68, 166, 163, 156)",
        'hint = "000000"',
        "emphasized",
    )
elif SYSTEM == "Windows":
    pass
else:
    raise SystemExit(f"Unsupported CLIPMESH_PLATFORM: {SYSTEM}")

print(f"v057 pairing UX self-test passed on {SYSTEM}")
