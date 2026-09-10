package dev.clipmesh.clipboard

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Handler
import android.os.Looper
import dev.clipmesh.SettingsStore
import dev.clipmesh.crypto.Crypto
import dev.clipmesh.exclusion.ForegroundTracker
import dev.clipmesh.model.ClipPayload
import dev.clipmesh.model.PortableFile
import dev.clipmesh.model.Representation
import dev.clipmesh.shizuku.ShizukuManager
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class ClipboardBridge(
    private val context: Context,
    private val settings: SettingsStore,
    private val shizuku: ShizukuManager,
    private val onLocalClip: (ClipPayload) -> Unit
) {
    private val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val main = Handler(Looper.getMainLooper())
    private val suppressedFingerprint = AtomicReference<String?>(null)
    private val lastWatchdogFingerprint = AtomicReference<String?>(null)
    private val captureInFlight = AtomicBoolean(false)
    private val capturePending = AtomicBoolean(false)
    private val captureExecutor = Executors.newSingleThreadExecutor { r -> Thread(r, "ClipMesh-ClipboardCapture").apply { isDaemon = true } }
    private var started = false
    private val listener = ClipboardManager.OnPrimaryClipChangedListener { captureAsync(fromWatchdog = false) }

    fun start() {
        if (started) return
        started = true
        ForegroundTracker.clipboardChanged = { captureNowForAccessibility() }
        main.post { clipboard.addPrimaryClipChangedListener(listener) }
    }

    fun stop() {
        if (!started) return
        started = false
        ForegroundTracker.clipboardChanged = null
        main.post { clipboard.removePrimaryClipChangedListener(listener) }
        captureExecutor.shutdownNow()
    }

    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)
    fun captureNowForBackgroundMonitor() = captureAsync(fromWatchdog = true)
    fun captureNowForForeground() = captureAsync(fromWatchdog = true)
    fun captureNowForAccessibility() = captureAsync(fromWatchdog = true)

    private fun captureAsync(fromWatchdog: Boolean) {
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
                val payload = readCurrent(sourcePackage) ?: return@execute
                if (isPairingPayload(payload)) return@execute
                val fp = payload.stableFingerprint()
                if (suppressedFingerprint.compareAndSet(fp, null)) {
                    lastWatchdogFingerprint.set(fp)
                    return@execute
                }
                if (fromWatchdog && lastWatchdogFingerprint.getAndSet(fp) == fp) return@execute
                lastWatchdogFingerprint.set(fp)
                onLocalClip(payload)
            } finally {
                captureInFlight.set(false)
                if (capturePending.getAndSet(false) && started) {
                    main.postDelayed({ captureAsync(fromWatchdog = false) }, 90L)
                }
            }
        }
    }

    private fun isPairingPayload(payload: ClipPayload): Boolean {
        return payload.representations.any { rep ->
            if (!rep.mime.startsWith("text/plain")) return@any false
            val text = runCatching { rep.data.toString(Charsets.UTF_8).trim() }.getOrDefault("")
            text.startsWith("clipmesh://pair?", ignoreCase = true)
        }
    }

    private fun readCurrent(sourcePackage: String?): ClipPayload? {
        // Shizuku is preferred because Android restricts normal background clipboard reads.
        val shizukuJson = if (shizuku.hasPermission()) shizuku.readSnapshotJson() else ""
        if (shizukuJson.isNotBlank()) return readShizukuSnapshot(shizukuJson, sourcePackage)

        // Fallback works while ClipMesh has input focus and on some OEM/Android combinations.
        val clip = clipboard.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        val reps = mutableListOf<Representation>()
        val descriptionImageMime = clipboard.primaryClipDescription?.let { description ->
            (0 until description.mimeTypeCount)
                .map { description.getMimeType(it) }
                .firstOrNull { it.lowercase(Locale.ROOT).startsWith("image/") }
        }
        var imageAdded = false
        if (settings.syncImages) {
            for (index in 0 until clip.itemCount) {
                val item = clip.getItemAt(index)
                val uri = item.uri ?: continue
                val uriMime = runCatching { context.contentResolver.getType(uri) }.getOrNull()
                val mime = uriMime ?: descriptionImageMime
                if (mime?.lowercase(Locale.ROOT)?.startsWith("image/") != true) continue
                val png = readUriBytes(uri)?.let { imageToPng(it) } ?: continue
                reps += Representation("image/png", png)
                imageAdded = true
                break
            }
        }
        if (!imageAdded && settings.syncText) {
            val text = clip.getItemAt(0).coerceToText(context)?.toString()
            if (!text.isNullOrEmpty()) reps += Representation("text/plain; charset=utf-8", text.toByteArray())
        }
        return ClipPayload(reps, sourceApp = sourcePackage).takeIf { it.representations.isNotEmpty() }
    }

    private fun readShizukuSnapshot(json: String, sourcePackage: String?): ClipPayload? {
        val o = runCatching { JSONObject(json) }.getOrNull() ?: return null
        if (o.optBoolean("sensitive", false)) return null
        val items = o.optJSONArray("items") ?: return null
        val reps = mutableListOf<Representation>()
        val files = mutableListOf<PortableFile>()
        var rawBinaryBytes = 0L
        for (i in 0 until items.length()) {
            val item = items.getJSONObject(i)
            val mime = item.optString("mime", "application/octet-stream")
            val text = item.optString("text").takeIf { it.isNotEmpty() }
            val html = item.optString("html").takeIf { it.isNotEmpty() }
            if (settings.syncText && text != null && reps.none { it.mime.startsWith("text/plain") }) {
                reps += Representation("text/plain; charset=utf-8", text.toByteArray())
            }
            if (settings.syncText && html != null && reps.none { it.mime == "text/html" }) {
                reps += Representation("text/html", html.toByteArray())
            }
            if (item.has("uri")) {
                val isImage = mime.lowercase(Locale.ROOT).startsWith("image/")
                if ((isImage && !settings.syncImages) || (!isImage && !settings.syncFiles)) continue
                val temp = File(context.cacheDir, "outgoing/${System.nanoTime()}-$i")
                if (shizuku.copyItem(item.getInt("index"), temp)) {
                    val bytes = temp.readBytes()
                    temp.delete()
                    rawBinaryBytes += bytes.size
                    if (rawBinaryBytes > 44L * 1024L * 1024L) break
                    val name = sanitizeName(item.optString("name", if (isImage) "clipboard.png" else "clipboard-$i"))
                    val hash = Crypto.hex(Crypto.sha256(bytes))
                    if (isImage && settings.syncImages && reps.none { it.mime.equals("image/png", ignoreCase = true) }) {
                        val png = imageToPng(bytes)
                        if (png != null) {
                            reps += Representation("image/png", png)
                        } else if (settings.syncFiles) {
                            files += PortableFile(name, bytes, hash)
                        }
                    } else if (settings.syncFiles) {
                        files += PortableFile(name, bytes, hash)
                    }
                }
            }
        }
        val payload = ClipPayload(reps, files, sourcePackage)
        return payload.takeIf { it.representations.isNotEmpty() || it.files.isNotEmpty() }
    }

    fun applyRemote(payload: ClipPayload) {
        if (!settings.receiveEnabled) return
        val remoteFingerprint = payload.stableFingerprint()
        suppressedFingerprint.set(remoteFingerprint)
        main.postDelayed({ suppressedFingerprint.compareAndSet(remoteFingerprint, null) }, 1_500L)
        val plain = payload.representations.firstOrNull { it.mime.startsWith("text/plain") }
        val html = payload.representations.firstOrNull { it.mime.startsWith("text/html") }
        val image = payload.representations.firstOrNull { it.mime.startsWith("image/") }
        // Binder connection/privileged write may block briefly, so perform it on the network/capture thread.
        if (plain != null && html == null && shizuku.hasPermission() && !settings.showRemoteCopyOverlay) {
            val text = plain.data.toString(Charsets.UTF_8)
            if (shizuku.setText(text)) return
        }
        main.post {
            runCatching {
                when {
                    payload.files.isNotEmpty() -> setFiles(payload.files)
                    image != null -> setSingleBinary("clipboard-${System.currentTimeMillis()}.${extension(image.mime)}", image.mime, image.data)
                    plain != null -> {
                        val text = plain.data.toString(Charsets.UTF_8)
                        val htmlText = html?.let { it.data.toString(Charsets.UTF_8) }
                        if (htmlText != null) clipboard.setPrimaryClip(markRemote(ClipData.newHtmlText("ClipMesh", text, htmlText)))
                        else clipboard.setPrimaryClip(markRemote(ClipData.newPlainText("ClipMesh", text)))
                    }
                }
            }
        }
    }

    private fun readUriBytes(uri: Uri): ByteArray? = runCatching {
        context.contentResolver.openInputStream(uri)?.use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                total += n
                if (total > 44L * 1024L * 1024L) return@use null
                output.write(buffer, 0, n)
            }
            output.toByteArray()
        }
    }.getOrNull()

    private fun imageToPng(bytes: ByteArray): ByteArray? {
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        return try {
            val output = ByteArrayOutputStream()
            if (!bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output)) null else output.toByteArray()
        } finally {
            bitmap.recycle()
        }
    }

    private fun markRemote(clip: ClipData): ClipData {
        if (settings.showRemoteCopyOverlay) return clip
        val extras = android.os.PersistableBundle().apply {
            putBoolean("com.android.systemui.SUPPRESS_CLIPBOARD_OVERLAY", true)
            putBoolean("android.content.extra.IS_REMOTE_DEVICE", true)
        }
        clip.description.extras = extras
        return clip
    }

    private fun setFiles(files: List<PortableFile>) {
        var clip: ClipData? = null
        files.forEach { f ->
            val file = File(context.cacheDir, "received/${uniqueName(f.name)}")
            file.parentFile?.mkdirs(); file.writeBytes(f.data)
            val mime = guessMime(f.name)
            val uri = Uri.Builder().scheme("content").authority("${context.packageName}.files")
                .appendPath(file.name).appendQueryParameter("mime", mime).appendQueryParameter("display", f.name).build()
            val item = ClipData.Item(uri)
            if (clip == null) clip = ClipData("ClipMesh files", arrayOf(mime), item) else clip!!.addItem(item)
        }
        clip?.let { clipboard.setPrimaryClip(markRemote(it)) }
    }

    private fun setSingleBinary(name: String, mime: String, bytes: ByteArray) {
        val file = File(context.cacheDir, "received/${uniqueName(name)}")
        file.parentFile?.mkdirs(); file.writeBytes(bytes)
        val uri = Uri.Builder().scheme("content").authority("${context.packageName}.files")
            .appendPath(file.name).appendQueryParameter("mime", mime).build()
        clipboard.setPrimaryClip(markRemote(ClipData("ClipMesh", arrayOf(mime), ClipData.Item(uri))))
    }

    private fun guessMime(name: String): String = java.net.URLConnection.guessContentTypeFromName(name) ?: "application/octet-stream"
    private fun uniqueName(name: String): String = "${System.currentTimeMillis()}-${sanitizeName(name)}"
    private fun sanitizeName(name: String): String = name.replace(Regex("[^A-Za-z0-9._ -]"), "_").take(120).ifBlank { "clipboard" }
    private fun extension(mime: String): String = when (mime.lowercase(Locale.ROOT)) {
        "image/jpeg" -> "jpg"; "image/webp" -> "webp"; "image/gif" -> "gif"; else -> "png"
    }
}
