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
    assert 'val clearInboundIdentity = methodName == "getPrimaryClip"' in service
    assert "val callingIdentity = if (clearInboundIdentity) Binder.clearCallingIdentity() else 0L" in service
    assert "if (clearInboundIdentity) Binder.restoreCallingIdentity(callingIdentity)" in service
    assert ".version(12)" in manager
    assert ".daemon(false)" in manager
    assert '"clipmesh-clipboard-event-v2"' in manager
    assert "Shizuku.unbindUserService(args, connection, true)" in manager
    assert ".version(4)" not in manager
    assert ".version(5)" not in manager

    guard_at = service.index('val clearInboundIdentity = methodName == "getPrimaryClip"')
    clear_at = service.index("Binder.clearCallingIdentity()", guard_at)
    invoke_at = service.index("val result = method.invoke(target, *args)", clear_at)
    restore_at = service.index("if (clearInboundIdentity) Binder.restoreCallingIdentity(callingIdentity)", invoke_at)
    assert guard_at < clear_at < invoke_at < restore_at

    # The regression guard is the conditional itself: setPrimaryClip must not
    # unconditionally clear the caller identity that worked on the physical S23.
    assert "val callingIdentity = Binder.clearCallingIdentity()" not in service

print(f"ClipMesh Shizuku background-read Binder-identity self-test passed on {system}")
