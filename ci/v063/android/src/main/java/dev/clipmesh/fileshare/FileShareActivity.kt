package dev.clipmesh.fileshare

import android.app.Activity
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.ui.graphics.asImageBitmap
import dev.clipmesh.ClipMeshDialog
import dev.clipmesh.MainActivity
import dev.clipmesh.toUi
import dev.clipmesh.ui.DeviceUi
import dev.clipmesh.ui.IncomingBanner
import dev.clipmesh.ui.SelectedFile
import dev.clipmesh.ui.SendState
import dev.clipmesh.ui.Tab
import dev.clipmesh.ui.TransferActions
import dev.clipmesh.ui.syncWith
import java.util.concurrent.Executors

/** "Send with ClipMesh" share target. Same UI as the launcher entry, opened on Transfer. */
class FileShareActivity : MainActivity() {
    override val initialTab: Tab get() = Tab.TRANSFER
}

/** Transfer tab logic: selection, nearby devices, sending and incoming progress. */
class TransferController(private val host: MainActivity) : ContextWrapper(host), TransferActions {
    private val ui get() = host.ui
    private val main get() = host.main
    private val io = Executors.newSingleThreadExecutor()
    private val thumbnails = Executors.newSingleThreadExecutor()
    private val selected = mutableListOf<Uri>()
    private var sending = false
    private var receiving = false
    private var transferProgress = 0f
    private val incomingProgressListener: (LocalTransferEngine.IncomingProgress) -> Unit = { progress ->
        host.runOnUiThread { showIncomingProgress(progress) }
    }

    fun onResume() {
        LocalTransferEngine.setIncomingProgressListener(incomingProgressListener)
        renderDevices()
    }

    fun onPause() { LocalTransferEngine.setIncomingProgressListener(null) }

    fun onDestroy() {
        io.shutdownNow()
        thumbnails.shutdownNow()
    }

    /** Adds files shared into ClipMesh. Returns true when the intent carried files. */
    fun consumeShareIntent(intent: Intent?): Boolean {
        val uris = extractSharedUris(intent)
        if (uris.isEmpty()) return false
        // Consume once so a configuration change does not re-add already sent files.
        intent?.removeExtra(Intent.EXTRA_STREAM)
        intent?.action = Intent.ACTION_MAIN
        addFiles(uris)
        LocalTransferEngine.discoverNow()
        return true
    }

    // -----------------------------------------------------------------------
    // Selection
    // -----------------------------------------------------------------------

    private fun addFiles(uris: List<Uri>) {
        uris.distinct().filterNot { it in selected }.forEach { uri ->
            selected += uri
            val rawName = displayName(uri)
            val size = querySize(uri)
            val mime = runCatching { contentResolver.getType(uri) }.getOrNull()
                ?: android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(rawName.substringAfterLast('.', "").lowercase())
            val name = PickerNames.friendly(this, uri, rawName, mime)
            ui.files.add(SelectedFile(uri, name, size, mime, null))
            if (mime == null || mime.startsWith("image/")) thumbnails.execute {
                val bitmap = runCatching { host.decodeSampled(uri, 320)?.first }.getOrNull() ?: return@execute
                main.post {
                    val index = ui.files.indexOfFirst { it.uri == uri }
                    if (index >= 0) ui.files[index] = ui.files[index].copy(thumbnail = bitmap.asImageBitmap())
                }
            }
        }
    }

    /** System photo picker (no storage permission); falls back to a media-filtered picker. */
    override fun choosePhotos() {
        val picker = if (android.os.Build.VERSION.SDK_INT >= 33 ||
            (android.os.Build.VERSION.SDK_INT >= 30 && android.os.ext.SdkExtensions.getExtensionVersion(android.os.Build.VERSION_CODES.R) >= 2)
        ) {
            Intent(android.provider.MediaStore.ACTION_PICK_IMAGES)
                .putExtra(android.provider.MediaStore.EXTRA_PICK_IMAGES_MAX, android.provider.MediaStore.getPickImagesMaxLimit())
        } else {
            Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "*/*"
                putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("image/*", "video/*"))
                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                addCategory(Intent.CATEGORY_OPENABLE)
            }
        }
        @Suppress("DEPRECATION")
        runCatching { host.startActivityForResult(picker, PICK_FILES) }.onFailure { chooseFiles() }
    }

    override fun chooseFiles() {
        @Suppress("DEPRECATION")
        host.startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "*/*"
            addCategory(Intent.CATEGORY_OPENABLE)
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }, PICK_FILES)
    }

    override fun clearFiles() {
        selected.clear()
        ui.files.clear()
    }

    override fun removeFile(file: SelectedFile) {
        selected.remove(file.uri)
        ui.files.removeAll { it.uri == file.uri }
    }

    // -----------------------------------------------------------------------
    // Devices + sending
    // -----------------------------------------------------------------------

    fun renderDevices() {
        // File Transfer trust/favorites are independent from encrypted clipboard pairing.
        // A clipboard-paired device must remain visible here as long as its live
        // LAN file receiver is discoverable.
        val devices = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())
        ui.devices.syncWith(devices.map { it.toUi(this) })
        ui.transferStatus = if (devices.isEmpty()) "Looking for devices on this network…" else "${devices.size} device${if (devices.size == 1) "" else "s"} nearby"
    }

    override fun toggleFavorite(device: DeviceUi) {
        LocalTransferEngine.setFavorite(this, device.fingerprint, !LocalTransferEngine.isFavorite(this, device.fingerprint))
        renderDevices()
    }

    override fun send(device: DeviceUi) {
        if (selected.isEmpty()) {
            chooseFiles()
            return
        }
        if (sending) return
        val target = LocalTransferEngine.nearbyDevices().firstOrNull { it.fingerprint == device.fingerprint }
            ?: run { host.toast("${device.alias} is no longer visible"); return }
        sending = true
        transferProgress = 0f
        val fingerprint = target.fingerprint
        ui.sendStates[fingerprint] = SendState.Sending(0f, "Connecting…")
        val outgoing = selected.toList()
        val outgoingId = java.util.UUID.randomUUID().toString()
        var lastNotifiedPercent = -1
        io.execute {
            runCatching {
                LocalTransferEngine.sendUris(this, outgoing, target) { _, _, sentBytes, totalBytes, message ->
                    val fraction = if (totalBytes <= 0L) 0 else ((sentBytes * 1000L) / totalBytes).toInt().coerceIn(0, 1000)
                    main.post {
                        transferProgress = fraction / 1000f
                        ui.sendStates[fingerprint] = SendState.Sending(transferProgress, message)
                        val percent = fraction / 10
                        if (percent != lastNotifiedPercent) {
                            lastNotifiedPercent = percent
                            TransferNotifications.showSending(this, outgoingId, target.alias, message, percent)
                        }
                    }
                }
            }.onSuccess {
                main.post {
                    val sentDescription = if (outgoing.size == 1) displayName(outgoing.first()) else "${outgoing.size} files"
                    // Clear exactly what was sent; anything added meanwhile stays selected.
                    selected.removeAll(outgoing)
                    ui.files.removeAll { it.uri in outgoing }
                    sending = false
                    transferProgress = 1f
                    TransferNotifications.cancelSending(this, outgoingId)
                    ui.sendStates[fingerprint] = SendState.Sent
                    host.toast("Sent $sentDescription to ${target.alias}")
                    // Continue intentionally remains on File Transfer.
                    main.postDelayed({ if (ui.sendStates[fingerprint] == SendState.Sent) ui.sendStates.remove(fingerprint) }, 2_400L)
                    LocalTransferEngine.discoverNow()
                    renderDevices()
                }
            }.onFailure { error ->
                main.post {
                    sending = false
                    ui.sendStates.remove(fingerprint)
                    TransferNotifications.cancelSending(this, outgoingId)
                    ClipMeshDialog.info(host, "Couldn’t send", error.message ?: "The transfer failed.")
                }
            }
        }
    }

    private fun showIncomingProgress(value: LocalTransferEngine.IncomingProgress) {
        val percent = if (value.totalBytes <= 0L) 1000 else ((value.receivedBytes * 1000L) / value.totalBytes).toInt().coerceIn(0, 1000)
        receiving = !value.complete && !value.failed
        val banner = IncomingBanner(
            title = when {
                value.failed -> "Couldn’t receive ${value.fileName} from ${value.senderAlias}"
                value.complete -> "Received from ${value.senderAlias}"
                else -> "Receiving ${value.fileName} from ${value.senderAlias} · ${percent / 10}%"
            },
            fraction = percent / 1000f,
            complete = value.complete,
            failed = value.failed,
        )
        ui.incoming = banner
        if (value.complete || value.failed) main.postDelayed({
            if (ui.incoming == banner) { ui.incoming = null; receiving = false; renderDevices() }
        }, 3_000L)
    }

    // -----------------------------------------------------------------------
    // Receive folder (shown in Settings)
    // -----------------------------------------------------------------------

    fun chooseOutputFolder() {
        @Suppress("DEPRECATION")
        host.startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or Intent.FLAG_GRANT_PREFIX_URI_PERMISSION)
        }, PICK_OUTPUT_FOLDER)
    }

    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == PICK_OUTPUT_FOLDER) {
            if (resultCode != Activity.RESULT_OK || data?.data == null) return
            val uri = data.data!!
            val flags = data.flags and (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            runCatching { contentResolver.takePersistableUriPermission(uri, flags) }
            LocalTransferEngine.setOutputTreeUri(this, uri)
            ui.settingsRevision++
            host.toast("Receive folder updated")
            return
        }
        if (requestCode != PICK_FILES || resultCode != Activity.RESULT_OK || data == null) return
        val picked = mutableListOf<Uri>()
        data.clipData?.let { clip -> for (i in 0 until clip.itemCount) picked += clip.getItemAt(i).uri }
        data.data?.let { picked += it }
        picked.distinct().forEach { uri -> runCatching { contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) } }
        addFiles(picked)
        ui.tab = Tab.TRANSFER
        LocalTransferEngine.discoverNow()
    }

    @Suppress("DEPRECATION")
    private fun extractSharedUris(intent: Intent?): List<Uri> {
        if (intent == null) return emptyList()
        return when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(intent.getParcelableExtra(Intent.EXTRA_STREAM) as? Uri)
            Intent.ACTION_SEND_MULTIPLE -> (intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM) ?: arrayListOf()).toList()
            else -> emptyList()
        }
    }

    private fun displayName(uri: Uri): String {
        runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (index >= 0) return cursor.getString(index) ?: "File"
                }
            }
        }
        return uri.lastPathSegment ?: "File"
    }

    private fun querySize(uri: Uri): Long = runCatching {
        contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else -1L
        } ?: -1L
    }.getOrDefault(-1L)

    companion object { private const val PICK_FILES = 2201; private const val PICK_OUTPUT_FOLDER = 2202 }
}
