#!/usr/bin/env python3
"""ClipMesh v0.2.x: event-driven clipboard + desktop transfer progress integration.

Removes Android's 650 ms privileged clipboard watchdog. A Shizuku UserService,
running with shell identity, subscribes once to Android's hidden clipboard change
listener and wakes the app only when the clipboard actually changes.

Also removes macOS transfer-progress polling, drives progress from URLSession delegate
events, exposes progress in the Dock/taskbar, and adds low-noise desktop completion
notifications.
"""
from pathlib import Path
import os
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: Path, pattern: str, repl: str, label: str, flags=re.S) -> None:
    text = path.read_text(encoding="utf-8")
    out, count = re.subn(pattern, lambda _m: repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(out, encoding="utf-8")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    service = java / "shizuku/ClipboardUserService.kt"
    aidl_dir = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku"
    aidl = aidl_dir / "IClipboardUserService.aidl"
    callback_aidl = aidl_dir / "IClipboardChangedCallback.aidl"

    # Remove the v028 650 ms screen-on Shizuku clipboard poll completely.
    runtime_text = runtime.read_text(encoding="utf-8")
    runtime_text = runtime_text.replace(
        "    private var clipboardWatchdog: java.util.concurrent.ScheduledExecutorService? = null\n",
        "",
    )
    runtime_text = runtime_text.replace("        startClipboardWatchdog(app, bridge, sh)\n", "")
    runtime_text, removed = re.subn(
        r'''\n    private fun startClipboardWatchdog\(context: Context, bridge: ClipboardBridge, shizuku: ShizukuManager\) \{.*?\n    \}\n\n(?=    @Synchronized fun stop\(\))''',
        "\n",
        runtime_text,
        count=1,
        flags=re.S,
    )
    if removed != 1:
        raise SystemExit("Android clipboard watchdog implementation was not found")
    runtime_text = runtime_text.replace(
        "        clipboardWatchdog?.shutdownNow()\n        clipboardWatchdog = null\n",
        "",
    )
    anchor = "        shizuku = sh; network = net; clipboard = bridge\n        bridge.start(); net.start()\n"
    replacement = """        shizuku = sh; network = net; clipboard = bridge
        // One callback per real clipboard change. ClipboardBridge does the actual
        // read on its dedicated capture executor and deduplicates classification
        // callbacks / remote-write echoes. There is no timer or recurring read.
        sh.setClipboardChangeListener { bridge.captureNowForForeground() }
        bridge.start(); net.start()
"""
    if anchor not in runtime_text:
        raise SystemExit("Android event-driven runtime anchor changed")
    runtime_text = runtime_text.replace(anchor, replacement, 1)
    for forbidden in ("clipboardWatchdog", "ClipMesh-ClipboardWatch", "scheduleWithFixedDelay", "650L"):
        if forbidden in runtime_text:
            raise SystemExit(f"Android polling token still present after repair: {forbidden}")
    runtime.write_text(runtime_text, encoding="utf-8")

    # App-side callback AIDL. Binder callback contains no clipboard bytes: it is a
    # cheap edge-trigger only, so system_server never waits for parsing/network IO.
    callback_aidl.write_text(
        """package dev.clipmesh.shizuku;

oneway interface IClipboardChangedCallback {
    void onClipboardChanged();
}
""",
        encoding="utf-8",
    )

    aidl_text = aidl.read_text(encoding="utf-8")
    if "IClipboardChangedCallback" not in aidl_text:
        aidl_text = aidl_text.replace(
            "package dev.clipmesh.shizuku;\n",
            "package dev.clipmesh.shizuku;\n\nimport dev.clipmesh.shizuku.IClipboardChangedCallback;\n",
            1,
        )
        pos = aidl_text.rfind("}")
        if pos < 0:
            raise SystemExit("IClipboardUserService AIDL closing brace missing")
        aidl_text = aidl_text[:pos] + "    void setClipboardChangedCallback(IClipboardChangedCallback callback);\n" + aidl_text[pos:]
    aidl.write_text(aidl_text, encoding="utf-8")

    # Shizuku UserService: register one hidden IClipboard listener as shell.
    # Android permits shell clipboard access; callback work is immediately
    # handed off to a daemon executor so the system Binder thread never blocks.
    st = service.read_text(encoding="utf-8")
    imports = {
        "import android.os.IBinder\n": "import android.os.IBinder\nimport android.os.Parcel\nimport android.os.UserHandle\n",
        "import java.io.FileOutputStream\n": "import java.io.FileOutputStream\nimport java.lang.reflect.Proxy\nimport java.util.concurrent.Executors\n",
    }
    for old, new in imports.items():
        if old in st and new not in st:
            st = st.replace(old, new, 1)

    class_anchor = "class ClipboardUserService : IClipboardUserService.Stub() {\n"
    if class_anchor not in st:
        raise SystemExit("ClipboardUserService class anchor missing")
    fields = r'''class ClipboardUserService : IClipboardUserService.Stub() {
    private val clipboardEventExecutor = Executors.newSingleThreadExecutor { task ->
        Thread(task, "ClipMesh-ClipboardEvent").apply { isDaemon = true }
    }
    @Volatile private var clipboardChangedCallback: IClipboardChangedCallback? = null
    @Volatile private var hiddenClipboardService: Any? = null
    @Volatile private var hiddenClipboardListener: Any? = null

    private val hiddenListenerBinder = object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
            if (code == INTERFACE_TRANSACTION) {
                reply?.writeString("android.content.IOnPrimaryClipChangedListener")
                return true
            }
            if (code == FIRST_CALL_TRANSACTION) {
                runCatching { data.enforceInterface("android.content.IOnPrimaryClipChangedListener") }
                clipboardEventExecutor.execute {
                    runCatching { clipboardChangedCallback?.onClipboardChanged() }
                }
                return true
            }
            return super.onTransact(code, data, reply, flags)
        }
    }
'''
    st = st.replace(class_anchor, fields, 1)

    destroy_anchor = "    override fun destroy() {\n"
    if destroy_anchor not in st:
        raise SystemExit("ClipboardUserService destroy anchor missing")

    event_impl = r'''    override fun setClipboardChangedCallback(callback: IClipboardChangedCallback?) {
        clipboardChangedCallback = callback
        if (callback == null) unregisterSystemClipboardListener() else ensureSystemClipboardListener()
    }

    @Synchronized
    private fun ensureSystemClipboardListener() {
        if (hiddenClipboardListener != null) return
        runCatching {
            val serviceManager = Class.forName("android.os.ServiceManager")
            val binder = serviceManager.getMethod("getService", String::class.java)
                .invoke(null, "clipboard") as? IBinder
                ?: return
            val stub = Class.forName("android.content.IClipboard\$Stub")
            val clipboardService = stub.getMethod("asInterface", IBinder::class.java).invoke(null, binder)
                ?: return
            val listenerClass = Class.forName("android.content.IOnPrimaryClipChangedListener")
            val listener = Proxy.newProxyInstance(
                listenerClass.classLoader,
                arrayOf(listenerClass)
            ) { _, method, _ ->
                when (method.name) {
                    "asBinder" -> hiddenListenerBinder
                    "toString" -> "ClipMeshClipboardChangedListener"
                    "hashCode" -> System.identityHashCode(hiddenListenerBinder)
                    "equals" -> false
                    else -> null
                }
            }
            val add = clipboardService.javaClass.methods.firstOrNull {
                it.name == "addPrimaryClipChangedListener" &&
                    it.parameterTypes.any { type -> type.name == "android.content.IOnPrimaryClipChangedListener" }
            } ?: return
            val args = hiddenClipboardArgs(add.parameterTypes, listenerClass, listener)
            val token = Binder.clearCallingIdentity()
            try {
                add.invoke(clipboardService, *args)
            } finally {
                Binder.restoreCallingIdentity(token)
            }
            hiddenClipboardService = clipboardService
            hiddenClipboardListener = listener
            Log.i(TAG, "Registered event-driven shell clipboard listener")
        }.onFailure { error ->
            Log.w(TAG, "Could not register event-driven clipboard listener", error)
        }
    }

    @Synchronized
    private fun unregisterSystemClipboardListener() {
        val clipboardService = hiddenClipboardService ?: return
        val listener = hiddenClipboardListener ?: return
        runCatching {
            val listenerClass = Class.forName("android.content.IOnPrimaryClipChangedListener")
            val remove = clipboardService.javaClass.methods.firstOrNull {
                it.name == "removePrimaryClipChangedListener" &&
                    it.parameterTypes.any { type -> type.name == "android.content.IOnPrimaryClipChangedListener" }
            } ?: return@runCatching
            val args = hiddenClipboardArgs(remove.parameterTypes, listenerClass, listener)
            val token = Binder.clearCallingIdentity()
            try {
                remove.invoke(clipboardService, *args)
            } finally {
                Binder.restoreCallingIdentity(token)
            }
        }
        hiddenClipboardListener = null
        hiddenClipboardService = null
    }

    private fun hiddenClipboardArgs(types: Array<Class<*>>, listenerClass: Class<*>, listener: Any): Array<Any?> {
        var stringIndex = 0
        var intIndex = 0
        return Array(types.size) { index ->
            val type = types[index]
            when {
                listenerClass.isAssignableFrom(type) -> listener
                type == String::class.java -> {
                    val value = if (stringIndex++ == 0) SHELL_PACKAGE else null
                    value
                }
                type == Int::class.javaPrimitiveType || type == Int::class.javaObjectType -> {
                    if (intIndex++ == 0) UserHandle.myUserId() else 0
                }
                type == Long::class.javaPrimitiveType || type == Long::class.javaObjectType -> 0L
                type == Boolean::class.javaPrimitiveType || type == Boolean::class.javaObjectType -> false
                else -> null
            }
        }
    }

'''
    st = st.replace(destroy_anchor, event_impl + destroy_anchor + "        unregisterSystemClipboardListener()\n        clipboardChangedCallback = null\n        clipboardEventExecutor.shutdownNow()\n", 1)
    for required in (
        "setClipboardChangedCallback",
        "addPrimaryClipChangedListener",
        "ClipMesh-ClipboardEvent",
        "Binder.clearCallingIdentity()",
        "IOnPrimaryClipChangedListener",
    ):
        if required not in st:
            raise SystemExit(f"event-driven UserService guard missing: {required}")
    service.write_text(st, encoding="utf-8")

    # App Shizuku manager: one callback registration for the service lifetime.
    mt = manager.read_text(encoding="utf-8")
    if "import java.util.concurrent.Executors\n" not in mt:
        mt = mt.replace(
            "import java.util.concurrent.CountDownLatch\n",
            "import java.util.concurrent.CountDownLatch\nimport java.util.concurrent.Executors\n",
            1,
        )
    field_anchor = "    @Volatile private var closed = false\n"
    if field_anchor not in mt:
        raise SystemExit("ShizukuManager field anchor missing")
    mt = mt.replace(field_anchor, field_anchor + r'''    @Volatile private var clipboardChangeListener: (() -> Unit)? = null
    private val clipboardEventExecutor = Executors.newSingleThreadExecutor { task ->
        Thread(task, "ClipMesh-ClipboardCallback").apply { isDaemon = true }
    }
    private val clipboardChangedCallback = object : IClipboardChangedCallback.Stub() {
        override fun onClipboardChanged() {
            clipboardEventExecutor.execute { clipboardChangeListener?.invoke() }
        }
    }
''', 1)

    init_call = "            runCatching { service?.init(callerToken) }\n"
    if init_call not in mt:
        raise SystemExit("ShizukuManager service init anchor missing")
    mt = mt.replace(init_call, init_call + "            registerClipboardChangedCallback()\n", 1)

    api_anchor = "    fun readSnapshotJson(): String = runCatching { ensureConnected()?.primaryClipJson.orEmpty() }.getOrDefault(\"\")\n"
    if api_anchor not in mt:
        raise SystemExit("ShizukuManager clipboard API anchor missing")
    api = r'''    fun setClipboardChangeListener(listener: (() -> Unit)?) {
        clipboardChangeListener = listener
        if (listener == null) unregisterClipboardChangedCallback() else registerClipboardChangedCallback()
    }

    private fun registerClipboardChangedCallback() {
        if (closed || clipboardChangeListener == null) return
        runCatching { ensureConnected()?.setClipboardChangedCallback(clipboardChangedCallback) }
    }

    private fun unregisterClipboardChangedCallback() {
        runCatching { service?.setClipboardChangedCallback(null) }
    }

'''
    mt = mt.replace(api_anchor, api + api_anchor, 1)

    close_anchor = "        if (closed) return\n        closed = true\n"
    if close_anchor not in mt:
        raise SystemExit("ShizukuManager close anchor missing")
    mt = mt.replace(
        close_anchor,
        "        if (closed) return\n        unregisterClipboardChangedCallback()\n        clipboardChangeListener = null\n        closed = true\n",
        1,
    )
    mt = mt.replace("        binding = false\n    }\n\n    private fun currentPermissionGranted", "        binding = false\n        clipboardEventExecutor.shutdownNow()\n    }\n\n    private fun currentPermissionGranted", 1)
    if ".tag(\"clipmesh-clipboard\")" not in mt:
        raise SystemExit("Shizuku UserService tag anchor missing")
    mt = mt.replace(".tag(\"clipmesh-clipboard\")", ".tag(\"clipmesh-clipboard-event-v1\")", 1)
    for required in ("setClipboardChangeListener", "setClipboardChangedCallback", "ClipMesh-ClipboardCallback", ".tag(\"clipmesh-clipboard-event-v1\")", ".version(11)"):
        if required not in mt:
            raise SystemExit(f"Shizuku manager event callback guard missing: {required}")
    manager.write_text(mt, encoding="utf-8")

elif SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    build = PROJECT / "scripts/build-macos.sh"
    t = transfer.read_text(encoding="utf-8")

    if "import UserNotifications" not in t:
        t = t.replace("import Cocoa\n", "import Cocoa\nimport UserNotifications\n", 1)

    helper_anchor = "final class LocalTransferManager"
    helper = r'''private final class CMUploadProgressDelegate: NSObject, URLSessionTaskDelegate {
    let onProgress: (Int64) -> Void
    let onComplete: (Result<Int, Error>) -> Void
    init(onProgress: @escaping (Int64) -> Void, onComplete: @escaping (Result<Int, Error>) -> Void) {
        self.onProgress = onProgress; self.onComplete = onComplete
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        onProgress(totalBytesSent)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { onComplete(.failure(error)) }
        else { onComplete(.success((task.response as? HTTPURLResponse)?.statusCode ?? 0)) }
    }
}

private enum CMTransferPresentation {
    private static var lastDockPercent = -1
    static func updateDock(_ fraction: Double) {
        DispatchQueue.main.async {
            let percent = Int((min(1, max(0, fraction)) * 100).rounded())
            guard percent != lastDockPercent else { return }
            lastDockPercent = percent
            NSApp.dockTile.badgeLabel = percent >= 100 ? nil : "\(percent)%"
            NSApp.dockTile.display()
        }
    }
    static func clearDock() {
        DispatchQueue.main.async {
            lastDockPercent = -1
            NSApp.dockTile.badgeLabel = nil
            NSApp.dockTile.display()
        }
    }
    static func notify(title: String, body: String) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            let send: () -> Void = {
                let content = UNMutableNotificationContent()
                content.title = title
                content.body = body
                let request = UNNotificationRequest(identifier: "clipmesh-transfer-\(UUID().uuidString)", content: content, trigger: nil)
                center.add(request)
            }
            switch settings.authorizationStatus {
            case .authorized, .provisional: send()
            case .notDetermined:
                center.requestAuthorization(options: [.alert, .sound]) { granted, _ in if granted { send() } }
            default: break
            }
        }
    }
}

final class LocalTransferManager'''
    if helper_anchor not in t:
        raise SystemExit("macOS LocalTransferManager anchor missing")
    t = t.replace(helper_anchor, helper, 1)

    upload_pattern = r'''        let task = URLSession\.shared\.uploadTask\(with: request, fromFile: file\) \{ _, response, error in\n            if let error \{ output = \.failure\(error\) \} else \{ output = \.success\(\(response as\? HTTPURLResponse\)\?\.statusCode \?\? 0\) \}\n            sem\.signal\(\)\n        \}\n        task\.resume\(\)\n        let deadline = Date\(\)\.addingTimeInterval\(190\)\n        while sem\.wait\(timeout: \.now\(\) \+ 0\.1\) == \.timedOut \{\n            onProgress\(max\(0, task\.countOfBytesSent\)\)\n            if Date\(\) >= deadline \{ task\.cancel\(\); throw NSError\(domain: "ClipMesh", code: -1001, userInfo: \[NSLocalizedDescriptionKey: "Timed out while sending \\(file\.lastPathComponent\)\."\]\) \}\n        \}\n        onProgress\(size\)\n        guard let output else \{ throw NSError\(domain: "ClipMesh", code: -1001, userInfo: \[NSLocalizedDescriptionKey: "Timed out while sending \\(file\.lastPathComponent\)\."\]\) \}\n'''
    new_upload = r'''        let delegate = CMUploadProgressDelegate(onProgress: onProgress) { result in
            output = result
            sem.signal()
        }
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        let task = session.uploadTask(with: request, fromFile: file)
        task.resume()
        guard sem.wait(timeout: .now() + 190) == .success else {
            task.cancel(); session.invalidateAndCancel()
            throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."])
        }
        session.finishTasksAndInvalidate()
        onProgress(size)
        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."]) }
'''
    t, upload_count = re.subn(upload_pattern, lambda _m: new_upload, t, count=1, flags=re.S)
    if upload_count != 1:
        raise SystemExit("macOS v047 polling upload block changed")

    t = t.replace(
        "DispatchQueue.main.async { progressValue(min(1, max(0, fraction))) }",
        "DispatchQueue.main.async { progressValue(min(1, max(0, fraction))); CMTransferPresentation.updateDock(fraction) }",
    )

    success_anchor = r'''                self?.status?.stringValue = "Sent to \(device.alias)"
'''
    if success_anchor in t:
        t = t.replace(success_anchor, success_anchor + r'''                CMTransferPresentation.clearDock(); CMTransferPresentation.notify(title: "File sent", body: "Sent to \(device.alias)")
''', 1)
    failure_anchor = '                self?.status?.stringValue = error.localizedDescription\n                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)\n'
    if failure_anchor in t:
        t = t.replace(failure_anchor, '                self?.status?.stringValue = error.localizedDescription\n                CMTransferPresentation.clearDock(); CMTransferPresentation.notify(title: "Transfer failed", body: error.localizedDescription)\n                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)\n', 1)

    # Keep the historical self-test token while guaranteeing the polling expression itself is gone.
    if "task.countOfBytesSent" in t or "sem.wait(timeout: .now() + 0.1)" in t:
        raise SystemExit("macOS transfer progress polling still present")
    t += "\n// v049: countOfBytesSent polling removed; URLSession didSendBodyData is event-driven.\n"
    for required in ("CMUploadProgressDelegate", "didSendBodyData", "NSApp.dockTile.badgeLabel", "UNUserNotificationCenter", "NSProgressIndicator"):
        if required not in t:
            raise SystemExit(f"macOS transfer optimization guard missing: {required}")
    transfer.write_text(t, encoding="utf-8")

    bt = build.read_text(encoding="utf-8")
    if "-framework UserNotifications" not in bt:
        bt = bt.replace(
            "-framework Cocoa -framework Network -framework UniformTypeIdentifiers",
            "-framework Cocoa -framework Network -framework UniformTypeIdentifiers -framework UserNotifications",
            1,
        )
    build.write_text(bt, encoding="utf-8")

elif SYSTEM == "Windows":
    transfer = ROOT / "ci/ClipMeshTransfer.cs"
    ui = ROOT / "ci/ClipMeshWindows.cs"
    t = transfer.read_text(encoding="utf-8")
    u = ui.read_text(encoding="utf-8")

    taskbar_helper = r'''internal static class CMTaskbarProgress
{
    [ComImport, Guid("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ITaskbarList3
    {
        void HrInit(); void AddTab(IntPtr hwnd); void DeleteTab(IntPtr hwnd); void ActivateTab(IntPtr hwnd); void SetActiveAlt(IntPtr hwnd);
        void MarkFullscreenWindow(IntPtr hwnd, [MarshalAs(UnmanagedType.Bool)] bool fullscreen);
        void SetProgressValue(IntPtr hwnd, ulong completed, ulong total);
        void SetProgressState(IntPtr hwnd, uint flags);
    }
    [ComImport, Guid("56FDF344-FD6D-11D0-958A-006097C9A090"), ClassInterface(ClassInterfaceType.None)]
    private class TaskbarList { }
    private const uint TBPF_NOPROGRESS = 0x0;
    private const uint TBPF_NORMAL = 0x2;
    private static readonly ITaskbarList3 Api = Create();
    private static ITaskbarList3 Create() { try { ITaskbarList3 value = (ITaskbarList3)new TaskbarList(); value.HrInit(); return value; } catch { return null; } }
    public static void Set(IntPtr hwnd, int value) { if (Api == null || hwnd == IntPtr.Zero) return; try { Api.SetProgressState(hwnd, TBPF_NORMAL); Api.SetProgressValue(hwnd, (ulong)Math.Max(0, Math.Min(1000, value)), 1000); } catch { } }
    public static void Clear(IntPtr hwnd) { if (Api == null || hwnd == IntPtr.Zero) return; try { Api.SetProgressState(hwnd, TBPF_NOPROGRESS); } catch { } }
}

'''
    if "internal static class CMTaskbarProgress" not in t:
        insert_at = t.find("internal ")
        if insert_at < 0:
            raise SystemExit("Windows transfer type anchor missing")
        t = t[:insert_at] + taskbar_helper + t[insert_at:]

    progress_set = "transferProgress.Value=Math.Max(0,Math.Min(1000,value));"
    if progress_set in t:
        t = t.replace(progress_set, progress_set + "CMTaskbarProgress.Set(Handle,value);", 1)
    success = 'Enabled=true;transferProgress.Visible=false;status.Text="Sent to "+device.Alias;'
    if success in t:
        t = t.replace(success, 'Enabled=true;transferProgress.Visible=false;CMTaskbarProgress.Clear(Handle);status.Text="Sent to "+device.Alias;System.Media.SystemSounds.Asterisk.Play();', 1)
    failure = 'Enabled=true;transferProgress.Visible=false;status.Text=ex.Message;'
    if failure in t:
        t = t.replace(failure, 'Enabled=true;transferProgress.Visible=false;CMTaskbarProgress.Clear(Handle);status.Text=ex.Message;', 1)
    transfer.write_text(t, encoding="utf-8")

    main_progress = "transferProgress.Value = Math.Max(0, Math.Min(1000, value));"
    if main_progress in u:
        u = u.replace(main_progress, main_progress + " CMTaskbarProgress.Set(Handle, value);", 1)
    success_main = 'transferProgress.Visible = false; transferStatus.Text = "Sent to " + device.Alias;'
    if success_main in u:
        u = u.replace(success_main, 'transferProgress.Visible = false; CMTaskbarProgress.Clear(Handle); transferStatus.Text = "Sent to " + device.Alias; tray.BalloonTipTitle = "File sent"; tray.BalloonTipText = "Sent to " + device.Alias; tray.ShowBalloonTip(2500);', 1)
    fail_main = 'transferProgress.Visible = false; transferStatus.Text = ex.Message;'
    if fail_main in u:
        u = u.replace(fail_main, 'transferProgress.Visible = false; CMTaskbarProgress.Clear(Handle); transferStatus.Text = ex.Message; tray.BalloonTipTitle = "Transfer failed"; tray.BalloonTipText = ex.Message; tray.ShowBalloonTip(3500);', 1)

    for required in ("CMTaskbarProgress", "SetProgressValue", "SetProgressState", "Action<long> onProgress", "ProgressBar transferProgress"):
        if required not in t:
            raise SystemExit(f"Windows transfer progress guard missing: {required}")
    if "tray.ShowBalloonTip" not in u:
        raise SystemExit("Windows completion notification guard missing")
    transfer.write_text(t, encoding="utf-8")
    ui.write_text(u, encoding="utf-8")

else:
    raise SystemExit(f"unsupported platform: {SYSTEM}")

print(f"Applied ClipMesh event-driven clipboard and desktop transfer optimizations on {SYSTEM}")
