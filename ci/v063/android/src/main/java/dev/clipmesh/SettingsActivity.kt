package dev.clipmesh

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.shizuku.ShizukuManager
import dev.clipmesh.ui.SettingsActions
import dev.clipmesh.ui.SettingsSnapshot
import dev.clipmesh.ui.Tab
import java.util.UUID

/**
 * Settings is a tab of [MainActivity]. This activity remains only so existing
 * deep links / intents that target it still land on the right screen.
 */
class SettingsActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val forward = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(MainActivity.EXTRA_TAB, Tab.SETTINGS.name)
        intent.getStringExtra(EXTRA_PAIR_URI)?.let { forward.data = Uri.parse(it) }
        startActivity(forward)
        finish()
        @Suppress("DEPRECATION")
        overridePendingTransition(0, 0)
    }

    companion object { const val EXTRA_PAIR_URI = "pair_uri" }
}

/** Settings tab logic. Every mutation bumps [dev.clipmesh.ui.ClipMeshUi.settingsRevision]. */
class SettingsController(private val host: MainActivity) : SettingsActions {
    private val settingsStore get() = host.settings
    private val secrets get() = host.secrets
    private var shizukuState: Triple<String, String, Boolean> = Triple("Checking…", "Connect", false)

    private fun changed() { host.ui.settingsRevision++ }

    fun onResume() { refreshShizukuUi() }
    fun onPause() = Unit

    override fun snapshot(): SettingsSnapshot = SettingsSnapshot(
        deviceName = settingsStore.deviceName,
        deviceId = settingsStore.deviceId.toString().let { "${it.take(8)}…${it.takeLast(4)}" },
        backgroundSync = settingsStore.backgroundSync,
        sendEnabled = settingsStore.sendEnabled,
        receiveEnabled = settingsStore.receiveEnabled,
        syncText = settingsStore.syncText,
        syncImages = settingsStore.syncImages,
        syncFiles = settingsStore.syncFiles,
        remotePopup = settingsStore.showRemoteCopyOverlay,
        watchdog = settingsStore.compatibilityWatchdog,
        receiveInBackground = settingsStore.receiveFilesInBackground,
        autoAcceptFavorites = settingsStore.autoAcceptFavoriteFiles,
        outputFolder = LocalTransferEngine.outputFolderLabel(host).let { if (it == "Downloads/ClipMesh") "Downloads/ClipMesh · images and videos in subfolders" else it },
        shizukuStatus = shizukuState.first,
        shizukuAction = shizukuState.second,
        shizukuActionEnabled = shizukuState.third,
        staticPeers = settingsStore.staticPeers.joinToString("\n"),
        version = BuildConfig.VERSION_NAME,
    )

    // -- Device --------------------------------------------------------------

    override fun rename() {
        ClipMeshDialog.prompt(host, "Rename this device", "Shown to your other ClipMesh devices.", settingsStore.deviceName, confirmLabel = "Save") { value ->
            val name = value?.trim().orEmpty()
            if (name.isEmpty()) return@prompt
            settingsStore.deviceName = name
            BackgroundRuntime.restart(host)
            changed(); host.refreshHome()
            host.toast("Device renamed")
        }
    }

    // -- Clipboard -------------------------------------------------------------

    override fun setBackgroundSync(value: Boolean) {
        if (value && (settingsStore.spaceId == null || secrets.loadSpaceKey() == null)) {
            settingsStore.backgroundSync = false
            host.toast("Pair this device first")
        } else {
            settingsStore.backgroundSync = value
            BackgroundRuntime.restart(host)
        }
        changed(); host.refreshHome()
    }

    override fun setSend(value: Boolean) { settingsStore.sendEnabled = value; restartSyncIfEnabled(); changed() }
    override fun setReceive(value: Boolean) { settingsStore.receiveEnabled = value; restartSyncIfEnabled(); changed() }
    override fun setSyncText(value: Boolean) { settingsStore.syncText = value; changed() }
    override fun setSyncImages(value: Boolean) { settingsStore.syncImages = value; changed() }
    override fun setSyncFiles(value: Boolean) { settingsStore.syncFiles = value; changed() }
    override fun setRemotePopup(value: Boolean) { settingsStore.showRemoteCopyOverlay = value; changed() }
    override fun setWatchdog(value: Boolean) { settingsStore.compatibilityWatchdog = value; restartSyncIfEnabled(); changed() }

    // -- File transfer ---------------------------------------------------------

    override fun setReceiveInBackground(value: Boolean) {
        settingsStore.receiveFilesInBackground = value
        if (value) BackgroundService.start(host) else { BackgroundRuntime.restart(host); LocalTransferEngine.start(host) }
        changed()
    }

    override fun setAutoAcceptFavorites(value: Boolean) { settingsStore.autoAcceptFavoriteFiles = value; changed() }
    override fun chooseOutputFolder() = host.transfer.chooseOutputFolder()

    // -- Android access ----------------------------------------------------------

    fun refreshShizukuUi() {
        val next = when {
            BackgroundRuntime.debugShizukuBound() -> Triple("Connected · background clipboard ready", "Connected", false)
            ShizukuManager.isShizukuAvailable() && ShizukuManager.hasShizukuPermission() -> Triple(
                if (settingsStore.backgroundSync) "Authorized · reconnecting automatically" else "Authorized · turn on background sync",
                "Authorized", settingsStore.backgroundSync,
            )
            ShizukuManager.isShizukuAvailable() -> Triple("Running, but ClipMesh isn't authorized", "Authorize", true)
            else -> Triple("Not running. Start Shizuku first", "Authorize", true)
        }
        if (next != shizukuState) { shizukuState = next; changed() }
    }

    override fun shizuku() {
        when {
            BackgroundRuntime.debugShizukuBound() -> host.toast("Shizuku is already connected")
            !ShizukuManager.isShizukuAvailable() -> host.toast("Start or install Shizuku first")
            ShizukuManager.hasShizukuPermission() -> {
                BackgroundRuntime.start(host)
                host.toast(if (settingsStore.backgroundSync) "Connecting clipboard runtime…" else "Authorized. Turn on background sync to connect")
            }
            else -> if (!ShizukuManager.requestShizukuPermission()) host.toast("Could not request Shizuku permission")
        }
        host.main.postDelayed({ refreshShizukuUi() }, 400L)
    }

    override fun accessibility() { host.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
    override fun exclusions() { host.startActivity(Intent(host, ExclusionActivity::class.java)) }
    override fun appInfo() { host.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${host.packageName}"))) }

    // -- Pairing -------------------------------------------------------------------

    override fun pairWithCode() = joinPairingCode(null)

    fun joinPairingCode(initial: String?) {
        ClipMeshDialog.prompt(host, "Pair with a code", "Paste a pairing code from a trusted ClipMesh device.", initial.orEmpty(), multiline = true, confirmLabel = "Pair") { value ->
            if (value == null) return@prompt
            val result = runCatching { Pairing.parse(value.trim()) }
            val parsed = result.getOrNull()
            if (parsed == null) { host.toast(result.exceptionOrNull()?.message ?: "Invalid pairing code"); return@prompt }
            BackgroundRuntime.stop()
            settingsStore.spaceId = parsed.spaceId
            secrets.saveSpaceKey(parsed.key)
            settingsStore.clearKnownPeers()
            parsed.deviceId?.takeIf { it != settingsStore.deviceId }?.let { settingsStore.seedPeer(it, parsed.name) }
            settingsStore.backgroundSync = true
            BackgroundRuntime.start(host)
            changed(); host.refreshHome()
            host.toast("Joined private space")
        }
    }

    override fun copyPairingCode() {
        val space = settingsStore.spaceId ?: run { host.toast("Create or join a space first"); return }
        val key = secrets.loadSpaceKey() ?: run { host.toast("Space key missing"); return }
        val uri = Pairing.toUri(Pairing.PairingData(space, key, settingsStore.deviceName, settingsStore.deviceId))
        (host.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("ClipMesh pairing code", uri))
        host.toast("Pairing code copied. ClipMesh won't sync it")
    }

    override fun resetPairing() {
        ClipMeshDialog.confirm(
            host, "Reset all pairing?",
            "This replaces this device's identity and private space and forgets every device. All devices must pair again.",
            confirmLabel = "Reset", destructive = true,
        ) { accepted -> if (accepted) resetPairingNow() }
    }

    private fun resetPairingNow() {
        BackgroundRuntime.stop()
        val newDeviceId = UUID.randomUUID()
        val data = Pairing.createSpace(settingsStore.deviceName, newDeviceId)
        settingsStore.deviceId = newDeviceId
        settingsStore.spaceId = data.spaceId
        secrets.saveSpaceKey(data.key)
        settingsStore.clearKnownPeers()
        settingsStore.staticPeers = emptySet()
        settingsStore.backgroundSync = true
        BackgroundRuntime.start(host)
        changed(); host.refreshHome()
        host.toast("Pairing reset. Pair your other devices again")
    }

    override fun saveStaticPeers(value: String) {
        settingsStore.staticPeers = value.lines().map { it.trim() }.filter { it.isNotBlank() }.toSet()
        restartSyncIfEnabled()
        changed()
        host.toast("Static peers saved")
    }

    private fun restartSyncIfEnabled() {
        if (!settingsStore.backgroundSync) return
        BackgroundRuntime.stop()
        BackgroundRuntime.start(host)
    }
}
