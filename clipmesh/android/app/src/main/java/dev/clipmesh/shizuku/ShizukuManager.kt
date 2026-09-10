package dev.clipmesh.shizuku

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
