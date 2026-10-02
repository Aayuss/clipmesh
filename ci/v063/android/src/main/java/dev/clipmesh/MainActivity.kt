package dev.clipmesh

import android.Manifest
import android.app.Dialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.view.Gravity
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.ui.graphics.asImageBitmap
import dev.clipmesh.fileshare.IncomingRequestUi
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.fileshare.NearbyPairingManager
import dev.clipmesh.fileshare.NearbyPairingUi
import dev.clipmesh.fileshare.TransferController
import dev.clipmesh.ui.ClipMeshRoot
import dev.clipmesh.ui.ClipMeshUi
import dev.clipmesh.ui.ClipPreview
import dev.clipmesh.ui.ClipboardActions
import dev.clipmesh.ui.DeviceUi
import dev.clipmesh.ui.EmberTheme
import dev.clipmesh.ui.PeerUi
import dev.clipmesh.ui.SyncHealth
import dev.clipmesh.ui.Tab
import dev.clipmesh.ui.guessMobile
import dev.clipmesh.ui.syncWith
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Single-activity host for the Clipboard, Transfer and Settings tabs. The share
 * target ([dev.clipmesh.fileshare.FileShareActivity]) is a subclass that opens on
 * the Transfer tab, so every entry point renders the exact same UI.
 */
open class MainActivity : ComponentActivity(), ClipboardActions {
    internal lateinit var settings: SettingsStore
    internal lateinit var secrets: SecretStore
    internal val ui = ClipMeshUi()
    internal lateinit var transfer: TransferController
    internal lateinit var settingsController: SettingsController
    internal val main = Handler(Looper.getMainLooper())
    private val previewWorker = Executors.newSingleThreadExecutor()
    private var nearbyCodeDialog: Dialog? = null
    private var resumed = false
    private var previewGeneration = 0

    protected open val initialTab: Tab get() = Tab.CLIPBOARD

    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener { renderClipboardContent() }

    // Event-driven refresh: engine/runtime/preferences changes post one coalesced
    // render. The only timers are one-shots for known future state changes
    // (a nearby device expiring, a peer going from Online to Last seen).
    private val render = Runnable { if (resumed) { refreshHome(); transfer.renderDevices(); armTransitions() } }
    private val transition = Runnable { requestRender() }
    private val engineListener: () -> Unit = { requestRender() }
    private val peersListener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == null || key == "known_peers_json" || key == "device_name") requestRender()
    }

    internal fun requestRender() {
        main.removeCallbacks(render)
        main.postDelayed(render, 100L)
    }

    private fun armTransitions() {
        main.removeCallbacks(transition)
        val now = System.currentTimeMillis()
        val peerFlip = settings.knownPeers().mapNotNull { peer ->
            (peer.lastSeenMs + 90_000L - now).takeIf { peer.lastSeenMs > 0 && it > 0 }
        }.minOrNull()
        val next = listOfNotNull(peerFlip?.plus(50L), LocalTransferEngine.nextDeviceExpiryInMs()).minOrNull() ?: return
        main.postDelayed(transition, next)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)
        if (BuildConfig.DEBUG) {
            intent.getStringExtra("clipmesh_ci_favorite")?.takeIf { it.isNotBlank() }?.let {
                LocalTransferEngine.setFavorite(this, it, true)
            }
        }
        BackgroundService.start(this)
        settings = SettingsStore(this)
        secrets = SecretStore(this)
        ensureLocalClipboardSpace()
        BackgroundRuntime.start(this)
        requestNotificationPermission()
        transfer = TransferController(this)
        settingsController = SettingsController(this)
        ui.tab = (savedInstanceState?.getString(STATE_TAB) ?: intent.getStringExtra(EXTRA_TAB))
            ?.let { runCatching { Tab.valueOf(it) }.getOrNull() } ?: initialTab
        transfer.consumeShareIntent(intent)
        setContent {
            EmberTheme { ClipMeshRoot(ui, this, transfer, settingsController) }
        }
        refreshHome()
        consumePairingIntent(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_TAB, ui.tab.name)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (transfer.consumeShareIntent(intent)) ui.tab = Tab.TRANSFER
        intent.getStringExtra(EXTRA_TAB)?.let { runCatching { ui.tab = Tab.valueOf(it) } }
        consumePairingIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        IncomingRequestUi.attach(this)
        NearbyPairingUi.attach(this) { refreshHome(); renderNearbyPairDevices() }
        BackgroundRuntime.start(this)
        LocalTransferEngine.start(this)
        transfer.onResume()
        LocalTransferEngine.discoverNow()
        BackgroundRuntime.captureNow()
        settingsController.onResume()
        (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).addPrimaryClipChangedListener(clipboardListener)
        LocalTransferEngine.setDevicesListener(engineListener)
        BackgroundRuntime.statusListener = engineListener
        getSharedPreferences("clipmesh_settings", Context.MODE_PRIVATE).registerOnSharedPreferenceChangeListener(peersListener)
        requestRender()
        renderClipboardContent()
    }

    override fun onPause() {
        resumed = false
        main.removeCallbacks(render)
        main.removeCallbacks(transition)
        LocalTransferEngine.setDevicesListener(null)
        BackgroundRuntime.statusListener = null
        getSharedPreferences("clipmesh_settings", Context.MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(peersListener)
        (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).removePrimaryClipChangedListener(clipboardListener)
        settingsController.onPause()
        transfer.onPause()
        IncomingRequestUi.detach(this)
        NearbyPairingUi.detach(this)
        if (!settings.receiveFilesInBackground) LocalTransferEngine.stop()
        super.onPause()
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        previewWorker.shutdownNow()
        transfer.onDestroy()
        super.onDestroy()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        // Android 10+ only exposes the clipboard to the focused app, so re-read on focus.
        if (hasFocus) renderClipboardContent()
    }

    @Deprecated("Activity result API is not used to keep the dependency surface minimal")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        transfer.onActivityResult(requestCode, resultCode, data)
    }

    // -----------------------------------------------------------------------
    // Clipboard tab
    // -----------------------------------------------------------------------

    internal fun refreshHome() {
        val paired = settings.spaceId != null && secrets.loadSpaceKey() != null
        val runtime = BackgroundRuntime.status
        when {
            !paired -> { ui.health = SyncHealth.OFF; ui.healthText = "Not paired" }
            !settings.backgroundSync -> { ui.health = SyncHealth.OFF; ui.healthText = "Sync paused" }
            runtime.contains("Shizuku permission", ignoreCase = true) -> { ui.health = SyncHealth.RECOVERING; ui.healthText = "Needs Shizuku" }
            runtime == "Stopped" || runtime.contains("fail", ignoreCase = true) || runtime.contains("error", ignoreCase = true) -> { ui.health = SyncHealth.STOPPED; ui.healthText = "Sync stopped" }
            runtime.contains("start", ignoreCase = true) || runtime.contains("connect", ignoreCase = true) -> { ui.health = SyncHealth.RECOVERING; ui.healthText = "Connecting…" }
            else -> { ui.health = SyncHealth.ON; ui.healthText = "Sync on" }
        }
        ui.deviceName = settings.deviceName
        renderPeers()
        renderNearbyPairDevices()
        settingsController.refreshShizukuUi()
    }

    private fun renderPeers() {
        val now = System.currentTimeMillis()
        val nearbyByName = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())
            .associateBy { it.alias.trim().lowercase() }
        val next = settings.knownPeers().map { peer ->
            val online = peer.lastSeenMs > 0 && now - peer.lastSeenMs < 90_000L
            val caption = when {
                online -> "Online"
                peer.lastSeenMs == 0L -> "Paired"
                else -> "Last seen ${lastSeen(peer.lastSeenMs)}"
            }
            val type = nearbyByName[peer.name.trim().lowercase()]?.deviceType
            PeerUi(peer.deviceId.toString(), peer.name, online, caption, type?.let { it == "mobile" } ?: guessMobile(peer.name))
        }
        ui.peers.syncWith(next)
    }

    private fun renderNearbyPairDevices() {
        val pairedNames = settings.knownPeers().map { it.name.trim().lowercase() }.toSet()
        val devices = LocalTransferEngine.nearbyDevices().filterNot { pairedNames.contains(it.alias.trim().lowercase()) };
        ui.nearby.syncWith(devices.map { it.toUi(this) })
    }

    override fun refreshDevices() {
        LocalTransferEngine.discoverNow()
        main.postDelayed({ refreshHome(); transfer.renderDevices() }, 450L)
    }

    override fun pairWithCode() = settingsController.pairWithCode()

    override fun pairNearby(device: DeviceUi) {
        val target = LocalTransferEngine.nearbyDevices().firstOrNull { it.fingerprint == device.fingerprint }
            ?: run { toast("${device.alias} is no longer visible"); return }
        startNearbyPair(target)
    }

    override fun removePeer(peer: PeerUi) {
        ClipMeshDialog.confirm(this, "Remove ${peer.name}?", "It will stop syncing with this device until you pair again.", confirmLabel = "Remove", destructive = true) { accepted ->
            if (!accepted) return@confirm
            settings.forgetPeer(java.util.UUID.fromString(peer.id))
            BackgroundRuntime.restart(this)
            refreshHome()
            toast("Removed ${peer.name}")
        }
    }

    override fun openPreview() {
        renderClipboardContent()
        ui.previewOpen = true
    }

    private fun startNearbyPair(device: LocalTransferEngine.TransferDevice) {
        ensureLocalClipboardSpace()
        val space = settings.spaceId ?: run { toast("ClipMesh could not prepare pairing"); return }
        val key = secrets.loadSpaceKey() ?: run { toast("ClipMesh could not prepare its encryption key"); return }
        val credential = Pairing.toUri(Pairing.PairingData(space, key, settings.deviceName, settings.deviceId))
        ui.pairingWith = device.fingerprint
        NearbyPairingManager.pairClipboard(this, device, credential, { value -> runOnUiThread { showNearbyCode(device.alias, value) } }, { result ->
            runOnUiThread {
                nearbyCodeDialog?.dismiss(); nearbyCodeDialog = null
                ui.pairingWith = null
                result.fold(
                    { toast("Paired with ${device.alias}"); LocalTransferEngine.discoverNow(); refreshHome() },
                    { toast(it.message ?: "Pairing failed"); refreshHome() },
                )
            }
        })
    }

    private fun showNearbyCode(device: String, value: String) {
        nearbyCodeDialog?.dismiss()
        val code = TextView(this).apply {
            text = value; textSize=46f; typeface = Typeface.MONOSPACE; gravity = Gravity.CENTER
            setTextColor(Color.WHITE); letterSpacing = .14f
        }
        nearbyCodeDialog = ClipMeshDialog.code(this, "Verification code", "Type this code on $device. This closes by itself when pairing completes.", code) {
            ui.pairingWith = null
        }
    }

    private fun renderClipboardContent() {
        if (!resumed && !hasWindowFocus()) return
        val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = runCatching { manager.primaryClip }.getOrNull()
        val generation = ++previewGeneration
        if (clip == null || clip.itemCount == 0) { ui.preview = ClipPreview.Empty; return }
        val first = clip.getItemAt(0)
        val description = clip.description
        val uris = (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri }
        val text = first.text?.toString()
        previewWorker.execute {
            val preview = runCatching { buildPreview(uris, description, text, first) }.getOrDefault(ClipPreview.Empty)
            main.post { if (generation == previewGeneration && !isDestroyed) ui.preview = preview }
        }
    }

    private fun buildPreview(uris: List<Uri>, description: android.content.ClipDescription, text: String?, first: ClipData.Item): ClipPreview {
        val imageUri = uris.firstOrNull { uri ->
            val mime = runCatching { contentResolver.getType(uri) }.getOrNull()
            mime?.startsWith("image/") == true || (0 until description.mimeTypeCount).any { description.getMimeType(it).startsWith("image/") }
        }
        if (imageUri != null) {
            val bitmap = decodeSampled(imageUri, 1280)
            if (bitmap != null) {
                val name = displayName(imageUri)
                val label = listOfNotNull(name, "${bitmap.second.first}×${bitmap.second.second}").joinToString(" · ")
                return ClipPreview.Image(bitmap.first.asImageBitmap(), label)
            }
        }
        val actualText = text ?: runCatching { first.coerceToText(this).toString() }.getOrNull()
        if (!actualText.isNullOrBlank() && uris.isEmpty()) return ClipPreview.Text(actualText.take(16_000))
        if (uris.isNotEmpty()) {
            val names = uris.mapIndexed { i, uri -> displayName(uri) ?: "File ${i + 1}" }
            return ClipPreview.Files(names, null)
        }
        if (!actualText.isNullOrBlank()) return ClipPreview.Text(actualText.take(16_000))
        return ClipPreview.Empty
    }

    /** Returns the sampled bitmap plus the original pixel size. */
    internal fun decodeSampled(uri: Uri, maxSide: Int): Pair<Bitmap, Pair<Int, Int>>? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        // A bounds-only decode always returns null; success is reported through outWidth/outHeight.
        (contentResolver.openInputStream(uri) ?: return null).use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= maxSide || bounds.outHeight / (sample * 2) >= maxSide) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val bitmap = contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) } ?: return null
        return bitmap to (bounds.outWidth to bounds.outHeight)
    }

    internal fun displayName(uri: Uri): String? = runCatching {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    }.getOrNull() ?: uri.lastPathSegment

    // -----------------------------------------------------------------------
    // Pairing / space helpers (shared with Settings)
    // -----------------------------------------------------------------------

    internal fun ensureLocalClipboardSpace() {
        if (settings.spaceId != null && secrets.loadSpaceKey() != null) return
        val data = Pairing.createSpace(settings.deviceName, settings.deviceId)
        settings.spaceId = data.spaceId
        secrets.saveSpaceKey(data.key)
        settings.clearKnownPeers()
    }

    private fun consumePairingIntent(incoming: Intent?) {
        val data = incoming?.dataString ?: return
        if (data.startsWith("clipmesh://pair")) {
            incoming.data = null
            ui.tab = Tab.SETTINGS
            main.post { settingsController.joinPairingCode(data) }
        }
    }

    private fun lastSeen(timestamp: Long): String {
        val elapsed = (System.currentTimeMillis() - timestamp).coerceAtLeast(0L)
        return when {
            elapsed < 60_000L -> "just now"
            elapsed < TimeUnit.HOURS.toMillis(1) -> "${elapsed / 60_000L}m ago"
            elapsed < TimeUnit.DAYS.toMillis(1) -> "${elapsed / TimeUnit.HOURS.toMillis(1)}h ago"
            else -> "${elapsed / TimeUnit.DAYS.toMillis(1)}d ago"
        }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 200)
        }
    }

    internal fun toast(text: String) { ui.toast(text) }

    companion object {
        const val EXTRA_TAB = "clipmesh_tab"
        private const val STATE_TAB = "clipmesh_tab_state"
    }
}

internal fun LocalTransferEngine.TransferDevice.toUi(context: Context) = DeviceUi(
    fingerprint = fingerprint,
    alias = alias,
    model = deviceModel,
    mobile = deviceType == "mobile",
    favorite = LocalTransferEngine.isFavorite(context, fingerprint),
)
