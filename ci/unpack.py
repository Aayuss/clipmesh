from __future__ import annotations

import base64
import hashlib
import pathlib
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CI = ROOT / "ci"
parts = sorted(CI.glob("source.part*.b64"))
if len(parts) != 4:
    raise SystemExit(f"Expected 4 source chunks, found {len(parts)}")

encoded = "".join(p.read_text(encoding="utf-8").strip() for p in parts)
archive_bytes = base64.b64decode(encoded, validate=True)
archive = CI / "clipmesh-source.tar.xz"
archive.write_bytes(archive_bytes)
print(f"source archive sha256={hashlib.sha256(archive_bytes).hexdigest()}")

with tarfile.open(archive, mode="r:xz") as tf:
    # The archive is created by us and contains one top-level clipmesh directory.
    tf.extractall(ROOT, filter="data")

project = ROOT / "clipmesh"
if not (project / "Cargo.toml").is_file() or not (project / "android" / "settings.gradle.kts").is_file():
    raise SystemExit("Source archive did not unpack into the expected clipmesh project")
print(f"Extracted project to {project}")
