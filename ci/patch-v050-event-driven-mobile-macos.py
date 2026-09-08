#!/usr/bin/env python3
"""ClipMesh v050: robust Android event-driven clipboard and macOS native progress layer.

This is the Linux/Darwin counterpart to the v049 Windows layer.  It is kept
separate because the generated Android runtime is reshaped by v030 and the
macOS build command is augmented by several later patch layers.
"""

from pathlib import Path
import os
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def ensure_import(text: str, package_line: str, import_line: str) -> str:
    if import_line in text:
        return text
    if package_line not in text:
        raise SystemExit(f"package anchor missing while inserting {import_line.strip()}")
    return text.replace(package_line, package_line + "\n" + import_line, 1)


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    bridge = java / "clipboard/ClipboardBridge.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    service = java / "shizuku/ClipboardUserService.kt"
    sync = java / "SyncService.kt"
    aidl_dir = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku"
    aidl = aidl_dir / "IClipboardUserService.aidl"
    callback_aidl = aidl_dir / "IClipboardChangeCallback.aidl"

    # ------------------------------------------------------------------
    # Android clipboard observation: ZERO periodic reads.
    # v028 introduced a 650 ms Shizuku watchdog. v030 later moved its teardown
    # into stopClipboardRuntime(), so remove the scheduler by semantic anchors
    # rather than the old stop() layout.
    # ------------------------------------------------------------------
    runtime_text = runtime.read_text(encoding="utf-8")
    runtime_text = replace_exact(
        runtime_text,
        "    private var clipboardWatchdog: java.util.concurrent.ScheduledExecutorService? = null\n",
        "",
        "Android clipboard watchdog field",
    )
    runtime_text = replace_exact(
        runtime_text,
        "        startClipboardWatchdog(app, bridge, sh)\n",
        "        // Global clipboard observation is callback-driven by the Shizuku UserService.\n",
        "Android clipboard watchdog start",
    )
    runtime_text, removed = re.subn(
        r'''\n    private fun startClipboardWatchdog\(context: Context, bridge: ClipboardBridge, shizuku: ShizukuManager\) \{.*?\n    \}\n(?=\n    private fun stopClipboardRuntime\(\))''',
        "\n",
        runtime_text,
        count=1,
        flags=re.S,
    )
    if removed != 1:
        raise SystemExit("Android startClipboardWatchdog function anchor changed")
    runtime_text = runtime_text.replace("        clipboardWatchdog?.shutdownNow()\n", "")
    runtime_text = runtime_text.replace("        clipboardWatchdog = null\n", "")
    runtime.write_text(runtime_text, encoding="utf-8")

    # Remove obsolete polling from the old service path as a defense in depth.
    if sync.exists():
        sync_text = sync.read_text(encoding="utf-8")
        sync_text = sync_text.replace("    private var shizukuMonitor: Job? = null\n", "")
        sync_text = sync_text.replace("    private var watchdog: Job? = null\n", "")
        sync_text = sync_text.replace("        shizukuMonitor?.cancel()\n", "")
        sync_text = sync_text.replace("        watchdog?.cancel()\n", "")
        sync_text, _ = re.subn(
            r'''\n        val power = getSystemService\(Context\.POWER_SERVICE\) as PowerManager\n        shizukuMonitor = scope\.launch \{.*?\n        \}\n\n        // Optional non-Shizuku OEM fallback\. OFF by default\.\n        if \(settings\.compatibilityWatchdog\) \{.*?\n        \}\n''',
            "\n",
            sync_text,
            count=1,
            flags=re.S,
        )
        sync.write_text(sync_text, encoding="utf-8")

    # ------------------------------------------------------------------
    # One Binder callback per actual clipboard/media change.
    # The app itself cannot globally observe the clipboard on Android 10+ while
    # unfocused. The authorized Shizuku UserService (shell identity) owns the
    # listener and sends tiny oneway callbacks to the app. The expensive clip
    # snapshot is read only after a real change event.
    # ------------------------------------------------------------------
    aidl_dir.mkdir(parents=True, exist_ok=True)
    callback_aidl.write_text(
        """package dev.clipmesh.shizuku;\n\noneway interface IClipboardChangeCallback {\n    void onClipboardChanged();\n    void onScreenshotChanged();\n}\n""",
        encoding="utf-8",
    )

    aidl_text = aidl.read_text(encoding="utf-8")
    aidl_text = replace_exact(
        aidl_text,
        "    boolean copyUriToFile(String uri, in ParcelFileDescriptor destination);\n    boolean setPrimaryClipText(String text);\n",
        "    boolean copyUriToFile(String uri, in ParcelFileDescriptor destination);\n"
        "    void registerClipboardChangeCallback(IClipboardChangeCallback callback);\n"
        "    void unregisterClipboardChangeCallback(IClipboardChangeCallback callback);\n"
        "    boolean setPrimaryClipText(String text);\n",
        "Android event callback AIDL methods",
    )
    aidl.write_text(aidl_text, encoding="utf-8")

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
            eventScreenshotObserver?.let { observer ->
                runCatching { ctx?.contentResolver?.unregisterContentObserver(observer) }
            }
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

    event_methods = r'''    override fun registerClipboardChangeCallback(callback: IClipboardChangeCallback) {
        changeCallbacks.register(callback)
        registerEventSourcesIfNeeded()
    }

    override fun unregisterClipboardChangeCallback(callback: IClipboardChangeCallback) {
        changeCallbacks.unregister(callback)
        if (changeCallbacks.registeredCallbackCount == 0) unregisterEventSources()
    }

'''
    service_text = replace_exact(
        service_text,
        "    override fun getLatestScreenshotJson(): String = runCatching {\n",
        event_methods + "    override fun getLatestScreenshotJson(): String = runCatching {\n",
        "Android UserService callback methods",
    )
    service_text = replace_exact(
        service_text,
        "    override fun destroy() {\n        lastClip = null\n        clipboardService = null\n    }\n",
        "    override fun destroy() {\n"
        "        unregisterEventSources()\n"
        "        changeCallbacks.kill()\n"
        "        lastClip = null\n"
        "        clipboardService = null\n"
        "    }\n",
        "Android UserService event cleanup",
    )
    service.write_text(service_text, encoding="utf-8")

    manager_text = manager.read_text(encoding="utf-8")
    manager_text = replace_exact(
        manager_text,
        "    @Volatile private var service: IClipboardUserService? = null\n",
        "    @Volatile private var service: IClipboardUserService? = null\n"
        "    @Volatile private var clipboardEventListener: (() -> Unit)? = null\n"
        "    @Volatile private var screenshotEventListener: (() -> Unit)? = null\n"
        "    private val clipboardChangeCallback = object : IClipboardChangeCallback.Stub() {\n"
        "        override fun onClipboardChanged() { clipboardEventListener?.invoke() }\n"
        "        override fun onScreenshotChanged() { screenshotEventListener?.invoke() }\n"
        "    }\n",
        "Android ShizukuManager callback field",
    )
    manager_text = replace_exact(
        manager_text,
        "            runCatching { service?.init(callerToken) }\n            latch.countDown()\n",
        "            runCatching {\n"
        "                service?.init(callerToken)\n"
        "                if (clipboardEventListener != null || screenshotEventListener != null) {\n"
        "                    service?.registerClipboardChangeCallback(clipboardChangeCallback)\n"
        "                }\n"
        "            }\n"
        "            latch.countDown()\n",
        "Android ShizukuManager callback registration",
    )
    manager_text = replace_exact(
        manager_text,
        "    fun readSnapshotJson(): String = runCatching { ensureConnected()?.primaryClipJson.orEmpty() }.getOrDefault(\"\")\n",
        "    fun setEventListeners(clipboard: (() -> Unit)?, screenshot: (() -> Unit)?) {\n"
        "        clipboardEventListener = clipboard\n"
        "        screenshotEventListener = screenshot\n"
        "        val active = clipboard != null || screenshot != null\n"
        "        val current = service\n"
        "        if (current != null) {\n"
        "            runCatching {\n"
        "                if (active) current.registerClipboardChangeCallback(clipboardChangeCallback)\n"
        "                else current.unregisterClipboardChangeCallback(clipboardChangeCallback)\n"
        "            }\n"
        "        } else if (active && hasPermission()) {\n"
        "            bindUserService()\n"
        "        }\n"
        "    }\n\n"
        "    fun readSnapshotJson(): String = runCatching { ensureConnected()?.primaryClipJson.orEmpty() }.getOrDefault(\"\")\n",
        "Android ShizukuManager event listener API",
    )
    manager_text = replace_exact(
        manager_text,
        "        if (service != null || binding) runCatching { Shizuku.unbindUserService(args, connection, false) }\n        service = null\n",
        "        service?.let { runCatching { it.unregisterClipboardChangeCallback(clipboardChangeCallback) } }\n"
        "        clipboardEventListener = null\n"
        "        screenshotEventListener = null\n"
        "        if (service != null || binding) runCatching { Shizuku.unbindUserService(args, connection, false) }\n"
        "        service = null\n",
        "Android ShizukuManager event cleanup",
    )
    manager_text = replace_exact(
        manager_text,
        ".version(11)",
        ".version(12)",
        "Android Shizuku UserService generation",
    )
    manager.write_text(manager_text, encoding="utf-8")

    bridge_text = bridge.read_text(encoding="utf-8")
    bridge_text = replace_exact(
        bridge_text,
        "        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }\n        main.post {\n",
        "        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }\n"
        "        shizuku.setEventListeners(\n"
        "            clipboard = { captureAsync(fromWatchdog = true) },\n"
        "            screenshot = { probeLatestScreenshotIfDue() },\n"
        "        )\n"
        "        main.post {\n",
        "Android ClipboardBridge event registration",
    )
    bridge_text = replace_exact(
        bridge_text,
        "        ForegroundTracker.clipboardChanged = null\n        main.post {\n",
        "        shizuku.setEventListeners(null, null)\n"
        "        ForegroundTracker.clipboardChanged = null\n"
        "        main.post {\n",
        "Android ClipboardBridge event cleanup",
    )
    bridge_text = replace_exact(
        bridge_text,
        "    fun captureNowForForeground() {\n"
        "        captureAsync(fromWatchdog = true)\n"
        "        // Samsung/Gboard records screenshots in MediaStore without changing the\n"
        "        // system clipboard and does not notify observers lacking broad gallery\n"
        "        // permission. Reuse the already-running interactive watchdog as a\n"
        "        // low-frequency Shizuku wake-up; persisted media IDs make it one-shot.\n"
        "        probeLatestScreenshotIfDue()\n"
        "    }\n",
        "    fun captureNowForForeground() = captureAsync(fromWatchdog = true)\n",
        "Android ClipboardBridge watchdog retirement",
    )
    bridge.write_text(bridge_text, encoding="utf-8")

    # Coalesce Android in-app/notification progress to whole-percent changes.
    share = java / "fileshare/FileShareActivity.kt"
    share_text = share.read_text(encoding="utf-8")
    callback_old = (
        "                        val fraction = if (totalBytes > 0L) ((sentBytes * 1000L) / totalBytes).toInt().coerceIn(0, 1000) else 1000\n"
        "                        val percent = fraction / 10\n"
        "                        main.post {\n"
        "                            transferProgress.progress = fraction\n"
        "                            status.text = \"Sending $fileName • $index/$total • $percent%\"\n"
        "                            TransferNotifications.showSending(this, outgoingId, target.alias, fileName, percent)\n"
        "                        }\n"
    )
    if callback_old in share_text:
        send_anchor = "                    LocalTransferEngine.sendUris(this, selected.toList(), target) { index, total, fileName, sentBytes, totalBytes ->\n"
        share_text = replace_exact(
            share_text,
            send_anchor,
            "                    var lastUiPercent = -1\n" + send_anchor,
            "Android transfer progress coalescing state",
        )
        callback_new = (
            "                        val fraction = if (totalBytes > 0L) ((sentBytes * 1000L) / totalBytes).toInt().coerceIn(0, 1000) else 1000\n"
            "                        val percent = fraction / 10\n"
            "                        if (percent != lastUiPercent || fraction >= 1000) {\n"
            "                            lastUiPercent = percent\n"
            "                            main.post {\n"
            "                                transferProgress.progress = fraction\n"
            "                                status.text = \"Sending $fileName • $index/$total • $percent%\"\n"
            "                                TransferNotifications.showSending(this, outgoingId, target.alias, fileName, percent)\n"
            "                            }\n"
            "                        }\n"
        )
        share_text = share_text.replace(callback_old, callback_new, 1)
        share.write_text(share_text, encoding="utf-8")

    # Hard regression guards: no periodic Android clipboard reader survives.
    runtime_final = runtime.read_text(encoding="utf-8")
    sync_final = sync.read_text(encoding="utf-8") if sync.exists() else ""
    for needle in ("clipboardWatchdog", "startClipboardWatchdog", "scheduleWithFixedDelay", "650L"):
        if needle in runtime_final:
            raise SystemExit(f"Android polling guard remains in BackgroundRuntime: {needle}")
    for needle in ("shizukuMonitor = scope.launch", "bridge.captureNowForBackgroundMonitor()"):
        if needle in sync_final:
            raise SystemExit(f"Android polling guard remains in SyncService: {needle}")
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

    helper_anchor = "private final class UploadSession {\n"
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
            center.add(UNNotificationRequest(
                identifier: "clipmesh-transfer-\(UUID().uuidString)",
                content: content,
                trigger: nil
            ))
        }
    }
}

'''
    text = replace_exact(text, helper_anchor, helpers + helper_anchor, "macOS transfer presentation helpers")

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
    event_replacement = r'''        let delegate = CMUploadProgressDelegate(onProgress)
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
        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."]) }
'''
    text = replace_exact(text, polling_old, event_replacement, "macOS URLSession byte polling")

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
    text = replace_exact(text, ui_old, ui_new, "macOS transfer presentation UI")
    transfer.write_text(text, encoding="utf-8")

    # Add UserNotifications to the generated swiftc invocation regardless of
    # which later patch appended other frameworks/options.
    build_text = build.read_text(encoding="utf-8")
    if "-framework UserNotifications" not in build_text:
        build_text, n = re.subn(
            r'(swiftc[^\n]*\$TRANSFER_SRC[^\n]*-framework UniformTypeIdentifiers)([^\n]*)',
            r'\1 -framework UserNotifications\2',
            build_text,
            count=1,
        )
        if n != 1:
            raise SystemExit("macOS swiftc framework invocation not found")
        build.write_text(build_text, encoding="utf-8")

    final = transfer.read_text(encoding="utf-8")
    for needle in ("URLSessionTaskDelegate", "didSendBodyData", "NSApp.dockTile.badgeLabel", "UNUserNotificationCenter"):
        if needle not in final:
            raise SystemExit(f"macOS native progress guard missing: {needle}")
    if "while sem.wait(timeout: .now() + 0.1)" in final or "countOfBytesSent" in final:
        raise SystemExit("macOS transfer byte polling remains after v050")

else:
    raise SystemExit(f"v050 applies only to Linux/Darwin, got {SYSTEM}")

print(f"Applied ClipMesh v050 event-driven mobile/macOS optimization on {SYSTEM}")
