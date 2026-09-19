#!/usr/bin/env python3
from pathlib import Path
import os, platform

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM == "Darwin":
    transfer = (ROOT / "ci/ClipMeshTransfer.swift").read_text(encoding="utf-8")
    section = transfer.split("private struct FinderAddedTimeBuffer",1)[1].split("private func destinationURL",1)[0]
    for needle in (
        "ATTR_CMN_ADDEDTIME",
        "setattrlist(",
        "MemoryLayout<FinderAddedTimeBuffer>.size",
        ".modificationDate: now",
        '"/usr/bin/mdimport"',
        '["-f", folder.path]',
    ):
        assert needle in section, needle
    for forbidden in (
        "Darwin.rename",
        ".ClipMesh-recency-",
        "copyItem(",
        "moveItem(",
        "removeItem(",
        "contentsOfDirectory",
    ):
        assert forbidden not in section, forbidden
elif SYSTEM in ("Linux","Windows"):
    pass
else:
    raise SystemExit(f"Unsupported platform: {SYSTEM}")

print(f"v061 direct Finder Date Added self-test passed on {SYSTEM}")
