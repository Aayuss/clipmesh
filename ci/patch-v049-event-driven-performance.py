#!/usr/bin/env python3
"""ClipMesh v049: event-driven Android clipboard + lower-overhead native transfer progress."""

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


def ensure_import(text: str, package_line: str, import_line: str) -> str:
    if import_line in text:
        return text
    return text.replace(package_line, package_line + "\n" + import_line, 1)


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    bridge = java / "clipboard/ClipboardBridge.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    service = java / "shizuku/ClipboardUserService.kt"
    sync = java / "SyncService.kt"
    aidl = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku/IClipboardUserService.aidl"
    callback_aidl = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku/IClipboardChangeCallback.aidl"

    # Android clipboard: remove the 650 ms Shizuku screen-on watchdog.
    # Clipboard changes are delivered by the Shizuku UserService instead.
    runtime_text = runtime.read_text(encoding="utf-8")
    runtime_text = runtime_text.replace(
        "    private var clipboardWatchdog: java.util.concurrent.ScheduledExecutorService? = null\n",
        "",
        1,
    )
    runtime_text = runtime_text.replace(
        "        startClipboardWatchdog(app, bridge, sh)\n",
        "        // Clipboard capture is event-driven through the Shizuku UserService.\n",
        1,
    )
    runtime_text, removed = re.subn(
        r'''\n    private fun startClipboardWatchdog\(context: Context, bridge: ClipboardBridge, shizuku: ShizukuManager\) \{.*?\n    \}\n\n    @Synchronized fun stop\(\) \{\n        clipboardWatchdog\?\.shutdownNow\(\)\n        clipboardWatchdog = null\n''',
        '''\n    @Synchronized fun stop() {\n''',
        runtime_text,
        count=1,
        flags=re.S,
    )
    if removed != 1:
        raise SystemExit("Android BackgroundRuntime clipboard watchdog anchor changed")
    runtime.write_text(runtime_text, encoding="utf-8")

    # Retire the old SyncService's active-peer and compatibility polling loops too.
    # BackgroundRuntime is the canonical runtime, but keeping this service poll-free
    # prevents an old boot/service path from reintroducing the same behavior.
    sync_text = sync.read_text(encoding="utf-8")
    sync_text = sync_text.replace("    private var shizukuMonitor: Job? = null\n", "")
    sync_text = sync_text.replace("    private var watchdog: Job? = null\n", "")
    sync_text = sync_text.replace("        shizukuMonitor?.cancel()\n", "")
    sync_text = sync_text.replace("        watchdog?.cancel()\n", "")
    sync_text, monitor_count = re.subn(
        r'''\n        val power = getSystemService\(Context\.POWER_SERVICE\) as PowerManager\n        shizukuMonitor = scope\.launch \{.*?\n        \}\n\n        // Optional non-Shizuku OEM fallback\. OFF by default\.\n        if \(settings\.compatibilityWatchdog\) \{.*?\n        \}\n''',
        "\n",
        sync_text,
        count=1,
        flags=re.S,
    )
    if monitor_count not in (0, 1):
        raise SystemExit("Unexpected Android SyncService monitor replacement count")
    sync.write_text(sync_text, encoding="utf-8")

    # Shizuku UserService -> app callback. Android 10+ only notifies the focused
    # app/default IME via normal ClipboardManager listeners, so the authorized
    # shell-identity service owns the background listener and sends ONE binder
    # callback per actual system clipboard change. It also owns a MediaStore
    # ContentObserver so screenshot sync no longer piggybacks on a polling loop.
    callback_aidl.write_text(
        '''package dev.clipmesh.shizuku;\n\noneway interface IClipboardChangeCallback {\n    void onClipboardChanged();\n    void onScreenshotChanged();\n}\n''',
        encoding="utf-8",
    )

    aidl_text = aidl.read_text(encoding="utf-8")
    aidl_anchor = '''    boolean copyUriToFile(String uri, in ParcelFileDescriptor destination);\n    boolean setPrimaryClipText(String text);\n'''
    aidl_replacement = '''    boolean copyUriToFile(String uri, in ParcelFileDescriptor destination);\n    void registerClipboardChangeCallback(IClipboardChangeCallback callback);\n    void unregisterClipboardChangeCallback(IClipboardChangeCallback callback);\n    boolean setPrimaryClipText(String text);\n'''
    if aidl_text.count(aidl_anchor) != 1:
        raise SystemExit("Android event callback AIDL anchor changed")
    aidl.write_text(aidl_text.replace(aidl_anchor, aidl_replacement, 1), encoding="utf-8")

    service_text = service.read_text(encoding="utf-8")
    package_line = "package dev.clipmesh.shizuku\n"
    for imp in (
        "import android.content.ClipboardManager\n",
        "import android.database.ContentObserver\n",
        "import android.os.Handler\n",
        "import android.os.Looper\n",
        "import android.os.RemoteCallbackList\n",
        "import android.provider.MediaStore\n",
    ):
        service_text = ensure_import(service_text, package_line, imp)

    class_match = re.search(r'(class ClipboardUserService[^\n]*\{\n)', service_text)
    if not class_match:
        raise SystemExit("Android ClipboardUserService class anchor changed")
    event_fields = r'''    private val changeCallbacks = RemoteCallbackList<IClipboardChangeCallback>()
    private val eventSourceLock = Any()
    @Volatile private var eventSourcesRegistered = false
    private var eventClipboard: ClipboardManager? = null
    private var eventScreenshotObserver: ContentObserver? = null

    private val eventClipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        broadcastClipboardChanged()
    }

    private fun eventContext(): Context? = serviceContext ?: runCatching { application() }.getOrNull()

    private fun registerEventSourcesIfNeeded() {
        synchronized(eventSourceLock) {
            if (eventSourcesRegistered) return
            val ctx = eventContext() ?: return
            val clipboard = ctx.getSystemService(ClipboardManager::class.java) ?: return
            val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
                override fun onChange(selfChange: Boolean) {
                    broadcastScreenshotChanged()
                }
            }
            clipboard.addPrimaryClipChangedListener(eventClipboardListener)
            runCatching {
                ctx.contentResolver.registerContentObserver(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    true,
                    observer,
                )
            }
            eventClipboard = clipboard
            eventScreenshotObserver = observer
            eventSourcesRegistered = true
        }
    }

    private fun unregisterEventSources() {
        synchronized(eventSourceLock) {
            if (!eventSourcesRegistered) return
            eventClipboard?.let { runCatching { it.removePrimaryClipChangedListener(eventClipboardListener) } }
            val ctx = eventContext()
            eventScreenshotObserver?.let { observer -> runCatching { ctx?.contentResolver?.unregisterContentObserver(observer) } }
            eventClipboard = null
            eventScreenshotObserver = null
            eventSourcesRegistered = false
        }
    }

    private fun broadcastClipboardChanged() {
        val count = changeCallbacks.beginBroadcast()
        try {
            for (index in 0 until count) {
                runCatching { changeCallbacks.getBroadcastItem(index).onClipboardChanged() }
            }
        } finally {
            changeCallbacks.finishBroadcast()
        }
    }

    private fun broadcastScreenshotChanged() {
        val count = changeCallbacks.beginBroadcast()
        try {
            for (index in 0 until count) {
                runCatching { changeCallbacks.getBroadcastItem(index).onScreenshotChanged() }
            }
        } finally {
            changeCallbacks.finishBroadcast()
        }
    }

'''
    insert_at = class_match.end()
    service_text = service_text[:insert_at] + event_fields + service_text[insert_at:]

    service_method_anchor = '''    override fun getLatestScreenshotJson(): String = runCatching {\n'''
    event_methods = r'''    override fun registerClipboardChangeCallback(callback: IClipboardChangeCallback) {
        changeCallbacks.register(callback)
        registerEventSourcesIfNeeded()
    }

    override fun unregisterClipboardChangeCallback(callback: IClipboardChangeCallback) {
        changeCallbacks.unregister(callback)
        if (changeCallbacks.registeredCallbackCount == 0) unregisterEventSources()
    }

'''
    if service_text.count(service_method_anchor) != 1:
        raise SystemExit("Android ClipboardUserService event method anchor changed")
    service_text = service_text.replace(service_method_anchor, event_methods + service_method_anchor, 1)

    destroy_old = '''    override fun destroy() {\n        lastClip = null\n        clipboardService = null\n    }\n'''
    destroy_new = '''    override fun destroy() {\n        unregisterEventSources()\n        changeCallbacks.kill()\n        lastClip = null\n        clipboardService = null\n    }\n'''
    if destroy_old in service_text:
        service_text = service_text.replace(destroy_old, destroy_new, 1)
    else:
        raise SystemExit("Android ClipboardUserService destroy anchor changed")
    service.write_text(service_text, encoding="utf-8")

    manager_text = manager.read_text(encoding="utf-8")
    manager_field_anchor = '''    @Volatile private var service: IClipboardUserService? = null\n'''
    manager_fields = '''    @Volatile private var service: IClipboardUserService? = null\n    @Volatile private var clipboardEventListener: (() -> Unit)? = null\n    @Volatile private var screenshotEventListener: (() -> Unit)? = null\n    private val clipboardChangeCallback = object : IClipboardChangeCallback.Stub() {\n        override fun onClipboardChanged() { clipboardEventListener?.invoke() }\n        override fun onScreenshotChanged() { screenshotEventListener?.invoke() }\n    }\n'''
    if manager_text.count(manager_field_anchor) != 1:
        raise SystemExit("Android ShizukuManager service field anchor changed")
    manager_text = manager_text.replace(manager_field_anchor, manager_fields, 1)

    manager_connect_old = '''            runCatching { service?.init(callerToken) }\n            latch.countDown()\n'''
    manager_connect_new = '''            runCatching {\n                service?.init(callerToken)\n                if (clipboardEventListener != null || screenshotEventListener != null) {\n                    service?.registerClipboardChangeCallback(clipboardChangeCallback)\n                }\n            }\n            latch.countDown()\n'''
    if manager_text.count(manager_connect_old) != 1:
        raise SystemExit("Android ShizukuManager connection anchor changed")
    manager_text = manager_text.replace(manager_connect_old, manager_connect_new, 1)

    manager_listener_anchor = '''    fun readSnapshotJson(): String = runCatching { ensureConnected()?.primaryClipJson.orEmpty() }.getOrDefault("")\n'''
    manager_listener_methods = '''    fun setEventListeners(clipboard: (() -> Unit)?, screenshot: (() -> Unit)?) {\n        clipboardEventListener = clipboard\n        screenshotEventListener = screenshot\n        val active = clipboard != null || screenshot != null\n        val current = service\n        if (current != null) {\n            runCatching {\n                if (active) current.registerClipboardChangeCallback(clipboardChangeCallback)\n                else current.unregisterClipboardChangeCallback(clipboardChangeCallback)\n            }\n        } else if (active && hasPermission()) {\n            bindUserService()\n        }\n    }\n\n    fun readSnapshotJson(): String = runCatching { ensureConnected()?.primaryClipJson.orEmpty() }.getOrDefault("")\n'''
    if manager_text.count(manager_listener_anchor) != 1:
        raise SystemExit("Android ShizukuManager listener method anchor changed")
    manager_text = manager_text.replace(manager_listener_anchor, manager_listener_methods, 1)

    close_anchor = '''        if (service != null || binding) runCatching { Shizuku.unbindUserService(args, connection, false) }\n        service = null\n'''
    close_replacement = '''        service?.let { runCatching { it.unregisterClipboardChangeCallback(clipboardChangeCallback) } }\n        clipboardEventListener = null\n        screenshotEventListener = null\n        if (service != null || binding) runCatching { Shizuku.unbindUserService(args, connection, false) }\n        service = null\n'''
    if manager_text.count(close_anchor) != 1:
        raise SystemExit("Android ShizukuManager close anchor changed")
    manager_text = manager_text.replace(close_anchor, close_replacement, 1)
    if ".version(11)" not in manager_text:
        raise SystemExit("Android Shizuku UserService generation 11 missing before event patch")
    manager_text = manager_text.replace(".version(11)", ".version(12)", 1)
    manager.write_text(manager_text, encoding="utf-8")

    bridge_text = bridge.read_text(encoding="utf-8")
    bridge_start_anchor = '''        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }\n        main.post {\n'''
    bridge_start_replacement = '''        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }\n        shizuku.setEventListeners(\n            clipboard = { captureAsync(fromWatchdog = true) },\n            screenshot = { probeLatestScreenshotIfDue() },\n        )\n        main.post {\n'''
    if bridge_text.count(bridge_start_anchor) != 1:
        raise SystemExit("Android ClipboardBridge start event anchor changed")
    bridge_text = bridge_text.replace(bridge_start_anchor, bridge_start_replacement, 1)

    bridge_stop_anchor = '''        ForegroundTracker.clipboardChanged = null\n        main.post {\n'''
    bridge_stop_replacement = '''        shizuku.setEventListeners(null, null)\n        ForegroundTracker.clipboardChanged = null\n        main.post {\n'''
    if bridge_text.count(bridge_stop_anchor) != 1:
        raise SystemExit("Android ClipboardBridge stop event anchor changed")
    bridge_text = bridge_text.replace(bridge_stop_anchor, bridge_stop_replacement, 1)

    foreground_old = '''    fun captureNowForForeground() {\n        captureAsync(fromWatchdog = true)\n        // Samsung/Gboard records screenshots in MediaStore without changing the\n        // system clipboard and does not notify observers lacking broad gallery\n        // permission. Reuse the already-running interactive watchdog as a\n        // low-frequency Shizuku wake-up; persisted media IDs make it one-shot.\n        probeLatestScreenshotIfDue()\n    }\n'''
    foreground_new = '''    fun captureNowForForeground() = captureAsync(fromWatchdog = true)\n'''
    if bridge_text.count(foreground_old) != 1:
        raise SystemExit("Android ClipboardBridge foreground watchdog anchor changed")
    bridge_text = bridge_text.replace(foreground_old, foreground_new, 1)
    bridge.write_text(bridge_text, encoding="utf-8")

    # File transfer progress is already byte-driven. Coalesce Android UI and
    # notification updates to whole-percent changes so a fast LAN transfer cannot
    # enqueue hundreds of main-thread/NotificationManager updates per second.
    share = java / "fileshare/FileShareActivity.kt"
    share_text = share.read_text(encoding="utf-8")
    callback_old = '''                        val fraction = if (totalBytes > 0L) ((sentBytes * 1000L) / totalBytes).toInt().coerceIn(0, 1000) else 1000\n                        val percent = fraction / 10\n                        main.post {\n                            transferProgress.progress = fraction\n                            status.text = "Sending $fileName • $index/$total • $percent%"\n                            TransferNotifications.showSending(this, outgoingId, target.alias, fileName, percent)\n                        }\n'''
    callback_new = '''                        val fraction = if (totalBytes > 0L) ((sentBytes * 1000L) / totalBytes).toInt().coerceIn(0, 1000) else 1000\n                        val percent = fraction / 10\n                        if (percent != lastUiPercent || fraction >= 1000) {\n                            lastUiPercent = percent\n                            main.post {\n                                transferProgress.progress = fraction\n                                status.text = "Sending $fileName • $index/$total • $percent%"\n                                TransferNotifications.showSending(this, outgoingId, target.alias, fileName, percent)\n                            }\n                        }\n'''
    if callback_old in share_text:
        send_anchor = '''                    LocalTransferEngine.sendUris(this, selected.toList(), target) { index, total, fileName, sentBytes, totalBytes ->\n'''
        if share_text.count(send_anchor) != 1:
            raise SystemExit("Android file progress callback anchor changed")
        share_text = share_text.replace(send_anchor, '''                    var lastUiPercent = -1\n''' + send_anchor, 1)
        share_text = share_text.replace(callback_old, callback_new, 1)
        share.write_text(share_text, encoding="utf-8")

    for path, forbidden in (
        (runtime, ("clipboardWatchdog", "scheduleWithFixedDelay", "650L")),
        (sync, ("shizukuMonitor = scope.launch", "bridge.captureNowForBackgroundMonitor()")),
    ):
        final = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in final:
                raise SystemExit(f"Android polling guard remains in {path}: {needle}")

    for path, required in (
        (callback_aidl, ("onClipboardChanged", "onScreenshotChanged")),
        (aidl, ("registerClipboardChangeCallback", "unregisterClipboardChangeCallback")),
        (service, ("addPrimaryClipChangedListener", "registerContentObserver", "RemoteCallbackList")),
        (manager, ("setEventListeners", ".version(12)")),
        (bridge, ("shizuku.setEventListeners", "probeLatestScreenshotIfDue")),
    ):
        final = path.read_text(encoding="utf-8")
        for needle in required:
            if needle not in final:
                raise SystemExit(f"Android event-driven guard missing in {path}: {needle}")

elif SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    build = PROJECT / "scripts/build-macos.sh"

    text = transfer.read_text(encoding="utf-8")
    if "import UserNotifications\n" not in text:
        text = text.replace("import Foundation\n", "import Foundation\nimport UserNotifications\n", 1)

    helper_anchor = '''private final class UploadSession {\n'''
    helpers = r'''private final class CMUploadProgressDelegate: NSObject, URLSessionTaskDelegate {
    private let callback: (Int64) -> Void
    init(_ callback: @escaping (Int64) -> Void) { self.callback = callback }
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        callback(max(0, totalBytesSent))
    }
}

private enum CMTransferPresentation {
    private static var lastDockPercent = -1

    static func begin() {
        DispatchQueue.main.async {
            lastDockPercent = -1
            update(0)
        }
    }

    static func update(_ fraction: Double) {
        let percent = Int((min(1, max(0, fraction)) * 100).rounded(.down))
        guard percent != lastDockPercent else { return }
        lastDockPercent = percent
        NSApp.dockTile.badgeLabel = percent >= 100 ? nil : "\(percent)%"
        NSApp.dockTile.display()
    }

    static func finish(receiver: String, fileCount: Int, error: Error? = nil) {
        DispatchQueue.main.async {
            lastDockPercent = -1
            NSApp.dockTile.badgeLabel = nil
            NSApp.dockTile.display()
        }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            if let error {
                content.title = "ClipMesh transfer failed"
                content.body = error.localizedDescription
            } else {
                content.title = "Sent to \(receiver)"
                content.body = fileCount == 1 ? "1 file sent successfully" : "\(fileCount) files sent successfully"
            }
            let request = UNNotificationRequest(identifier: "clipmesh-transfer-\(UUID().uuidString)", content: content, trigger: nil)
            center.add(request)
        }
    }
}

'''
    if text.count(helper_anchor) != 1:
        raise SystemExit("macOS transfer helper anchor changed")
    text = text.replace(helper_anchor, helpers + helper_anchor, 1)

    polling_old = r'''        let task = URLSession.shared.uploadTask(with: request, fromFile: file) { _, response, error in
            if let error { output = .failure(error) } else { output = .success((response as? HTTPURLResponse)?.statusCode ?? 0) }
            sem.signal()
        }
        task.resume()
        let deadline = Date().addingTimeInterval(190)
        while sem.wait(timeout: .now() + 0.1) == .timedOut {
            onProgress(max(0, task.countOfBytesSent))
            if Date() >= deadline { task.cancel(); throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."]) }
        }
        onProgress(size)
        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."]) }
'''
    event_old_replacement = r'''        let delegate = CMUploadProgressDelegate(onProgress)
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        let task = session.uploadTask(with: request, fromFile: file) { _, response, error in
            if let error { output = .failure(error) } else { output = .success((response as? HTTPURLResponse)?.statusCode ?? 0) }
            sem.signal()
        }
        task.resume()
        guard sem.wait(timeout: .now() + 190) == .success else {
            task.cancel(); session.invalidateAndCancel()
            throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."])
        }
        onProgress(size)
        session.finishTasksAndInvalidate()
        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."])
'''
    if text.count(polling_old) != 1:
        raise SystemExit("macOS URLSession byte-polling anchor changed")
    text = text.replace(polling_old, event_old_replacement, 1)

    ui_old = r'''        status?.stringValue = "Connecting to \(device.alias)…"
        transferProgress?.doubleValue = 0; transferProgress?.isHidden = false
        LocalTransferManager.shared.send(files: files, to: device, progress: { [weak self] text in self?.status?.stringValue = text }, progressValue: { [weak self] value in self?.transferProgress?.doubleValue = value }) { [weak self] result in
            switch result {
            case .success:
                self?.files.removeAll(); self?.refreshFiles()
                self?.transferProgress?.doubleValue = 1; self?.transferProgress?.isHidden = true
                self?.status?.stringValue = "Sent to \(device.alias)"
            case .failure(let error):
                self?.transferProgress?.isHidden = true
                self?.status?.stringValue = error.localizedDescription
                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)
            }
        }
'''
    ui_new = r'''        status?.stringValue = "Connecting to \(device.alias)…"
        transferProgress?.doubleValue = 0; transferProgress?.isHidden = false
        let fileCount = files.count
        CMTransferPresentation.begin()
        LocalTransferManager.shared.send(files: files, to: device, progress: { [weak self] text in self?.status?.stringValue = text }, progressValue: { [weak self] value in
            self?.transferProgress?.doubleValue = value
            CMTransferPresentation.update(value)
        }) { [weak self] result in
            switch result {
            case .success:
                self?.files.removeAll(); self?.refreshFiles()
                self?.transferProgress?.doubleValue = 1; self?.transferProgress?.isHidden = true
                self?.status?.stringValue = "Sent to \(device.alias)"
                CMTransferPresentation.finish(receiver: device.alias, fileCount: fileCount)
            case .failure(let error):
                self?.transferProgress?.isHidden = true
                self?.status?.stringValue = error.localizedDescription
                CMTransferPresentation.finish(receiver: device.alias, fileCount: fileCount, error: error)
                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)
            }
        }
'''
    if text.count(ui_old) != 1:
        raise SystemExit("macOS transfer presentation UI anchor changed")
    text = text.replace(ui_old, ui_new, 1)
    transfer.write_text(text, encoding="utf-8")

    build_text = build.read_text(encoding="utf-8")
    compile_old = 'swiftc -O "$MAIN_SRC" "$TRANSFER_SRC" -o "$APP/Contents/MacOS/ClipMesh" -framework Cocoa -framework Network -framework UniformTypeIdentifiers'
    compile_new = compile_old + ' -framework UserNotifications'
    if build_text.count(compile_old) != 1:
        raise SystemExit("macOS build framework anchor changed")
    build.write_text(build_text.replace(compile_old, compile_new, 1), encoding="utf-8")

    final = transfer.read_text(encoding="utf-8")
    for needle in ("URLSessionTaskDelegate", "didSendBodyData", "NSApp.dockTile.badgeLabel", "UNUserNotificationCenter"):
        if needle not in final:
            raise SystemExit(f"macOS native progress guard missing: {needle}")
    if "while sem.wait(timeout: .now() + 0.1)" in final or "countOfBytesSent" in final:
        raise SystemExit("macOS transfer byte polling remains after v049")

elif SYSTEM == "Windows":
    transfer = ROOT / "ci/ClipMeshTransfer.cs"
    ui = ROOT / "ci/ClipMeshWindows.cs"

    text = transfer.read_text(encoding="utf-8")
    if "using System.Runtime.InteropServices;\n" not in text:
        text = text.replace("using System.Net.Sockets;\n", "using System.Net.Sockets;\nusing System.Runtime.InteropServices;\n", 1)

    helper_anchor = '''internal sealed class TransferDeviceC\n'''
    taskbar_helper = r'''internal static class ClipMeshTaskbarProgress
{
    private enum TBPFLAG : uint { NOPROGRESS = 0x0, INDETERMINATE = 0x1, NORMAL = 0x2, ERROR = 0x4, PAUSED = 0x8 }

    [ComImport, Guid("56FDF344-FD6D-11d0-958A-006097C9A090"), ClassInterface(ClassInterfaceType.None)]
    private class CTaskbarList { }

    [ComImport, Guid("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ITaskbarList3
    {
        void HrInit();
        void AddTab(IntPtr hwnd);
        void DeleteTab(IntPtr hwnd);
        void ActivateTab(IntPtr hwnd);
        void SetActiveAlt(IntPtr hwnd);
        void MarkFullscreenWindow(IntPtr hwnd, [MarshalAs(UnmanagedType.Bool)] bool fullscreen);
        void SetProgressValue(IntPtr hwnd, ulong completed, ulong total);
        void SetProgressState(IntPtr hwnd, TBPFLAG flags);
    }

    private static readonly object Gate = new object();
    private static ITaskbarList3 api;

    private static ITaskbarList3 Api
    {
        get
        {
            lock (Gate)
            {
                if (api == null) { api = (ITaskbarList3)new CTaskbarList(); api.HrInit(); }
                return api;
            }
        }
    }

    public static void Set(IntPtr hwnd, int value, int maximum)
    {
        if (hwnd == IntPtr.Zero || Environment.OSVersion.Version.Major < 6) return;
        try { Api.SetProgressState(hwnd, TBPFLAG.NORMAL); Api.SetProgressValue(hwnd, (ulong)Math.Max(0, value), (ulong)Math.Max(1, maximum)); } catch { }
    }

    public static void Error(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return;
        try { Api.SetProgressState(hwnd, TBPFLAG.ERROR); } catch { }
    }

    public static void Clear(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return;
        try { Api.SetProgressState(hwnd, TBPFLAG.NOPROGRESS); } catch { }
    }
}

'''
    if text.count(helper_anchor) != 1:
        raise SystemExit("Windows taskbar helper anchor changed")
    text = text.replace(helper_anchor, taskbar_helper + helper_anchor, 1)

    total_old = '''        long totalBytes = 0; foreach (string path in byId.Values) totalBytes += new FileInfo(path).Length; long completedBytes = 0;\n'''
    total_new = '''        long totalBytes = 0; foreach (string path in byId.Values) totalBytes += new FileInfo(path).Length; long completedBytes = 0; int lastProgressValue = -1;\n'''
    if text.count(total_old) != 1:
        raise SystemExit("Windows transfer aggregate progress anchor changed")
    text = text.replace(total_old, total_new, 1)

    callback_old = '''            Upload(target, sid, item.Key, Convert.ToString(tokenRaw), item.Value, delegate(long sent) { if (progressValue != null) progressValue(totalBytes <= 0 ? 1000 : (int)Math.Min(1000L, ((before + sent) * 1000L) / totalBytes)); });\n'''
    callback_new = '''            Upload(target, sid, item.Key, Convert.ToString(tokenRaw), item.Value, delegate(long sent) { if (progressValue != null) { int value = totalBytes <= 0 ? 1000 : (int)Math.Min(1000L, ((before + sent) * 1000L) / totalBytes); if (value >= 1000 || lastProgressValue < 0 || value - lastProgressValue >= 5) { lastProgressValue = value; progressValue(value); } } });\n'''
    if text.count(callback_old) != 1:
        raise SystemExit("Windows transfer progress throttle anchor changed")
    text = text.replace(callback_old, callback_new, 1)

    chooser_old = '''    private void Send(TransferDeviceC device) { if (files.Count==0) { Choose(); return; } Enabled=false; transferProgress.Value=0; transferProgress.Visible=true; status.Text="Connecting to "+device.Alias+"…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(new List<string>(files),device,delegate(string s){ if(!IsDisposed) BeginInvoke((Action)(delegate{status.Text=s;}));},delegate(int value){if(!IsDisposed)BeginInvoke((Action)(delegate{transferProgress.Value=Math.Max(0,Math.Min(1000,value));}));}); if(!IsDisposed) BeginInvoke((Action)(delegate{files.Clear();RefreshFiles();Enabled=true;transferProgress.Visible=false;status.Text="Sent to "+device.Alias;})); } catch(Exception ex){ if(!IsDisposed) BeginInvoke((Action)(delegate{Enabled=true;transferProgress.Visible=false;status.Text=ex.Message;ClipMeshDialogC.Show(this,"Couldn’t send",ex.Message,false);})); } }); }\n'''
    chooser_new = '''    private void Send(TransferDeviceC device) { if (files.Count==0) { Choose(); return; } Enabled=false; transferProgress.Value=0; transferProgress.Visible=true; ClipMeshTaskbarProgress.Set(Handle,0,1000); status.Text="Connecting to "+device.Alias+"…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(new List<string>(files),device,delegate(string s){ if(!IsDisposed) BeginInvoke((Action)(delegate{status.Text=s;}));},delegate(int value){if(!IsDisposed)BeginInvoke((Action)(delegate{int safe=Math.Max(0,Math.Min(1000,value));transferProgress.Value=safe;ClipMeshTaskbarProgress.Set(Handle,safe,1000);}));}); if(!IsDisposed) BeginInvoke((Action)(delegate{files.Clear();RefreshFiles();Enabled=true;transferProgress.Visible=false;ClipMeshTaskbarProgress.Clear(Handle);status.Text="Sent to "+device.Alias;var owner=Owner as ClipMeshForm;if(owner!=null)owner.ShowTransferNotification("ClipMesh","Sent files to "+device.Alias,false);})); } catch(Exception ex){ if(!IsDisposed) BeginInvoke((Action)(delegate{Enabled=true;transferProgress.Visible=false;ClipMeshTaskbarProgress.Error(Handle);status.Text=ex.Message;var owner=Owner as ClipMeshForm;if(owner!=null)owner.ShowTransferNotification("ClipMesh transfer failed",ex.Message,true);ClipMeshDialogC.Show(this,"Couldn’t send",ex.Message,false);})); } }); }\n'''
    if text.count(chooser_old) != 1:
        raise SystemExit("Windows chooser taskbar progress anchor changed")
    text = text.replace(chooser_old, chooser_new, 1)
    transfer.write_text(text, encoding="utf-8")

    ui_text = ui.read_text(encoding="utf-8")
    notification_anchor = '''    private void RenameDevice()\n    {\n'''
    notification_method = '''    internal void ShowTransferNotification(string title, string message, bool error)\n    {\n        if (tray == null) return;\n        tray.ShowBalloonTip(3500, title, message, error ? ToolTipIcon.Error : ToolTipIcon.Info);\n    }\n\n    private void RenameDevice()\n    {\n'''
    if ui_text.count(notification_anchor) != 1:
        raise SystemExit("Windows notification method anchor changed")
    ui_text = ui_text.replace(notification_anchor, notification_method, 1)

    main_old = '''    private void SendTransfer(TransferDeviceC device) { if (transferFiles.Count == 0) { ChooseTransferFiles(); return; } transferProgress.Value = 0; transferProgress.Visible = true; transferStatus.Text = "Connecting to " + device.Alias + "…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(new List<string>(transferFiles), device, delegate(string text) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = text; })); }, delegate(int value) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferProgress.Value = Math.Max(0, Math.Min(1000, value)); })); }); if (!IsDisposed) BeginInvoke((Action)(delegate { transferFiles.Clear(); UpdateTransferFiles(); transferProgress.Visible = false; transferStatus.Text = "Sent to " + device.Alias; })); } catch (Exception ex) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferProgress.Visible = false; transferStatus.Text = ex.Message; ClipMeshDialogC.Show(this, "Couldn’t send", ex.Message, false); })); } }); }\n'''
    main_new = '''    private void SendTransfer(TransferDeviceC device) { if (transferFiles.Count == 0) { ChooseTransferFiles(); return; } transferProgress.Value = 0; transferProgress.Visible = true; ClipMeshTaskbarProgress.Set(Handle,0,1000); transferStatus.Text = "Connecting to " + device.Alias + "…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(new List<string>(transferFiles), device, delegate(string text) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = text; })); }, delegate(int value) { if (!IsDisposed) BeginInvoke((Action)(delegate { int safe=Math.Max(0,Math.Min(1000,value)); transferProgress.Value=safe; ClipMeshTaskbarProgress.Set(Handle,safe,1000); })); }); if (!IsDisposed) BeginInvoke((Action)(delegate { transferFiles.Clear(); UpdateTransferFiles(); transferProgress.Visible = false; ClipMeshTaskbarProgress.Clear(Handle); transferStatus.Text = "Sent to " + device.Alias; ShowTransferNotification("ClipMesh", "Sent files to " + device.Alias, false); })); } catch (Exception ex) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferProgress.Visible = false; ClipMeshTaskbarProgress.Error(Handle); transferStatus.Text = ex.Message; ShowTransferNotification("ClipMesh transfer failed", ex.Message, true); ClipMeshDialogC.Show(this, "Couldn’t send", ex.Message, false); })); } }); }\n'''
    if ui_text.count(main_old) != 1:
        raise SystemExit("Windows main taskbar progress anchor changed")
    ui_text = ui_text.replace(main_old, main_new, 1)
    ui.write_text(ui_text, encoding="utf-8")

    for path, required in (
        (transfer, ("ClipMeshTaskbarProgress", "SetProgressValue", "lastProgressValue", "ShowTransferNotification")),
        (ui, ("ShowTransferNotification", "ClipMeshTaskbarProgress.Set", "ClipMeshTaskbarProgress.Clear")),
    ):
        final = path.read_text(encoding="utf-8")
        for needle in required:
            if needle not in final:
                raise SystemExit(f"Windows native progress guard missing in {path}: {needle}")

else:
    raise SystemExit(f"unsupported platform: {SYSTEM}")

print(f"Applied ClipMesh v049 event-driven clipboard and native transfer progress on {SYSTEM}")
