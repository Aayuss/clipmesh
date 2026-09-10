#!/usr/bin/env python3
"""Second-pass runtime hardening and receiver-side transfer progress."""

from __future__ import annotations

import os
import platform
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"v053 {label} anchor changed in {path}: found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: Path, start: str, end: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(start) != 1 or text.count(end) != 1:
        raise SystemExit(f"v053 {label} boundary changed in {path}")
    left = text.index(start)
    right = text.index(end, left)
    path.write_text(text[:left] + replacement + text[right:], encoding="utf-8")


def patch_android() -> None:
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    bridge = java / "clipboard/ClipboardBridge.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    service = java / "shizuku/ClipboardUserService.kt"
    runtime = java / "BackgroundRuntime.kt"
    network = java / "network/NetworkEngine.kt"
    transfer = java / "fileshare/LocalTransferEngine.kt"
    notifications = java / "fileshare/TransferNotifications.kt"
    activity = java / "fileshare/FileShareActivity.kt"

    replace_once(
        bridge,
        "import java.util.concurrent.Executors\n",
        "import java.util.concurrent.Executors\nimport java.util.concurrent.TimeUnit\n",
        "clipboard scheduled worker import",
    )
    replace_once(
        bridge,
        '''    private val captureInFlight = AtomicBoolean(false)
    private val capturePending = AtomicBoolean(false)
    private val screenshotProbePending = AtomicBoolean(false)
    private val captureExecutor = Executors.newSingleThreadExecutor { r -> Thread(r, "ClipMesh-ClipboardCapture").apply { isDaemon = true } }
    @Volatile private var started = false
''',
        '''    private val captureInFlight = AtomicBoolean(false)
    private val clipboardCapturePending = AtomicBoolean(false)
    private val screenshotProbePending = AtomicBoolean(false)
    private val captureExecutor = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "ClipMesh-ClipboardCapture").apply { isDaemon = true } }
    @Volatile private var privilegedListenerRegistered: Boolean? = null
    @Volatile private var started = false
''',
        "independent pending work",
    )
    replace_between(
        bridge,
        "    private val listener = ClipboardManager.OnPrimaryClipChangedListener",
        "    private fun recordObservedEvent(eventKey: String)",
        r'''    private val listener = ClipboardManager.OnPrimaryClipChangedListener { signalSecondaryClipboardEvent() }
    private val screenshotObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) {
            signalScreenshotProbe()
        }
    }

    fun start() {
        if (started) return
        started = true
        ForegroundTracker.clipboardChanged = { signalSecondaryClipboardEvent() }
        main.post {
            clipboard.addPrimaryClipChangedListener(listener)
            runCatching {
                context.contentResolver.registerContentObserver(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    true,
                    screenshotObserver
                )
            }
            captureExecutor.execute { seedLatestScreenshot() }
        }
    }

    fun stop() {
        if (!started) return
        started = false
        privilegedListenerRegistered = null
        ForegroundTracker.clipboardChanged = null
        main.post {
            clipboard.removePrimaryClipChangedListener(listener)
            runCatching { context.contentResolver.unregisterContentObserver(screenshotObserver) }
        }
        captureExecutor.shutdownNow()
    }

    fun setPrivilegedListenerRegistered(registered: Boolean?) {
        privilegedListenerRegistered = registered
    }

    /** Authoritative hidden IClipboard event. */
    fun captureNowForSystemEvent() = signalClipboardEvent(manual = false)

    /** Explicit action skips the automatic-edge debounce. */
    fun captureNowForUserAction() = signalClipboardEvent(manual = true)

    fun captureNowForAccessibilityEvent() = signalSecondaryClipboardEvent()
    fun captureNowForCompatibilityFallback() = signalClipboardEvent(manual = false)
    fun captureInjectedForTest(clip: ClipData) {
        if (!dev.clipmesh.BuildConfig.DEBUG) return
        debugInjectedClip.set(clip)
        signalClipboardEvent(manual = true)
    }

    private fun signalSecondaryClipboardEvent() {
        // Normal-app and Accessibility listeners remain installed for OEM
        // compatibility and source metadata, but the hidden shell listener owns
        // capture edges while its registration is healthy.
        if (privilegedListenerRegistered == true) return
        signalClipboardEvent(manual = false)
    }

    private fun signalScreenshotProbe() {
        if (!started) return
        screenshotProbePending.set(true)
        scheduleDrain(EDGE_COALESCE_MS)
    }

    private fun signalClipboardEvent(manual: Boolean) {
        if (!started) return
        clipboardCapturePending.set(true)
        scheduleDrain(if (manual) 0L else EDGE_COALESCE_MS)
    }

    private fun scheduleDrain(delayMs: Long) {
        if (!captureInFlight.compareAndSet(false, true)) return
        runCatching {
            captureExecutor.schedule({ drainPendingWork() }, delayMs, TimeUnit.MILLISECONDS)
        }.onFailure { captureInFlight.set(false) }
    }

    private fun drainPendingWork() {
        try {
            if (!started || !settings.sendEnabled) {
                clipboardCapturePending.set(false)
                screenshotProbePending.set(false)
                return
            }
            if (screenshotProbePending.getAndSet(false)) probeLatestScreenshotIfDue()
            if (clipboardCapturePending.getAndSet(false)) captureClipboardSnapshot()
        } finally {
            captureInFlight.set(false)
            if (started && (clipboardCapturePending.get() || screenshotProbePending.get())) {
                // One latest-state follow-up is enough for any number of edges
                // that arrived while the Binder snapshot was in progress.
                scheduleDrain(EDGE_COALESCE_MS)
            }
        }
    }

    private fun captureClipboardSnapshot() {
        val sourcePackage = ForegroundTracker.currentPackage
        if (sourcePackage != null && sourcePackage != context.packageName &&
            settings.excludedPackages.contains(sourcePackage)
        ) return
        val observation = readCurrent(sourcePackage) ?: return
        val payload = observation.payload
        if (isPairingPayload(payload)) return
        val fp = payload.stableFingerprint()
        val eventKey = if (observation.generation > 0L) {
            "generation:${observation.generation}:$fp"
        } else {
            "fingerprint:$fp"
        }
        if (suppressedFingerprint.compareAndSet(fp, null)) {
            recordObservedEvent(eventKey)
            recordVisibleContent(echoFingerprint(payload))
            return
        }
        if (lastObservedClipboardEvent.get() == eventKey) return
        recordObservedEvent(eventKey)
        emitLocal(payload, fromScreenshot = false)
    }

''',
        "clipboard event arbiter",
    )
    bridge_text = bridge.read_text(encoding="utf-8").replace(".commit()", ".apply()")
    replace_start = "    private fun seedLatestScreenshot() {"
    replace_end = "    private fun isPairingPayload(payload: ClipPayload): Boolean {"
    old_block_start = bridge_text.index(replace_start)
    old_block_end = bridge_text.index(replace_end, old_block_start)
    new_screenshot = r'''    private fun seedLatestScreenshot() {
        if (lastScreenshotId.get() >= 0L) return
        val latest = latestScreenshot() ?: return
        lastScreenshotId.set(latest.id)
        statePrefs.edit().putLong("last_screenshot_id", latest.id).apply()
    }

    private fun probeLatestScreenshotIfDue() {
        if (!settings.syncImages) return
        val now = android.os.SystemClock.elapsedRealtime()
        val previous = lastScreenshotProbeAt.get()
        if (now - previous < 2_000L || !lastScreenshotProbeAt.compareAndSet(previous, now)) return
        // Discover exactly one candidate for this coalesced MediaStore edge.
        val candidate = latestScreenshot() ?: return
        if (candidate.id <= lastScreenshotId.get()) return
        copyScreenshotCandidate(candidate, attempt = 0)
    }

    private fun copyScreenshotCandidate(candidate: ScreenshotObservation, attempt: Int) {
        if (!started || !settings.sendEnabled || !settings.syncImages) return
        val temp = File(context.cacheDir, "outgoing/screenshot-${candidate.id}")
        val copied = shizuku.copyUri(candidate.uri, temp)
        val bytes = if (copied) runCatching { temp.readBytes() }.getOrNull() else null
        temp.delete()
        val png = bytes?.let(::imageToPng)
        if (png == null) {
            if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("screenshot_copy_fail_count")
            if (attempt < SCREENSHOT_COPY_RETRIES && started) {
                val delay = 250L * (attempt + 1L)
                captureExecutor.schedule(
                    { copyScreenshotCandidate(candidate, attempt + 1) },
                    delay,
                    TimeUnit.MILLISECONDS,
                )
            }
            return
        }
        lastScreenshotId.set(candidate.id)
        statePrefs.edit().putLong("last_screenshot_id", candidate.id).apply()
        emitLocal(
            ClipPayload(
                representations = listOf(Representation("image/png", png)),
                sourceApp = "android.screenshot",
            ),
            fromScreenshot = true,
        )
    }

'''
    bridge_text = bridge_text[:old_block_start] + new_screenshot + bridge_text[old_block_end:]
    class_end = bridge_text.index("\n}\n\n/**\n * Tracks multiple recently-applied")
    bridge_text = bridge_text[:class_end] + r'''

    private companion object {
        const val EDGE_COALESCE_MS = 60L
        const val SCREENSHOT_COPY_RETRIES = 8
    }
''' + bridge_text[class_end:]
    bridge.write_text(bridge_text, encoding="utf-8")
    replace_once(
        bridge,
        '''                if (shizuku.copyItem(item.getInt("index"), temp)) {
                    val bytes = temp.readBytes()
                    temp.delete()
                    rawBinaryBytes += bytes.size''',
        '''                val bytes = try {
                    if (shizuku.copyItem(item.getInt("index"), temp) &&
                        temp.length() <= 44L * 1024L * 1024L
                    ) temp.readBytes() else null
                } finally {
                    temp.delete()
                }
                if (bytes != null) {
                    rawBinaryBytes += bytes.size''',
        "clipboard temp cleanup and preallocation limit",
    )

    replace_once(
        runtime,
        "onRegistrationChanged = { registered -> onClipboardListenerRegistration(app, registered) },",
        "onRegistrationChanged = { registered ->\n                bridge.setPrivilegedListenerRegistered(registered)\n                onClipboardListenerRegistration(app, registered)\n            },",
        "authoritative listener state",
    )

    replace_once(
        manager,
        "import java.util.concurrent.TimeUnit\n",
        "import java.util.concurrent.TimeUnit\nimport java.util.concurrent.ScheduledFuture\n",
        "bind timeout import",
    )
    replace_once(
        manager,
        "private val connectionExecutor = Executors.newSingleThreadExecutor",
        "private val connectionExecutor = Executors.newSingleThreadScheduledExecutor",
        "scheduled connection executor",
    )
    replace_once(
        manager,
        "    private val connection = object : ServiceConnection {",
        "    private val connection: ServiceConnection = object : ServiceConnection {",
        "typed service connection for close race",
    )
    replace_once(
        manager,
        "    @Volatile private var listenerRegistered: Boolean? = null\n",
        "    @Volatile private var listenerRegistered: Boolean? = null\n    @Volatile private var bindTimeout: ScheduledFuture<*>? = null\n    @Volatile private var bindRetry: ScheduledFuture<*>? = null\n    @Volatile private var bindRetryAttempt = 0\n",
        "bind state",
    )
    replace_once(manager, "            binding = false\n            val connected", "            binding = false\n            cancelBindTimers(resetAttempt = true)\n            val connected", "connected timeout cancel")
    replace_once(
        manager,
        "        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {\n            binding = false\n            cancelBindTimers(resetAttempt = true)\n",
        "        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {\n            if (closed) {\n                binding = false\n                cancelBindTimers(resetAttempt = true)\n                service = null\n                runCatching { Shizuku.unbindUserService(args, connection, true) }\n                return\n            }\n            binding = false\n            cancelBindTimers(resetAttempt = true)\n",
        "late connection after close",
    )
    replace_once(manager, "                testConnected.countDown()\n                return\n", "                testConnected.countDown()\n                scheduleBindingRetry()\n                return\n", "null connection retry")
    replace_once(manager, "            binding = false\n            service = null\n", "            binding = false\n            cancelBindTimers(resetAttempt = false)\n            service = null\n", "disconnect timeout cancel")
    replace_once(manager, "            if (!closed && serviceRequired()) requestBinding()\n", "            if (!closed && serviceRequired()) scheduleBindingRetry()\n", "bounded disconnect retry")
    replace_once(manager, "        binding = false\n        service = null\n", "        binding = false\n        cancelBindTimers(resetAttempt = false)\n        service = null\n", "binder death timeout cancel")
    replace_once(manager, "        permissionGranted = result == PackageManager.PERMISSION_GRANTED\n", "        permissionGranted = result == PackageManager.PERMISSION_GRANTED\n        if (permissionGranted) bindRetryAttempt = 0\n", "permission retry reset")
    replace_once(manager, "        binderAvailable = true\n        permissionGranted = currentPermissionGranted()\n", "        binderAvailable = true\n        bindRetryAttempt = 0\n        permissionGranted = currentPermissionGranted()\n", "binder retry reset")
    replace_once(manager, "        } else {\n            requestBinding()\n            service?.let { connected -> initializeClipboardListener(connected) }\n", "        } else {\n            bindRetryAttempt = 0\n            requestBinding()\n            service?.let { connected -> initializeClipboardListener(connected) }\n", "listener retry reset")
    replace_once(
        manager,
        '''        closed = true
        // setClipboardChangedCallback(null) unregisters the hidden system listener
        // inside the UserService before Shizuku invokes its reserved destroy call.
        runCatching { service?.setClipboardChangedCallback(null) }
        clipboardChangeListener = null
        registrationListener = null
        listenerRegistered = null
''',
        '''        closed = true
        val connected = service
        // Detach in-process callbacks before any remote Binder cleanup can stall.
        clipboardChangeListener = null
        registrationListener = null
        listenerRegistered = null
        // Keep unregister + unbind synchronous so restart cannot create a second
        // production UserService before the old one receives reserved destroy.
        runCatching { connected?.setClipboardChangedCallback(null) }
''',
        "close callback detachment order",
    )
    replace_once(
        manager,
        "        pendingClipboardCapture.set(false)\n        connectionExecutor.shutdownNow()\n",
        "        pendingClipboardCapture.set(false)\n        cancelBindTimers(resetAttempt = true)\n        connectionExecutor.shutdownNow()\n",
        "close timer cleanup",
    )
    replace_between(
        manager,
        "    @Synchronized\n    private fun requestBinding()",
        "    private fun serviceOrRequest(pendingCapture: Boolean)",
        r'''    @Synchronized
    private fun requestBinding() {
        if (closed || !serviceRequired() || service != null || binding) return
        binding = true
        bindRetry?.cancel(false)
        bindRetry = null
        runCatching { connectionExecutor.execute {
            if (closed || !serviceRequired()) {
                binding = false
                return@execute
            }
            binderAvailable = isShizukuAvailable()
            permissionGranted = currentPermissionGranted()
            if (!binderAvailable || !permissionGranted) {
                binding = false
                listenerRegistered = null
                registrationListener?.invoke(null)
                testConnected.countDown()
                return@execute
            }
            runCatching { Shizuku.bindUserService(args, connection) }
                .onSuccess {
                    synchronized(this) { if (binding && service == null) armBindTimeout() }
                }
                .onFailure {
                    binding = false
                    listenerRegistered = null
                    registrationListener?.invoke(null)
                    testConnected.countDown()
                    scheduleBindingRetry()
                }
        } }.onFailure { binding = false }
    }

    @Synchronized
    private fun armBindTimeout() {
        bindTimeout?.cancel(false)
        bindTimeout = runCatching { connectionExecutor.schedule({
            synchronized(this) {
                if (closed || !binding || service != null) return@synchronized
                binding = false
                listenerRegistered = null
                registrationListener?.invoke(null)
                scheduleBindingRetry()
            }
        }, BIND_TIMEOUT_SECONDS, TimeUnit.SECONDS) }.getOrNull()
    }

    @Synchronized
    private fun scheduleBindingRetry() {
        if (closed || !serviceRequired() || service != null || bindRetry?.isDone == false) return
        if (bindRetryAttempt >= BIND_RETRY_DELAYS_MS.size) return
        val index = bindRetryAttempt
        val delayMs = BIND_RETRY_DELAYS_MS[index]
        bindRetryAttempt += 1
        bindRetry = runCatching { connectionExecutor.schedule({
            synchronized(this) { bindRetry = null }
            requestBinding()
        }, delayMs, TimeUnit.MILLISECONDS) }.getOrNull()
    }

    @Synchronized
    private fun cancelBindTimers(resetAttempt: Boolean) {
        bindTimeout?.cancel(false)
        bindTimeout = null
        bindRetry?.cancel(false)
        bindRetry = null
        if (resetAttempt) bindRetryAttempt = 0
    }

''',
        "bounded async bind state machine",
    )
    manager_text = manager.read_text(encoding="utf-8")
    companion_end = manager_text.index("\n    private val callerToken")
    manager_text = manager_text[:companion_end].replace(
        "        private val runtimeLock = Any()\n",
        "        private val runtimeLock = Any()\n        private const val BIND_TIMEOUT_SECONDS = 8L\n        private val BIND_RETRY_DELAYS_MS = longArrayOf(1_000L, 2_000L, 4_000L, 8_000L)\n",
        1,
    ) + manager_text[companion_end:]
    manager.write_text(manager_text, encoding="utf-8")
    replace_once(
        manager,
        "            connectionExecutor.execute {\n                if (closed || service !== connected) return@execute\n",
        "            runCatching { connectionExecutor.execute {\n                if (closed || service !== connected) return@execute\n",
        "connected executor close race start",
    )
    replace_once(
        manager,
        "                if (pendingClipboardCapture.getAndSet(false)) clipboardChangeListener?.invoke()\n            }\n        }\n\n        override fun onServiceDisconnected",
        "                if (pendingClipboardCapture.getAndSet(false)) clipboardChangeListener?.invoke()\n            } }\n        }\n\n        override fun onServiceDisconnected",
        "connected executor close race finish",
    )
    replace_once(
        manager,
        "        connectionExecutor.execute {\n            if (closed || service !== connected || clipboardChangeListener == null) return@execute\n",
        "        runCatching { connectionExecutor.execute {\n            if (closed || service !== connected || clipboardChangeListener == null) return@execute\n",
        "listener executor close race start",
    )
    replace_once(
        manager,
        "            registrationListener?.invoke(registered)\n        }\n    }\n\n    fun readSnapshotJson",
        "            registrationListener?.invoke(registered)\n        } }\n    }\n\n    fun readSnapshotJson",
        "listener executor close race finish",
    )

    replace_once(
        service,
        "import java.lang.reflect.Proxy\n",
        "import java.lang.reflect.Proxy\nimport java.util.concurrent.Executors\nimport java.util.concurrent.TimeUnit\n",
        "content process watchdog imports",
    )
    replace_once(
        service,
        "    @Volatile private var listenerRegistrationSucceeded = false\n",
        "    @Volatile private var listenerRegistrationSucceeded = false\n    private val processWatchdog = Executors.newSingleThreadScheduledExecutor { task ->\n        Thread(task, \"ClipMesh-ContentProcessWatchdog\").apply { isDaemon = true }\n    }\n",
        "process watchdog",
    )
    replace_once(
        service,
        "        val output = process.inputStream.bufferedReader().use { it.readText() }\n        if (process.waitFor() != 0) return@runCatching \"\"\n",
        "        val timeout = armProcessTimeout(process)\n        val output = try {\n            process.inputStream.bufferedReader().use { it.readText() }\n        } finally {\n            timeout.cancel(false)\n        }\n        if (!process.waitFor(1, TimeUnit.SECONDS) || process.exitValue() != 0) {\n            process.destroyForcibly()\n            return@runCatching \"\"\n        }\n",
        "screenshot query timeout",
    )
    replace_once(
        service,
        "        var total = 0L\n        ParcelFileDescriptor.dup(destination.fileDescriptor).use { duplicate ->",
        "        val timeout = armProcessTimeout(process)\n        var total = 0L\n        var exited = false\n        try {\n        ParcelFileDescriptor.dup(destination.fileDescriptor).use { duplicate ->",
        "content read timeout start",
    )
    replace_once(
        service,
        "        process.waitFor() == 0 && total > 0L\n    }.getOrDefault(false)\n",
        "        exited = process.waitFor(1, TimeUnit.SECONDS)\n        } finally {\n            timeout.cancel(false)\n            if (process.isAlive) process.destroyForcibly()\n        }\n        exited && process.exitValue() == 0 && total > 0L\n    }.getOrDefault(false)\n",
        "content read timeout finish",
    )
    replace_once(
        service,
        "    override fun destroy() {\n        runCatching { unregisterSystemClipboardListener() }",
        "    private fun armProcessTimeout(process: Process) = processWatchdog.schedule({\n        if (process.isAlive) process.destroyForcibly()\n    }, CONTENT_PROCESS_TIMEOUT_SECONDS, TimeUnit.SECONDS)\n\n    override fun destroy() {\n        runCatching { unregisterSystemClipboardListener() }",
        "watchdog helper",
    )
    replace_once(service, "        clipboardService = null\n        System.exit(0)", "        clipboardService = null\n        processWatchdog.shutdownNow()\n        System.exit(0)", "watchdog shutdown")
    service_text = service.read_text(encoding="utf-8").replace(
        "        private const val MAX_ITEM_BYTES = 44L * 1024L * 1024L\n",
        "        private const val MAX_ITEM_BYTES = 44L * 1024L * 1024L\n        private const val CONTENT_PROCESS_TIMEOUT_SECONDS = 12L\n",
        1,
    )
    service.write_text(service_text, encoding="utf-8")

    patch_android_network(network)
    patch_android_transfer(transfer, notifications, activity)

    boot = java / "BootReceiver.kt"
    replace_once(boot, "        val service = Intent(context, SyncService::class.java)\n", "        val service = Intent(context, BackgroundService::class.java)\n", "boot service target")
    sync = java / "SyncService.kt"
    if not sync.is_file():
        raise SystemExit("v053 expected legacy SyncService before removal")
    sync.unlink()


def patch_android_network(path: Path) -> None:
    replace_once(path, "import kotlinx.coroutines.channels.Channel\n", "import kotlinx.coroutines.channels.Channel\nimport kotlinx.coroutines.selects.select\n", "bounded peer select import")
    replace_once(
        path,
        "class NetworkEngine(\n",
        r'''/** Bounded per-peer queue policy, separated for deterministic stress testing. */
internal class PeerOutgoingQueue(controlCapacity: Int = 64) {
    private val controlQueue = Channel<ByteArray>(capacity = controlCapacity)
    private val latestClipboard = Channel<ByteArray>(capacity = Channel.CONFLATED)
    private val closed = AtomicBoolean(false)

    suspend fun sendControl(bytes: ByteArray): Boolean {
        if (closed.get()) return false
        return runCatching { controlQueue.send(bytes); true }.getOrDefault(false)
    }

    fun sendLatest(bytes: ByteArray): Boolean =
        !closed.get() && latestClipboard.trySend(bytes).isSuccess

    suspend fun receive(): ByteArray? = controlQueue.tryReceive().getOrNull() ?: select {
        controlQueue.onReceiveCatching { it.getOrNull() }
        latestClipboard.onReceiveCatching { it.getOrNull() }
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return
        controlQueue.close()
        latestClipboard.close()
    }
}

class NetworkEngine(
''',
        "testable bounded peer queue",
    )
    replace_once(path, "private val pending = ConcurrentHashMap<String, PendingFrame>()", "private val pending = ConcurrentHashMap<UUID, PendingFrame>()", "one pending state per peer")
    text = path.read_text(encoding="utf-8")
    text = text.replace("connection.send(frame)", "connection.sendLatest(frame)")
    text = text.replace("connection.send(latest.bytes)", "connection.sendLatest(latest.bytes)")
    text = text.replace("connection.send(p.bytes)", "connection.sendLatest(p.bytes)")
    text = text.replace("p.send(it)", "p.sendControl(it)")
    text = text.replace("connection.send(ack)", "connection.sendControl(ack)")
    text = text.replace("connection.send(pong)", "connection.sendControl(pong)")
    old_track = '''                val key = pendingKey(peerId, messageId)
                pending[key] = PendingFrame(peerId, messageId, frame)
                scheduleRetry(key, connection)
'''
    new_track = '''                pending[peerId] = PendingFrame(peerId, messageId, frame)
                scheduleRetry(peerId, messageId, connection)
'''
    if text.count(old_track) != 1:
        raise SystemExit("v053 live clipboard pending anchor changed")
    text = text.replace(old_track, new_track, 1)
    old_replay = '''                    val key = pendingKey(peerId, latest.message)
                    pending[key] = PendingFrame(peerId, latest.message, latest.bytes)
                    scheduleRetry(key, connection)
'''
    new_replay = '''                    pending[peerId] = PendingFrame(peerId, latest.message, latest.bytes)
                    scheduleRetry(peerId, latest.message, connection)
'''
    if text.count(old_replay) != 1:
        raise SystemExit("v053 replay pending anchor changed")
    text = text.replace(old_replay, new_replay, 1)
    text = text.replace(
        "Crypto.Kind.ACK -> pending.remove(pendingKey(peerId, frame.messageId))",
        "Crypto.Kind.ACK -> pending.computeIfPresent(peerId) { _, value -> if (value.message == frame.messageId) null else value }",
        1,
    )
    text = text.replace('pending.keys.removeIf { it.startsWith("$peerId|") }', "pending.remove(peerId)", 1)
    start = text.index("    private fun scheduleRetry(")
    end = text.index("    private fun shouldInitiate", start)
    text = text[:start] + r'''    private fun scheduleRetry(peerId: UUID, messageId: UUID, connection: PeerConnection) {
        scope.launch {
            for (delayMs in longArrayOf(750, 1500, 3000)) {
                delay(delayMs)
                val frame = pending[peerId] ?: return@launch
                if (frame.message != messageId) return@launch
                if (!connection.sendLatest(frame.bytes)) break
            }
            pending.computeIfPresent(peerId) { _, value -> if (value.message == messageId) null else value }
        }
    }

''' + text[end:]
    peer_start = text.index("    private class PeerConnection(")
    peer_end = text.rfind("\n}")
    peer = r'''    private class PeerConnection(
        val id: UUID,
        val peerId: UUID,
        val remoteAddress: InetAddress,
        private val socket: Socket,
        private val output: DataOutputStream
    ) {
        // Control frames are small and lossless with backpressure. Clipboard
        // state is conflated: a stalled peer retains only the latest encrypted
        // state instead of an unbounded sequence of large ByteArrays.
        private val outgoing = PeerOutgoingQueue()
        private val closed = AtomicBoolean(false)

        suspend fun sendControl(bytes: ByteArray): Boolean =
            !closed.get() && outgoing.sendControl(bytes)

        fun sendLatest(bytes: ByteArray): Boolean =
            !closed.get() && outgoing.sendLatest(bytes)

        suspend fun writerLoop() {
            try {
                while (!closed.get()) {
                    val frame = outgoing.receive() ?: break
                    if (frame.size > Crypto.MAX_FRAME_SIZE) break
                    output.writeInt(frame.size)
                    output.write(frame)
                    output.flush()
                }
            } catch (_: Exception) {
            } finally {
                close()
            }
        }

        fun close() {
            if (!closed.compareAndSet(false, true)) return
            outgoing.close()
            runCatching { socket.close() }
        }
    }
'''
    path.write_text(text[:peer_start] + peer + text[peer_end:], encoding="utf-8")

    build = PROJECT / "android/app/build.gradle.kts"
    replace_once(
        build,
        '    implementation("dev.rikka.shizuku:provider:13.1.5")\n',
        '    implementation("dev.rikka.shizuku:provider:13.1.5")\n    testImplementation("junit:junit:4.13.2")\n',
        "network queue test dependency",
    )
    test = PROJECT / "android/app/src/test/java/dev/clipmesh/network/PeerOutgoingQueueTest.kt"
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text(r'''package dev.clipmesh.network

import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PeerOutgoingQueueTest {
    @Test
    fun slowWriterKeepsControlsOrderedAndOnlyLatestClipboardState() = runBlocking {
        val queue = PeerOutgoingQueue(controlCapacity = 8)
        repeat(100) { index ->
            assertTrue(queue.sendLatest(byteArrayOf(0x7f, index.toByte())))
        }
        val producer = launch {
            repeat(100) { index -> assertTrue(queue.sendControl(byteArrayOf(index.toByte()))) }
        }
        val controls = mutableListOf<Int>()
        var latest = -1
        withTimeout(5_000L) {
            while (controls.size < 100 || latest != 99) {
                val frame = queue.receive() ?: error("queue closed early")
                if (frame.size == 1) controls += frame[0].toInt() and 0xff
                else latest = frame[1].toInt() and 0xff
                delay(1L) // deliberately slower than both producers
            }
        }
        producer.join()
        assertEquals((0 until 100).toList(), controls)
        assertEquals(99, latest)
        queue.close()
    }
}
''', encoding="utf-8")


def patch_android_transfer(transfer: Path, notifications: Path, activity: Path) -> None:
    replace_once(transfer, "import java.util.concurrent.atomic.AtomicBoolean\n", "import java.util.concurrent.atomic.AtomicBoolean\nimport java.util.concurrent.atomic.AtomicInteger\nimport java.util.concurrent.atomic.AtomicLong\n", "receive progress atomics")
    replace_once(
        transfer,
        "        val automaticallyAccepted: Boolean,\n        val received: MutableSet<String> = ConcurrentHashMap.newKeySet()\n    )",
        "        val automaticallyAccepted: Boolean,\n        val received: MutableSet<String> = ConcurrentHashMap.newKeySet()\n    ) {\n        val totalBytes = files.values.sumOf { it.size }\n        val receivedBytes = AtomicLong(0L)\n        val lastPublishedPercent = AtomicInteger(-1)\n        val lastPublishedAt = AtomicLong(0L)\n    }",
        "upload session progress",
    )
    replace_once(
        transfer,
        "    data class IncomingDecision(\n",
        "    data class IncomingProgress(\n        val sessionId: String,\n        val senderAlias: String,\n        val fileName: String,\n        val receivedBytes: Long,\n        val totalBytes: Long,\n        val complete: Boolean,\n        val failed: Boolean = false,\n    )\n\n    data class IncomingDecision(\n",
        "incoming progress model",
    )
    replace_once(
        transfer,
        "    @Volatile private var multicastLock: WifiManager.MulticastLock? = null\n",
        "    @Volatile private var multicastLock: WifiManager.MulticastLock? = null\n    @Volatile private var incomingProgressListener: ((IncomingProgress) -> Unit)? = null\n    @Volatile private var currentIncomingProgress: IncomingProgress? = null\n",
        "incoming progress state",
    )
    replace_once(
        transfer,
        "    fun resolveIncoming(requestId: String, accepted: Boolean) {",
        '''    fun setIncomingProgressListener(listener: ((IncomingProgress) -> Unit)?) {
        incomingProgressListener = listener
        if (listener != null) currentIncomingProgress?.let(listener)
    }

    private fun publishIncoming(session: UploadSession, fileName: String, complete: Boolean = false, failed: Boolean = false) {
        val progress = IncomingProgress(
            session.id,
            session.senderAlias,
            fileName,
            session.receivedBytes.get().coerceAtMost(session.totalBytes),
            session.totalBytes,
            complete,
            failed,
        )
        currentIncomingProgress = if (complete || failed) null else progress
        incomingProgressListener?.invoke(progress)
        if (failed) TransferNotifications.showReceiveFailed(requireContext(), progress)
        else if (complete) TransferNotifications.cancelReceiving(requireContext(), session.id)
        else TransferNotifications.showReceiving(requireContext(), progress)
    }

    fun resolveIncoming(requestId: String, accepted: Boolean) {''',
        "incoming progress publisher",
    )
    replace_once(
        transfer,
        "                query(uri)[\"sessionId\"]?.let { sessions.remove(it) }\n",
        "                query(uri)[\"sessionId\"]?.let { id -> sessions.remove(id); TransferNotifications.cancelReceiving(requireContext(), id) }\n",
        "cancel receive notification",
    )
    replace_once(
        transfer,
        "        sessions[sessionId] = UploadSession(\n",
        "        sessions[sessionId] = UploadSession(\n",
        "session creation presence",
    )
    replace_once(
        transfer,
        "        val tokenJson = JSONObject()\n",
        "        sessions[sessionId]?.let { publishIncoming(it, files.values.first().fileName) }\n        val tokenJson = JSONObject()\n",
        "initial receive progress",
    )
    replace_once(
        transfer,
        "        var remaining = length\n        var success = false\n",
        "        var remaining = length\n        var fileReceived = 0L\n        var success = false\n",
        "file receive counter",
    )
    replace_once(
        transfer,
        "                    remaining -= count\n",
        '''                    remaining -= count
                    fileReceived += count
                    val totalReceived = session.receivedBytes.addAndGet(count.toLong())
                    val percent = if (session.totalBytes <= 0L) 100 else ((totalReceived * 100L) / session.totalBytes).toInt().coerceIn(0, 100)
                    val now = android.os.SystemClock.elapsedRealtime()
                    val lastAt = session.lastPublishedAt.get()
                    if (percent != session.lastPublishedPercent.get() &&
                        (percent == 100 || now - lastAt >= 250L) &&
                        session.lastPublishedAt.compareAndSet(lastAt, now)
                    ) {
                        session.lastPublishedPercent.set(percent)
                        publishIncoming(session, meta.fileName)
                    }
''',
        "streamed receiver progress",
    )
    replace_once(
        transfer,
        "                    target.finish(false)\n                    return respond(output, 422, \"Checksum mismatch\")",
        "                    target.finish(false)\n                    session.receivedBytes.addAndGet(-fileReceived)\n                    publishIncoming(session, meta.fileName, failed = true)\n                    return respond(output, 422, \"Checksum mismatch\")",
        "checksum progress rollback",
    )
    replace_once(
        transfer,
        "                sessions.remove(sessionId)\n                if (session.automaticallyAccepted)",
        "                sessions.remove(sessionId)\n                publishIncoming(session, meta.fileName, complete = true)\n                if (session.automaticallyAccepted)",
        "receive completion",
    )
    replace_once(
        transfer,
        "        } catch (_: Throwable) {\n            if (!success) runCatching { target.finish(false) }",
        "        } catch (_: Throwable) {\n            if (!success) {\n                session.receivedBytes.addAndGet(-fileReceived)\n                publishIncoming(session, meta.fileName, failed = true)\n                runCatching { target.finish(false) }\n            }",
        "failed receive progress rollback",
    )

    replace_once(notifications, "    private const val SEND_CHANNEL = \"clipmesh_file_send_v047\"\n", "    private const val SEND_CHANNEL = \"clipmesh_file_send_v047\"\n    private const val RECEIVE_CHANNEL = \"clipmesh_file_receive_v053\"\n", "receive channel")
    replace_once(
        notifications,
        "        manager.createNotificationChannel(NotificationChannel(\n            COMPLETE_CHANNEL,",
        '''        manager.createNotificationChannel(NotificationChannel(
            RECEIVE_CHANNEL,
            "File receiving progress",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Shows progress while ClipMesh receives files"
            enableVibration(false)
            setSound(null, null)
        })
        manager.createNotificationChannel(NotificationChannel(
            COMPLETE_CHANNEL,''',
        "receive notification channel setup",
    )
    replace_once(
        notifications,
        "    fun showAutomaticallySaved(context: Context, sender: String, files: List<String>) {",
        '''    fun showReceiving(context: Context, progress: LocalTransferEngine.IncomingProgress) {
        ensureChannels(context)
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val percent = if (progress.totalBytes <= 0L) 100 else ((progress.receivedBytes * 100L) / progress.totalBytes).toInt().coerceIn(0, 100)
        val open = PendingIntent.getActivity(
            context,
            receivingId(progress.sessionId),
            Intent(context, FileShareActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        manager.notify(
            receivingId(progress.sessionId),
            android.app.Notification.Builder(context, RECEIVE_CHANNEL)
                .setSmallIcon(R.drawable.ic_clipmesh_notification)
                .setContentTitle("Receiving from ${progress.senderAlias} • $percent%")
                .setContentText(progress.fileName)
                .setProgress(100, percent, false)
                .setContentIntent(open)
                .setOnlyAlertOnce(true)
                .setOngoing(true)
                .build()
        )
    }

    fun cancelReceiving(context: Context, sessionId: String) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancel(receivingId(sessionId))
    }

    fun showReceiveFailed(context: Context, progress: LocalTransferEngine.IncomingProgress) {
        ensureChannels(context)
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val open = PendingIntent.getActivity(
            context,
            receivingId(progress.sessionId),
            Intent(context, FileShareActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        manager.notify(
            receivingId(progress.sessionId),
            android.app.Notification.Builder(context, COMPLETE_CHANNEL)
                .setSmallIcon(R.drawable.ic_clipmesh_notification)
                .setContentTitle("Transfer failed")
                .setContentText("Could not receive ${progress.fileName} from ${progress.senderAlias}")
                .setContentIntent(open)
                .setAutoCancel(true)
                .setOngoing(false)
                .build()
        )
    }

    fun showAutomaticallySaved(context: Context, sender: String, files: List<String>) {''',
        "receive notification methods",
    )
    replace_once(notifications, "    private fun outgoingId(id: String): Int = 0x53000000 xor id.hashCode()\n", "    private fun outgoingId(id: String): Int = 0x53000000 xor id.hashCode()\n    private fun receivingId(id: String): Int = 0x54000000 xor id.hashCode()\n", "receive notification id")

    replace_once(activity, "    private var sending = false\n", "    private var sending = false\n    private var receiving = false\n    private val incomingProgressListener: (LocalTransferEngine.IncomingProgress) -> Unit = { progress ->\n        runOnUiThread { showIncomingProgress(progress) }\n    }\n", "activity receive state")
    replace_once(activity, "            if (!isFinishing && !sending) renderDevices()", "            if (!isFinishing && !sending && !receiving) renderDevices()", "do not overwrite receive progress")
    replace_once(
        activity,
        "    override fun onResume() { super.onResume(); IncomingRequestUi.attach(this); NearbyPairingUi.attach(this); LocalTransferEngine.start(this); LocalTransferEngine.discoverNow() }\n    override fun onPause() { IncomingRequestUi.detach(this); NearbyPairingUi.detach(this); if (!dev.clipmesh.SettingsStore(this).receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }",
        "    override fun onResume() { super.onResume(); IncomingRequestUi.attach(this); NearbyPairingUi.attach(this); LocalTransferEngine.setIncomingProgressListener(incomingProgressListener); LocalTransferEngine.start(this); LocalTransferEngine.discoverNow() }\n    override fun onPause() { LocalTransferEngine.setIncomingProgressListener(null); IncomingRequestUi.detach(this); NearbyPairingUi.detach(this); if (!dev.clipmesh.SettingsStore(this).receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }",
        "activity progress lifecycle",
    )
    replace_once(
        activity,
        "    private fun showChooseMenu() {",
        '''    private fun showIncomingProgress(value: LocalTransferEngine.IncomingProgress) {
        if (!::transferProgress.isInitialized || sending) return
        val percent = if (value.totalBytes <= 0L) 100 else ((value.receivedBytes * 1000L) / value.totalBytes).toInt().coerceIn(0, 1000)
        receiving = !value.complete && !value.failed
        transferProgress.progress = percent
        transferProgress.visibility = if (value.complete || value.failed) View.GONE else View.VISIBLE
        status.text = when {
            value.failed -> "Could not receive ${value.fileName} from ${value.senderAlias}"
            value.complete -> "Received from ${value.senderAlias}"
            else -> "Receiving ${value.fileName} from ${value.senderAlias} • ${percent / 10}%"
        }
        if (value.complete || value.failed) main.postDelayed({ if (!isFinishing) { receiving = false; renderDevices() } }, 2_500L)
    }

    private fun showChooseMenu() {''',
        "activity receive UI",
    )


def patch_macos() -> None:
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    app = ROOT / "ci/ClipMeshApp.swift"
    replace_once(
        transfer,
        "    var received = Set<String>()\n",
        "    var received = Set<String>()\n    var receivedBytes: Int64 = 0\n    var lastProgressPercent = -1\n    var lastNotifiedPercent = -10\n    var totalBytes: Int64 { files.values.reduce(0) { $0 + $1.size } }\n",
        "mac receive session progress",
    )
    replace_once(
        transfer,
        "    var incomingPrompt: ((String, [TransferMeta]) -> Bool)?\n",
        "    var incomingPrompt: ((String, [TransferMeta]) -> Bool)?\n    var incomingProgress: ((String, String, Double, Bool) -> Void)?\n",
        "mac receive callback",
    )
    old_upload = r'''            let first = initial.prefix(min(initial.count, expected))
            if !first.isEmpty { try handle.write(contentsOf: first) }
            receiveUpload(connection, handle: handle, destination: url, remaining: expected - first.count) { success in
                try? handle.close()
                guard success else { try? FileManager.default.removeItem(at: url); return self.respond(connection, code: 500, body: "Transfer failed") }
                self.stateLock.lock()
                session.received.insert(fid)
                let done = session.received.count >= session.files.count
                if done { self.sessions.removeValue(forKey: sid) }
                self.stateLock.unlock()
                self.respond(connection, code: 200, body: "")
            }
'''
    new_upload = r'''            let first = initial.prefix(min(initial.count, expected))
            if !first.isEmpty { try handle.write(contentsOf: first) }
            var fileReceived = first.count
            session.receivedBytes += Int64(first.count)
            publishIncomingProgress(session: session, file: meta.name, complete: false)
            receiveUpload(connection, handle: handle, destination: url, remaining: expected - first.count, onProgress: { count in
                fileReceived += count
                session.receivedBytes += Int64(count)
                self.publishIncomingProgress(session: session, file: meta.name, complete: false)
            }) { success in
                try? handle.close()
                guard success else {
                    session.receivedBytes -= Int64(fileReceived)
                    try? FileManager.default.removeItem(at: url)
                    self.publishIncomingFailure(session: session, file: meta.name)
                    return self.respond(connection, code: 500, body: "Transfer failed")
                }
                self.stateLock.lock()
                session.received.insert(fid)
                let done = session.received.count >= session.files.count
                if done { self.sessions.removeValue(forKey: sid) }
                self.stateLock.unlock()
                if done {
                    self.publishIncomingProgress(session: session, file: meta.name, complete: true)
                    self.refreshDownloadsFolderRecency()
                }
                self.respond(connection, code: 200, body: "")
            }
'''
    replace_once(transfer, old_upload, new_upload, "mac streamed receive progress")
    replace_once(
        transfer,
        "    private func receiveUpload(_ connection: NWConnection, handle: FileHandle, destination: URL, remaining: Int, completion: @escaping (Bool) -> Void) {",
        "    private func receiveUpload(_ connection: NWConnection, handle: FileHandle, destination: URL, remaining: Int, onProgress: @escaping (Int) -> Void, completion: @escaping (Bool) -> Void) {",
        "mac receive progress callback",
    )
    replace_once(transfer, "            let left = remaining - data.count\n", "            onProgress(data.count)\n            let left = remaining - data.count\n", "mac receive chunk report")
    replace_once(transfer, "else { self?.receiveUpload(connection, handle: handle, destination: destination, remaining: left, completion: completion) }", "else { self?.receiveUpload(connection, handle: handle, destination: destination, remaining: left, onProgress: onProgress, completion: completion) }", "mac recursive progress")
    replace_once(
        transfer,
        "    private func destinationURL(for meta: TransferMeta) throws -> URL {",
        r'''    private func publishIncomingProgress(session: UploadSession, file: String, complete: Bool) {
        let fraction = session.totalBytes <= 0 ? 1 : min(1, max(0, Double(session.receivedBytes) / Double(session.totalBytes)))
        let percent = Int((fraction * 100).rounded())
        if !complete && percent == session.lastProgressPercent { return }
        session.lastProgressPercent = percent
        DispatchQueue.main.async { [weak self] in
            self?.incomingProgress?(session.sender, file, fraction, complete)
            if complete {
                CMTransferPresentation.clearDock()
                CMTransferPresentation.notify(identifier: "clipmesh-receive-\(session.id)", title: "Files received", body: "Saved from \(session.sender) to Downloads/ClipMesh")
            } else {
                CMTransferPresentation.updateDock(fraction)
                if percent == 0 || percent == 100 || percent - session.lastNotifiedPercent >= 10 {
                    session.lastNotifiedPercent = percent
                    CMTransferPresentation.notify(identifier: "clipmesh-receive-\(session.id)", title: "Receiving from \(session.sender) • \(percent)%", body: file)
                }
            }
        }
    }

    private func publishIncomingFailure(session: UploadSession, file: String) {
        DispatchQueue.main.async { [weak self] in
            self?.incomingProgress?(session.sender, file, -1, false)
            CMTransferPresentation.clearDock()
            CMTransferPresentation.notify(identifier: "clipmesh-receive-\(session.id)", title: "Transfer failed", body: "Could not receive \(file) from \(session.sender)")
        }
    }

    private func refreshDownloadsFolderRecency() {
        let manager = FileManager.default
        let downloads = manager.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let folder = downloads.appendingPathComponent("ClipMesh", isDirectory: true)
        guard manager.fileExists(atPath: folder.path) else { return }
        // addedToDirectoryDate is read-only but macOS defines it as the time an
        // item was renamed within its parent. Rename only after every active
        // receive session has closed its file handle, then restore immediately.
        let temporary = downloads.appendingPathComponent(".ClipMesh-recency-\(UUID().uuidString)", isDirectory: true)
        do {
            try manager.moveItem(at: folder, to: temporary)
            do {
                try manager.moveItem(at: temporary, to: folder)
            } catch {
                if !manager.fileExists(atPath: folder.path) { try? manager.moveItem(at: temporary, to: folder) }
                throw error
            }
        } catch {
            NSLog("ClipMesh could not refresh Downloads folder recency: %@", error.localizedDescription)
        }
        try? manager.setAttributes([.modificationDate: Date()], ofItemAtPath: folder.path)
    }

    private func destinationURL(for meta: TransferMeta) throws -> URL {''',
        "mac recency and presentation",
    )
    replace_once(
        transfer,
        "    static func notify(title: String, body: String) {",
        "    static func notify(identifier: String = \"clipmesh-transfer-\\(UUID().uuidString)\", title: String, body: String) {",
        "stable mac notification id",
    )
    replace_once(transfer, 'center.add(UNNotificationRequest(identifier: "clipmesh-transfer-\\(UUID().uuidString)", content: content, trigger: nil))', 'center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil))', "mac notification replacement")
    replace_once(transfer, "                content.body = body\n", "                content.body = body\n                center.removeDeliveredNotifications(withIdentifiers: [identifier])\n", "replace delivered mac progress notification")

    replace_once(
        app,
        "        LocalTransferManager.shared.incomingPrompt = { sender, files in\n            TransferDialogs.ask(sender: sender, files: files)\n        }\n",
        '''        LocalTransferManager.shared.incomingPrompt = { sender, files in
            TransferDialogs.ask(sender: sender, files: files)
        }
        LocalTransferManager.shared.incomingProgress = { [weak self] sender, file, fraction, complete in
            self?.showIncomingTransferProgress(sender: sender, file: file, fraction: fraction, complete: complete)
        }
''',
        "mac app receive callback",
    )
    replace_once(
        app,
        "    private func buildStatusItem() {",
        r'''    private func showIncomingTransferProgress(sender: String, file: String, fraction: Double, complete: Bool) {
        if fraction < 0 {
            statusItem?.length = NSStatusItem.squareLength
            statusItem?.button?.title = ""
            statusItem?.button?.toolTip = nil
            if window?.isVisible == true { transferStatusLabel?.stringValue = "Could not receive \(file) from \(sender)" }
            return
        }
        let percent = Int((min(1, max(0, fraction)) * 100).rounded())
        if complete {
            statusItem?.length = NSStatusItem.squareLength
            statusItem?.button?.title = ""
            statusItem?.button?.toolTip = nil
            if window?.isVisible == true { transferStatusLabel?.stringValue = "Received from \(sender)" }
        } else {
            statusItem?.length = NSStatusItem.variableLength
            statusItem?.button?.title = " ↓ \(percent)%"
            statusItem?.button?.toolTip = "Receiving \(file) from \(sender)"
            if window?.isVisible == true { transferStatusLabel?.stringValue = "Receiving \(file) from \(sender) • \(percent)%" }
        }
    }

    private func buildStatusItem() {''',
        "mac menu bar receive progress",
    )


def patch_windows() -> None:
    transfer = ROOT / "ci/ClipMeshTransfer.cs"
    app = ROOT / "ci/ClipMeshWindows.cs"
    replace_once(transfer, "    public readonly HashSet<string> Received = new HashSet<string>();\n", "    public readonly HashSet<string> Received = new HashSet<string>();\n    public long ReceivedBytes;\n    public int LastProgress = -1;\n", "windows receive session progress")
    replace_once(transfer, "    public Func<string, List<TransferFileMetaC>, bool> IncomingPrompt;\n", "    public Func<string, List<TransferFileMetaC>, bool> IncomingPrompt;\n    public Action<string, string, int, bool> IncomingProgress;\n", "windows receive callback")
    old_loop = "                byte[] buffer = new byte[131072]; long left = length;\n                while (left > 0) { int read = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, left)); if (read <= 0) throw new IOException(\"Upload ended early\"); output.Write(buffer, 0, read); left -= read; }\n"
    new_loop = "                byte[] buffer = new byte[131072]; long left = length;\n                while (left > 0) { int read = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, left)); if (read <= 0) throw new IOException(\"Upload ended early\"); output.Write(buffer, 0, read); left -= read; fileReceived += read; Interlocked.Add(ref session.ReceivedBytes, read); PublishIncoming(session, meta.Name, false); }\n"
    replace_once(transfer, old_loop, new_loop, "windows streamed receive progress")
    replace_once(transfer, "        string path = Destination(meta); bool success = false;\n", "        string path = Destination(meta); bool success = false; long fileReceived = 0;\n", "windows receive rollback counter")
    replace_once(transfer, "        catch { try { File.Delete(path); } catch { } }\n", "        catch { Interlocked.Add(ref session.ReceivedBytes, -fileReceived); Action<string, string, int, bool> failed = IncomingProgress; if (failed != null) failed(session.Sender, meta.Name, -1, false); try { File.Delete(path); } catch { } }\n", "windows receive failure presentation")
    replace_once(
        transfer,
        "        lock (gate)\n        {\n            session.Received.Add(fid); if (session.Received.Count >= session.Files.Count) sessions.Remove(sid);\n        }\n        Respond(stream, 200, \"\", \"text/plain\");",
        "        bool complete; lock (gate)\n        {\n            session.Received.Add(fid); complete = session.Received.Count >= session.Files.Count; if (complete) sessions.Remove(sid);\n        }\n        if (complete) PublishIncoming(session, meta.Name, true);\n        Respond(stream, 200, \"\", \"text/plain\");",
        "windows receive completion",
    )
    replace_once(
        transfer,
        "    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress)",
        '''    private void PublishIncoming(TransferSessionC session, string file, bool complete)
    {
        long total = 0; foreach (TransferFileMetaC item in session.Files.Values) total += item.Size;
        long received = Interlocked.Read(ref session.ReceivedBytes);
        int value = total <= 0 ? 1000 : (int)Math.Min(1000L, (received * 1000L) / total);
        lock (session) { if (!complete && value == session.LastProgress) return; session.LastProgress = value; }
        Action<string, string, int, bool> callback = IncomingProgress;
        if (callback != null) callback(session.Sender, file, value, complete);
    }

    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress)''',
        "windows receive publisher",
    )
    replace_once(
        app,
        "                LocalTransferManagerC.Shared.IncomingPrompt = AskIncomingFiles;\n",
        "                LocalTransferManagerC.Shared.IncomingPrompt = AskIncomingFiles;\n                LocalTransferManagerC.Shared.IncomingProgress = ShowIncomingTransferProgress;\n",
        "windows app receive callback",
    )
    replace_once(
        app,
        "    private void OnShown(object sender, EventArgs e)\n",
        '''    private int lastIncomingBalloonPercent = -10;
    private void ShowIncomingTransferProgress(string sender, string file, int value, bool complete)
    {
        if (IsDisposed) return;
        try { BeginInvoke((MethodInvoker)delegate
        {
            if (value < 0) { transferProgress.Visible = false; CMTaskbarProgress.Clear(Handle); tray.Text = "ClipMesh"; transferStatus.Text = "Incoming transfer failed"; tray.BalloonTipTitle = "Transfer failed"; tray.BalloonTipText = "Could not receive " + file + " from " + sender; tray.ShowBalloonTip(3000); return; }
            int percent = Math.Max(0, Math.Min(100, value / 10));
            if (complete)
            {
                transferProgress.Visible = false; CMTaskbarProgress.Clear(Handle); tray.Text = "ClipMesh"; lastIncomingBalloonPercent = -10;
                transferStatus.Text = "Received from " + sender; tray.BalloonTipTitle = "Files received"; tray.BalloonTipText = "Saved from " + sender + " to Downloads\\\\ClipMesh"; tray.ShowBalloonTip(3000);
            }
            else
            {
                transferProgress.Visible = true; transferProgress.Value = Math.Max(0, Math.Min(1000, value)); CMTaskbarProgress.Set(Handle, value);
                transferStatus.Text = "Receiving " + file + " from " + sender + " • " + percent + "%";
                string tooltip = "ClipMesh - receiving " + percent + "%"; tray.Text = tooltip.Length > 63 ? tooltip.Substring(0, 63) : tooltip;
                if (percent == 0 || percent == 100 || percent - lastIncomingBalloonPercent >= 10) { lastIncomingBalloonPercent = percent; tray.BalloonTipTitle = "Receiving from " + sender + " • " + percent + "%"; tray.BalloonTipText = file; tray.ShowBalloonTip(1500); }
            }
        }); } catch { }
    }

    private void OnShown(object sender, EventArgs e)
''',
        "windows tray and app receive progress",
    )


if SYSTEM == "Linux":
    patch_android()
elif SYSTEM == "Darwin":
    patch_macos()
elif SYSTEM == "Windows":
    patch_windows()
else:
    raise SystemExit(f"Unsupported CLIPMESH_PLATFORM for v053: {SYSTEM}")

print(f"Applied ClipMesh v053 second-pass runtime and receiver progress on {SYSTEM}")
