#!/usr/bin/env python3
from pathlib import Path
import os, platform

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM == "Darwin":
    transfer = (ROOT / "ci/ClipMeshTransfer.swift").read_text(encoding="utf-8")
    section = transfer.split("private func refreshDownloadsFolderRecency()",1)[1].split("private func destinationURL",1)[0]
    for needle in (
        "TransferPrefs.outputFolder.standardizedFileURL",
        ".modificationDate: now",
        "setFinderDateAdded(now, for: folder.path)",
        '"/usr/bin/mdimport"',
    ):
        assert needle in section, needle
    for needle in ("ATTR_CMN_ADDEDTIME", "setattrlist("):
        assert needle in transfer, needle
    for forbidden in (
        "Darwin.rename",
        ".ClipMesh-recency-",
        "copyItem(",
        "moveItem(",
        "removeItem(",
        "contentsOfDirectory",
    ):
        assert forbidden not in section, forbidden
    assert "if done {" in transfer and "refreshDownloadsFolderRecency()" in transfer
elif SYSTEM in ("Linux","Windows"):
    pass
else:
    raise SystemExit(f"Unsupported platform: {SYSTEM}")

print(f"v059 Finder-recency self-test passed on {SYSTEM}")
