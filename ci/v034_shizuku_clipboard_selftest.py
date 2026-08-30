#!/usr/bin/env python3
from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if system == "Linux":
    java = root / "clipmesh/android/app/src/main/java/dev/clipmesh"
    service = (java / "shizuku/ClipboardUserService.kt").read_text(encoding="utf-8")
    manager = (java / "shizuku/ShizukuManager.kt").read_text(encoding="utf-8")

    assert "import android.os.Binder" in service
    assert 'private const val SHELL_PACKAGE = "com.android.shell"' in service
    assert "val callingIdentity = Binder.clearCallingIdentity()" in service
    assert "Binder.restoreCallingIdentity(callingIdentity)" in service
    assert ".version(5)" in manager
    assert ".version(4)" not in manager

    clear_at = service.index("val callingIdentity = Binder.clearCallingIdentity()")
    invoke_at = service.index("val result = method.invoke(target, *args)", clear_at)
    restore_at = service.index("Binder.restoreCallingIdentity(callingIdentity)", invoke_at)
    assert clear_at < invoke_at < restore_at

print(f"ClipMesh Shizuku clipboard Binder-identity self-test passed on {system}")
