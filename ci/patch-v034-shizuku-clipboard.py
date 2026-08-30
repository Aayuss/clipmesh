#!/usr/bin/env python3
"""ClipMesh v0.2.11: use Shizuku identity only for restricted background reads."""

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

    service_text = service.read_text(encoding="utf-8")

    # Samsung restricts background clipboard READS when the nested IClipboard
    # call inherits ClipMesh's normal app Binder identity. Clear that inbound
    # identity only for getPrimaryClip so the system sees the Shizuku UserService
    # identity. Do not change setPrimaryClip: that write path worked reliably on
    # the physical Samsung before v034 and does not need the read-only workaround.
    if 'val clearInboundIdentity = methodName == "getPrimaryClip"' not in service_text:
        if "import android.os.Binder" not in service_text:
            replace_once(
                service,
                "import android.os.Build\nimport android.os.IBinder\n",
                "import android.os.Build\nimport android.os.Binder\nimport android.os.IBinder\n",
                "Shizuku clipboard Binder import",
            )
            service_text = service.read_text(encoding="utf-8")

        broad = '''            val callingIdentity = Binder.clearCallingIdentity()\n            try {\n                val result = method.invoke(target, *args)\n                return result ?: if (method.returnType == Void.TYPE) true else null\n            } catch (error: Exception) {\n                Log.d(TAG, "Clipboard signature did not match: ${method.parameterTypes.joinToString { it.simpleName }}")\n            } finally {\n                Binder.restoreCallingIdentity(callingIdentity)\n            }\n'''
        original = '''            try {\n                val result = method.invoke(target, *args)\n                return result ?: if (method.returnType == Void.TYPE) true else null\n            } catch (error: Exception) {\n                Log.d(TAG, "Clipboard signature did not match: ${method.parameterTypes.joinToString { it.simpleName }}")\n            }\n'''
        narrowed = '''            val clearInboundIdentity = methodName == "getPrimaryClip"\n            val callingIdentity = if (clearInboundIdentity) Binder.clearCallingIdentity() else 0L\n            try {\n                val result = method.invoke(target, *args)\n                return result ?: if (method.returnType == Void.TYPE) true else null\n            } catch (error: Exception) {\n                Log.d(TAG, "Clipboard signature did not match: ${method.parameterTypes.joinToString { it.simpleName }}")\n            } finally {\n                if (clearInboundIdentity) Binder.restoreCallingIdentity(callingIdentity)\n            }\n'''
        current = service.read_text(encoding="utf-8")
        if broad in current:
            replace_once(service, broad, narrowed, "narrow broad v034 Binder identity repair")
        elif original in current:
            replace_once(service, original, narrowed, "Shizuku background-read Binder identity")
        else:
            raise SystemExit("Could not locate ClipboardUserService Binder invocation block")

    # Shizuku keys UserService replacement to this version. v6 guarantees that
    # a v5 service from the broad identity-changing build cannot remain alive.
    manager_text = manager.read_text(encoding="utf-8")
    if ".version(4)" in manager_text:
        replace_once(manager, ".version(4)", ".version(6)", "Shizuku UserService generation 4->6")
    elif ".version(5)" in manager_text:
        replace_once(manager, ".version(5)", ".version(6)", "Shizuku UserService generation 5->6")
    elif ".version(6)" not in manager_text:
        raise SystemExit("Unexpected Shizuku UserService generation before identity repair")

    final_service = service.read_text(encoding="utf-8")
    final_manager = manager.read_text(encoding="utf-8")
    for value in (
        'private const val SHELL_PACKAGE = "com.android.shell"',
        "import android.os.Binder",
        'val clearInboundIdentity = methodName == "getPrimaryClip"',
        "Binder.clearCallingIdentity()",
        "if (clearInboundIdentity) Binder.restoreCallingIdentity(callingIdentity)",
    ):
        if value not in final_service:
            raise SystemExit(f"Shizuku clipboard identity guard missing after patch: {value}")
    if ".version(6)" not in final_manager:
        raise SystemExit("Shizuku UserService generation was not bumped to 6")

print(f"Applied ClipMesh Shizuku background-read Binder-identity repair on {system}")
