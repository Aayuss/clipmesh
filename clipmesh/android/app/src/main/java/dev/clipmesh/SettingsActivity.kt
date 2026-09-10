package dev.clipmesh

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.ClipData
import android.content.ClipboardManager
import android.content.res.ColorStateList
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup
import android.widget.*
import dev.clipmesh.shizuku.ShizukuManager
import dev.clipmesh.fileshare.FileShareActivity
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.fileshare.IncomingRequestUi
import dev.clipmesh.fileshare.NearbyPairingUi
import java.util.UUID

class SettingsActivity : Activity() {
    private lateinit var settingsStore: SettingsStore
    private lateinit var secrets: SecretStore
    private lateinit var shizukuStatus: TextView
    private lateinit var shizukuButton: Button
    private val shizukuUiHandler = Handler(Looper.getMainLooper())
    private val shizukuUiRefresh = object : Runnable {
        override fun run() {
            if (!isFinishing && ::shizukuButton.isInitialized) {
                refreshShizukuUi()
                shizukuUiHandler.postDelayed(this, 1_500L)
            }
        }
    }

    private val pageBackground = Color.rgb(7, 8, 10)
    private val cardBackground = Color.rgb(17, 18, 22)
    private val ink = Color.rgb(246, 242, 233)
    private val muted = Color.rgb(174, 169, 160)
    private val primary = Color.rgb(181, 137, 52)
    private val border = Color.argb(34, 255, 255, 255)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settingsStore = SettingsStore(this)
        secrets = SecretStore(this)
        render()
    }

    override fun onResume() {
        super.onResume()
        IncomingRequestUi.attach(this)
        NearbyPairingUi.attach(this)
        LocalTransferEngine.start(this)
        LocalTransferEngine.discoverNow()
        shizukuUiHandler.removeCallbacks(shizukuUiRefresh)
        shizukuUiHandler.post(shizukuUiRefresh)
    }

    override fun onPause() {
        shizukuUiHandler.removeCallbacks(shizukuUiRefresh)
        IncomingRequestUi.detach(this)
        NearbyPairingUi.detach(this)
        if (!settingsStore.receiveFilesInBackground) LocalTransferEngine.stop()
        super.onPause()
    }

    override fun onDestroy() {
        shizukuUiHandler.removeCallbacks(shizukuUiRefresh)
        super.onDestroy()
    }

    private fun render() {
        window.statusBarColor = pageBackground
        window.navigationBarColor = pageBackground
        if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = 0

        val shell = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(pageBackground) }
        val outer = ScrollView(this).apply { setBackgroundColor(pageBackground); isFillViewport = true }
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(22), dp(18), dp(28)) }
        outer.addView(root)
        shell.addView(outer, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        root.addView(label("Settings", 31f, true, ink))
        root.addView(label("Device, clipboard, receiving and network", 14f, false, muted).apply { setPadding(0, dp(4), 0, dp(16)) })

        val general = card(root)
        general.addView(sectionTitle("GENERAL"))
        general.addView(label(settingsStore.deviceName, 20f, true, ink).apply { setPadding(0, dp(9), 0, dp(2)) })
        general.addView(label("Device name shown to nearby ClipMesh devices", 12f, false, muted).apply { setPadding(0, 0, 0, dp(10)) })
        general.addView(button("Rename device", false) { renameDevice() })

        val clipboardCard = card(root)
        clipboardCard.addView(sectionTitle("CLIPBOARD"))
        val backgroundSwitch = styledSwitch("Background auto-sync", settingsStore.backgroundSync)
        backgroundSwitch.setOnCheckedChangeListener { _, checked ->
            if (checked && (settingsStore.spaceId == null || secrets.loadSpaceKey() == null)) {
                settingsStore.backgroundSync = false
                backgroundSwitch.isChecked = false
                toast("Pair this device first")
            } else {
                settingsStore.backgroundSync = checked
                BackgroundRuntime.restart(this)
            }
        }
        clipboardCard.addView(backgroundSwitch)
        clipboardCard.addView(toggle("Send clipboard", settingsStore.sendEnabled) { settingsStore.sendEnabled = it; restartSyncIfEnabled() })
        clipboardCard.addView(toggle("Receive clipboard", settingsStore.receiveEnabled) { settingsStore.receiveEnabled = it; restartSyncIfEnabled() })
        clipboardCard.addView(toggle("Text + HTML", settingsStore.syncText) { settingsStore.syncText = it })
        clipboardCard.addView(toggle("Images / screenshots", settingsStore.syncImages) { settingsStore.syncImages = it })
        clipboardCard.addView(toggle("Files", settingsStore.syncFiles) { settingsStore.syncFiles = it })
        clipboardCard.addView(toggle("Show remote copy popup", settingsStore.showRemoteCopyOverlay) { settingsStore.showRemoteCopyOverlay = it })
        clipboardCard.addView(toggle("Compatibility watchdog (more battery)", settingsStore.compatibilityWatchdog) {
            settingsStore.compatibilityWatchdog = it; restartSyncIfEnabled()
        })
        clipboardCard.addView(label("Keep the watchdog off unless your ROM misses Accessibility clipboard events.", 12f, false, muted).apply { setPadding(0, dp(5), 0, 0) })

        val receiveCard = card(root)
        receiveCard.addView(sectionTitle("FILE TRANSFER - RECEIVE"))
        receiveCard.addView(toggle("Receive files when the app is not opened", settingsStore.receiveFilesInBackground) {
            settingsStore.receiveFilesInBackground = it
            if (it) BackgroundService.start(this) else { BackgroundRuntime.restart(this); LocalTransferEngine.start(this) }
        })
        receiveCard.addView(toggle("Auto-save from favorited devices", settingsStore.autoAcceptFavoriteFiles) {
            settingsStore.autoAcceptFavoriteFiles = it
        })
        receiveCard.addView(label("Unknown devices always require Accept / Reject. Favorites save automatically only when this option is enabled.", 12f, false, muted).apply { setPadding(0, dp(5), 0, dp(10)) })
        receiveCard.addView(label("Save destination", 12f, true, muted))
        receiveCard.addView(label("Images  ·  Downloads/ClipMesh/Images\nVideos  ·  Downloads/ClipMesh/Videos\nOther files  ·  Downloads/ClipMesh", 13f, false, ink).apply { setPadding(0, dp(7), 0, 0) })

        val accessCard = card(root)
        accessCard.addView(sectionTitle("ANDROID CLIPBOARD ACCESS"))
        accessCard.addView(label("For notification-free background sync, keep the ClipMesh Accessibility helper enabled and authorize Shizuku. Accessibility wakes ClipMesh on relevant events; Shizuku reads the actual clipboard bytes.", 13f, false, muted).apply { setPadding(0, dp(8), 0, dp(12)) })
        shizukuStatus = label("Checking Shizuku…", 13f, false, muted).apply { setPadding(0, 0, 0, dp(10)) }
        accessCard.addView(shizukuStatus)
        shizukuButton = button("Request Shizuku permission") {
            when {
                BackgroundRuntime.debugShizukuBound() -> toast("Shizuku is already connected")
                !ShizukuManager.isShizukuAvailable() -> toast("Start or install Shizuku first")
                ShizukuManager.hasShizukuPermission() -> {
                    BackgroundRuntime.start(this)
                    toast(if (settingsStore.backgroundSync) "Connecting clipboard runtime…" else "Shizuku authorized; enable background sync to connect")
                }
                else -> if (!ShizukuManager.requestShizukuPermission()) toast("Could not request Shizuku permission")
            }
            shizukuUiHandler.postDelayed({ refreshShizukuUi() }, 400L)
        }
        accessCard.addView(shizukuButton)
        accessCard.addView(button("Accessibility settings", false) { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }, fullWidthParams(dp(48)).apply { topMargin = dp(8) })
        accessCard.addView(button("ClipMesh app info", false) { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) }, fullWidthParams(dp(48)).apply { topMargin = dp(8) })

        val privacyCard = card(root)
        privacyCard.addView(sectionTitle("PRIVACY"))
        privacyCard.addView(label("Excluded apps are ignored by ClipMesh's Android exclusion helper so sensitive clipboard content is not intentionally captured from them.", 13f, false, muted).apply { setPadding(0, dp(8), 0, dp(10)) })
        privacyCard.addView(button("Choose excluded apps", false) { startActivity(Intent(this, ExclusionActivity::class.java)) })

        val networkCard = card(root)
        networkCard.addView(sectionTitle("NETWORK"))
        networkCard.addView(label("Nearby file transfer uses direct LAN HTTP on ClipMesh port 53421. Clipboard sync remains a separate encrypted paired-space protocol.", 13f, false, muted).apply { setPadding(0, dp(8), 0, dp(10)) })
        val peers = EditText(this).apply {
            hint = "192.168.1.10:41474\n192.168.1.11:41474"
            minLines = 3; maxLines = 6
            setText(settingsStore.staticPeers.joinToString("\n")); setTextColor(ink); setHintTextColor(muted)
            setPadding(dp(14), dp(10), dp(14), dp(10)); background = rounded(Color.rgb(26, 24, 21), dp(14).toFloat(), border)
        }
        networkCard.addView(peers, fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(10) })
        networkCard.addView(button("Save static peers") { settingsStore.staticPeers = peers.text.lines().map { it.trim() }.filter { it.isNotBlank() }.toSet(); restartSyncIfEnabled(); toast("Static peers saved") })

        val pairingCard = card(root)
        pairingCard.addView(sectionTitle("PAIRING"))
        pairingCard.addView(label("Pairing codes contain the private space key. Treat them like passwords and never sync them as ordinary clipboard content.", 13f, false, muted).apply { setPadding(0, dp(8), 0, dp(10)) })
        pairingCard.addView(button("Copy pairing code") { copyPairingCode() })
        pairingCard.addView(button("Pair with a code", false) { joinPairingCode(null) }, fullWidthParams(dp(48)).apply { topMargin = dp(8) })
        pairingCard.addView(button("Reset all pairing", false) { confirmResetPairing() }, fullWidthParams(dp(48)).apply { topMargin = dp(8) })

        val securityCard = card(root)
        securityCard.addView(sectionTitle("SECURITY"))
        securityCard.addView(label("Clipboard sync is end-to-end encrypted. Nearby file transfer is direct on your local network and is authorized through favorite trust or an explicit incoming approval.", 13f, false, muted).apply { setPadding(0, dp(8), 0, 0) })

        shell.addView(bottomNav(2), LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(72)))
        setContentView(shell)

        if (intent.getBooleanExtra("open_pairing", false)) {
            intent.removeExtra("open_pairing")
            root.post { joinPairingCode(null) }
        }
        intent.getStringExtra(EXTRA_PAIR_URI)?.takeIf { it.startsWith("clipmesh://pair") }?.let {
            intent.removeExtra(EXTRA_PAIR_URI)
            root.post { joinPairingCode(it) }
        }
    }

    private fun bottomNav(selected: Int): android.view.View {
        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER; setPadding(dp(10), dp(8), dp(10), dp(8)); background = rounded(Color.rgb(12, 13, 16), dp(24).toFloat(), border) }
        fun item(title: String, index: Int, click: () -> Unit): TextView = TextView(this).apply {
            text = title; gravity = Gravity.CENTER; textSize = 12f; setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (selected == index) Color.rgb(13, 12, 10) else muted)
            background = rounded(if (selected == index) Color.rgb(188, 145, 57) else Color.TRANSPARENT, dp(18).toFloat(), Color.TRANSPARENT)
            setOnClickListener { click() }
        }
        bar.addView(item("Clipboard", 0) { startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out); finish() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { rightMargin = dp(6) })
        bar.addView(item("File transfer", 1) { LocalTransferEngine.discoverNow(); startActivity(Intent(this, FileShareActivity::class.java)); overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out); finish() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { leftMargin = dp(3); rightMargin = dp(3) })
        bar.addView(item("Settings", 2) {}, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { leftMargin = dp(6) })
        return bar
    }

    private fun renameDevice() {
        ClipMeshDialog.prompt(this, "Rename this device", "Choose the name shown to nearby ClipMesh devices.", settingsStore.deviceName) { value ->
            if (value != null) { settingsStore.deviceName = value; BackgroundRuntime.restart(this); render(); toast("Device name updated") }
        }
    }

    private fun copyPairingCode() {
        val space = settingsStore.spaceId ?: run { toast("Create or join a space first"); return }
        val key = secrets.loadSpaceKey() ?: run { toast("Space key missing"); return }
        val uri = Pairing.toUri(Pairing.PairingData(space, key, settingsStore.deviceName, settingsStore.deviceId))
        (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("ClipMesh pairing code", uri))
        toast("Pairing code copied - ClipMesh will not sync it")
    }

    private fun joinPairingCode(initial: String?) {
        ClipMeshDialog.prompt(this, "Pair with another device", "Paste a pairing code from a trusted ClipMesh device.", initial.orEmpty(), multiline = true) { value ->
            if (value != null) { val result = runCatching { Pairing.parse(value.trim()) }; val parsed = result.getOrNull(); if (parsed == null) toast(result.exceptionOrNull()?.message ?: "Invalid pairing code") else { BackgroundRuntime.stop(); settingsStore.spaceId = parsed.spaceId; secrets.saveSpaceKey(parsed.key); settingsStore.clearKnownPeers(); parsed.deviceId?.takeIf { it != settingsStore.deviceId }?.let { settingsStore.seedPeer(it, parsed.name) }; settingsStore.backgroundSync = true; BackgroundRuntime.start(this); toast("Joined private space") } }
        }
    }

    private fun refreshShizukuUi() {
        when {
            BackgroundRuntime.debugShizukuBound() -> {
                shizukuStatus.text = "Connected - background clipboard access is ready"
                shizukuButton.text = "Shizuku connected"
                shizukuButton.isEnabled = false
            }
            ShizukuManager.isShizukuAvailable() && ShizukuManager.hasShizukuPermission() -> {
                shizukuStatus.text = if (settingsStore.backgroundSync) {
                    "Authorized - clipboard runtime will reconnect automatically"
                } else {
                    "Authorized - enable background sync when needed"
                }
                shizukuButton.text = "Shizuku authorized"
                shizukuButton.isEnabled = settingsStore.backgroundSync
            }
            ShizukuManager.isShizukuAvailable() -> {
                shizukuStatus.text = "Shizuku is running but ClipMesh is not authorized"
                shizukuButton.text = "Request Shizuku permission"
                shizukuButton.isEnabled = true
            }
            else -> {
                shizukuStatus.text = "Shizuku is not connected"
                shizukuButton.text = "Request Shizuku permission"
                shizukuButton.isEnabled = true
            }
        }
    }

    private fun confirmResetPairing() {
        ClipMeshDialog.confirm(this, "Reset all ClipMesh pairing?", "This permanently replaces this device's ClipMesh identity and private space, clears every remembered device and forces all devices to pair again.") { accepted -> if (accepted) resetPairingNow() }
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
        startSyncService()
        toast("Pairing reset. Pair your other devices again.")
        finish()
    }

    private fun restartSyncIfEnabled() {
        if (!settingsStore.backgroundSync) return
        BackgroundRuntime.stop()
        startSyncService()
    }

    private fun startSyncService() { BackgroundRuntime.start(this) }

    private fun card(root: LinearLayout): LinearLayout {
        val view = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(17), dp(18), dp(17))
            background = rounded(cardBackground, dp(18).toFloat(), border)
            elevation = dp(1).toFloat()
        }
        root.addView(view, fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(14) })
        return view
    }

    private fun sectionTitle(text: String) = label(text, 12f, true, muted)

    private fun label(text: String, size: Float, bold: Boolean, color: Int) = TextView(this).apply {
        this.text = text
        textSize = size
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun styledSwitch(text: String, checked: Boolean) = Switch(this).apply {
        this.text = text
        isChecked = checked
        textSize = 15f
        setTextColor(ink)
        setPadding(0, dp(7), 0, dp(7))
        val states = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
        thumbTintList = ColorStateList(states, intArrayOf(Color.rgb(188, 145, 57), Color.rgb(174,169,160)))
        trackTintList = ColorStateList(states, intArrayOf(Color.rgb(232,145,60), Color.rgb(62,58,54)))
    }

    private fun toggle(text: String, checked: Boolean, changed: (Boolean) -> Unit) = styledSwitch(text, checked).apply {
        setOnCheckedChangeListener { _, value -> changed(value) }
    }

    private fun button(text: String, primaryStyle: Boolean = true, clicked: () -> Unit) = Button(this).apply {
        this.text = text
        isAllCaps = false
        textSize = 14f
        setTypeface(typeface, Typeface.BOLD)
        setTextColor(if (primaryStyle) Color.rgb(13,12,10) else ink)
        background = rounded(if (primaryStyle) primary else Color.rgb(24, 25, 30), dp(16).toFloat(), if (primaryStyle) primary else border)
        minHeight = dp(46)
        setOnClickListener {
            performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP)
            animate().scaleX(.97f).scaleY(.97f).setDuration(55).withEndAction {
                animate().scaleX(1f).scaleY(1f).setDuration(90).start()
            }.start()
            clicked()
        }
    }

    private fun rounded(fill: Int, radius: Float, stroke: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        setColor(fill)
        cornerRadius = radius
        setStroke(dp(1), stroke)
    }

    private fun fullWidthParams(height: Int) = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, height)
    private fun toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object { const val EXTRA_PAIR_URI = "pair_uri" }

}
