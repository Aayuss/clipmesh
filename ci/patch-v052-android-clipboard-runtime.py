#!/usr/bin/env python3
"""ClipMesh v052: event-only Android clipboard capture and one Shizuku owner."""

from pathlib import Path
import os
import platform
import re
import runpy


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"{label}: missing expected pre-v052 anchor {needle!r}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    debug_java = PROJECT / "android/app/src/debug/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    bridge = java / "clipboard/ClipboardBridge.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    user_service = java / "shizuku/ClipboardUserService.kt"
    accessibility = java / "exclusion/ExclusionAccessibilityService.kt"
    settings = java / "SettingsActivity.kt"
    sync_service = java / "SyncService.kt"
    aidl = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku/IClipboardUserService.aidl"

    old_runtime = runtime.read_text(encoding="utf-8")
    require(old_runtime, "sh.setClipboardChangeListener", "event-driven runtime")
    require(old_runtime, "private fun stopClipboardRuntime()", "runtime shutdown")
    runtime.write_text(r'''package dev.clipmesh

import android.content.Context
import dev.clipmesh.clipboard.ClipboardBridge
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.network.NetworkEngine
import dev.clipmesh.shizuku.ShizukuManager
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/** Tracks whether a ClipMesh activity is actually foreground. ClipboardBridge
 * uses this only to gate the normal-UID ClipboardManager fallback. */
internal object ClipMeshUiVisibility : android.app.Application.ActivityLifecycleCallbacks {
    @Volatile private var installed = false
    private val startedActivities = java.util.Collections.newSetFromMap(
        java.util.IdentityHashMap<android.app.Activity, Boolean>()
    )
    private var hideGeneration = 0L

    fun install(context: Context) {
        val application = context.applicationContext as? android.app.Application ?: return
        var register = false
        var foreground = false
        synchronized(this) {
            if (!installed) {
                installed = true
                register = true
            }
            if (context is android.app.Activity) {
                startedActivities.add(context)
                hideGeneration += 1
                foreground = true
            }
        }
        if (register) application.registerActivityLifecycleCallbacks(this)
        if (foreground) LocalTransferEngine.setUiVisible(true)
    }

    fun isForeground(): Boolean = synchronized(this) { startedActivities.isNotEmpty() }

    override fun onActivityStarted(activity: android.app.Activity) {
        synchronized(this) {
            startedActivities.add(activity)
            hideGeneration += 1
        }
        LocalTransferEngine.setUiVisible(true)
    }

    override fun onActivityStopped(activity: android.app.Activity) {
        var generation = 0L
        var shouldScheduleHide = false
        synchronized(this) {
            startedActivities.remove(activity)
            hideGeneration += 1
            generation = hideGeneration
            shouldScheduleHide = startedActivities.isEmpty()
        }
        if (!shouldScheduleHide) return
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
            val stillHidden = synchronized(this) {
                startedActivities.isEmpty() && hideGeneration == generation
            }
            if (stillHidden) LocalTransferEngine.setUiVisible(false)
        }, 350L)
    }

    override fun onActivityCreated(activity: android.app.Activity, state: android.os.Bundle?) = Unit
    override fun onActivityResumed(activity: android.app.Activity) = Unit
    override fun onActivityPaused(activity: android.app.Activity) = Unit
    override fun onActivitySaveInstanceState(activity: android.app.Activity, state: android.os.Bundle) = Unit
    override fun onActivityDestroyed(activity: android.app.Activity) {
        synchronized(this) { startedActivities.remove(activity) }
    }
}

object BackgroundRuntime {
    @Volatile var status: String = "Stopped"
        private set
    private var appContext: Context? = null
    private var shizuku: ShizukuManager? = null
    private var network: NetworkEngine? = null
    private var clipboard: ClipboardBridge? = null

    // This one-shot scheduler exists only for the explicit compatibility mode
    // after hidden-listener registration has actually failed. Supported devices
    // never create it and therefore perform zero routine clipboard reads.
    private var listenerRegistrationSucceeded: Boolean? = null
    private var fallbackExecutor: ScheduledExecutorService? = null
    private var fallbackTask: ScheduledFuture<*>? = null
    private var fallbackDelayMs = 1_000L
    private var fallbackScreenReceiver: android.content.BroadcastReceiver? = null

    @Synchronized fun start(context: Context) {
        val app = context.applicationContext
        if (SettingsStore(app).receiveFilesInBackground) LocalTransferEngine.start(app) else LocalTransferEngine.stop()
        ClipMeshUiVisibility.install(context)
        val settings = SettingsStore(app)
        if (!settings.backgroundSync) { status = "Clipboard sync off - nearby file receive ready"; return }
        val space = settings.spaceId
        val key = SecretStore(app).loadSpaceKey()
        if (space == null || key == null) { status = "Not paired - nearby file receive ready"; return }
        if (network != null && clipboard != null) return

        appContext = app
        val sh = ShizukuManager.acquireRuntime(app)
        lateinit var bridge: ClipboardBridge
        val net = NetworkEngine(settings, key, { payload ->
            if (BuildConfig.DEBUG) {
                app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                    .putLong("last_remote_received_at", System.currentTimeMillis())
                    .putString("last_remote_received_fingerprint", payload.stableFingerprint())
                    .apply()
            }
            bridge.applyRemote(payload)
        }, { text ->
            status = text
            reconcileClipboardFallback(resetBackoff = true)
        })
        bridge = ClipboardBridge(app, settings, sh) { payload ->
            if (BuildConfig.DEBUG) {
                app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                    .putLong("last_outgoing_at", System.currentTimeMillis())
                    .putInt("last_outgoing_representation_count", payload.representations.size)
                    .apply()
            }
            net.sendClipboard(payload)
        }
        shizuku = sh; network = net; clipboard = bridge
        bridge.start(); net.start()
        sh.setClipboardChangeListener(
            listener = { bridge.captureNowForSystemEvent() },
            onRegistrationChanged = { registered -> onClipboardListenerRegistration(app, registered) },
        )
        status = if (sh.hasPermission()) "Clipboard sync ready" else "Shizuku permission needed for background clipboard"
    }

    @Synchronized
    private fun onClipboardListenerRegistration(context: Context, registered: Boolean?) {
        listenerRegistrationSucceeded = registered
        if (registered != false) {
            stopClipboardFallback()
            return
        }
        ensureFallbackScreenReceiver(context)
        reconcileClipboardFallback(resetBackoff = true)
    }

    @Synchronized
    private fun ensureFallbackScreenReceiver(context: Context) {
        if (fallbackScreenReceiver != null) return
        val receiver = object : android.content.BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: android.content.Intent?) {
                when (intent?.action) {
                    android.content.Intent.ACTION_SCREEN_ON -> reconcileClipboardFallback(resetBackoff = true)
                    android.content.Intent.ACTION_SCREEN_OFF -> reconcileClipboardFallback(resetBackoff = false)
                }
            }
        }
        val filter = android.content.IntentFilter().apply {
            addAction(android.content.Intent.ACTION_SCREEN_ON)
            addAction(android.content.Intent.ACTION_SCREEN_OFF)
        }
        val registered = runCatching {
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("DEPRECATION")
                context.registerReceiver(receiver, filter)
            }
        }.isSuccess
        if (registered) fallbackScreenReceiver = receiver
    }

    @Synchronized
    private fun fallbackEligible(): Boolean {
        val app = appContext ?: return false
        val settings = SettingsStore(app)
        val power = app.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        return listenerRegistrationSucceeded == false &&
            settings.backgroundSync && settings.compatibilityWatchdog && settings.sendEnabled &&
            power.isInteractive && (network?.peerCount() ?: 0) > 0 && shizuku?.hasPermission() == true
    }

    @Synchronized
    private fun reconcileClipboardFallback(resetBackoff: Boolean) {
        if (!fallbackEligible()) {
            fallbackTask?.cancel(false)
            fallbackTask = null
            return
        }
        if (resetBackoff) {
            fallbackDelayMs = 1_000L
            fallbackTask?.cancel(false)
            fallbackTask = null
        }
        if (fallbackTask?.isDone == false) return
        val executor = fallbackExecutor ?: java.util.concurrent.Executors.newSingleThreadScheduledExecutor { task ->
            Thread(task, "ClipMesh-ClipboardCompatibility").apply { isDaemon = true }
        }.also { fallbackExecutor = it }
        val scheduledDelay = fallbackDelayMs
        fallbackTask = executor.schedule({
            val shouldCapture = synchronized(BackgroundRuntime) {
                fallbackTask = null
                fallbackEligible()
            }
            if (shouldCapture) clipboard?.captureNowForCompatibilityFallback()
            synchronized(BackgroundRuntime) {
                fallbackDelayMs = (scheduledDelay * 2L).coerceAtMost(5_000L)
                reconcileClipboardFallback(resetBackoff = false)
            }
        }, scheduledDelay, TimeUnit.MILLISECONDS)
    }

    @Synchronized
    private fun stopClipboardFallback() {
        fallbackTask?.cancel(false)
        fallbackTask = null
        fallbackExecutor?.shutdownNow()
        fallbackExecutor = null
        fallbackDelayMs = 1_000L
        val app = appContext
        val receiver = fallbackScreenReceiver
        fallbackScreenReceiver = null
        if (app != null && receiver != null) runCatching { app.unregisterReceiver(receiver) }
    }

    private fun stopClipboardRuntime() {
        listenerRegistrationSucceeded = null
        stopClipboardFallback()
        appContext = null
        clipboard?.stop(); clipboard = null
        network?.stop(); network = null
        shizuku?.close(); shizuku = null
    }

    @Synchronized fun stop() {
        stopClipboardRuntime()
        LocalTransferEngine.stop()
        status = "Stopped"
    }

    @Synchronized fun restart(context: Context) {
        stopClipboardRuntime()
        status = "Stopped"
        start(context)
    }

    @Synchronized fun captureNow() {
        clipboard?.captureNowForUserAction()
        if (listenerRegistrationSucceeded == false) reconcileClipboardFallback(resetBackoff = true)
    }
    @Synchronized fun captureAccessibility() {
        clipboard?.captureNowForAccessibilityEvent()
        if (listenerRegistrationSucceeded == false) reconcileClipboardFallback(resetBackoff = true)
    }
    fun captureInjectedForTest(clip: android.content.ClipData) {
        if (BuildConfig.DEBUG) clipboard?.captureInjectedForTest(clip)
    }
    fun debugPeerCount(): Int = network?.peerCount() ?: 0
    fun debugShizukuBound(): Boolean = shizuku?.isBound() == true
    fun debugClipboardListenerRegistered(): Boolean = shizuku?.isClipboardListenerRegistered() == true
}
''', encoding="utf-8")

    old_manager = manager.read_text(encoding="utf-8")
    require(old_manager, 'latch.await(3, TimeUnit.SECONDS)', "blocking Shizuku connection")
    require(old_manager, '.tag("clipmesh-clipboard-event-v1")', "v049 service tag")
    manager.write_text(r'''package dev.clipmesh.shizuku

import android.content.ComponentName
import android.content.Context
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Binder
import android.os.IBinder
import android.os.ParcelFileDescriptor
import dev.clipmesh.BuildConfig
import rikka.shizuku.Shizuku
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The single process-wide production owner of ClipMesh's privileged clipboard
 * UserService. Binding and reconnect are event driven; clipboard callers never
 * wait for a connection.
 */
class ShizukuManager private constructor(
    context: Context,
    private val testConnection: Boolean,
) {
    companion object {
        const val REQUEST_CODE_PERMISSION = 8844
        private val runtimeLock = Any()
        @Volatile private var runtimeOwner: ShizukuManager? = null

        fun acquireRuntime(context: Context): ShizukuManager = synchronized(runtimeLock) {
            runtimeOwner?.takeUnless { it.closed } ?: ShizukuManager(context.applicationContext, false).also {
                runtimeOwner = it
            }
        }

        fun forTest(context: Context): ShizukuManager =
            ShizukuManager(context.applicationContext, true).also { it.requestBinding() }

        fun isShizukuAvailable(): Boolean =
            runCatching { Shizuku.pingBinder() }.getOrDefault(false)

        fun hasShizukuPermission(): Boolean = isShizukuAvailable() && runCatching {
            !Shizuku.isPreV11() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
        }.getOrDefault(false)

        fun requestShizukuPermission(): Boolean {
            if (!isShizukuAvailable()) return false
            if (runCatching { Shizuku.isPreV11() }.getOrDefault(true)) return false
            if (hasShizukuPermission()) return true
            if (runCatching { Shizuku.shouldShowRequestPermissionRationale() }.getOrDefault(false)) return false
            return runCatching {
                Shizuku.requestPermission(REQUEST_CODE_PERMISSION)
                true
            }.getOrDefault(false)
        }

        private fun releaseRuntime(owner: ShizukuManager) = synchronized(runtimeLock) {
            if (runtimeOwner === owner) runtimeOwner = null
        }
    }

    private val callerToken = Binder()
    private val connectionExecutor = Executors.newSingleThreadExecutor { task ->
        Thread(task, if (testConnection) "ClipMesh-ShizukuTest" else "ClipMesh-ShizukuConnection").apply { isDaemon = true }
    }
    private val pendingClipboardCapture = AtomicBoolean(false)
    private val testConnected = CountDownLatch(1)
    @Volatile private var service: IClipboardUserService? = null
    @Volatile private var binding = false
    @Volatile private var binderAvailable = false
    @Volatile private var permissionGranted = false
    @Volatile internal var closed = false
    @Volatile private var clipboardChangeListener: (() -> Unit)? = null
    @Volatile private var registrationListener: ((Boolean?) -> Unit)? = null
    @Volatile private var listenerRegistered: Boolean? = null

    private val args: Shizuku.UserServiceArgs by lazy {
        Shizuku.UserServiceArgs(ComponentName(context.packageName, ClipboardUserService::class.java.name))
            .daemon(false)
            .processNameSuffix(if (testConnection) "clipboard-test" else "clipboard")
            .tag(if (testConnection) "clipmesh-clipboard-test-v2" else "clipmesh-clipboard-event-v2")
            .debuggable(BuildConfig.DEBUG)
            .version(12)
    }

    private val clipboardChangedCallback = object : IClipboardChangedCallback.Stub() {
        override fun onClipboardChanged() {
            // This is a oneway edge. ClipboardBridge only flips/enqueues capture
            // state here; all clipboard parsing and I/O runs on its worker.
            clipboardChangeListener?.invoke()
        }
    }

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            binding = false
            val connected = binder?.takeIf { it.isBinderAlive }?.let(IClipboardUserService.Stub::asInterface)
            service = connected
            if (connected == null) {
                listenerRegistered = null
                registrationListener?.invoke(null)
                testConnected.countDown()
                return
            }
            connectionExecutor.execute {
                if (closed || service !== connected) return@execute
                val registered = runCatching {
                    connected.init(callerToken)
                    if (clipboardChangeListener != null) {
                        connected.setClipboardChangedCallback(clipboardChangedCallback)
                        connected.isClipboardListenerRegistered()
                    } else null
                }.getOrElse { false }
                listenerRegistered = registered
                registrationListener?.invoke(registered)
                testConnected.countDown()
                if (pendingClipboardCapture.getAndSet(false)) clipboardChangeListener?.invoke()
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            binding = false
            service = null
            listenerRegistered = null
            if (clipboardChangeListener != null) pendingClipboardCapture.set(true)
            registrationListener?.invoke(null)
            testConnected.countDown()
            if (!closed && serviceRequired()) requestBinding()
        }
    }

    private val permissionListener = Shizuku.OnRequestPermissionResultListener { requestCode, result ->
        if (requestCode != REQUEST_CODE_PERMISSION) return@OnRequestPermissionResultListener
        permissionGranted = result == PackageManager.PERMISSION_GRANTED
        if (permissionGranted && serviceRequired()) requestBinding()
    }

    private val binderReceivedListener = Shizuku.OnBinderReceivedListener {
        binderAvailable = true
        permissionGranted = currentPermissionGranted()
        if (permissionGranted && serviceRequired()) requestBinding()
    }

    private val binderDeadListener = Shizuku.OnBinderDeadListener {
        binderAvailable = false
        permissionGranted = false
        binding = false
        service = null
        listenerRegistered = null
        if (clipboardChangeListener != null) pendingClipboardCapture.set(true)
        registrationListener?.invoke(null)
        testConnected.countDown()
    }

    init {
        Shizuku.addRequestPermissionResultListener(permissionListener)
        Shizuku.addBinderReceivedListenerSticky(binderReceivedListener)
        Shizuku.addBinderDeadListener(binderDeadListener)
        binderAvailable = isShizukuAvailable()
        permissionGranted = currentPermissionGranted()
        // Deliberately do not bind here. Only the process runtime or an explicit
        // test acquisition is allowed to create a UserService.
    }

    fun isAvailable(): Boolean {
        if (closed) return false
        binderAvailable = isShizukuAvailable()
        if (!binderAvailable) {
            permissionGranted = false
            service = null
        }
        return binderAvailable
    }

    fun hasPermission(): Boolean {
        if (closed) return false
        permissionGranted = hasShizukuPermission()
        return permissionGranted
    }

    fun isBound(): Boolean = service?.let { current ->
        runCatching { current.asBinder().isBinderAlive }.getOrDefault(false)
    } == true

    fun isClipboardListenerRegistered(): Boolean = listenerRegistered == true

    fun setClipboardChangeListener(
        listener: (() -> Unit)?,
        onRegistrationChanged: ((Boolean?) -> Unit)? = null,
    ) {
        clipboardChangeListener = listener
        registrationListener = onRegistrationChanged
        if (listener == null) {
            runCatching { service?.setClipboardChangedCallback(null) }
            listenerRegistered = null
            onRegistrationChanged?.invoke(null)
        } else {
            requestBinding()
            service?.let { connected -> initializeClipboardListener(connected) }
        }
    }

    private fun initializeClipboardListener(connected: IClipboardUserService) {
        connectionExecutor.execute {
            if (closed || service !== connected || clipboardChangeListener == null) return@execute
            val registered = runCatching {
                connected.setClipboardChangedCallback(clipboardChangedCallback)
                connected.isClipboardListenerRegistered()
            }.getOrDefault(false)
            listenerRegistered = registered
            registrationListener?.invoke(registered)
        }
    }

    fun readSnapshotJson(): String {
        val connected = serviceOrRequest(pendingCapture = true) ?: return ""
        return runCatching { connected.primaryClipJson.orEmpty() }.getOrDefault("")
    }

    fun copyItem(index: Int, destination: File): Boolean {
        val connected = serviceOrRequest(pendingCapture = true) ?: return false
        destination.parentFile?.mkdirs()
        val descriptor = ParcelFileDescriptor.open(
            destination,
            ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE,
        )
        return try {
            connected.copyPrimaryClipItemToFile(index, descriptor)
        } catch (_: Exception) {
            false
        } finally {
            descriptor.close()
        }
    }

    fun readLatestScreenshotJson(): String {
        val connected = serviceOrRequest(pendingCapture = true) ?: return ""
        return runCatching { connected.latestScreenshotJson.orEmpty() }.getOrDefault("")
    }

    fun copyUri(uri: android.net.Uri, destination: File): Boolean {
        val connected = serviceOrRequest(pendingCapture = true) ?: return false
        destination.parentFile?.mkdirs()
        val descriptor = ParcelFileDescriptor.open(
            destination,
            ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE,
        )
        return try {
            connected.copyUriToFile(uri.toString(), descriptor)
        } catch (_: Exception) {
            false
        } finally {
            descriptor.close()
        }
    }

    fun setText(text: String): Boolean {
        val connected = serviceOrRequest(pendingCapture = false) ?: return false
        return runCatching { connected.setPrimaryClipText(text) }.getOrDefault(false)
    }

    /** Test-only blocking gate. Debug callers invoke this from a dedicated worker. */
    fun awaitConnectedForTest(timeoutMs: Long = 3_000L): Boolean {
        check(testConnection) { "Only explicit test connections may wait" }
        requestBinding()
        if (isBound()) return true
        runCatching { testConnected.await(timeoutMs, TimeUnit.MILLISECONDS) }
        return isBound()
    }

    /** Remove only ClipMesh's UserService. Never stop the Shizuku server. */
    fun close() {
        if (closed) return
        closed = true
        // setClipboardChangedCallback(null) unregisters the hidden system listener
        // inside the UserService before Shizuku invokes its reserved destroy call.
        runCatching { service?.setClipboardChangedCallback(null) }
        clipboardChangeListener = null
        registrationListener = null
        listenerRegistered = null
        runCatching { Shizuku.removeRequestPermissionResultListener(permissionListener) }
        runCatching { Shizuku.removeBinderReceivedListener(binderReceivedListener) }
        runCatching { Shizuku.removeBinderDeadListener(binderDeadListener) }
        runCatching { Shizuku.unbindUserService(args, connection, true) }
        service = null
        binding = false
        pendingClipboardCapture.set(false)
        connectionExecutor.shutdownNow()
        if (!testConnection) releaseRuntime(this)
    }

    private fun serviceRequired(): Boolean = testConnection || clipboardChangeListener != null

    private fun currentPermissionGranted(): Boolean = runCatching {
        isShizukuAvailable() && !Shizuku.isPreV11() &&
            Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    @Synchronized
    private fun requestBinding() {
        if (closed || !serviceRequired() || service != null || binding) return
        binding = true
        connectionExecutor.execute {
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
            runCatching { Shizuku.bindUserService(args, connection) }.onFailure {
                binding = false
                listenerRegistered = null
                registrationListener?.invoke(null)
                testConnected.countDown()
            }
        }
    }

    private fun serviceOrRequest(pendingCapture: Boolean): IClipboardUserService? {
        service?.takeIf { runCatching { it.asBinder().isBinderAlive }.getOrDefault(false) }?.let { return it }
        service = null
        if (pendingCapture) pendingClipboardCapture.set(true)
        requestBinding()
        return null
    }
}
''', encoding="utf-8")

    aidl.write_text(r'''package dev.clipmesh.shizuku;

import dev.clipmesh.shizuku.IClipboardChangedCallback;

import android.os.IBinder;
import android.os.ParcelFileDescriptor;

interface IClipboardUserService {
    // Shizuku's reserved destroy transaction. Keep this exact explicit ID.
    void destroy() = 16777114;

    void init(in IBinder callerToken) = 1;
    String getPrimaryClipJson() = 2;
    boolean copyPrimaryClipItemToFile(int index, in ParcelFileDescriptor destination) = 3;
    String getLatestScreenshotJson() = 4;
    boolean copyUriToFile(String uri, in ParcelFileDescriptor destination) = 5;
    boolean setPrimaryClipText(String text) = 6;
    void setClipboardChangedCallback(IClipboardChangedCallback callback) = 7;
    boolean isClipboardListenerRegistered() = 8;
}
''', encoding="utf-8")

    replace_once(
        user_service,
        "    @Volatile private var hiddenClipboardListener: Any? = null\n",
        "    @Volatile private var hiddenClipboardListener: Any? = null\n    @Volatile private var listenerRegistrationSucceeded = false\n",
        "listener registration state",
    )
    replace_once(
        user_service,
        "    // The platform listener is oneway. Do no clipboard parsing, disk work or\n    // network work on this Binder thread; enqueue the tiny edge notification.\n",
        "    // The platform listener performs only one oneway AIDL edge notification.\n    // Clipboard parsing, disk, network and hashing never run on this Binder thread.\n",
        "system listener callback contract",
    )
    old_listener_methods = r'''    override fun setClipboardChangedCallback(callback: IClipboardChangedCallback?) {
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
'''
    new_listener_methods = r'''    override fun setClipboardChangedCallback(callback: IClipboardChangedCallback?) {
        clipboardChangedCallback = callback
        if (callback == null) unregisterSystemClipboardListener() else ensureSystemClipboardListener()
    }

    override fun isClipboardListenerRegistered(): Boolean = listenerRegistrationSucceeded

    @Synchronized
    private fun ensureSystemClipboardListener() {
        if (hiddenClipboardListener != null) {
            listenerRegistrationSucceeded = true
            return
        }
        listenerRegistrationSucceeded = runCatching {
            val sm = Class.forName("android.os.ServiceManager")
            val binder = sm.getMethod("getService", String::class.java).invoke(null, "clipboard") as? IBinder
                ?: return@runCatching false
            val stub = Class.forName("android.content.IClipboard\$Stub")
            val target = stub.getMethod("asInterface", IBinder::class.java).invoke(null, binder)
                ?: return@runCatching false
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
            } ?: return@runCatching false
            val args = hiddenClipboardArgs(add.parameterTypes, listenerClass, listener)
            add.isAccessible = true
            val identity = Binder.clearCallingIdentity()
            try { add.invoke(target, *args) } finally { Binder.restoreCallingIdentity(identity) }
            hiddenClipboardService = target
            hiddenClipboardListener = listener
            Log.i(TAG, "Registered event-driven shell clipboard listener")
            true
        }.onFailure {
            Log.w(TAG, "Could not register event-driven clipboard listener", it)
        }.getOrDefault(false)
    }

    @Synchronized
    private fun unregisterSystemClipboardListener() {
        val target = hiddenClipboardService
        val listener = hiddenClipboardListener
        if (target != null && listener != null) runCatching {
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
        listenerRegistrationSucceeded = false
    }
'''
    replace_once(user_service, old_listener_methods, new_listener_methods, "listener registration lifecycle")
    replace_once(
        user_service,
        '''    override fun destroy() {
        unregisterSystemClipboardListener()
        clipboardChangedCallback = null
        lastClip = null
        clipboardService = null
    }
''',
        '''    override fun destroy() {
        runCatching { unregisterSystemClipboardListener() }
        clipboardChangedCallback = null
        lastClip = null
        clipboardService = null
        System.exit(0)
    }
''',
        "reserved UserService destroy",
    )

    bridge_text = bridge.read_text(encoding="utf-8")
    require(bridge_text, "private val capturePending = AtomicBoolean(false)", "capture coalescer")
    bridge_text = bridge_text.replace("import dev.clipmesh.SettingsStore\n", "import dev.clipmesh.SettingsStore\nimport dev.clipmesh.ClipMeshUiVisibility\n", 1)
    bridge_text = bridge_text.replace(
        "    private val accessibilityClip = AtomicReference<ClipData?>(null)\n",
        "    private val debugInjectedClip = AtomicReference<ClipData?>(null)\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "    private val capturePending = AtomicBoolean(false)\n",
        "    private val capturePending = AtomicBoolean(false)\n    private val screenshotProbePending = AtomicBoolean(false)\n",
        1,
    )
    bridge_text = bridge_text.replace("    private var started = false\n", "    @Volatile private var started = false\n", 1)
    bridge_text = bridge_text.replace(
        "    private val listener = ClipboardManager.OnPrimaryClipChangedListener { captureAsync(fromWatchdog = false) }\n",
        "    private val listener = ClipboardManager.OnPrimaryClipChangedListener { signalClipboardCapture() }\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }\n",
        "        ForegroundTracker.clipboardChanged = { signalClipboardCapture() }\n",
        1,
    )
    bridge_text = bridge_text.replace(
        '''    private val screenshotObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) {
            probeLatestScreenshotIfDue()
        }
    }
''',
        '''    private val screenshotObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) {
            signalClipboardCapture(includeScreenshotProbe = true)
        }
    }
''',
        1,
    )
    old_capture_api = r'''    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)
    fun captureNowForBackgroundMonitor() = captureAsync(fromWatchdog = true)
    fun captureNowForForeground() {
        captureAsync(fromWatchdog = true)
        // Samsung/Gboard records screenshots in MediaStore without changing the
        // system clipboard and does not notify observers lacking broad gallery
        // permission. Reuse the already-running interactive watchdog as a
        // low-frequency Shizuku wake-up; persisted media IDs make it one-shot.
        probeLatestScreenshotIfDue()
    }
    fun captureNowForAccessibility(clip: ClipData? = null) {
        if (clip != null) accessibilityClip.set(clip)
        captureAsync(fromWatchdog = false)
    }

    private fun captureAsync(fromWatchdog: Boolean) {
'''
    new_capture_api = r'''    fun captureNowForSystemEvent() = signalClipboardCapture(includeScreenshotProbe = true)

    fun captureNowForUserAction() = signalClipboardCapture(includeScreenshotProbe = true)

    fun captureNowForAccessibilityEvent() = signalClipboardCapture()
    fun captureNowForCompatibilityFallback() = signalClipboardCapture()
    fun captureInjectedForTest(clip: ClipData) {
        if (!dev.clipmesh.BuildConfig.DEBUG) return
        debugInjectedClip.set(clip)
        signalClipboardCapture()
    }

    private fun signalClipboardCapture(includeScreenshotProbe: Boolean = false) {
        if (includeScreenshotProbe) screenshotProbePending.set(true)
'''
    if bridge_text.count(old_capture_api) != 1:
        raise SystemExit("ClipboardBridge capture API anchor changed")
    bridge_text = bridge_text.replace(old_capture_api, new_capture_api, 1)
    bridge_text = bridge_text.replace(
        "                val observation = readCurrent(sourcePackage, accessibilityClip.getAndSet(null)) ?: return@execute\n",
        "                val observation = readCurrent(sourcePackage) ?: return@execute\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "                    main.postDelayed({ captureAsync(fromWatchdog = false) }, 90L)\n",
        "                    main.postDelayed({ signalClipboardCapture() }, 90L)\n",
        1,
    )
    old_capture_worker = r'''    private fun signalClipboardCapture(includeScreenshotProbe: Boolean = false) {
        if (includeScreenshotProbe) screenshotProbePending.set(true)
        if (!started || !settings.sendEnabled) return
        val sourcePackage = ForegroundTracker.currentPackage
        // Never exclude our own foreground window. The clipboard may have changed
        // just before the user returned to ClipMesh, and fingerprint suppression is
        // the correct mechanism for preventing remote echo loops.
        if (sourcePackage != null && sourcePackage != context.packageName && settings.excludedPackages.contains(sourcePackage)) return
        if (!captureInFlight.compareAndSet(false, true)) {
            capturePending.set(true)
            return
        }
        captureExecutor.execute {
            try {
                val observation = readCurrent(sourcePackage) ?: return@execute
                val payload = observation.payload
                if (isPairingPayload(payload)) return@execute
                val fp = payload.stableFingerprint()
                // ClipDescription.timestamp identifies the actual clipboard SET
                // operation. Watchdogs and duplicate OEM callbacks for that same
                // event must never create new transport messages. If an OEM omits
                // timestamps, canonical content remains the safe fallback.
                val eventKey = if (observation.generation > 0L) {
                    "generation:${observation.generation}:$fp"
                } else {
                    "fingerprint:$fp"
                }
                if (suppressedFingerprint.compareAndSet(fp, null)) {
                    recordObservedEvent(eventKey)
                    recordVisibleContent(echoFingerprint(payload))
                    return@execute
                }
                if (lastObservedClipboardEvent.get() == eventKey) return@execute
                recordObservedEvent(eventKey)
                emitLocal(payload, fromScreenshot = false)
            } finally {
                captureInFlight.set(false)
                if (capturePending.getAndSet(false) && started) {
                    main.postDelayed({ signalClipboardCapture() }, 90L)
                }
            }
        }
    }
'''
    new_capture_worker = r'''    private fun signalClipboardCapture(includeScreenshotProbe: Boolean = false) {
        if (includeScreenshotProbe) screenshotProbePending.set(true)
        if (!started) return
        if (!captureInFlight.compareAndSet(false, true)) {
            capturePending.set(true)
            return
        }
        runCatching {
            captureExecutor.execute {
                try {
                    // Callback threads do only atomics plus this enqueue. Settings,
                    // exclusions, IPC, parsing, hashing, persistence and network
                    // work all starts on this one serialized capture worker.
                    if (!started || !settings.sendEnabled) return@execute
                    if (screenshotProbePending.getAndSet(false)) probeLatestScreenshotIfDue()
                    val sourcePackage = ForegroundTracker.currentPackage
                    if (sourcePackage != null && sourcePackage != context.packageName &&
                        settings.excludedPackages.contains(sourcePackage)
                    ) return@execute
                    val observation = readCurrent(sourcePackage) ?: return@execute
                    val payload = observation.payload
                    if (isPairingPayload(payload)) return@execute
                    val fp = payload.stableFingerprint()
                    val eventKey = if (observation.generation > 0L) {
                        "generation:${observation.generation}:$fp"
                    } else {
                        "fingerprint:$fp"
                    }
                    if (suppressedFingerprint.compareAndSet(fp, null)) {
                        recordObservedEvent(eventKey)
                        recordVisibleContent(echoFingerprint(payload))
                        return@execute
                    }
                    if (lastObservedClipboardEvent.get() == eventKey) return@execute
                    recordObservedEvent(eventKey)
                    emitLocal(payload, fromScreenshot = false)
                } finally {
                    captureInFlight.set(false)
                    if (capturePending.getAndSet(false) && started) {
                        main.postDelayed({ signalClipboardCapture() }, 90L)
                    }
                }
            }
        }.onFailure {
            captureInFlight.set(false)
        }
    }
'''
    if bridge_text.count(old_capture_worker) != 1:
        raise SystemExit("ClipboardBridge worker-only capture anchor changed")
    bridge_text = bridge_text.replace(old_capture_worker, new_capture_worker, 1)
    old_read = r'''    private fun readCurrent(sourcePackage: String?, preferredClip: ClipData? = null): ClipboardObservation? {
        // AccessibilityService is the most reliable source for copied gallery and
        // screenshot URIs because it receives the URI grant with the event.
        preferredClip?.let { clip ->
            readClipData(clip, sourcePackage)?.let { payload ->
                return ClipboardObservation(payload, clip.description.timestamp)
            }
        }
        // Shizuku remains the fallback for OEMs that restrict app clipboard reads.
        val shizukuJson = if (shizuku.hasPermission()) shizuku.readSnapshotJson() else ""
        if (shizukuJson.isNotBlank()) {
            val snapshot = runCatching { JSONObject(shizukuJson) }.getOrNull()
            readShizukuSnapshot(shizukuJson, sourcePackage)?.let { payload ->
                return ClipboardObservation(payload, snapshot?.optLong("timestamp", 0L) ?: 0L)
            }
        }

        // Fallback works while ClipMesh has input focus and on some OEM combinations.
        return clipboard.primaryClip?.let { clip ->
            readClipData(clip, sourcePackage)?.let { payload ->
                ClipboardObservation(payload, clip.description.timestamp)
            }
        }
    }
'''
    new_read = r'''    private fun readCurrent(sourcePackage: String?): ClipboardObservation? {
        if (dev.clipmesh.BuildConfig.DEBUG) {
            debugInjectedClip.getAndSet(null)?.let { clip ->
                readClipData(clip, sourcePackage)?.let { payload ->
                    return ClipboardObservation(payload, clip.description.timestamp)
                }
            }
        }
        // Every background read goes through the shell-identity UserService. If it
        // is reconnecting, ShizukuManager records one pending edge and returns.
        val shizukuJson = shizuku.readSnapshotJson()
        if (shizukuJson.isNotBlank()) {
            val snapshot = runCatching { JSONObject(shizukuJson) }.getOrNull()
            readShizukuSnapshot(shizukuJson, sourcePackage)?.let { payload ->
                return ClipboardObservation(payload, snapshot?.optLong("timestamp", 0L) ?: 0L)
            }
        }

        // Android 10+ denies normal-UID clipboard reads in the background. This
        // fallback is strictly limited to a foreground ClipMesh activity.
        if (!ClipMeshUiVisibility.isForeground()) return null
        return clipboard.primaryClip?.let { clip ->
            readClipData(clip, sourcePackage)?.let { payload ->
                ClipboardObservation(payload, clip.description.timestamp)
            }
        }
    }
'''
    if bridge_text.count(old_read) != 1:
        raise SystemExit("ClipboardBridge background-read anchor changed")
    bridge_text = bridge_text.replace(old_read, new_read, 1)
    for forbidden in ("fromWatchdog", "captureNowForWatchdog", "captureNowForBackgroundMonitor", "accessibilityClip"):
        if forbidden in bridge_text:
            raise SystemExit(f"ClipboardBridge obsolete polling path survived: {forbidden}")
    bridge.write_text(bridge_text, encoding="utf-8")

    accessibility.write_text(r'''package dev.clipmesh.exclusion

import android.accessibilityservice.AccessibilityService
import android.content.ClipboardManager
import android.view.accessibility.AccessibilityEvent
import dev.clipmesh.BackgroundRuntime
import dev.clipmesh.BackgroundService

/** Source-app tracking plus an optional clipboard edge source. The callback never
 * reads ClipboardManager; privileged bytes are captured by ClipboardUserService. */
class ExclusionAccessibilityService : AccessibilityService() {
    private var clipboard: ClipboardManager? = null
    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        BackgroundRuntime.start(this)
        BackgroundRuntime.captureAccessibility()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        ForegroundTracker.accessibilityConnected = true
        BackgroundService.start(this)
        clipboard = getSystemService(ClipboardManager::class.java)
        clipboard?.addPrimaryClipChangedListener(clipboardListener)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val pkg = event?.packageName?.toString()
        if (!pkg.isNullOrBlank()) ForegroundTracker.currentPackage = pkg
    }

    override fun onDestroy() {
        ForegroundTracker.accessibilityConnected = false
        clipboard?.removePrimaryClipChangedListener(clipboardListener)
        clipboard = null
        super.onDestroy()
    }

    override fun onInterrupt() = Unit
}
''', encoding="utf-8")

    settings_text = settings.read_text(encoding="utf-8")
    settings_text = settings_text.replace("    private lateinit var shizuku: ShizukuManager\n", "", 1)
    settings_text = settings_text.replace("        shizuku = ShizukuManager(this)\n", "", 1)
    settings_text = settings_text.replace("        shizuku.close()\n", "", 1)
    old_button = r'''        shizukuButton = button("Request Shizuku permission") {
            when {
                shizuku.isBound() -> toast("Shizuku is already connected")
                !shizuku.isAvailable() -> toast("Start or install Shizuku first")
                shizuku.hasPermission() -> { shizuku.requestPermission(); toast("Connecting ClipMesh to Shizuku…") }
                else -> if (!shizuku.requestPermission()) toast("Could not request Shizuku permission")
            }
            shizukuUiHandler.postDelayed({ refreshShizukuUi() }, 400L)
        }
'''
    new_button = r'''        shizukuButton = button("Request Shizuku permission") {
            when {
                BackgroundRuntime.debugShizukuBound() -> toast("Shizuku is already connected")
                !ShizukuManager.isShizukuAvailable() -> toast("Start or install Shizuku first")
                ShizukuManager.hasShizukuPermission() -> {
                    BackgroundRuntime.start(this)
                    toast(if (settingsStore.backgroundSync) "Connecting clipboard runtime…" else "Shizuku authorized; enable background sync to connect")
                }
                else -> if (!ShizukuManager.requestShizukuPermission()) toast("Could not request Shizuku permission")
            }
            shizukuUiHandler.postDelayed({ refreshShizukuUi() }, 400L)
        }
'''
    if settings_text.count(old_button) != 1:
        raise SystemExit("Settings Shizuku permission button anchor changed")
    settings_text = settings_text.replace(old_button, new_button, 1)
    old_refresh = r'''    private fun refreshShizukuUi() {
        when {
            shizuku.isBound() -> {
                shizukuStatus.text = "Connected - background clipboard access is ready"
                shizukuButton.text = "Shizuku connected"
                shizukuButton.isEnabled = false
            }
            shizuku.isAvailable() && shizuku.hasPermission() -> {
                shizukuStatus.text = "Authorized - connecting ClipMesh service…"
                shizukuButton.text = "Connect Shizuku"
                shizukuButton.isEnabled = true
                shizuku.requestPermission()
            }
            shizuku.isAvailable() -> {
                shizukuStatus.text = "Shizuku is running but ClipMesh is not authorized"
                shizukuButton.text = "Request Shizuku permission"
                shizukuButton.isEnabled = true
            }
            else -> {
                shizukuStatus.text = "Shizuku is not connected"
                shizukuButton.text = "Request Shizuku permission"
                shizukuButton.isEnabled = true
            }
        }
    }
'''
    new_refresh = r'''    private fun refreshShizukuUi() {
        when {
            BackgroundRuntime.debugShizukuBound() -> {
                shizukuStatus.text = "Connected - background clipboard access is ready"
                shizukuButton.text = "Shizuku connected"
                shizukuButton.isEnabled = false
            }
            ShizukuManager.isShizukuAvailable() && ShizukuManager.hasShizukuPermission() -> {
                shizukuStatus.text = if (settingsStore.backgroundSync) {
                    "Authorized - clipboard runtime will reconnect automatically"
                } else {
                    "Authorized - enable background sync when needed"
                }
                shizukuButton.text = "Shizuku authorized"
                shizukuButton.isEnabled = settingsStore.backgroundSync
            }
            ShizukuManager.isShizukuAvailable() -> {
                shizukuStatus.text = "Shizuku is running but ClipMesh is not authorized"
                shizukuButton.text = "Request Shizuku permission"
                shizukuButton.isEnabled = true
            }
            else -> {
                shizukuStatus.text = "Shizuku is not connected"
                shizukuButton.text = "Request Shizuku permission"
                shizukuButton.isEnabled = true
            }
        }
    }
'''
    if settings_text.count(old_refresh) != 1:
        raise SystemExit("Settings Shizuku status anchor changed")
    settings.write_text(settings_text.replace(old_refresh, new_refresh, 1), encoding="utf-8")

    # SyncService is retained as a compatibility entry point, but no longer owns
    # a network engine, Shizuku client, capture worker or recurring monitor.
    old_sync = sync_service.read_text(encoding="utf-8")
    require(old_sync, "delay(750L)", "legacy 750 ms clipboard monitor")
    sync_service.write_text(r'''package dev.clipmesh

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder

/** Legacy service entry point retained for old intents. The process-wide
 * BackgroundRuntime is the sole clipboard/Shizuku owner. */
class SyncService : Service() {
    companion object {
        const val ACTION_STOP = "dev.clipmesh.STOP"
        const val ACTION_CAPTURE_CURRENT = "dev.clipmesh.CAPTURE_CURRENT"
        private const val CHANNEL_ID = "clipmesh_sync_quiet_v019"
        private const val NOTIFICATION_ID = 41474
        @Volatile var status: String = "Stopped"
    }

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(NOTIFICATION_ID, notification("Starting encrypted LAN sync…"))
        BackgroundRuntime.start(this)
        status = BackgroundRuntime.status
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            SettingsStore(this).backgroundSync = false
            BackgroundRuntime.stop()
            stopSelf()
            return START_NOT_STICKY
        }
        BackgroundRuntime.start(this)
        if (intent?.action == ACTION_CAPTURE_CURRENT) BackgroundRuntime.captureNow()
        status = BackgroundRuntime.status
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        status = "Stopped"
        super.onDestroy()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "ClipMesh background sync", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Keeps the private LAN clipboard bridge available in the background"
                    setShowBadge(false)
                },
            )
        }
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, SyncService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_clipmesh_notification)
            .setContentTitle("ClipMesh")
            .setContentText(text)
            .setOngoing(true)
            .setShowWhen(false)
            .setPriority(Notification.PRIORITY_MIN)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(
                android.graphics.drawable.Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                "Stop",
                stop,
            ).build())
            .build()
    }
}
''', encoding="utf-8")

    debug_receiver = debug_java / "DevTestReceiver.kt"
    if debug_receiver.is_file():
        debug_text = debug_receiver.read_text(encoding="utf-8")
        debug_text, request_count = re.subn(
            r'''            ACTION_REQUEST_SHIZUKU -> \{.*?\n            ACTION_READ_SHIZUKU ->''',
            lambda _match: '''            ACTION_REQUEST_SHIZUKU -> {
                val requested = runCatching { ShizukuManager.requestShizukuPermission() }.getOrDefault(false)
                result(app, "requested=$requested\\n")
            }
            ACTION_READ_SHIZUKU ->''',
            debug_text,
            count=1,
            flags=re.S,
        )
        if request_count != 1:
            raise SystemExit("DevTestReceiver Shizuku permission action anchor changed")
        debug_text = debug_text.replace("        val shizuku = ShizukuManager(app)\n        val ci =", "        val ci =", 1)
        debug_text = debug_text.replace("append(\"shizuku_available=\").append(shizuku.isAvailable())", "append(\"shizuku_available=\").append(ShizukuManager.isShizukuAvailable())", 1)
        debug_text = debug_text.replace("append(\"shizuku_permission=\").append(shizuku.hasPermission())", "append(\"shizuku_permission=\").append(ShizukuManager.hasShizukuPermission())", 1)
        debug_text = debug_text.replace("        result(app, text)\n        shizuku.close()\n", "        result(app, text)\n", 1)
        debug_text = debug_text.replace("val shizuku = ShizukuManager(app)", "val shizuku = ShizukuManager.forTest(app)")
        debug_text = debug_text.replace(
            "            try {\n                val snapshot = shizuku.readSnapshotJson()\n",
            "            try {\n                val connected = shizuku.awaitConnectedForTest()\n                val snapshot = if (connected) shizuku.readSnapshotJson() else \"\"\n",
            1,
        )
        debug_text = debug_text.replace(
            "            try {\n                val pass = expected.isNotEmpty() && shizuku.setText(expected)\n",
            "            try {\n                val connected = shizuku.awaitConnectedForTest()\n                val pass = connected && expected.isNotEmpty() && shizuku.setText(expected)\n",
            1,
        )
        if "ShizukuManager(app)" in debug_text:
            raise SystemExit("DevTestReceiver still constructs a production Shizuku owner")
        debug_receiver.write_text(debug_text, encoding="utf-8")

    ci_capture = debug_java / "CiBackgroundCaptureReceiver.kt"
    if ci_capture.is_file():
        replace_once(
            ci_capture,
            '        BackgroundRuntime.captureAccessibility(ClipData.newPlainText("ClipMesh CI", text))\n',
            '        BackgroundRuntime.captureInjectedForTest(ClipData.newPlainText("ClipMesh CI", text))\n',
            "debug background capture injection",
        )

    runpy.run_path(str(ROOT / "ci/v052_android_clipboard_runtime_selftest.py"), run_name="__main__")

print(f"Applied ClipMesh v052 Android clipboard runtime repair on {SYSTEM}")
