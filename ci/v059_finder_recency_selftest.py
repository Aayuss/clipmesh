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
        ".modificationDate: Date()",
        ".downloadsDirectory",
        "Darwin.rename",
        ".ClipMesh-recency-",
        "for _ in 0..<5",
        "manager.moveItem(at: temporary, to: folder)",
    ):
        assert needle in section, needle
    assert "copyItem(" not in section
    assert "removeItem(" not in section
    assert "contentsOfDirectory" not in section
    assert "if done {" in transfer and "refreshDownloadsFolderRecency()" in transfer
elif SYSTEM in ("Linux","Windows"):
    pass
else:
    raise SystemExit(f"Unsupported platform: {SYSTEM}")

print(f"v059 Finder-recency self-test passed on {SYSTEM}")
