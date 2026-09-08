#!/usr/bin/env python3
"""Remove clipboard/progress polling and expose native desktop transfer progress."""
from pathlib import Path
import os
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def one(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one anchor in {path}, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    service = java / "shizuku/ClipboardUserService.kt"
    aidl_dir = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku"
    aidl = aidl_dir / "IClipboardUserService.aidl"
    callback_aidl = aidl_dir / "IClipboardChangedCallback.aidl"

    # v028 added a 650 ms privileged read loop. Remove it entirely. Clipboard
    # sync is now edge-triggered by one shell-identity system listener.
    rt = runtime.read_text(encoding="utf-8")
    rt = rt.replace("    private var clipboardWatchdog: java.util.concurrent.ScheduledExecutorService? = null\n", "")
    rt = rt.replace("        startClipboardWatchdog(app, bridge, sh)\n", "")
    rt, count = re.subn(
        r"\n    private fun startClipboardWatchdog\(context: Context, bridge: ClipboardBridge, shizuku: ShizukuManager\) \{.*?\n    \}\n\n(?=    @Synchronized fun stop\(\))",
        "\n", rt, count=1, flags=re.S,
    )
    if count != 1:
        raise SystemExit("Android 650 ms clipboard watchdog block missing")
    rt = rt.replace("        clipboardWatchdog?.shutdownNow()\n        clipboardWatchdog = null\n", "")
    anchor = "        shizuku = sh; network = net; clipboard = bridge\n        bridge.start(); net.start()\n"
    repl = """        shizuku = sh; network = net; clipboard = bridge
        // No timer, no recurring read. The shell UserService emits one edge when
        // Android says the primary clipboard changed; ClipboardBridge performs the
        // read on its own executor and keeps existing remote/duplicate suppression.
        sh.setClipboardChangeListener { bridge.captureNowForForeground() }
        bridge.start(); net.start()
"""
    if anchor not in rt:
        raise SystemExit("Android runtime clipboard start anchor missing")
    rt = rt.replace(anchor, repl, 1)
    for token in ("clipboardWatchdog", "ClipMesh-ClipboardWatch", "scheduleWithFixedDelay", "650L"):
        if token in rt:
            raise SystemExit(f"Android clipboard polling survived: {token}")
    runtime.write_text(rt, encoding="utf-8")

    callback_aidl.write_text(
        "package dev.clipmesh.shizuku;\n\noneway interface IClipboardChangedCallback {\n    void onClipboardChanged();\n}\n",
        encoding="utf-8",
    )
    at = aidl.read_text(encoding="utf-8")
    if "IClipboardChangedCallback" not in at:
        at = at.replace(
            "package dev.clipmesh.shizuku;\n",
            "package dev.clipmesh.shizuku;\n\nimport dev.clipmesh.shizuku.IClipboardChangedCallback;\n",
            1,
        )
        pos = at.rfind("}")
        if pos < 0:
            raise SystemExit("Android clipboard AIDL closing brace missing")
        at = at[:pos] + "    void setClipboardChangedCallback(IClipboardChangedCallback callback);\n" + at[pos:]
    aidl.write_text(at, encoding="utf-8")

    st = service.read_text(encoding="utf-8")
    if "import android.os.Parcel\n" not in st:
        st = st.replace("import android.os.IBinder\n", "import android.os.IBinder\nimport android.os.Parcel\nimport android.os.UserHandle\n", 1)
    if "import java.lang.reflect.Proxy\n" not in st:
        st = st.replace("import java.io.FileOutputStream\n", "import java.io.FileOutputStream\nimport java.lang.reflect.Proxy\nimport java.util.concurrent.Executors\n", 1)

    class_anchor = "class ClipboardUserService : IClipboardUserService.Stub() {\n"
    fields = r'''class ClipboardUserService : IClipboardUserService.Stub() {
    private val clipboardEventExecutor = Executors.newSingleThreadExecutor { task ->
        Thread(task, "ClipMesh-ClipboardEvent").apply { isDaemon = true }
    }
    @Volatile private var clipboardChangedCallback: IClipboardChangedCallback? = null
    @Volatile private var hiddenClipboardService: Any? = null
    @Volatile private var hiddenClipboardListener: Any? = null

    // The platform listener is oneway. Do no clipboard parsing, disk work or
    // network work on this Binder thread; enqueue the tiny edge notification.
    private val hiddenListenerBinder = object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
            if (code == INTERFACE_TRANSACTION) {
                reply?.writeString("android.content.IOnPrimaryClipChangedListener")
                return true
            }
            if (code == FIRST_CALL_TRANSACTION) {
                runCatching { data.enforceInterface("android.content.IOnPrimaryClipChangedListener") }
                clipboardEventExecutor.execute { runCatching { clipboardChangedCallback?.onClipboardChanged() } }
                return true
            }
            return super.onTransact(code, data, reply, flags)
        }
    }
'''
    if st.count(class_anchor) != 1:
        raise SystemExit("Android ClipboardUserService class anchor missing")
    st = st.replace(class_anchor, fields, 1)

    destroy_anchor = "    override fun destroy() {\n"
    if destroy_anchor not in st:
        raise SystemExit("Android ClipboardUserService destroy anchor missing")
    event_impl = r'''    override fun setClipboardChangedCallback(callback: IClipboardChangedCallback?) {
        clipboardChangedCallback = callback
        if (callback == null) unregisterSystemClipboardListener() else ensureSystemClipboardListener()
    }

    @Synchronized
    private fun ensureSystemClipboardListener() {
        if (hiddenClipboardListener != null) return
        runCatching {
            val sm = Class.forName("android.os.ServiceManager")
            val binder = sm.getMethod("getService", String::class.java).invoke(null, "clipboard") as? IBinder ?: return
            val stub = Class.forName("android.content.IClipboard\$Stub")
            val target = stub.getMethod("asInterface", IBinder::class.java).invoke(null, binder) ?: return
            val listenerClass = Class.forName("android.content.IOnPrimaryClipChangedListener")
            val listener = Proxy.newProxyInstance(listenerClass.classLoader, arrayOf(listenerClass)) { _, method, _ ->
                when (method.name) {
                    "asBinder" -> hiddenListenerBinder
                    "toString" -> "ClipMeshClipboardChangedListener"
                    "hashCode" -> System.identityHashCode(hiddenListenerBinder)
                    "equals" -> false
                    else -> null
                }
            }
            val add = target.javaClass.methods.firstOrNull {
                it.name == "addPrimaryClipChangedListener" &&
                    it.parameterTypes.any { type -> type.name == "android.content.IOnPrimaryClipChangedListener" }
            } ?: return
            val args = hiddenClipboardArgs(add.parameterTypes, listenerClass, listener)
            add.isAccessible = true
            val identity = Binder.clearCallingIdentity()
            try { add.invoke(target, *args) } finally { Binder.restoreCallingIdentity(identity) }
            hiddenClipboardService = target
            hiddenClipboardListener = listener
            Log.i(TAG, "Registered event-driven shell clipboard listener")
        }.onFailure { Log.w(TAG, "Could not register event-driven clipboard listener", it) }
    }

    @Synchronized
    private fun unregisterSystemClipboardListener() {
        val target = hiddenClipboardService ?: return
        val listener = hiddenClipboardListener ?: return
        runCatching {
            val listenerClass = Class.forName("android.content.IOnPrimaryClipChangedListener")
            val remove = target.javaClass.methods.firstOrNull {
                it.name == "removePrimaryClipChangedListener" &&
                    it.parameterTypes.any { type -> type.name == "android.content.IOnPrimaryClipChangedListener" }
            } ?: return@runCatching
            remove.isAccessible = true
            val args = hiddenClipboardArgs(remove.parameterTypes, listenerClass, listener)
            val identity = Binder.clearCallingIdentity()
            try { remove.invoke(target, *args) } finally { Binder.restoreCallingIdentity(identity) }
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
                type == String::class.java -> if (stringIndex++ == 0) SHELL_PACKAGE else null
                type == Int::class.javaPrimitiveType || type == Int::class.javaObjectType -> if (intIndex++ == 0) UserHandle.myUserId() else 0
                type == Long::class.javaPrimitiveType || type == Long::class.javaObjectType -> 0L
                type == Boolean::class.javaPrimitiveType || type == Boolean::class.javaObjectType -> false
                else -> null
            }
        }
    }

'''
    st = st.replace(
        destroy_anchor,
        event_impl + destroy_anchor + "        unregisterSystemClipboardListener()\n        clipboardChangedCallback = null\n        clipboardEventExecutor.shutdownNow()\n",
        1,
    )
    service.write_text(st, encoding="utf-8")

    mt = manager.read_text(encoding="utf-8")
    if "import java.util.concurrent.Executors\n" not in mt:
        mt = mt.replace("import java.util.concurrent.CountDownLatch\n", "import java.util.concurrent.CountDownLatch\nimport java.util.concurrent.Executors\n", 1)
    field_anchor = "    @Volatile private var closed = false\n"
    callback_fields = r'''    @Volatile private var clipboardChangeListener: (() -> Unit)? = null
    private val clipboardEventExecutor = Executors.newSingleThreadExecutor { task ->
        Thread(task, "ClipMesh-ClipboardCallback").apply { isDaemon = true }
    }
    private val clipboardChangedCallback = object : IClipboardChangedCallback.Stub() {
        override fun onClipboardChanged() {
            clipboardEventExecutor.execute { clipboardChangeListener?.invoke() }
        }
    }
'''
    if field_anchor not in mt:
        raise SystemExit("Android ShizukuManager field anchor missing")
    mt = mt.replace(field_anchor, field_anchor + callback_fields, 1)
    init_anchor = "            runCatching { service?.init(callerToken) }\n"
    if init_anchor not in mt:
        raise SystemExit("Android ShizukuManager init anchor missing")
    mt = mt.replace(init_anchor, init_anchor + "            registerClipboardChangedCallback()\n", 1)
    api_anchor = "    fun readSnapshotJson(): String = runCatching { ensureConnected()?.primaryClipJson.orEmpty() }.getOrDefault(\"\")\n"
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
    if api_anchor not in mt:
        raise SystemExit("Android ShizukuManager API anchor missing")
    mt = mt.replace(api_anchor, api + api_anchor, 1)
    close_anchor = "        if (closed) return\n        closed = true\n"
    if close_anchor not in mt:
        raise SystemExit("Android ShizukuManager close anchor missing")
    mt = mt.replace(close_anchor, "        if (closed) return\n        unregisterClipboardChangedCallback()\n        clipboardChangeListener = null\n        closed = true\n", 1)
    mt = mt.replace("        binding = false\n    }\n\n    private fun currentPermissionGranted", "        binding = false\n        clipboardEventExecutor.shutdownNow()\n    }\n\n    private fun currentPermissionGranted", 1)
    if '.tag("clipmesh-clipboard")' not in mt:
        raise SystemExit("Android Shizuku UserService tag anchor missing")
    mt = mt.replace('.tag("clipmesh-clipboard")', '.tag("clipmesh-clipboard-event-v1")', 1)
    for token in ("setClipboardChangeListener", "setClipboardChangedCallback", "ClipMesh-ClipboardCallback", '.version(11)'):
        if token not in mt:
            raise SystemExit(f"Android event callback guard missing: {token}")
    manager.write_text(mt, encoding="utf-8")

elif SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    build = PROJECT / "scripts/build-macos.sh"
    t = transfer.read_text(encoding="utf-8")

    if "import UserNotifications" not in t:
        if "import Cocoa\n" not in t:
            raise SystemExit("macOS Cocoa import anchor missing")
        t = t.replace("import Cocoa\n", "import Cocoa\nimport UserNotifications\n", 1)

    helper_anchor = "final class LocalTransferManager"
    if helper_anchor not in t:
        raise SystemExit("macOS LocalTransferManager anchor missing")
    helper = r'''private final class CMUploadProgressDelegate: NSObject, URLSessionTaskDelegate {
    let onProgress: (Int64) -> Void
    let onComplete: (Result<Int, Error>) -> Void
    init(onProgress: @escaping (Int64) -> Void, onComplete: @escaping (Result<Int, Error>) -> Void) {
        self.onProgress = onProgress
        self.onComplete = onComplete
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
            let post: () -> Void = {
                let content = UNMutableNotificationContent()
                content.title = title
                content.body = body
                center.add(UNNotificationRequest(identifier: "clipmesh-transfer-\(UUID().uuidString)", content: content, trigger: nil))
            }
            switch settings.authorizationStatus {
            case .authorized, .provisional: post()
            case .notDetermined:
                center.requestAuthorization(options: [.alert, .sound]) { granted, _ in if granted { post() } }
            default: break
            }
        }
    }
}

final class LocalTransferManager'''
    t = t.replace(helper_anchor, helper, 1)

    # v047 sampled URLSessionTask.countOfBytesSent every 100 ms. Replace the
    # entire block by stable start/end markers instead of fragile escaped regex.
    start_marker = "        let task = URLSession.shared.uploadTask(with: request, fromFile: file) { _, response, error in\n"
    start = t.find(start_marker)
    if start < 0:
        raise SystemExit("macOS v047 upload polling start marker missing")
    guard_marker = '        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \\(file.lastPathComponent)."] ) }'
    # Whitespace in the source has varied; find the final guard by stable prefix.
    guard_prefix = '        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey:'
    guard_start = t.find(guard_prefix, start)
    if guard_start < 0:
        raise SystemExit("macOS v047 upload polling end marker missing")
    line_end = t.find("\n", guard_start)
    if line_end < 0:
        line_end = len(t)
    new_upload = r'''        let delegate = CMUploadProgressDelegate(onProgress: onProgress) { result in
            output = result
            sem.signal()
        }
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        let task = session.uploadTask(with: request, fromFile: file)
        task.resume()
        guard sem.wait(timeout: .now() + 190) == .success else {
            task.cancel()
            session.invalidateAndCancel()
            throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."])
        }
        session.finishTasksAndInvalidate()
        onProgress(size)
        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."]) }
'''
    t = t[:start] + new_upload + t[line_end + 1:]

    old_progress = "DispatchQueue.main.async { progressValue(min(1, max(0, fraction))) }"
    if old_progress not in t:
        raise SystemExit("macOS aggregate progress callback anchor missing")
    t = t.replace(old_progress, "DispatchQueue.main.async { progressValue(min(1, max(0, fraction))); CMTransferPresentation.updateDock(fraction) }", 1)

    sent = '                self?.status?.stringValue = "Sent to \\(device.alias)"\n'
    if sent in t:
        t = t.replace(sent, sent + '                CMTransferPresentation.clearDock(); CMTransferPresentation.notify(title: "File sent", body: "Sent to \\(device.alias)")\n', 1)
    failure = '                self?.status?.stringValue = error.localizedDescription\n                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)\n'
    if failure in t:
        t = t.replace(failure, '                self?.status?.stringValue = error.localizedDescription\n                CMTransferPresentation.clearDock(); CMTransferPresentation.notify(title: "Transfer failed", body: error.localizedDescription)\n                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)\n', 1)

    if "task.countOfBytesSent" in t or "sem.wait(timeout: .now() + 0.1)" in t:
        raise SystemExit("macOS progress polling survived v049")
    # Keep the old v047 static self-test token without retaining polling code.
    t += "\n// v049 compatibility marker: countOfBytesSent polling was removed; progress uses URLSession didSendBodyData.\n"
    for token in ("CMUploadProgressDelegate", "didSendBodyData", "NSApp.dockTile.badgeLabel", "UNUserNotificationCenter", "NSProgressIndicator"):
        if token not in t:
            raise SystemExit(f"macOS progress guard missing: {token}")
    transfer.write_text(t, encoding="utf-8")

    bt = build.read_text(encoding="utf-8")
    linker = "-framework Cocoa -framework Network -framework UniformTypeIdentifiers"
    if "-framework UserNotifications" not in bt:
        if linker not in bt:
            raise SystemExit("macOS linker framework anchor missing")
        bt = bt.replace(linker, linker + " -framework UserNotifications", 1)
    build.write_text(bt, encoding="utf-8")

elif SYSTEM == "Windows":
    transfer = ROOT / "ci/ClipMeshTransfer.cs"
    ui = ROOT / "ci/ClipMeshWindows.cs"
    t = transfer.read_text(encoding="utf-8")
    u = ui.read_text(encoding="utf-8")

    helper = r'''internal static class CMTaskbarProgress
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
        pos = t.find("internal ")
        if pos < 0:
            raise SystemExit("Windows transfer type anchor missing")
        t = t[:pos] + helper + t[pos:]

    chooser_progress = "transferProgress.Value=Math.Max(0,Math.Min(1000,value));"
    if chooser_progress in t:
        t = t.replace(chooser_progress, chooser_progress + "CMTaskbarProgress.Set(Handle,value);", 1)
    chooser_success = 'Enabled=true;transferProgress.Visible=false;status.Text="Sent to "+device.Alias;'
    if chooser_success in t:
        t = t.replace(chooser_success, 'Enabled=true;transferProgress.Visible=false;CMTaskbarProgress.Clear(Handle);status.Text="Sent to "+device.Alias;System.Media.SystemSounds.Asterisk.Play();', 1)
    chooser_failure = 'Enabled=true;transferProgress.Visible=false;status.Text=ex.Message;'
    if chooser_failure in t:
        t = t.replace(chooser_failure, 'Enabled=true;transferProgress.Visible=false;CMTaskbarProgress.Clear(Handle);status.Text=ex.Message;', 1)
    transfer.write_text(t, encoding="utf-8")

    main_progress = "transferProgress.Value = Math.Max(0, Math.Min(1000, value));"
    if main_progress in u:
        u = u.replace(main_progress, main_progress + " CMTaskbarProgress.Set(Handle, value);", 1)
    main_success = 'transferProgress.Visible = false; transferStatus.Text = "Sent to " + device.Alias;'
    if main_success in u:
        u = u.replace(main_success, 'transferProgress.Visible = false; CMTaskbarProgress.Clear(Handle); transferStatus.Text = "Sent to " + device.Alias; tray.BalloonTipTitle = "File sent"; tray.BalloonTipText = "Sent to " + device.Alias; tray.ShowBalloonTip(2500);', 1)
    main_failure = 'transferProgress.Visible = false; transferStatus.Text = ex.Message;'
    if main_failure in u:
        u = u.replace(main_failure, 'transferProgress.Visible = false; CMTaskbarProgress.Clear(Handle); transferStatus.Text = ex.Message; tray.BalloonTipTitle = "Transfer failed"; tray.BalloonTipText = ex.Message; tray.ShowBalloonTip(3500);', 1)

    for token in ("CMTaskbarProgress", "SetProgressValue", "SetProgressState", "Action<long> onProgress", "ProgressBar transferProgress"):
        if token not in t:
            raise SystemExit(f"Windows taskbar progress guard missing: {token}")
    if "tray.ShowBalloonTip" not in u:
        raise SystemExit("Windows transfer notification guard missing")
    transfer.write_text(t, encoding="utf-8")
    ui.write_text(u, encoding="utf-8")

else:
    raise SystemExit(f"unsupported platform: {SYSTEM}")

print(f"Applied ClipMesh v049 event-driven performance repair on {SYSTEM}")
