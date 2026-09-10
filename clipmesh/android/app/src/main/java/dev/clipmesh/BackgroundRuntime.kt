package dev.clipmesh

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
