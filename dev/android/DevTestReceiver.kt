package dev.clipmesh

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Base64
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.shizuku.ShizukuManager
import java.io.File
import java.util.concurrent.Executors

/**
 * Shell-protected debug control plane for the physical-device E2E harness.
 * It is copied only into src/debug and every exported action also requires DUMP.
 */
class DevTestReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (!BuildConfig.DEBUG || intent == null) return
        val app = context.applicationContext
        when (intent.action) {
            ACTION_CONFIGURE -> configure(app, intent)
            ACTION_INFO -> writeInfo(app)
            ACTION_FAVORITE -> {
                val fingerprint = intent.getStringExtra(EXTRA_FINGERPRINT).orEmpty().trim()
                require(fingerprint.isNotEmpty()) { "missing fingerprint" }
                LocalTransferEngine.setFavorite(app, fingerprint, true)
                result(app, "favorite=$fingerprint\n")
            }
            ACTION_REQUEST_SHIZUKU -> {
                val shizuku = ShizukuManager(app)
                val requested = runCatching { shizuku.requestPermission() }.getOrDefault(false)
                result(app, "requested=$requested\n")
                shizuku.close()
            }
            ACTION_READ_SHIZUKU -> readShizuku(app, intent, goAsync())
            ACTION_WRITE_SHIZUKU -> writeShizuku(app, intent, goAsync())
            ACTION_SEND_FILE -> sendFile(app, intent, goAsync())
        }
    }

    private fun configure(app: Context, intent: Intent) {
        val encoded = intent.getStringExtra(EXTRA_PAIRING_B64).orEmpty()
        require(encoded.isNotBlank()) { "missing pairing data" }
        val pairingUri = String(Base64.decode(encoded, Base64.DEFAULT), Charsets.UTF_8)
        val pairing = Pairing.parse(pairingUri)
        val settings = SettingsStore(app)
        settings.spaceId = pairing.spaceId
        SecretStore(app).saveSpaceKey(pairing.key)
        settings.clearKnownPeers()
        pairing.deviceId?.takeIf { it != settings.deviceId }?.let { settings.seedPeer(it, pairing.name) }
        settings.backgroundSync = true
        intent.getStringExtra(EXTRA_FINGERPRINT)?.trim()?.takeIf { it.isNotEmpty() }?.let {
            LocalTransferEngine.setFavorite(app, it, true)
        }
        app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit().clear().apply()
        BackgroundRuntime.restart(app)
        BackgroundService.start(app)
        result(app, "configured=true\nspace=${pairing.spaceId}\n")
    }

    private fun writeInfo(app: Context) {
        LocalTransferEngine.start(app)
        val shizuku = ShizukuManager(app)
        val ci = app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE)
        val text = buildString {
            append("fingerprint=").append(LocalTransferEngine.fingerprint(app)).append('\n')
            append("shizuku_available=").append(shizuku.isAvailable()).append('\n')
            append("shizuku_permission=").append(shizuku.hasPermission()).append('\n')
            append("background_status=").append(BackgroundRuntime.status.replace('\n', ' ')).append('\n')
            append("clipboard_peer_count=").append(BackgroundRuntime.debugPeerCount()).append('\n')
            append("last_remote_received_at=").append(ci.getLong("last_remote_received_at", 0L)).append('\n')
            append("last_remote_received_fingerprint=").append(ci.getString("last_remote_received_fingerprint", "").orEmpty()).append('\n')
            append("last_remote_apply_at=").append(ci.getLong("last_remote_apply_at", 0L)).append('\n')
            append("last_remote_apply_fingerprint=").append(ci.getString("last_remote_apply_fingerprint", "").orEmpty()).append('\n')
            append("last_remote_shizuku_write_at=").append(ci.getLong("last_remote_shizuku_write_at", 0L)).append('\n')
            append("last_remote_shizuku_write_ok=").append(ci.getBoolean("last_remote_shizuku_write_ok", false)).append('\n')
            append("last_remote_fallback_at=").append(ci.getLong("last_remote_fallback_at", 0L)).append('\n')
        }
        result(app, text)
        shizuku.close()
    }

    private fun readShizuku(app: Context, intent: Intent, pending: BroadcastReceiver.PendingResult) {
        val expected = decodeExpected(intent)
        Executors.newSingleThreadExecutor().execute {
            val shizuku = ShizukuManager(app)
            try {
                val snapshot = shizuku.readSnapshotJson()
                val pass = expected.isNotEmpty() && snapshot.contains(expected)
                result(app, buildString {
                    append("shizuku_read=").append(if (pass) "PASS" else "FAIL").append('\n')
                    append("snapshot=").append(snapshot.replace('\n', ' ')).append('\n')
                })
            } catch (t: Throwable) {
                result(app, "shizuku_read=FAIL\nerror=${t.javaClass.simpleName}:${t.message.orEmpty()}\n")
            } finally {
                shizuku.close()
                pending.finish()
            }
        }
    }

    private fun writeShizuku(app: Context, intent: Intent, pending: BroadcastReceiver.PendingResult) {
        val expected = decodeExpected(intent)
        Executors.newSingleThreadExecutor().execute {
            val shizuku = ShizukuManager(app)
            try {
                val pass = expected.isNotEmpty() && shizuku.setText(expected)
                result(app, buildString {
                    append("shizuku_write=").append(if (pass) "PASS" else "FAIL").append('\n')
                    append("value_b64=").append(Base64.encodeToString(expected.toByteArray(), Base64.NO_WRAP)).append('\n')
                })
            } catch (t: Throwable) {
                result(app, "shizuku_write=FAIL\nerror=${t.javaClass.simpleName}:${t.message.orEmpty()}\n")
            } finally {
                shizuku.close()
                pending.finish()
            }
        }
    }

    private fun sendFile(app: Context, intent: Intent, pending: BroadcastReceiver.PendingResult) {
        val address = intent.getStringExtra(EXTRA_ADDRESS).orEmpty().trim()
        val fingerprint = intent.getStringExtra(EXTRA_FINGERPRINT).orEmpty().trim()
        val fileName = sanitize(intent.getStringExtra(EXTRA_FILE_NAME).orEmpty())
        val payload = intent.getStringExtra(EXTRA_PAYLOAD_B64).orEmpty()
        if (address.isEmpty() || fingerprint.isEmpty() || fileName.isEmpty() || payload.isEmpty()) {
            result(app, "send=FAIL missing arguments\n")
            pending.finish()
            return
        }
        Executors.newSingleThreadExecutor().execute {
            try {
                val bytes = Base64.decode(payload, Base64.DEFAULT)
                val folder = File(app.cacheDir, "devtest-send").apply { mkdirs() }
                val file = File(folder, fileName).canonicalFile
                require(file.path.startsWith(folder.canonicalPath + File.separator)) { "invalid file" }
                file.writeBytes(bytes)
                val uri = Uri.Builder()
                    .scheme("content")
                    .authority(BuildConfig.APPLICATION_ID + ".devtest")
                    .appendPath(file.name)
                    .build()
                LocalTransferEngine.start(app)
                val target = LocalTransferEngine.TransferDevice(
                    alias = "ClipMesh Mac E2E",
                    fingerprint = fingerprint,
                    address = address,
                    port = LocalTransferEngine.PORT,
                    deviceModel = "Mac",
                    deviceType = "desktop",
                    lastSeenMs = System.currentTimeMillis()
                )
                LocalTransferEngine.sendUris(app, listOf(uri), target) { _, _, _ -> }
                result(app, "send=PASS\nfile=$fileName\nbytes=${bytes.size}\n")
            } catch (t: Throwable) {
                result(app, "send=FAIL\nerror=${t.javaClass.simpleName}:${t.message.orEmpty()}\n")
            } finally {
                pending.finish()
            }
        }
    }

    private fun decodeExpected(intent: Intent): String = String(
        Base64.decode(intent.getStringExtra(EXTRA_EXPECTED_B64).orEmpty(), Base64.DEFAULT),
        Charsets.UTF_8
    )

    private fun sanitize(value: String): String = value.substringAfterLast('/').substringAfterLast('\\')
        .replace(Regex("[^A-Za-z0-9._-]"), "_")
        .take(120)

    private fun result(app: Context, text: String) {
        File(app.filesDir, RESULT_FILE).writeText(text, Charsets.UTF_8)
    }

    companion object {
        const val ACTION_CONFIGURE = "dev.clipmesh.devtest.CONFIGURE"
        const val ACTION_INFO = "dev.clipmesh.devtest.INFO"
        const val ACTION_FAVORITE = "dev.clipmesh.devtest.FAVORITE"
        const val ACTION_REQUEST_SHIZUKU = "dev.clipmesh.devtest.REQUEST_SHIZUKU"
        const val ACTION_READ_SHIZUKU = "dev.clipmesh.devtest.READ_SHIZUKU"
        const val ACTION_WRITE_SHIZUKU = "dev.clipmesh.devtest.WRITE_SHIZUKU"
        const val ACTION_SEND_FILE = "dev.clipmesh.devtest.SEND_FILE"
        const val EXTRA_PAIRING_B64 = "pairing_b64"
        const val EXTRA_FINGERPRINT = "fingerprint"
        const val EXTRA_EXPECTED_B64 = "expected_b64"
        const val EXTRA_ADDRESS = "address"
        const val EXTRA_FILE_NAME = "file_name"
        const val EXTRA_PAYLOAD_B64 = "payload_b64"
        const val RESULT_FILE = "clipmesh-devtest.txt"
    }
}
