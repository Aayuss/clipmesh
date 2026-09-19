#!/usr/bin/env python3
"""Runtime verification for the macOS Finder Date Added setter."""

from pathlib import Path
import ctypes
import os
import platform
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM == "Darwin":
    transfer = (ROOT / "ci/ClipMeshTransfer.swift").read_text(encoding="utf-8")
    build = (ROOT / "clipmesh/scripts/build-macos.sh").read_text(encoding="utf-8")
    helper = ROOT / "ci/ClipMeshDateAdded.c"

    section = transfer.split("private func refreshDownloadsFolderRecency()", 1)[1].split("private func destinationURL", 1)[0]
    for needle in (
        "clipmeshSetDateAddedNow",
        "ATTR_CMN_ADDEDTIME",
        "NSWorkspace.shared.noteFileSystemChanged(folder.path)",
    ):
        haystack = helper.read_text(encoding="utf-8") if needle == "ATTR_CMN_ADDEDTIME" else transfer
        assert needle in haystack, needle

    assert "Darwin.rename" not in section
    assert ".ClipMesh-recency-" not in section
    assert "copyItem(" not in section
    assert "removeItem(" not in section
    assert 'DATE_ADDED_SRC="../ci/ClipMeshDateAdded.c"' in build
    assert 'clang -O2 -c "$DATE_ADDED_SRC"' in build
    assert '"$DATE_ADDED_OBJ"' in build

    with tempfile.TemporaryDirectory(prefix="clipmesh-date-added-") as td:
        dylib = Path(td) / "libclipmesh-dateadded.dylib"
        subprocess.run(["clang", "-dynamiclib", "-O2", str(helper), "-o", str(dylib)], check=True)
        lib = ctypes.CDLL(str(dylib), use_errno=True)
        lib.clipmesh_get_date_added.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_int64)]
        lib.clipmesh_get_date_added.restype = ctypes.c_int
        lib.clipmesh_set_date_added_now.argtypes = [ctypes.c_char_p]
        lib.clipmesh_set_date_added_now.restype = ctypes.c_int

        target = Path(td) / "ClipMesh"
        target.mkdir()

        def added_ns() -> int:
            sec = ctypes.c_int64()
            nsec = ctypes.c_int64()
            rc = lib.clipmesh_get_date_added(os.fsencode(target), ctypes.byref(sec), ctypes.byref(nsec))
            if rc != 0:
                raise OSError(ctypes.get_errno(), "getattrlist ATTR_CMN_ADDEDTIME failed")
            return sec.value * 1_000_000_000 + nsec.value

        before = added_ns()
        time.sleep(0.05)
        rc = lib.clipmesh_set_date_added_now(os.fsencode(target))
        if rc != 0:
            raise OSError(ctypes.get_errno(), "setattrlist ATTR_CMN_ADDEDTIME failed")
        after = added_ns()
        assert after > before, (before, after)

elif SYSTEM in ("Linux", "Windows"):
    pass
else:
    raise SystemExit(f"Unsupported platform: {SYSTEM}")

print(f"v061 direct Date Added runtime self-test passed on {SYSTEM}")
