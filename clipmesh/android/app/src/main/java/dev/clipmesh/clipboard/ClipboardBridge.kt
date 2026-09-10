package dev.clipmesh.clipboard

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.database.ContentObserver
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import dev.clipmesh.SettingsStore
import dev.clipmesh.ClipMeshUiVisibility
import dev.clipmesh.crypto.Crypto
import dev.clipmesh.exclusion.ForegroundTracker
import dev.clipmesh.model.ClipPayload
import dev.clipmesh.model.PortableFile
import dev.clipmesh.model.Representation
import dev.clipmesh.shizuku.ShizukuManager
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.nio.ByteBuffer
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

class ClipboardBridge(
    private val context: Context,
    private val settings: SettingsStore,
    private val shizuku: ShizukuManager,
    private val onLocalClip: (ClipPayload) -> Unit
) {
    private val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val main = Handler(Looper.getMainLooper())
    private val statePrefs = context.getSharedPreferences("clipmesh_clipboard_state", Context.MODE_PRIVATE)
    private val suppressedFingerprint = RecentRemoteFingerprintSuppressor()
    private val debugInjectedClip = AtomicReference<ClipData?>(null)
    private val lastObservedClipboardEvent = AtomicReference(statePrefs.getString("last_event", null))
    private val lastVisibleContentFingerprint = AtomicReference(statePrefs.getString("last_content", null))
    private val lastScreenshotId = AtomicLong(statePrefs.getLong("last_screenshot_id", -1L))
    private val lastScreenshotProbeAt = AtomicLong(0L)
    private val captureInFlight = AtomicBoolean(false)
    private val capturePending = AtomicBoolean(false)
    private val screenshotProbePending = AtomicBoolean(false)
    private val captureExecutor = Executors.newSingleThreadExecutor { r -> Thread(r, "ClipMesh-ClipboardCapture").apply { isDaemon = true } }
    @Volatile private var started = false
    private val listener = ClipboardManager.OnPrimaryClipChangedListener { signalClipboardCapture() }
    private val screenshotObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) {
            signalClipboardCapture(includeScreenshotProbe = true)
        }
    }

    fun start() {
        if (started) return
        started = true
        ForegroundTracker.clipboardChanged = { signalClipboardCapture() }
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
        ForegroundTracker.clipboardChanged = null
        main.post {
            clipboard.removePrimaryClipChangedListener(listener)
            runCatching { context.contentResolver.unregisterContentObserver(screenshotObserver) }
        }
        captureExecutor.shutdownNow()
    }

    fun captureNowForSystemEvent() = signalClipboardCapture(includeScreenshotProbe = true)

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

    private fun recordObservedEvent(eventKey: String) {
        lastObservedClipboardEvent.set(eventKey)
        statePrefs.edit().putString("last_event", eventKey).commit()
    }

    private fun recordVisibleContent(fingerprint: String) {
        lastVisibleContentFingerprint.set(fingerprint)
        statePrefs.edit().putString("last_content", fingerprint).commit()
    }

    private fun emitLocal(payload: ClipPayload, fromScreenshot: Boolean) {
        val fingerprint = echoFingerprint(payload)
        if (lastVisibleContentFingerprint.getAndSet(fingerprint) == fingerprint) {
            if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("adjacent_duplicate_suppressed_count")
            statePrefs.edit().putString("last_content", fingerprint).commit()
            return
        }
        statePrefs.edit().putString("last_content", fingerprint).commit()
        if (dev.clipmesh.BuildConfig.DEBUG) {
            incrementDebugCounter("outgoing_clip_count")
            if (fromScreenshot) incrementDebugCounter("screenshot_send_count")
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putString("last_outgoing_content_fingerprint", fingerprint)
                .commit()
        }
        onLocalClip(payload)
    }

    private data class ScreenshotObservation(
        val id: Long,
        val uri: Uri,
        val mime: String,
        val name: String,
    )

    private fun latestScreenshot(): ScreenshotObservation? {
        val json = shizuku.readLatestScreenshotJson()
        if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("screenshot_probe_count")
        val value = runCatching { JSONObject(json) }.getOrNull() ?: return null
        val id = value.optLong("id", -1L)
        val uri = value.optString("uri").takeIf { it.isNotBlank() }?.let(Uri::parse)
        if (id < 0L || uri == null) return null
        if (dev.clipmesh.BuildConfig.DEBUG) {
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putLong("last_screenshot_candidate_id", id)
                .commit()
        }
        return ScreenshotObservation(
            id,
            uri,
            value.optString("mime", "image/png"),
            sanitizeName(value.optString("name", "screenshot.png")),
        )
    }

    private fun seedLatestScreenshot() {
        if (lastScreenshotId.get() >= 0L) return
        val latest = latestScreenshot() ?: return
        lastScreenshotId.set(latest.id)
        statePrefs.edit().putLong("last_screenshot_id", latest.id).commit()
    }

    private fun probeLatestScreenshotIfDue() {
        val now = android.os.SystemClock.elapsedRealtime()
        val previous = lastScreenshotProbeAt.get()
        if (now - previous >= 2_000L && lastScreenshotProbeAt.compareAndSet(previous, now)) {
            captureLatestScreenshot(0)
        }
    }

    private fun captureLatestScreenshot(attempt: Int) {
        if (!started || !settings.sendEnabled || !settings.syncImages) return
        captureExecutor.execute {
            val latest = latestScreenshot() ?: return@execute
            if (latest.id <= lastScreenshotId.get()) return@execute
            val temp = File(context.cacheDir, "outgoing/screenshot-${latest.id}")
            val copied = shizuku.copyUri(latest.uri, temp)
            val bytes = if (copied) runCatching { temp.readBytes() }.getOrNull() else null
            temp.delete()
            val png = bytes?.let(::imageToPng)
            if (png == null) {
                if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("screenshot_copy_fail_count")
                if (attempt < 8 && started) {
                    main.postDelayed({ captureLatestScreenshot(attempt + 1) }, 250L)
                }
                return@execute
            }
            lastScreenshotId.set(latest.id)
            statePrefs.edit().putLong("last_screenshot_id", latest.id).commit()
            emitLocal(
                ClipPayload(
                    representations = listOf(Representation("image/png", png)),
                    sourceApp = "android.screenshot",
                ),
                fromScreenshot = true,
            )
        }
    }

    private fun isPairingPayload(payload: ClipPayload): Boolean {
        return payload.representations.any { rep ->
            if (!rep.mime.startsWith("text/plain")) return@any false
            val text = runCatching { rep.data.toString(Charsets.UTF_8).trim() }.getOrDefault("")
            text.startsWith("clipmesh://pair?", ignoreCase = true)
        }
    }

    private data class ClipboardObservation(val payload: ClipPayload, val generation: Long)

    private fun readCurrent(sourcePackage: String?): ClipboardObservation? {
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

    private fun readClipData(clip: ClipData, sourcePackage: String?): ClipPayload? {
        if (clip.itemCount == 0 || isRemoteClip(clip)) return null
        val reps = mutableListOf<Representation>()
        val descriptionImageMime = clip.description.let { description ->
            (0 until description.mimeTypeCount).map { description.getMimeType(it) }
                .firstOrNull { it.lowercase(Locale.ROOT).startsWith("image/") }
        }
        var imageAdded = false
        if (settings.syncImages) {
            for (index in 0 until clip.itemCount) {
                val uri = clip.getItemAt(index).uri ?: continue
                val mime = runCatching { context.contentResolver.getType(uri) }.getOrNull() ?: descriptionImageMime
                if (mime?.lowercase(Locale.ROOT)?.startsWith("image/") != true) continue
                val png = readUriBytes(uri)?.let(::imageToPng) ?: continue
                reps += Representation("image/png", png); imageAdded = true; break
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
        if (o.optBoolean("sensitive", false) || o.optBoolean("remote", false)) return null
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
        val remoteFingerprint = echoFingerprint(payload)
        if (lastVisibleContentFingerprint.getAndSet(remoteFingerprint) == remoteFingerprint) {
            if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("adjacent_duplicate_suppressed_count")
            statePrefs.edit().putString("last_content", remoteFingerprint).commit()
            return
        }
        statePrefs.edit().putString("last_content", remoteFingerprint).commit()
        val now = System.currentTimeMillis()
        if (dev.clipmesh.BuildConfig.DEBUG) {
            incrementDebugCounter("remote_apply_count")
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putLong("last_remote_apply_at", now)
                .putString("last_remote_apply_fingerprint", remoteFingerprint)
                .apply()
        }
        suppressedFingerprint.set(remoteFingerprint)
        main.postDelayed({ suppressedFingerprint.compareAndSet(remoteFingerprint, null) }, 15_000L)
        val plain = payload.representations.firstOrNull { it.mime.startsWith("text/plain") }
        val html = payload.representations.firstOrNull { it.mime.startsWith("text/html") }
        val image = payload.representations.firstOrNull { it.mime.startsWith("image/") }
        // Binder connection/privileged write may block briefly, so perform it on the network/capture thread.
        if (plain != null && html == null && shizuku.hasPermission() && !settings.showRemoteCopyOverlay) {
            val text = plain.data.toString(Charsets.UTF_8)
            val wrote = shizuku.setText(text)
            if (dev.clipmesh.BuildConfig.DEBUG) {
                context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                    .putLong("last_remote_shizuku_write_at", System.currentTimeMillis())
                    .putBoolean("last_remote_shizuku_write_ok", wrote)
                    .apply()
            }
            if (wrote) return
        }
        if (dev.clipmesh.BuildConfig.DEBUG) {
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putLong("last_remote_fallback_at", System.currentTimeMillis())
                .apply()
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

    private fun echoFingerprint(payload: ClipPayload): String {
        val normalized = payload.representations.map { representation ->
            if (representation.mime.lowercase(Locale.ROOT).startsWith("image/")) {
                imagePerceptualIdentity(representation.data)?.let {
                    Representation("image/x-clipmesh-perceptual", it)
                } ?: representation
            } else representation
        }
        return payload.copy(representations = normalized).stableFingerprint()
    }

    private fun imagePerceptualIdentity(bytes: ByteArray): ByteArray? {
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val orientation = runCatching {
            ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )
        }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
        val bitmap = orientBitmap(decoded, orientation)
        return try {
            if (bitmap.width <= 0 || bitmap.height <= 0) return null
            val luminance = IntArray(64)
            var sumR = 0L; var sumG = 0L; var sumB = 0L
            for (gy in 0 until 8) {
                for (gx in 0 until 8) {
                    val x = ((((2L * gx + 1L) * bitmap.width) / 16L).toInt()).coerceAtMost(bitmap.width - 1)
                    val y = ((((2L * gy + 1L) * bitmap.height) / 16L).toInt()).coerceAtMost(bitmap.height - 1)
                    val pixel = bitmap.getPixel(x, y)
                    val r = Color.red(pixel); val g = Color.green(pixel); val b = Color.blue(pixel)
                    val index = gy * 8 + gx
                    sumR += r; sumG += g; sumB += b
                    luminance[index] = 299 * r + 587 * g + 114 * b
                }
            }
            val average = luminance.sum() / 64
            val hash = ByteArray(8)
            luminance.forEachIndexed { index, value ->
                if (value >= average) {
                    hash[index / 8] = (hash[index / 8].toInt() or (1 shl (7 - index % 8))).toByte()
                }
            }
            ByteBuffer.allocate(19)
                .putInt(bitmap.width)
                .putInt(bitmap.height)
                .put(hash)
                .put((sumR / 64L / 16L).toByte())
                .put((sumG / 64L / 16L).toByte())
                .put((sumB / 64L / 16L).toByte())
                .array()
        } finally {
            if (bitmap !== decoded) bitmap.recycle()
            decoded.recycle()
        }
    }

    private fun imageToPng(bytes: ByteArray): ByteArray? {
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val orientation = runCatching {
            ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )
        }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
        val oriented = orientBitmap(decoded, orientation)
        return try {
            val output = ByteArrayOutputStream()
            if (!oriented.compress(Bitmap.CompressFormat.PNG, 100, output)) null else output.toByteArray()
        } finally {
            if (oriented !== decoded) oriented.recycle()
            decoded.recycle()
        }
    }

    private fun orientBitmap(bitmap: Bitmap, orientation: Int): Bitmap {
        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
            ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.setRotate(-90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(-90f)
            else -> return bitmap
        }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    }

    private fun isRemoteClip(clip: ClipData): Boolean {
        val extras = clip.description.extras
        val markedRemote = extras?.getBoolean("dev.clipmesh.extra.REMOTE", false) == true ||
            extras?.getBoolean("android.content.extra.IS_REMOTE_DEVICE", false) == true
        if (markedRemote) return true
        // URI ownership is a second provenance signal in case an OEM strips
        // ClipDescription extras. This provider is used only for remote writes.
        val remoteAuthority = "${context.packageName}.files"
        return (0 until clip.itemCount).any { clip.getItemAt(it).uri?.authority == remoteAuthority }
    }

    private fun incrementDebugCounter(name: String) {
        val prefs = context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE)
        prefs.edit().putInt(name, prefs.getInt(name, 0) + 1).commit()
    }

    private fun markRemote(clip: ClipData): ClipData {
        val extras = clip.description.extras ?: android.os.PersistableBundle()
        extras.putBoolean("dev.clipmesh.extra.REMOTE", true)
        if (!settings.showRemoteCopyOverlay) {
            extras.putBoolean("com.android.systemui.SUPPRESS_CLIPBOARD_OVERLAY", true)
            extras.putBoolean("android.content.extra.IS_REMOTE_DEVICE", true)
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

/**
 * Tracks multiple recently-applied remote clipboard fingerprints until the
 * corresponding Android clipboard-change callback consumes them.
 *
 * A single AtomicReference is racy during rapid remote bursts: remote N+1 can
 * replace N before Android delivers N's callback, causing N to be mistaken for
 * a local copy and echoed back to the sender. Keeping each pending fingerprint
 * independently prevents that reorder/ping-pong race while retaining the same
 * set()/compareAndSet() contract used by ClipboardBridge.
 */
private class RecentRemoteFingerprintSuppressor(
    private val ttlMs: Long = 15_000L,
    private val maxEntries: Int = 64,
) {
    private val lock = Any()
    private val pendingUntil = LinkedHashMap<String, Long>()

    fun set(value: String?) {
        synchronized(lock) {
            val now = System.currentTimeMillis()
            pruneLocked(now)
            if (value == null) {
                pendingUntil.clear()
                return
            }
            // Refresh insertion order as well as expiry for a repeated value.
            pendingUntil.remove(value)
            pendingUntil[value] = now + ttlMs
            while (pendingUntil.size > maxEntries) {
                val oldest = pendingUntil.entries.iterator()
                if (!oldest.hasNext()) break
                oldest.next()
                oldest.remove()
            }
        }
    }

    fun compareAndSet(expected: String?, update: String?): Boolean {
        if (expected == null) return false
        synchronized(lock) {
            val now = System.currentTimeMillis()
            pruneLocked(now)
            if (!pendingUntil.containsKey(expected)) return false
            pendingUntil.remove(expected)
            if (update != null) pendingUntil[update] = now + ttlMs
            return true
        }
    }

    private fun pruneLocked(now: Long) {
        val iterator = pendingUntil.entries.iterator()
        while (iterator.hasNext()) {
            if (iterator.next().value <= now) iterator.remove()
        }
    }
}

