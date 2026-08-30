#!/usr/bin/env python3
"""ClipMesh v0.2.11: preserve Shizuku shell identity for nested clipboard Binder calls."""

from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    service = java / "shizuku/ClipboardUserService.kt"
    manager = java / "shizuku/ShizukuManager.kt"

    # ClipboardUserService is itself entered through Binder from the normal
    # ClipMesh app process. A nested call from that Binder transaction into
    # Android's IClipboard service otherwise retains the original app caller
    # identity. Samsung/Android then evaluates the read as dev.clipmesh and
    # rejects it while the app is backgrounded, even though the UserService is
    # running with Shizuku's shell identity. Clear the inbound Binder identity
    # around the nested system-service call so IClipboard sees the actual
    # UserService process identity instead.
    replace_once(
        service,
        "import android.os.Build\nimport android.os.IBinder\n",
        "import android.os.Build\nimport android.os.Binder\nimport android.os.IBinder\n",
        "Shizuku clipboard Binder import",
    )

    replace_once(
        service,
        '''            try {\n                val result = method.invoke(target, *args)\n                return result ?: if (method.returnType == Void.TYPE) true else null\n            } catch (error: Exception) {\n                Log.d(TAG, "Clipboard signature did not match: ${method.parameterTypes.joinToString { it.simpleName }}")\n            }\n''',
        '''            val callingIdentity = Binder.clearCallingIdentity()\n            try {\n                val result = method.invoke(target, *args)\n                return result ?: if (method.returnType == Void.TYPE) true else null\n            } catch (error: Exception) {\n                Log.d(TAG, "Clipboard signature did not match: ${method.parameterTypes.joinToString { it.simpleName }}")\n            } finally {\n                Binder.restoreCallingIdentity(callingIdentity)\n            }\n''',
        "Shizuku nested clipboard Binder identity",
    )

    # Shizuku keys UserService replacement to this version. The implementation
    # changed, so force replacement of any v4 service process left alive by a
    # previous development APK install.
    replace_once(manager, ".version(4)", ".version(5)", "Shizuku UserService generation")

    final_service = service.read_text(encoding="utf-8")
    final_manager = manager.read_text(encoding="utf-8")
    for value in (
        'private const val SHELL_PACKAGE = "com.android.shell"',
        "Binder.clearCallingIdentity()",
        "Binder.restoreCallingIdentity(callingIdentity)",
    ):
        if value not in final_service:
            raise SystemExit(f"Shizuku clipboard identity guard missing after patch: {value}")
    if ".version(5)" not in final_manager:
        raise SystemExit("Shizuku UserService generation was not bumped to 5")

print(f"Applied ClipMesh Shizuku clipboard Binder-identity repair on {system}")
