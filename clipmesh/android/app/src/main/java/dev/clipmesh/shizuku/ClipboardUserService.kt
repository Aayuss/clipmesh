package dev.clipmesh.shizuku

import android.app.Application
import android.content.ClipData
import android.content.ClipDescription
import android.net.Uri
import android.os.Build
import android.os.Binder
import android.os.IBinder
import android.os.Parcel
import android.os.ParcelFileDescriptor
import android.os.PersistableBundle
import android.provider.OpenableColumns
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.FileOutputStream
import java.lang.reflect.Proxy

/**
 * Adapted from UniClipboard/UniClip's MIT-licensed shizuku-clipboard module.
 * See THIRD_PARTY_NOTICES.md and licenses/UNICLIP-MIT.txt in the repository root.
 */
class ClipboardUserService : IClipboardUserService.Stub() {
    @Volatile private var clipboardChangedCallback: IClipboardChangedCallback? = null
    @Volatile private var hiddenClipboardService: Any? = null
    @Volatile private var hiddenClipboardListener: Any? = null
    @Volatile private var listenerRegistrationSucceeded = false

    // The platform listener performs only one oneway AIDL edge notification.
    // Clipboard parsing, disk, network and hashing never run on this Binder thread.
    private val hiddenListenerBinder = object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
            if (code == INTERFACE_TRANSACTION) {
                reply?.writeString("android.content.IOnPrimaryClipChangedListener")
                return true
            }
            if (code == FIRST_CALL_TRANSACTION) {
                runCatching { data.enforceInterface("android.content.IOnPrimaryClipChangedListener") }
                runCatching { clipboardChangedCallback?.onClipboardChanged() }
                return true
            }
            return super.onTransact(code, data, reply, flags)
        }
    }
    companion object {
        private const val TAG = "ClipMeshShizuku"
        private const val SHELL_PACKAGE = "com.android.shell"
        private const val MAX_ITEM_BYTES = 44L * 1024L * 1024L
        @Volatile private var clipboardService: Any? = null

        // Shizuku owns the UserService execution identity. Do not mutate
        // process UID/GID ourselves; doing so is brittle on OEM Android builds.

        private fun application(): Application? = runCatching {
            Class.forName("android.app.ActivityThread").getMethod("currentApplication").invoke(null) as? Application
        }.getOrNull() ?: runCatching {
            Class.forName("android.app.AppGlobals").getMethod("getInitialApplication").invoke(null) as? Application
        }.getOrNull()

        private fun clipboard(): Any? {
            clipboardService?.let { return it }
            return runCatching {
                val sm = Class.forName("android.os.ServiceManager")
                val binder = sm.getMethod("getService", String::class.java).invoke(null, "clipboard") as? IBinder ?: return null
                val stub = Class.forName("android.content.IClipboard\$Stub")
                stub.getMethod("asInterface", IBinder::class.java).invoke(null, binder).also { clipboardService = it }
            }.onFailure { Log.e(TAG, "Unable to obtain clipboard binder", it) }.getOrNull()
        }
    }

    @Volatile private var lastClip: ClipData? = null

    override fun init(callerToken: IBinder) {
        // Shizuku owns this process lifecycle. Never terminate a process from a
        // caller-token death callback.
    }

    override fun getPrimaryClipJson(): String {
        val clip = invokeClipboard("getPrimaryClip") as? ClipData ?: return ""
        if (clip.itemCount == 0) return ""
        lastClip = clip
        val description = clip.description
        val items = JSONArray()
        for (i in 0 until clip.itemCount) {
            val item = clip.getItemAt(i)
            val uri = item.uri
            val resolvedMime = uri?.let { u -> runCatching { application()?.contentResolver?.getType(u) }.getOrNull() }
            val mime = resolvedMime ?: description?.let { d ->
                (0 until d.mimeTypeCount).map { d.getMimeType(it) }.firstOrNull { m ->
                    if (uri != null) !m.startsWith("text/") else m.startsWith("text/")
                } ?: if (d.mimeTypeCount > 0) d.getMimeType(0) else null
            } ?: if (item.text != null) "text/plain" else "application/octet-stream"
            items.put(JSONObject().apply {
                put("index", i)
                put("mime", mime)
                if (item.text != null) put("text", item.text.toString())
                if (item.htmlText != null) put("html", item.htmlText)
                if (uri != null) {
                    put("uri", uri.toString())
                    put("name", queryDisplayName(uri).ifBlank { "clipboard-$i" })
                }
            })
        }
        val extras = description?.extras
        val sensitive = if (Build.VERSION.SDK_INT >= 33) {
            extras?.getBoolean(ClipDescription.EXTRA_IS_SENSITIVE, false) ?: false
        } else {
            extras?.getBoolean("android.content.extra.IS_SENSITIVE", false) ?: false
        }
        val remote = (extras?.getBoolean("dev.clipmesh.extra.REMOTE", false) ?: false) ||
            (extras?.getBoolean("android.content.extra.IS_REMOTE_DEVICE", false) ?: false)
        val timestamp = description?.timestamp ?: 0L
        return JSONObject().put("sensitive", sensitive).put("remote", remote)
            .put("timestamp", timestamp).put("items", items).toString()
    }

    override fun copyPrimaryClipItemToFile(index: Int, destination: ParcelFileDescriptor): Boolean {
        val clip = lastClip ?: (invokeClipboard("getPrimaryClip") as? ClipData) ?: return false
        if (index !in 0 until clip.itemCount) return false
        val uri = clip.getItemAt(index).uri ?: return false
        return readUriAsShell(uri, destination) || readUriWithResolver(uri, destination)
    }

    override fun getLatestScreenshotJson(): String = runCatching {
        // Samsung attributes ContentResolver media queries to the ClipMesh
        // package even inside a shell-UID UserService, which denies the query
        // without broad gallery permission. The platform content utility keeps
        // the Shizuku shell attribution and needs no user photo-library grant.
        val collection = "content://media/external/images/media"
        val recentCutoff = System.currentTimeMillis() / 1000L - 30L
        val process = ProcessBuilder(
            "/system/bin/content",
            "query",
            "--uri", collection,
            "--projection", "_id:_display_name:relative_path:mime_type:date_added",
            "--where", "(relative_path LIKE '%Screenshots/%' OR _display_name LIKE 'Screenshot_%') AND date_added >= $recentCutoff",
            "--sort", "date_added DESC",
        ).redirectErrorStream(true).start()
        val output = process.inputStream.bufferedReader().use { it.readText() }
        if (process.waitFor() != 0) return@runCatching ""
        val first = output.lineSequence().firstOrNull { it.startsWith("Row:") } ?: return@runCatching ""
        val id = Regex("""_id=(\d+)""").find(first)?.groupValues?.get(1)?.toLongOrNull()
            ?: return@runCatching ""
        val name = Regex("""_display_name=(.*?), relative_path=""").find(first)?.groupValues?.get(1).orEmpty()
        val mime = Regex("""mime_type=(.*?), date_added=""").find(first)?.groupValues?.get(1).orEmpty()
        val added = Regex("""date_added=(\d+)""").find(first)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        JSONObject()
            .put("id", id)
            .put("uri", "$collection/$id")
            .put("name", name)
            .put("mime", mime.ifBlank { "image/png" })
            .put("date_added", added)
            .toString()
    }.getOrDefault("")

    override fun copyUriToFile(uri: String, destination: ParcelFileDescriptor): Boolean {
        val parsed = runCatching { Uri.parse(uri) }.getOrNull() ?: return false
        if (parsed.scheme != "content" || parsed.authority?.startsWith("media") != true) return false
        return readUriAsShell(parsed, destination) || readUriWithResolver(parsed, destination)
    }

    private fun readUriAsShell(uri: Uri, destination: ParcelFileDescriptor): Boolean = runCatching {
        val process = ProcessBuilder("/system/bin/content", "read", "--uri", uri.toString())
            .redirectErrorStream(false)
            .start()
        var total = 0L
        ParcelFileDescriptor.dup(destination.fileDescriptor).use { duplicate ->
            process.inputStream.use { input ->
                FileOutputStream(duplicate.fileDescriptor).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        total += n
                        if (total > MAX_ITEM_BYTES) {
                            process.destroyForcibly()
                            return@runCatching false
                        }
                        output.write(buffer, 0, n)
                    }
                    output.flush()
                }
            }
        }
        process.waitFor() == 0 && total > 0L
    }.getOrDefault(false)

    private fun readUriWithResolver(uri: Uri, destination: ParcelFileDescriptor): Boolean = runCatching {
        val resolver = application()?.contentResolver ?: return@runCatching false
        resolver.openInputStream(uri)?.use { input ->
            ParcelFileDescriptor.dup(destination.fileDescriptor).use { duplicate ->
                FileOutputStream(duplicate.fileDescriptor).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        total += n
                        if (total > MAX_ITEM_BYTES) return@runCatching false
                        output.write(buffer, 0, n)
                    }
                    output.flush()
                    return@runCatching total > 0L
                }
            }
        }
        false
    }.getOrDefault(false)

    override fun setPrimaryClipText(text: String): Boolean {
        val clip = ClipData.newPlainText("ClipMesh", text)
        clip.description.extras = PersistableBundle().apply {
            // Android SystemUI recognizes this for shell-originated mirrored
            // clipboard writes. ClipMesh's Shizuku UserService invokes the
            // clipboard binder as com.android.shell, avoiding the distracting
            // copy overlay for remote text synchronization.
            putBoolean("com.android.systemui.SUPPRESS_CLIPBOARD_OVERLAY", true)
            putBoolean("android.content.extra.IS_REMOTE_DEVICE", true)
        }
        return invokeClipboard("setPrimaryClip", clip) != null
    }

    override fun setClipboardChangedCallback(callback: IClipboardChangedCallback?) {
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

    private fun hiddenClipboardArgs(types: Array<Class<*>>, listenerClass: Class<*>, listener: Any): Array<Any?> {
        var stringIndex = 0
        var intIndex = 0
        return Array(types.size) { index ->
            val type = types[index]
            when {
                listenerClass.isAssignableFrom(type) -> listener
                type == String::class.java -> if (stringIndex++ == 0) SHELL_PACKAGE else null
                type == Int::class.javaPrimitiveType || type == Int::class.javaObjectType -> if (intIndex++ == 0) (android.os.Process.myUid() / 100000) else 0
                type == Long::class.javaPrimitiveType || type == Long::class.javaObjectType -> 0L
                type == Boolean::class.javaPrimitiveType || type == Boolean::class.javaObjectType -> false
                else -> null
            }
        }
    }

    override fun destroy() {
        runCatching { unregisterSystemClipboardListener() }
        clipboardChangedCallback = null
        lastClip = null
        clipboardService = null
        System.exit(0)
    }

    private fun queryDisplayName(uri: Uri): String {
        val resolver = application()?.contentResolver ?: return ""
        return runCatching {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) cursor.getString(0).orEmpty() else ""
            }.orEmpty()
        }.getOrDefault("")
    }

    private fun invokeClipboard(methodName: String, clipData: ClipData? = null): Any? {
        val target = clipboard() ?: return null
        val methods = target.javaClass.methods.filter { it.name == methodName }.sortedByDescending { it.parameterCount }
        for (method in methods) {
            val args = arrayOfNulls<Any>(method.parameterCount)
            var stringIndex = 0
            var supported = true
            method.parameterTypes.forEachIndexed { i, type ->
                args[i] = when {
                    ClipData::class.java.isAssignableFrom(type) -> clipData
                    type == String::class.java -> if (stringIndex++ == 0) SHELL_PACKAGE else null
                    type == Int::class.javaPrimitiveType || type == Int::class.java -> 0
                    type == Long::class.javaPrimitiveType || type == Long::class.java -> 0L
                    type == Boolean::class.javaPrimitiveType || type == Boolean::class.java -> false
                    else -> { supported = false; null }
                }
            }
            if (!supported || (methodName == "setPrimaryClip" && clipData == null)) continue
            val clearInboundIdentity = methodName == "getPrimaryClip"
            val callingIdentity = if (clearInboundIdentity) Binder.clearCallingIdentity() else 0L
            try {
                val result = method.invoke(target, *args)
                return result ?: if (method.returnType == Void.TYPE) true else null
            } catch (error: Exception) {
                Log.d(TAG, "Clipboard signature did not match: ${method.parameterTypes.joinToString { it.simpleName }}")
            } finally {
                if (clearInboundIdentity) Binder.restoreCallingIdentity(callingIdentity)
            }
        }
        return null
    }
}
