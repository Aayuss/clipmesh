#!/usr/bin/env python3
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "ci/patch-acceptance-v2.py"), run_name="__main__")
runpy.run_path(str(ROOT / "ci/patch-acceptance-v3.py"), run_name="__main__")
print("Applied ClipMesh complete physical acceptance patch chain")
