#!/usr/bin/env python3
# ClipMesh v050: finish event-driven idle architecture and remove avoidable idle workers.
from pathlib import Path
import os
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def require_once(text: str, needle: str, label: str) -> None:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    service = java / "shizuku/ClipboardUserService.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    transfer = java / "fileshare/LocalTransferEngine.kt"

    rt = runtime.read_text(encoding="utf-8")
    if "private fun stopClipboardRuntime()" not in rt:
        anchor = "    @Synchronized fun stop() {\n"
        require_once(rt, anchor, "Android stopClipboardRuntime insertion")
        helper = '''    private fun stopClipboardRuntime() {
        clipboard?.stop(); clipboard = null
        network?.stop(); network = null
        shizuku?.close(); shizuku = null
    }

'''
        rt = rt.replace(anchor, helper + anchor, 1)
    for forbidden in ("clipboardWatchdog", "scheduleWithFixedDelay", "ClipMesh-ClipboardWatch", "650L"):
        if forbidden in rt:
            raise SystemExit(f"Android idle clipboard polling survived v050: {forbidden}")
    runtime.write_text(rt, encoding="utf-8")

    st = service.read_text(encoding="utf-8")
    # UserHandle.myUserId() is hidden from the public Android SDK. Shizuku's
    # UserService UID is still encoded with Android's stable per-user UID range,
    # so derive the current user directly without reflection/hidden API calls.
    st = st.replace(
        "UserHandle.myUserId()",
        "(android.os.Process.myUid() / 100000)",
    )
    st, field_count = re.subn(
        r'''    private val clipboardEventExecutor = Executors\.newSingleThreadExecutor \{ task ->\n        Thread\(task, "ClipMesh-ClipboardEvent"\)\.apply \{ isDaemon = true \}\n    \}\n''',
        "",
        st,
        count=1,
    )
    if field_count != 1:
        raise SystemExit("Android service-side clipboard executor field missing")
    require_once(
        st,
        "                clipboardEventExecutor.execute { runCatching { clipboardChangedCallback?.onClipboardChanged() } }\n",
        "Android service-side clipboard callback",
    )
    st = st.replace(
        "                clipboardEventExecutor.execute { runCatching { clipboardChangedCallback?.onClipboardChanged() } }\n",
        "                runCatching { clipboardChangedCallback?.onClipboardChanged() }\n",
        1,
    )
    st = st.replace("        clipboardEventExecutor.shutdownNow()\n", "", 1)
    if "Executors." not in st:
        st = st.replace("import java.util.concurrent.Executors\n", "")
    if "UserHandle." not in st:
        st = st.replace("import android.os.UserHandle\n", "")
    if "clipboardEventExecutor" in st:
        raise SystemExit("Android service-side idle clipboard executor survived")
    if "UserHandle.myUserId()" in st or ".identifier" in st:
        raise SystemExit("Android hidden/incompatible user-id API survived")
    service.write_text(st, encoding="utf-8")

    mt = manager.read_text(encoding="utf-8")
    mt, manager_field_count = re.subn(
        r'''    private val clipboardEventExecutor = Executors\.newSingleThreadExecutor \{ task ->\n        Thread\(task, "ClipMesh-ClipboardCallback"\)\.apply \{ isDaemon = true \}\n    \}\n''',
        "",
        mt,
        count=1,
    )
    if manager_field_count != 1:
        raise SystemExit("Android manager clipboard executor field missing")
    require_once(
        mt,
        "            clipboardEventExecutor.execute { clipboardChangeListener?.invoke() }\n",
        "Android manager callback executor",
    )
    mt = mt.replace(
        "            clipboardEventExecutor.execute { clipboardChangeListener?.invoke() }\n",
        "            clipboardChangeListener?.invoke()\n",
        1,
    )
    mt = mt.replace("        clipboardEventExecutor.shutdownNow()\n", "", 1)
    if "Executors." not in mt:
        mt = mt.replace("import java.util.concurrent.Executors\n", "")
    if "clipboardEventExecutor" in mt or "ClipMesh-ClipboardCallback" in mt:
        raise SystemExit("Android manager idle callback worker survived")
    manager.write_text(mt, encoding="utf-8")

    ft = transfer.read_text(encoding="utf-8")
    if "        executor.execute(::runAnnouncer)\n" in ft:
        ft = ft.replace("        executor.execute(::runAnnouncer)\n", "", 1)
    ft, announcer_count = re.subn(
        r'''\n    private fun runAnnouncer\(\) \{.*?\n    \}\n\n(?=    fun discoverNow\(\))''',
        "\n",
        ft,
        count=1,
        flags=re.S,
    )
    if announcer_count != 1:
        raise SystemExit("Android recurring file-transfer announcer block missing")
    if "runAnnouncer" in ft:
        raise SystemExit("Android recurring file-transfer announcer survived")
    transfer.write_text(ft, encoding="utf-8")

elif SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    clipboard = PROJECT / "apps/desktop/src/clipboard.rs"

    ct = clipboard.read_text(encoding="utf-8")
    ct, fallback_count = re.subn(
        r'''\n    #\[cfg\(target_os="macos"\)\]\n    \{\n        let poll_cfg=cfg\.clone\(\);.*?\n    \}\n(?=    Ok\(\(\)\))''',
        "\n",
        ct,
        count=1,
        flags=re.S,
    )
    if fallback_count != 1:
        raise SystemExit("macOS 350 ms clipboard fallback block missing")
    for forbidden in ("clipmesh-macos-pasteboard-fallback", "Duration::from_millis(350)"):
        if forbidden in ct:
            raise SystemExit(f"macOS clipboard polling survived: {forbidden}")
    clipboard.write_text(ct, encoding="utf-8")

    tt = transfer.read_text(encoding="utf-8")
    tt = tt.replace("        startAnnouncer()\n", "", 1)
    tt = tt.replace("    private var timer: DispatchSourceTimer?\n", "", 1)
    tt = tt.replace("        timer?.cancel(); timer = nil\n", "", 1)
    tt, timer_count = re.subn(
        r'''\n    private func startAnnouncer\(\) \{.*?\n    \}\n\n(?=    private func sendAnnouncement)''',
        "\n",
        tt,
        count=1,
        flags=re.S,
    )
    if timer_count != 1:
        raise SystemExit("macOS recurring file-transfer announcer block missing")
    for forbidden in ("startAnnouncer()", "DispatchSource.makeTimerSource", "repeating: 5.0"):
        if forbidden in tt:
            raise SystemExit(f"macOS recurring file-transfer discovery survived: {forbidden}")
    transfer.write_text(tt, encoding="utf-8")

elif SYSTEM == "Windows":
    transfer = ROOT / "ci/ClipMeshTransfer.cs"
    tt = transfer.read_text(encoding="utf-8")

    if "using System.Runtime.InteropServices;\n" not in tt:
        require_once(tt, "using System.Net.Sockets;\n", "Windows interop import anchor")
        tt = tt.replace(
            "using System.Net.Sockets;\n",
            "using System.Net.Sockets;\nusing System.Runtime.InteropServices;\n",
            1,
        )

    tt = tt.replace("        Task.Run((Action)AnnounceLoop);\n", "", 1)
    tt, loop_count = re.subn(
        r'''\n    private void AnnounceLoop\(\)\n    \{.*?\n    \}\n\n(?=    private void SendAnnouncement)''',
        "\n",
        tt,
        count=1,
        flags=re.S,
    )
    if loop_count != 1:
        raise SystemExit("Windows recurring file-transfer announcer block missing")
    if "AnnounceLoop" in tt:
        raise SystemExit("Windows recurring file-transfer announcer survived")
    if "using System.Runtime.InteropServices;" not in tt:
        raise SystemExit("Windows COM interop import missing")
    transfer.write_text(tt, encoding="utf-8")

else:
    raise SystemExit(f"unsupported platform: {SYSTEM}")

print(f"Applied ClipMesh v050 ultra-idle/runtime fixes on {SYSTEM}")
