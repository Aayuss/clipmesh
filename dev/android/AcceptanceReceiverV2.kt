package dev.clipmesh

import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import android.util.Base64
import dev.clipmesh.fileshare.FileShareActivity
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.fileshare.TransferActionReceiver
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.concurrent.Executors

/** Debug-only control plane for the comprehensive physical acceptance suite. */
class AcceptanceReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (!BuildConfig.DEBUG || intent == null) return
        val app = context.applicationContext
        when (intent.action) {
            ACTION_INFO -> writeInfo(app)
            ACTION_SET_FAVORITE -> setFavorite(app, intent)
            ACTION_CHECK_FAVORITE -> checkFavorite(app, intent)
            ACTION_SET_TEXT -> setText(app, intent)
            ACTION_SET_IMAGE -> setImage(app)
            ACTION_CHECK_TEXT -> checkText(app, intent)
            ACTION_CHECK_IMAGE -> checkImage(app)
            ACTION_OPEN_MAIN -> {
                app.startActivity(Intent(app, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
                result(app, "open_main=PASS\n")
            }
            ACTION_OPEN_FILE -> {
                app.startActivity(Intent(app, FileShareActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
                result(app, "open_file=PASS\n")
            }
            ACTION_UI_INFO -> writeUiInfo(app)
            ACTION_CLEAR_NEARBY -> {
                LocalTransferEngine.start(app)
                LocalTransferEngine.devAcceptanceClearNearby()
                result(app, "clear_nearby=PASS\n")
            }
            ACTION_DISCOVER -> {
                LocalTransferEngine.start(app)
                LocalTransferEngine.discoverNow()
                result(app, "discover=PASS\n")
            }
            ACTION_PENDING -> writePending(app)
            ACTION_RESOLVE_PENDING -> resolvePending(app, intent)
            ACTION_SET_POLICY -> {
                val policy = intent.getStringExtra(EXTRA_POLICY).orEmpty().lowercase()
                require(policy in setOf("", "accept", "reject")) { "invalid policy" }
                app.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("incoming_policy", policy).commit()
                result(app, "policy=$policy\n")
            }
            ACTION_SET_BACKGROUND_RECEIVE -> {
                val enabled = intent.getBooleanExtra(EXTRA_ENABLED, true)
                val settings = SettingsStore(app)
                settings.receiveFilesInBackground = enabled
                if (enabled) {
                    LocalTransferEngine.start(app)
                    BackgroundService.start(app)
                } else {
                    LocalTransferEngine.stop()
                }
                result(app, "background_receive=$enabled\n")
            }
            ACTION_SEND_GENERATED -> sendGenerated(app, intent, goAsync())
        }
    }

    private fun writeInfo(app: Context) {
        LocalTransferEngine.start(app)
        val devices = LocalTransferEngine.nearbyDevices()
        val text = buildString {
            append("fingerprint=").append(LocalTransferEngine.fingerprint(app)).append('\n')
            append("nearby_count=").append(devices.size).append('\n')
            devices.forEach { d ->
                append("nearby=")
                    .append(d.fingerprint).append('|')
                    .append(if (LocalTransferEngine.isFavorite(app, d.fingerprint)) "1" else "0").append('|')
                    .append(d.address).append('|')
                    .append(d.port).append('|')
                    .append(Base64.encodeToString(d.alias.toByteArray(), Base64.NO_WRAP))
                    .append('\n')
            }
            val pending = LocalTransferEngine.devAcceptancePendingRequestIds()
            append("pending_count=").append(pending.size).append('\n')
            pending.forEach { append("pending=").append(it).append('\n') }
            append("background_receive=").append(SettingsStore(app).receiveFilesInBackground).append('\n')
        }
        result(app, text)
    }

    private fun setFavorite(app: Context, intent: Intent) {
        val fingerprint = intent.getStringExtra(EXTRA_FINGERPRINT).orEmpty().trim()
        require(fingerprint.isNotEmpty()) { "missing fingerprint" }
        val favorite = intent.getBooleanExtra(EXTRA_FAVORITE, false)
        LocalTransferEngine.setFavorite(app, fingerprint, favorite)
        result(app, "favorite=$fingerprint\nvalue=$favorite\n")
    }

    private fun checkFavorite(app: Context, intent: Intent) {
        val fingerprint = intent.getStringExtra(EXTRA_FINGERPRINT).orEmpty().trim()
        require(fingerprint.isNotEmpty()) { "missing fingerprint" }
        result(app, "favorite=$fingerprint\nvalue=${LocalTransferEngine.isFavorite(app, fingerprint)}\n")
    }

    private fun setText(app: Context, intent: Intent) {
        val expected = decodeExpected(intent)
        val clipboard = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("ClipMesh acceptance", expected))
        result(app, "set_text=PASS\n")
    }

    private fun setImage(app: Context) {
        val folder = File(app.cacheDir, "devtest-send").apply { mkdirs() }
        val file = File(folder, "acceptance-3x2.png")
        val bitmap = Bitmap.createBitmap(3, 2, Bitmap.Config.ARGB_8888)
        bitmap.setPixels(intArrayOf(Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW, Color.MAGENTA, Color.CYAN), 0, 3, 0, 0, 3, 2)
        FileOutputStream(file).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
        val uri = Uri.Builder().scheme("content").authority(BuildConfig.APPLICATION_ID + ".devtest").appendPath(file.name).build()
        val clipboard = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newUri(app.contentResolver, "ClipMesh acceptance image", uri))
        result(app, "set_image=PASS\nwidth=3\nheight=2\n")
    }

    private fun checkText(app: Context, intent: Intent) {
        val expected = decodeExpected(intent)
        val clipboard = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = runCatching { clipboard.primaryClip }.getOrNull()
        val actual = clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(app)?.toString().orEmpty()
        result(app, "check_text=${if (actual == expected) "PASS" else "FAIL"}\nactual_b64=${Base64.encodeToString(actual.toByteArray(), Base64.NO_WRAP)}\n")
    }

    private fun checkImage(app: Context) {
        val clipboard = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = runCatching { clipboard.primaryClip }.getOrNull()
        var width = 0
        var height = 0
        val uri = clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.uri
        if (uri != null) {
            runCatching {
                app.contentResolver.openInputStream(uri)?.use { input ->
                    val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeStream(input, null, opts)
                    width = opts.outWidth
                    height = opts.outHeight
                }
            }
        }
        result(app, "check_image=${if (width == 3 && height == 2) "PASS" else "FAIL"}\nwidth=$width\nheight=$height\n")
    }

    private fun writeUiInfo(app: Context) {
        val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        result(app, "clipboard_nearby_count=${prefs.getInt("clipboard_nearby_count", -1)}\nfile_nearby_count=${prefs.getInt("file_nearby_count", -1)}\n")
    }

    private fun writePending(app: Context) {
        LocalTransferEngine.start(app)
        val ids = LocalTransferEngine.devAcceptancePendingRequestIds()
        result(app, buildString {
            append("pending_count=").append(ids.size).append('\n')
            ids.forEach { append("pending=").append(it).append('\n') }
        })
    }

    private fun resolvePending(app: Context, intent: Intent) {
        val requestId = intent.getStringExtra(EXTRA_REQUEST_ID).orEmpty().trim()
        require(requestId.isNotEmpty()) { "missing request id" }
        val accept = intent.getBooleanExtra(EXTRA_ACCEPT, false)
        TransferActionReceiver().onReceive(
            app,
            Intent(app, TransferActionReceiver::class.java)
                .setAction(if (accept) TransferActionReceiver.ACTION_ACCEPT else TransferActionReceiver.ACTION_REJECT)
                .putExtra(TransferActionReceiver.EXTRA_REQUEST_ID, requestId)
        )
        result(app, "resolved=$requestId\naccepted=$accept\n")
    }

    private fun sendGenerated(app: Context, intent: Intent, pendingResult: PendingResult) {
        val address = intent.getStringExtra(EXTRA_ADDRESS).orEmpty().trim()
        val fingerprint = intent.getStringExtra(EXTRA_FINGERPRINT).orEmpty().trim()
        val prefix = sanitize(intent.getStringExtra(EXTRA_FILE_PREFIX).orEmpty().ifBlank { "acceptance" })
        val extension = sanitize(intent.getStringExtra(EXTRA_EXTENSION).orEmpty().ifBlank { "bin" }).trimStart('.')
        val count = intent.getIntExtra(EXTRA_COUNT, 1).coerceIn(1, 8)
        val size = intent.getIntExtra(EXTRA_SIZE, 128).coerceIn(1, 2 * 1024 * 1024)
        if (address.isEmpty() || fingerprint.isEmpty()) {
            result(app, "send_generated=FAIL\nerror=missing arguments\n")
            pendingResult.finish()
            return
        }
        Executors.newSingleThreadExecutor().execute {
            try {
                val folder = File(app.cacheDir, "devtest-send").apply { mkdirs() }
                val expected = mutableListOf<Triple<String, String, Int>>()
                val uris = (0 until count).map { index ->
                    val suffix = if (count == 1) "" else "-$index"
                    val name = "$prefix$suffix.$extension"
                    val file = File(folder, name)
                    val bytes = ByteArray(size) { offset -> ((offset + index * 37 + 11) % 251).toByte() }
                    file.writeBytes(bytes)
                    expected += Triple(name, sha256(bytes), bytes.size)
                    Uri.Builder().scheme("content").authority(BuildConfig.APPLICATION_ID + ".devtest").appendPath(file.name).build()
                }
                LocalTransferEngine.start(app)
                val target = LocalTransferEngine.TransferDevice(
                    alias = "ClipMesh Mac Acceptance", fingerprint = fingerprint, address = address,
                    port = LocalTransferEngine.PORT, deviceModel = "Mac", deviceType = "desktop",
                    lastSeenMs = System.currentTimeMillis()
                )
                LocalTransferEngine.sendUris(app, uris, target) { _, _, _ -> }
                result(app, buildString {
                    append("send_generated=PASS\n")
                    expected.forEach { (name, hash, bytes) -> append("file=").append(name).append('|').append(hash).append('|').append(bytes).append('\n') }
                })
            } catch (t: Throwable) {
                result(app, "send_generated=FAIL\nerror=${t.javaClass.simpleName}:${t.message.orEmpty()}\n")
            } finally {
                pendingResult.finish()
            }
        }
    }

    private fun decodeExpected(intent: Intent): String = String(Base64.decode(intent.getStringExtra(EXTRA_EXPECTED_B64).orEmpty(), Base64.DEFAULT), Charsets.UTF_8)
    private fun sanitize(value: String): String = value.substringAfterLast('/').substringAfterLast('\\').replace(Regex("[^A-Za-z0-9._-]"), "_").take(96)
    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    private fun result(app: Context, text: String) { File(app.filesDir, RESULT_FILE).writeText(text, Charsets.UTF_8) }

    companion object {
        const val ACTION_INFO = "dev.clipmesh.acceptance.INFO"
        const val ACTION_SET_FAVORITE = "dev.clipmesh.acceptance.SET_FAVORITE"
        const val ACTION_CHECK_FAVORITE = "dev.clipmesh.acceptance.CHECK_FAVORITE"
        const val ACTION_SET_TEXT = "dev.clipmesh.acceptance.SET_TEXT"
        const val ACTION_SET_IMAGE = "dev.clipmesh.acceptance.SET_IMAGE"
        const val ACTION_CHECK_TEXT = "dev.clipmesh.acceptance.CHECK_TEXT"
        const val ACTION_CHECK_IMAGE = "dev.clipmesh.acceptance.CHECK_IMAGE"
        const val ACTION_OPEN_MAIN = "dev.clipmesh.acceptance.OPEN_MAIN"
        const val ACTION_OPEN_FILE = "dev.clipmesh.acceptance.OPEN_FILE"
        const val ACTION_UI_INFO = "dev.clipmesh.acceptance.UI_INFO"
        const val ACTION_CLEAR_NEARBY = "dev.clipmesh.acceptance.CLEAR_NEARBY"
        const val ACTION_DISCOVER = "dev.clipmesh.acceptance.DISCOVER"
        const val ACTION_PENDING = "dev.clipmesh.acceptance.PENDING"
        const val ACTION_RESOLVE_PENDING = "dev.clipmesh.acceptance.RESOLVE_PENDING"
        const val ACTION_SET_POLICY = "dev.clipmesh.acceptance.SET_POLICY"
        const val ACTION_SET_BACKGROUND_RECEIVE = "dev.clipmesh.acceptance.SET_BACKGROUND_RECEIVE"
        const val ACTION_SEND_GENERATED = "dev.clipmesh.acceptance.SEND_GENERATED"
        const val EXTRA_FINGERPRINT = "fingerprint"
        const val EXTRA_FAVORITE = "favorite"
        const val EXTRA_EXPECTED_B64 = "expected_b64"
        const val EXTRA_REQUEST_ID = "request_id"
        const val EXTRA_ACCEPT = "accept"
        const val EXTRA_POLICY = "policy"
        const val EXTRA_ENABLED = "enabled"
        const val EXTRA_ADDRESS = "address"
        const val EXTRA_FILE_PREFIX = "file_prefix"
        const val EXTRA_EXTENSION = "extension"
        const val EXTRA_COUNT = "count"
        const val EXTRA_SIZE = "size"
        const val RESULT_FILE = "clipmesh-acceptance.txt"
        const val PREFS = "clipmesh_acceptance"
    }
}
