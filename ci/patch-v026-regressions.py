from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace(path: Path, old: str, new: str, label: str, count=None):
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found == 0 or (count is not None and found != count):
        raise SystemExit(f"{label}: expected {count or 'at least one'} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# Device removal is enforced by the encrypted clipboard engine on every desktop
# platform. Removing only a UI row would be insecure because the shared-space
# discovery packet would immediately recreate it.
config = project / "apps/desktop/src/config.rs"
core_main = project / "apps/desktop/src/main.rs"
network_core = project / "apps/desktop/src/network.rs"
replace(config,
    '    pub static_peers: Vec<SocketAddr>,',
    '    pub static_peers: Vec<SocketAddr>,\n    #[serde(default)]\n    pub blocked_devices: Vec<Uuid>,',
    "desktop blocked-device config", 1)
replace(config,
    '            static_peers: Vec::new(),',
    '            static_peers: Vec::new(),\n            blocked_devices: Vec::new(),',
    "desktop blocked-device default", 1)
replace(config,
    '    pub fn seed_peer(space_id: Uuid, device_id: Uuid, name: &str) -> Result<()> {',
    '''    pub fn forget_peer(space_id: Uuid, device_id: Uuid) -> Result<()> {
        let peers = Self::load_known_peers(space_id)?.into_iter().filter(|peer| peer.device_id != device_id).collect();
        Self::save_known_peers(space_id, peers)
    }

    pub fn seed_peer(space_id: Uuid, device_id: Uuid, name: &str) -> Result<()> {''',
    "desktop forget peer storage", 1)
replace(core_main,
    '    SetName { #[arg(long)] name: String },',
    '    SetName { #[arg(long)] name: String },\n    ForgetPeer { device_id: uuid::Uuid },',
    "desktop forget CLI", 1)
replace(core_main,
    '        Command::SetName{name} => set_name(name),',
    '        Command::SetName{name} => set_name(name),\n        Command::ForgetPeer{device_id} => forget_peer(device_id),',
    "desktop forget dispatch", 1)
replace(core_main,
    'fn set_name(name:String)->Result<()> {',
    '''fn forget_peer(device_id:uuid::Uuid)->Result<()> {
    let mut cfg=Config::load()?;
    if device_id==cfg.device_id { bail!("cannot remove this device"); }
    if !cfg.blocked_devices.contains(&device_id) { cfg.blocked_devices.push(device_id); }
    cfg.save()?; Config::forget_peer(cfg.space_id,device_id)?;
    println!("Removed paired device {device_id}"); Ok(())
}

fn set_name(name:String)->Result<()> {''',
    "desktop forget function", 1)
replace(core_main,
    '    cfg.space_id=pairing.space_id;\n\n    secrets::save',
    '    cfg.space_id=pairing.space_id;\n    if let Some(source)=pairing.source_device_id { cfg.blocked_devices.retain(|id| *id != source); }\n\n    secrets::save',
    "desktop explicit pairing unblock", 1)
replace(network_core,
    '                if packet.device_id==cfg.device_id || packet.verify(&master,cfg.space_id).is_err() { continue; }',
    '                if packet.device_id==cfg.device_id || cfg.blocked_devices.contains(&packet.device_id) || packet.verify(&master,cfg.space_id).is_err() { continue; }',
    "desktop block discovery", 1)
replace(network_core,
    '    if remote_hello.device_id==cfg.device_id { bail!("self connection"); }',
    '    if remote_hello.device_id==cfg.device_id { bail!("self connection"); }\n    if cfg.blocked_devices.contains(&remote_hello.device_id) { bail!("removed peer"); }',
    "desktop block authenticated peer", 1)


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    engine = java / "fileshare/LocalTransferEngine.kt"
    bridge = java / "clipboard/ClipboardBridge.kt"
    tracker = java / "exclusion/ForegroundTracker.kt"
    access = java / "exclusion/ExclusionAccessibilityService.kt"
    store = java / "SettingsStore.kt"
    network = java / "network/NetworkEngine.kt"
    main = java / "MainActivity.kt"
    share = java / "fileshare/FileShareActivity.kt"
    settings_ui = java / "SettingsActivity.kt"
    gradle = project / "android/app/build.gradle.kts"

    replace(gradle, "versionCode = 15", "versionCode = 16", "Android version code", 1)
    replace(gradle, 'versionName = "0.2.5"', 'versionName = "0.2.6"', "Android version", 1)
    replace(share, 'import dev.clipmesh.MainActivity', 'import dev.clipmesh.MainActivity\nimport dev.clipmesh.ClipMeshDialog', "Android custom dialog import", 1)

    # Complete the HTTP handshake before either peer starts reading a body.
    replace(engine,
        '        val length = headers["content-length"]?.toLongOrNull()?.coerceAtLeast(0L) ?: 0L',
        '''        val length = headers["content-length"]?.toLongOrNull()?.coerceAtLeast(0L) ?: 0L
        if (headers["expect"]?.contains("100-continue", ignoreCase = true) == true) {
            output.write("HTTP/1.1 100 Continue\\r\\n\\r\\n".toByteArray(Charsets.US_ASCII))
            output.flush()
        }''', "Android Expect handshake", 1)

    # Capture ClipData while AccessibilityService still owns the URI permission.
    replace(tracker,
        '    @Volatile var clipboardChanged: (() -> Unit)? = null',
        '    @Volatile var clipboardChanged: ((android.content.ClipData?) -> Unit)? = null',
        "Android clipboard event payload", 1)
    replace(access,
        '''    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        ForegroundTracker.clipboardChanged?.invoke()
    }''',
        '''    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        // Read now: gallery/screenshot content URI grants belong to this system-bound
        // service and may no longer be readable by a later shell/Shizuku snapshot.
        val clip = runCatching { clipboard?.primaryClip }.getOrNull()
        BackgroundRuntime.start(this)
        val callback = ForegroundTracker.clipboardChanged
        if (callback != null) callback(clip) else BackgroundService.start(this, captureCurrent = true)
    }''', "Android event-driven background capture", 1)
    replace(bridge,
        '    private val suppressedFingerprint = AtomicReference<String?>(null)',
        '''    private val suppressedFingerprint = AtomicReference<String?>(null)
    private val accessibilityClip = AtomicReference<ClipData?>(null)
    private val lastRemoteFingerprint = AtomicReference<String?>(null)
    @Volatile private var lastRemoteAppliedAt = 0L''', "Android clipboard dedupe state", 1)
    replace(bridge,
        '        ForegroundTracker.clipboardChanged = { captureNowForAccessibility() }',
        '        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }',
        "Android accessibility callback", 1)
    replace(bridge,
        '    fun captureNowForAccessibility() = captureAsync(fromWatchdog = true)',
        '''    fun captureNowForAccessibility(clip: ClipData? = null) {
        if (clip != null) accessibilityClip.set(clip)
        captureAsync(fromWatchdog = false)
    }''', "Android direct accessibility capture", 1)
    replace(bridge,
        '                val payload = readCurrent(sourcePackage) ?: return@execute',
        '                val payload = readCurrent(sourcePackage, accessibilityClip.getAndSet(null)) ?: return@execute',
        "Android consume event ClipData", 1)
    replace(bridge,
        '    private fun readCurrent(sourcePackage: String?): ClipPayload? {\n        // Shizuku is preferred because Android restricts normal background clipboard reads.',
        '''    private fun readCurrent(sourcePackage: String?, preferredClip: ClipData? = null): ClipPayload? {
        // AccessibilityService is the most reliable source for copied gallery and
        // screenshot URIs because it receives the URI grant with the event.
        preferredClip?.let { readClipData(it, sourcePackage)?.let { payload -> return payload } }
        // Shizuku remains the fallback for OEMs that restrict app clipboard reads.''',
        "Android prefer granted ClipData", 1)
    old_fallback = '''        // Fallback works while ClipMesh has input focus and on some OEM/Android combinations.
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
    }'''
    new_fallback = '''        // Fallback works while ClipMesh has input focus and on some OEM combinations.
        return clipboard.primaryClip?.let { readClipData(it, sourcePackage) }
    }

    private fun readClipData(clip: ClipData, sourcePackage: String?): ClipPayload? {
        if (clip.itemCount == 0) return null
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
    }'''
    replace(bridge, old_fallback, new_fallback, "Android ClipData reader", 1)
    replace(bridge,
        '''        val remoteFingerprint = payload.stableFingerprint()
        suppressedFingerprint.set(remoteFingerprint)
        main.postDelayed({ suppressedFingerprint.compareAndSet(remoteFingerprint, null) }, 1_500L)''',
        '''        val remoteFingerprint = payload.stableFingerprint()
        val now = System.currentTimeMillis()
        // Retries and reconnect outbox delivery must ACK at the network layer but
        // must never rewrite Android's clipboard (or trigger SystemUI) repeatedly.
        if (lastRemoteFingerprint.get() == remoteFingerprint && now - lastRemoteAppliedAt < 30_000L) return
        lastRemoteFingerprint.set(remoteFingerprint)
        lastRemoteAppliedAt = now
        suppressedFingerprint.set(remoteFingerprint)
        main.postDelayed({ suppressedFingerprint.compareAndSet(remoteFingerprint, null) }, 15_000L)''',
        "Android remote write dedupe", 1)

    # A per-peer deny list makes Remove meaningful even though all paired devices
    # still know the shared space secret. Explicit pairing unblocks it again.
    replace(store,
        '    var staticPeers: Set<String>',
        '''    var blockedPeerIds: Set<String>
        get() = prefs.getStringSet("blocked_peer_ids", emptySet())?.toSet() ?: emptySet()
        private set(value) = prefs.edit().putStringSet("blocked_peer_ids", value).apply()

    fun isPeerBlocked(deviceId: UUID) = blockedPeerIds.contains(deviceId.toString())

    @Synchronized fun forgetPeer(deviceId: UUID) {
        saveKnownPeers(parseKnownPeers().filterNot { it.deviceId == deviceId })
        blockedPeerIds = blockedPeerIds + deviceId.toString()
    }

    private fun unblockPeer(deviceId: UUID) { blockedPeerIds = blockedPeerIds - deviceId.toString() }

    var staticPeers: Set<String>''', "Android per-device blocklist", 1)
    replace(store,
        '    fun seedPeer(deviceId: UUID, name: String?) {\n        val peers = parseKnownPeers().toMutableList()',
        '    fun seedPeer(deviceId: UUID, name: String?) {\n        unblockPeer(deviceId)\n        val peers = parseKnownPeers().toMutableList()',
        "Android explicit re-pair unblocks", 1)
    replace(store,
        '    fun rememberPeer(deviceId: UUID, name: String?, address: String, port: Int) {\n        val peers = parseKnownPeers().toMutableList()',
        '    fun rememberPeer(deviceId: UUID, name: String?, address: String, port: Int) {\n        if (isPeerBlocked(deviceId)) return\n        val peers = parseKnownPeers().toMutableList()',
        "Android ignore blocked discovery", 1)
    replace(store,
        '    fun touchPeer(deviceId: UUID, address: String) {\n        val peers = parseKnownPeers().toMutableList()',
        '    fun touchPeer(deviceId: UUID, address: String) {\n        if (isPeerBlocked(deviceId)) return\n        val peers = parseKnownPeers().toMutableList()',
        "Android ignore blocked connection", 1)
    replace(network,
        '                    if (d.deviceId == settings.deviceId) continue',
        '                    if (d.deviceId == settings.deviceId || settings.isPeerBlocked(d.deviceId)) continue',
        "Android block discovery", 1)
    replace(network,
        '            if (peerId == settings.deviceId) throw IllegalStateException("self connection")',
        '            if (peerId == settings.deviceId) throw IllegalStateException("self connection")\n            if (settings.isPeerBlocked(peerId)) throw IllegalStateException("removed peer")',
        "Android block authenticated peer", 1)

    # Hide already-paired devices from both nearby lists (device IDs are not part
    # of file discovery yet, so normalized display name is the safe bridge).
    replace(main,
        'val devices=LocalTransferEngine.nearbyDevices();if(devices.isEmpty())',
        'val pairedNames=settings.knownPeers().map{it.name.trim().lowercase()}.toSet();val devices=LocalTransferEngine.nearbyDevices().filterNot{pairedNames.contains(it.alias.trim().lowercase())};if(devices.isEmpty())',
        "Android hide paired nearby devices", 1)
    replace(share,
        'val devices = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())',
        'val pairedNames = dev.clipmesh.SettingsStore(this).knownPeers().map { it.name.trim().lowercase() }.toSet()\n        val devices = runCatching { LocalTransferEngine.nearbyDevices().filterNot { pairedNames.contains(it.alias.trim().lowercase()) } }.getOrDefault(emptyList())',
        "Android file list hides paired devices", 1)
    replace(main,
        '            row.addView(label(state, 13f, online, if (online) good else muted).apply { gravity = Gravity.END })\n            peersContainer.addView(row)',
        '''            row.addView(label(state, 13f, online, if (online) good else muted).apply { gravity = Gravity.END })
            row.addView(button("Remove", false) {
                settings.forgetPeer(peer.deviceId)
                BackgroundRuntime.restart(this)
                renderPeers(); renderNearbyPairDevices()
            }, LinearLayout.LayoutParams(dp(92), dp(42)).apply { leftMargin = dp(8) })
            peersContainer.addView(row)''', "Android individual peer removal", 1)

    # Muted gold plus pressed-state animation/haptic confirmation for every app button.
    for path in (main, settings_ui, share):
        text = path.read_text(encoding="utf-8")
        text = text.replace("Color.rgb(214, 161, 46)", "Color.rgb(181, 137, 52)")
        text = text.replace("Color.rgb(224, 174, 55)", "Color.rgb(188, 145, 57)")
        path.write_text(text, encoding="utf-8")
    for path in (main, settings_ui):
        replace(path,
            '        setOnClickListener { clicked() }',
            '''        setOnClickListener {
            performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP)
            animate().scaleX(.97f).scaleY(.97f).setDuration(55).withEndAction {
                animate().scaleX(1f).scaleY(1f).setDuration(90).start()
            }.start()
            clicked()
        }''', f"Android button feedback {path.name}", 1)

    dialog = java / "ClipMeshDialog.kt"
    dialog.write_text(r'''package dev.clipmesh

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.text.InputType
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** ClipMesh-owned black/gold modal surface. The OS document picker remains
 * system-owned because Android's storage permission model requires it. */
object ClipMeshDialog {
    private val GOLD = 0xFFB58934.toInt()
    private val CARD = 0xFF111216.toInt()
    private val FIELD = 0xFF18191E.toInt()
    private val INK = 0xFFF4F1EA.toInt()
    private val MUTED = 0xFFA6A39C.toInt()

    fun info(activity: Activity, title: String, message: String, done: (() -> Unit)? = null) =
        show(activity, title, message, null, listOf("Done")) { done?.invoke() }

    fun confirm(activity: Activity, title: String, message: String, done: (Boolean) -> Unit) =
        show(activity, title, message, null, listOf("Cancel", "Continue")) { done(it == 1) }

    fun prompt(activity: Activity, title: String, message: String, initial: String = "", numeric: Boolean = false, multiline: Boolean = false, done: (String?) -> Unit) {
        val input = EditText(activity).apply {
            setText(initial); setTextColor(INK); setHintTextColor(MUTED); textSize = 15f
            inputType = if (numeric) InputType.TYPE_CLASS_NUMBER else InputType.TYPE_CLASS_TEXT
            if (multiline) { minLines = 2; maxLines = 5 } else setSingleLine(true)
            background = shape(FIELD, 12f, 0xFF34363E.toInt()); setPadding(dp(activity, 14), dp(activity, 11), dp(activity, 14), dp(activity, 11))
            if (initial.isNotEmpty()) setSelection(text.length)
        }
        show(activity, title, message, input, listOf("Cancel", "Continue")) { done(if (it == 1) input.text.toString() else null) }
    }

    fun choices(activity: Activity, title: String, choices: List<String>, done: (Int?) -> Unit) =
        show(activity, title, "", null, choices + "Cancel") { done(it.takeIf { index -> index in choices.indices }) }

    private fun show(activity: Activity, title: String, message: String, input: EditText?, actions: List<String>, done: (Int) -> Unit): Dialog {
        val dialog = Dialog(activity)
        val card = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(activity, 22), dp(activity, 20), dp(activity, 22), dp(activity, 18)); background = shape(CARD, 22f, 0xFF34363E.toInt())
        }
        card.addView(TextView(activity).apply { text = title; textSize = 21f; setTextColor(INK); setTypeface(typeface, Typeface.BOLD) })
        if (message.isNotBlank()) card.addView(TextView(activity).apply { text = message; textSize = 14f; setTextColor(MUTED); setPadding(0, dp(activity, 9), 0, dp(activity, 12)) })
        if (input != null) card.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(activity, 13) })
        val buttons = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.END }
        var completed = false
        actions.forEachIndexed { index, label ->
            buttons.addView(Button(activity).apply {
                text = label; isAllCaps = false; setTypeface(typeface, Typeface.BOLD); minHeight = dp(activity, 46)
                setTextColor(if (index == actions.lastIndex) Color.rgb(12, 12, 10) else INK)
                background = shape(if (index == actions.lastIndex) GOLD else FIELD, 16f, if (index == actions.lastIndex) GOLD else 0xFF34363E.toInt())
                setOnClickListener { performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); completed = true; dialog.dismiss(); done(index) }
            }, LinearLayout.LayoutParams(0, dp(activity, 48), 1f).apply { if (index > 0) leftMargin = dp(activity, 8) })
        }
        card.addView(buttons, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(activity, 5) })
        dialog.setContentView(card); dialog.setCanceledOnTouchOutside(false)
        dialog.setOnCancelListener { if (!completed) { completed = true; done(-1) } }
        dialog.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT)); addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            attributes = attributes.apply { dimAmount = .72f; width = (activity.resources.displayMetrics.widthPixels * .88f).toInt() }
            if (Build.VERSION.SDK_INT >= 31) { addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND); attributes = attributes.apply { blurBehindRadius = dp(activity, 24) } }
        }
        dialog.show()
        dialog.window?.setLayout((activity.resources.displayMetrics.widthPixels * .88f).toInt(), ViewGroup.LayoutParams.WRAP_CONTENT)
        return dialog
    }

    private fun shape(fill: Int, radiusDp: Float, stroke: Int) = GradientDrawable().apply { shape = GradientDrawable.RECTANGLE; setColor(fill); cornerRadius = radiusDp * 3; setStroke(1, stroke) }
    private fun dp(activity: Activity, value: Int) = (value * activity.resources.displayMetrics.density).toInt()
}
''', encoding="utf-8")

    replace(main,
        'AlertDialog.Builder(this).setTitle("Verification code").setMessage("Type this code on ${device.alias}:\\n\\n$value").setPositiveButton("Keep pairing",null).show()',
        'ClipMeshDialog.info(this, "Verification code", "Type this code on ${device.alias}:\\n\\n$value")',
        "Android custom pairing-code modal", 1)
    replace(main,
        '''        AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage("This device is already paired. Continuing will replace its current ClipMesh space and known-device list.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Continue") { _, _ -> action() }
            .show()''',
        '''        ClipMeshDialog.confirm(this, title, "This device is already paired. Continuing will replace its current ClipMesh space and known-device list.") { accepted -> if (accepted) action() }''',
        "Android custom replacement confirmation", 1)
    replace(main,
        '''        val input = EditText(this).apply {
            setText(settings.deviceName)
            setSelection(text.length)
            setSingleLine(true)
            setPadding(dp(14), dp(10), dp(14), dp(10))
        }
        AlertDialog.Builder(this)
            .setTitle("Rename this device")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Save") { _, _ ->
                settings.deviceName = input.text.toString()
                refreshHome()
                toast("Device name updated")
            }
            .show()''',
        '''        ClipMeshDialog.prompt(this, "Rename this device", "Choose the name shown to nearby ClipMesh devices.", settings.deviceName) { value ->
            if (value != null) { settings.deviceName = value; refreshHome(); toast("Device name updated") }
        }''', "Android custom rename modal", 1)

    replace(settings_ui,
        '''        val input = EditText(this).apply { setText(settingsStore.deviceName); setSelection(text.length); setSingleLine(true); setTextColor(ink); background = rounded(Color.rgb(26,24,21), dp(12).toFloat(), border); setPadding(dp(12),dp(9),dp(12),dp(9)) }
        AlertDialog.Builder(this).setTitle("Rename this device").setView(input).setNegativeButton("Cancel", null).setPositiveButton("Save") { _, _ ->
            settingsStore.deviceName = input.text.toString(); BackgroundRuntime.restart(this); render(); toast("Device name updated")
        }.show()''',
        '''        ClipMeshDialog.prompt(this, "Rename this device", "Choose the name shown to nearby ClipMesh devices.", settingsStore.deviceName) { value ->
            if (value != null) { settingsStore.deviceName = value; BackgroundRuntime.restart(this); render(); toast("Device name updated") }
        }''', "Android settings custom rename", 1)
    replace(settings_ui,
        '''        val input = EditText(this).apply { setText(initial.orEmpty()); minLines = 2; maxLines = 5; setTextColor(ink); setHintTextColor(muted); hint = "clipmesh://pair?..."; background = rounded(Color.rgb(26,24,21), dp(12).toFloat(), border); setPadding(dp(12),dp(9),dp(12),dp(9)) }
        AlertDialog.Builder(this).setTitle("Pair with another device").setMessage("Paste a pairing code from a trusted ClipMesh device.").setView(input).setNegativeButton("Cancel", null).setPositiveButton("Join") { _, _ ->
            val result = runCatching { Pairing.parse(input.text.toString().trim()) }
            val parsed = result.getOrNull()
            if (parsed == null) {
                toast(result.exceptionOrNull()?.message ?: "Invalid pairing code")
            } else {
                BackgroundRuntime.stop(); settingsStore.spaceId = parsed.spaceId; secrets.saveSpaceKey(parsed.key); settingsStore.clearKnownPeers(); parsed.deviceId?.takeIf { it != settingsStore.deviceId }?.let { settingsStore.seedPeer(it, parsed.name) }; settingsStore.backgroundSync = true; BackgroundRuntime.start(this); toast("Joined private space")
            }
        }.show()''',
        '''        ClipMeshDialog.prompt(this, "Pair with another device", "Paste a pairing code from a trusted ClipMesh device.", initial.orEmpty(), multiline = true) { value ->
            if (value != null) { val result = runCatching { Pairing.parse(value.trim()) }; val parsed = result.getOrNull(); if (parsed == null) toast(result.exceptionOrNull()?.message ?: "Invalid pairing code") else { BackgroundRuntime.stop(); settingsStore.spaceId = parsed.spaceId; secrets.saveSpaceKey(parsed.key); settingsStore.clearKnownPeers(); parsed.deviceId?.takeIf { it != settingsStore.deviceId }?.let { settingsStore.seedPeer(it, parsed.name) }; settingsStore.backgroundSync = true; BackgroundRuntime.start(this); toast("Joined private space") } }
        }''', "Android settings custom pairing input", 1)
    replace(settings_ui,
        '''        AlertDialog.Builder(this)
            .setTitle("Reset all ClipMesh pairing?")
            .setMessage("This permanently replaces this device's ClipMesh identity and private space, clears every remembered device and forces all devices to pair again.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Reset") { _, _ -> resetPairingNow() }
            .show()''',
        '''        ClipMeshDialog.confirm(this, "Reset all ClipMesh pairing?", "This permanently replaces this device's ClipMesh identity and private space, clears every remembered device and forces all devices to pair again.") { accepted -> if (accepted) resetPairingNow() }''',
        "Android custom reset modal", 1)

    replace(share,
        '''                    AlertDialog.Builder(this)
                        .setTitle("Sent")
                        .setMessage("${if (selected.size == 1) displayName(selected.first()) else "${selected.size} files"} was sent to ${device.alias}.")
                        .setPositiveButton("Done") { _, _ -> finish() }
                        .setNegativeButton("Send again", null)
                        .show()''',
        '''                    ClipMeshDialog.confirm(this, "Sent", "${if (selected.size == 1) displayName(selected.first()) else "${selected.size} files"} was sent to ${device.alias}.") { done -> if (done) finish() }''',
        "Android custom sent modal", 1)
    replace(share,
        '''                    AlertDialog.Builder(this)
                        .setTitle("Couldn’t send")
                        .setMessage(error.message ?: "The transfer failed.")
                        .setPositiveButton("OK", null)
                        .show()''',
        '''                    ClipMeshDialog.info(this, "Couldn’t send", error.message ?: "The transfer failed.")''',
        "Android custom error modal", 1)
    replace(share,
        '''        val options = arrayOf("Image", "Video", "File")
        AlertDialog.Builder(this).setTitle("Choose file type").setItems(options) { _, which ->
            chooseFiles(when (which) { 0 -> "image/*"; 1 -> "video/*"; else -> "*/*" })
        }.show()''',
        '''        val options = listOf("Image", "Video", "File")
        ClipMeshDialog.choices(this, "Choose file type", options) { which -> if (which != null) chooseFiles(when (which) { 0 -> "image/*"; 1 -> "video/*"; else -> "*/*" }) }''',
        "Android custom file-type modal", 1)
    replace(share,
        '        setOnClickListener { action() }',
        '''        setOnClickListener { performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP); animate().scaleX(.97f).scaleY(.97f).setDuration(55).withEndAction { animate().scaleX(1f).scaleY(1f).setDuration(90).start() }.start(); action() }''',
        "Android transfer button feedback", 1)

    nearby_ui = java / "fileshare/NearbyPairingUi.kt"
    nearby_ui.write_text(r'''package dev.clipmesh.fileshare

import android.app.Activity
import dev.clipmesh.ClipMeshDialog
import java.lang.ref.WeakReference
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object NearbyPairingUi {
    @Volatile private var visible = WeakReference<Activity>(null)
    fun attach(activity: Activity) { visible = WeakReference(activity) }
    fun detach(activity: Activity) { if (visible.get() === activity) visible.clear() }
    fun approve(sender: String): Boolean {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return false
        val latch = CountDownLatch(1); var accepted = false
        activity.runOnUiThread { ClipMeshDialog.confirm(activity, "Clipboard pairing request", "$sender wants to pair with this device for encrypted clipboard sync.") { accepted = it; latch.countDown() } }
        latch.await(60, TimeUnit.SECONDS); return accepted
    }
    fun promptCode(sender: String, submit: (String?) -> Unit) {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return submit(null)
        activity.runOnUiThread { ClipMeshDialog.prompt(activity, "Verify $sender", "Type the six-digit code shown on $sender. This authenticates the encrypted connection.", numeric = true) { submit(it) } }
    }
}
''', encoding="utf-8")

elif system == "Darwin":
    app = root / "ci/ClipMeshApp.swift"
    transfer = root / "ci/ClipMeshTransfer.swift"
    build = project / "scripts/build-macos.sh"
    replace(build, "0.2.5", "0.2.6", "macOS version")
    replace(transfer, '        let length = Int(headers["content-length"] ?? "0") ?? 0', '''        let length = Int(headers["content-length"] ?? "0") ?? 0
        if headers["expect"]?.lowercased().contains("100-continue") == true {
            connection.send(content: Data("HTTP/1.1 100 Continue\\r\\n\\r\\n".utf8), completion: .contentProcessed { error in if error != nil { connection.cancel() } })
        }''', "macOS Expect handshake", 1)
    replace(transfer, '''        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let sem = DispatchSemaphore(value: 0)
        var output: Result<(Int, Data), Error>!
        URLSession.shared.uploadTask(with: request, from: body)''', '''        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body; request.setValue(String(body.count), forHTTPHeaderField: "Content-Length")
        let sem = DispatchSemaphore(value: 0)
        var output: Result<(Int, Data), Error>!
        URLSession.shared.dataTask(with: request)''', "macOS metadata request body", 1)
    replace(transfer, '''        _ = sem.wait(timeout: .now() + 80)
        return try output.get()''', '''        guard sem.wait(timeout: .now() + 80) == .success, let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out waiting for \\(device.alias). Check the firewall and Wi-Fi connection."]) }
        return try output.get()''', "macOS prepare timeout", 1)
    replace(transfer, '''        _ = sem.wait(timeout: .now() + 190)
        let status = try output.get()''', '''        guard sem.wait(timeout: .now() + 190) == .success, let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \\(file.lastPathComponent)."]) }
        let status = try output.get()''', "macOS upload timeout", 1)
    replace(app, 'import Foundation\n', r'''import Foundation

private final class CMModalTarget: NSObject {
    @objc func choose(_ sender: NSButton) { NSApp.stopModal(withCode: NSApplication.ModalResponse(rawValue: sender.tag)) }
}

enum CMDialog {
    @discardableResult static func run(title: String, message: String, accessory: NSView? = nil, buttons: [String] = ["Done"]) -> Int {
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 460, height: 220), styleMask: [.titled, .fullSizeContentView], backing: .buffered, defer: false)
        panel.title = "ClipMesh"; panel.isMovableByWindowBackground = true; panel.titlebarAppearsTransparent = true; panel.backgroundColor = NSColor(calibratedRed: 7/255, green: 8/255, blue: 10/255, alpha: 1)
        let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 14; stack.edgeInsets = NSEdgeInsets(top: 26, left: 26, bottom: 24, right: 26); stack.translatesAutoresizingMaskIntoConstraints = false
        let heading = NSTextField(wrappingLabelWithString: title); heading.font = .systemFont(ofSize: 22, weight: .bold); heading.textColor = .white; stack.addArrangedSubview(heading)
        if !message.isEmpty { let detail = NSTextField(wrappingLabelWithString: message); detail.font = .systemFont(ofSize: 13); detail.textColor = NSColor(calibratedWhite: 0.72, alpha: 1); detail.preferredMaxLayoutWidth = 408; stack.addArrangedSubview(detail) }
        if let accessory { stack.addArrangedSubview(accessory); accessory.widthAnchor.constraint(equalToConstant: 408).isActive = true }
        let actions = NSStackView(); actions.orientation = .horizontal; actions.spacing = 10; actions.alignment = .centerY; actions.addArrangedSubview(NSView())
        let target = CMModalTarget()
        for (index, label) in buttons.enumerated() { let b = NSButton(title: label, target: target, action: #selector(CMModalTarget.choose(_:))); b.tag = index; b.isBordered = false; b.wantsLayer = true; b.layer?.cornerRadius = 9; b.layer?.backgroundColor = (index == buttons.count - 1 ? NSColor(calibratedRed: 181/255, green: 137/255, blue: 52/255, alpha: 1) : NSColor(calibratedWhite: 0.14, alpha: 1)).cgColor; b.contentTintColor = index == buttons.count - 1 ? .black : .white; b.translatesAutoresizingMaskIntoConstraints = false; b.heightAnchor.constraint(equalToConstant: 38).isActive = true; b.widthAnchor.constraint(greaterThanOrEqualToConstant: 94).isActive = true; actions.addArrangedSubview(b) }
        stack.addArrangedSubview(actions); actions.widthAnchor.constraint(equalToConstant: 408).isActive = true
        panel.contentView = NSView(); panel.contentView?.wantsLayer = true; panel.contentView?.layer?.backgroundColor = panel.backgroundColor.cgColor; panel.contentView?.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: panel.contentView!.leadingAnchor), stack.trailingAnchor.constraint(equalTo: panel.contentView!.trailingAnchor), stack.topAnchor.constraint(equalTo: panel.contentView!.topAnchor), stack.bottomAnchor.constraint(equalTo: panel.contentView!.bottomAnchor)])
        panel.setContentSize(stack.fittingSize); panel.center(); NSApp.activate(ignoringOtherApps: true); panel.makeKeyAndOrderFront(nil)
        let response = NSApp.runModal(for: panel); panel.orderOut(nil); _ = target
        return response.rawValue
    }
    static func confirm(title: String, message: String) -> Bool { run(title: title, message: message, buttons: ["Cancel", "Continue"]) == 1 }
}
''', "macOS custom dialog component", 1)
    replace(app,
        '    static func setName(_ name: String) throws {',
        '''    static func forgetPeer(_ id: String) throws {
        _ = try checked(["forget-peer", id], message: "Could not remove this paired device.")
    }

    static func setName(_ name: String) throws {''', "macOS forget runtime", 1)
    replace(app,
        'let devices = LocalTransferManager.shared.nearbyDevices()',
        'let pairedNames = Set((latestState?.peers ?? []).map { $0.name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() })\n        let devices = LocalTransferManager.shared.nearbyDevices().filter { !pairedNames.contains($0.alias.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()) }',
        "macOS hide paired nearby devices")
    replace(app,
        'let devices=LocalTransferManager.shared.nearbyDevices()',
        'let pairedNames=Set((latestState?.peers ?? []).map{$0.name.trimmingCharacters(in:.whitespacesAndNewlines).lowercased()});let devices=LocalTransferManager.shared.nearbyDevices().filter{!pairedNames.contains($0.alias.trimmingCharacters(in:.whitespacesAndNewlines).lowercased())}',
        "macOS hide paired pairing candidates", 1)
    replace(app,
        '            row.addArrangedSubview(state)\n            row.translatesAutoresizingMaskIntoConstraints = false',
        '''            row.addArrangedSubview(state)
            row.addArrangedSubview(closureButton("Remove", primary: false) { [weak self] in
                guard let self else { return }
                self.mutateRuntime { try Runtime.forgetPeer(peer.id) }
            })
            row.translatesAutoresizingMaskIntoConstraints = false''',
        "macOS individual peer removal", 1)
    replace(app, '''        let alert = NSAlert()
        alert.messageText = "Rename this device"
        alert.informativeText = "This name is shown to your other ClipMesh devices."
        alert.addButton(withTitle: "Save")
        // Keep this dialog distinct from the Settings alert patch anchor.
        alert.addButton(withTitle: "Cancel")
        let input = NSTextField(string: latestState?.deviceName ?? Runtime.deviceName())
        input.frame = NSRect(x: 0, y: 0, width: 320, height: 24)
        alert.accessoryView = input
        guard alert.runModal() == .alertFirstButtonReturn else { return }''', '''        let input = NSTextField(string: latestState?.deviceName ?? Runtime.deviceName()); input.placeholderString = "Device name"
        guard CMDialog.run(title: "Rename this device", message: "This name is shown to your other ClipMesh devices.", accessory: input, buttons: ["Cancel", "Save"]) == 1 else { return }''', "macOS custom rename modal", 1)
    replace(app, '''        let alert = NSAlert()
        alert.messageText = "ClipMesh Settings"
        alert.informativeText = "These settings apply to background clipboard synchronization."
        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Reset All Pairing…")

        let stack = NSStackView()''', '''        let stack = NSStackView()''', "macOS custom settings setup", 1)
    replace(app, '''        stack.frame = NSRect(x: 0, y: 0, width: 320, height: 60)
        alert.accessoryView = stack
        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            mutateRuntime { try Runtime.setSync(send: send.state == .on, receive: receive.state == .on) }
            return
        }
        if response == .alertThirdButtonReturn {
            let confirm = NSAlert()
            confirm.alertStyle = .critical
            confirm.messageText = "Reset all ClipMesh pairing?"
            confirm.informativeText = "This creates a new device identity and private space, clears every remembered device, and forces all other devices to pair again."
            confirm.addButton(withTitle: "Reset")
            confirm.addButton(withTitle: "Cancel")
            guard confirm.runModal() == .alertFirstButtonReturn else { return }
            let name = current.deviceName
            mutateRuntime { try Runtime.resetIdentity(name: name) }
        }''', '''        let response = CMDialog.run(title: "ClipMesh Settings", message: "These settings apply to background clipboard synchronization.", accessory: stack, buttons: ["Cancel", "Reset All Pairing…", "Save"])
        if response == 2 { mutateRuntime { try Runtime.setSync(send: send.state == .on, receive: receive.state == .on) }; return }
        if response == 1 && CMDialog.confirm(title: "Reset all ClipMesh pairing?", message: "This creates a new device identity and private space, clears every remembered device, and forces all other devices to pair again.") { let name = current.deviceName; mutateRuntime { try Runtime.resetIdentity(name: name) } }''', "macOS custom settings modal", 1)
    replace(app, '''        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = "This replaces this Mac's current ClipMesh space and known-device list."
        alert.addButton(withTitle: "Continue")
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn''', '''        CMDialog.confirm(title: title, message: "This replaces this Mac's current ClipMesh space and known-device list.")''', "macOS custom confirmation", 1)
    replace(transfer, 'let alert = NSAlert(); alert.messageText = "Couldn’t send"; alert.informativeText = error.localizedDescription; alert.addButton(withTitle: "OK"); alert.runModal()', 'CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)', "macOS custom transfer error", 1)
    replace(transfer, '''        let alert = NSAlert(); alert.alertStyle = .informational; alert.messageText = "\\(sender) wants to send you \\(files.count == 1 ? files[0].name : "\\(files.count) files")"
        alert.informativeText = "Accept to save it in Downloads/ClipMesh. Star this device later if you want future transfers from it to save automatically."
        alert.addButton(withTitle: "Accept"); alert.addButton(withTitle: "Reject")
        NSApp.activate(ignoringOtherApps: true)
        return alert.runModal() == .alertFirstButtonReturn''', '''        return CMDialog.run(title: "Incoming file transfer", message: "\\(sender) wants to send you \\(files.count == 1 ? files[0].name : "\\(files.count) files"). Accept to save in Downloads/ClipMesh.", buttons: ["Reject", "Accept"]) == 1''', "macOS custom incoming modal", 1)
    replace(app, 'let alert=NSAlert();alert.messageText="Verification code";alert.informativeText="Type this code on \\(device.alias):\\n\\n\\(value)";alert.addButton(withTitle:"Keep pairing");alert.runModal()', 'CMDialog.run(title:"Verification code",message:"Type this code on \\(device.alias):\\n\\n\\(value)")', "macOS custom pairing code", 1)
    replace(app, 'let alert=NSAlert();alert.messageText="Clipboard pairing request";alert.informativeText="\\(sender) wants to pair with this Mac for encrypted clipboard sync.";alert.addButton(withTitle:"Accept");alert.addButton(withTitle:"Reject");NSApp.activate(ignoringOtherApps:true);accepted=alert.runModal() == .alertFirstButtonReturn', 'accepted=CMDialog.run(title:"Clipboard pairing request",message:"\\(sender) wants to pair with this Mac for encrypted clipboard sync.",buttons:["Reject","Accept"]) == 1', "macOS custom pairing approval", 1)
    replace(app, 'let alert=NSAlert();alert.messageText="Verify \\(sender)";alert.informativeText="Type the six-digit code shown on \\(sender).";alert.addButton(withTitle:"Pair");alert.addButton(withTitle:"Cancel");let input=NSTextField(string:"");input.placeholderString="6-digit code";input.frame=NSRect(x:0,y:0,width:260,height:26);alert.accessoryView=input;submit(alert.runModal() == .alertFirstButtonReturn ? input.stringValue:nil)', 'let input=NSTextField(string:"");input.placeholderString="6-digit code";submit(CMDialog.run(title:"Verify \\(sender)",message:"Type the six-digit code shown on \\(sender).",accessory:input,buttons:["Cancel","Pair"]) == 1 ? input.stringValue:nil)', "macOS custom code input", 1)
    replace(app, 'let alert = NSAlert(); alert.messageText = "Couldn’t send"; alert.informativeText = error.localizedDescription; alert.runModal()', 'CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)', "macOS integrated transfer error", 1)
    replace(app, 'let alert = NSAlert(); alert.messageText = (a == 0 && e == 0) ? "Finder Share refreshed" : "Finder controls Share extensions"; alert.informativeText = "Look under Finder → right-click a file → Share → ClipMesh. If macOS hides it, open Share → Edit Extensions and enable ClipMesh."; alert.addButton(withTitle: "OK"); alert.runModal()', 'CMDialog.run(title: (a == 0 && e == 0) ? "Finder Share refreshed" : "Finder controls Share extensions", message: "Look under Finder → right-click a file → Share → ClipMesh. If macOS hides it, open Share → Edit Extensions and enable ClipMesh.")', "macOS share status dialog", 1)

elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    transfer = root / "ci/ClipMeshTransfer.cs"
    replace(ui, 'private const string Version = "0.2.5";', 'private const string Version = "0.2.6";', "Windows version", 1)
    replace(ui, 'internal sealed class CliResult', r'''internal static class ClipMeshDialogC
{
    public static bool Show(IWin32Window owner, string title, string message, bool confirm)
    {
        using (Form dialog = new Form())
        {
            dialog.Text = "ClipMesh"; dialog.Width = 470; dialog.Height = 245; dialog.FormBorderStyle = FormBorderStyle.FixedDialog; dialog.StartPosition = FormStartPosition.CenterParent; dialog.MaximizeBox = false; dialog.MinimizeBox = false; dialog.BackColor = Color.FromArgb(11, 12, 15); dialog.ForeColor = Color.FromArgb(244, 241, 234);
            Label heading = new Label(); heading.Text = title; heading.Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 15, FontStyle.Bold); heading.ForeColor = dialog.ForeColor; heading.SetBounds(24, 22, 405, 30);
            Label detail = new Label(); detail.Text = message; detail.Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 9, FontStyle.Regular); detail.ForeColor = Color.FromArgb(166, 163, 156); detail.SetBounds(24, 61, 405, 84);
            Button cancel = new Button(); cancel.Text = confirm ? "Cancel" : "Done"; cancel.DialogResult = confirm ? DialogResult.Cancel : DialogResult.OK; cancel.FlatStyle = FlatStyle.Flat; cancel.FlatAppearance.BorderColor = Color.FromArgb(52, 54, 62); cancel.BackColor = Color.FromArgb(24, 25, 30); cancel.ForeColor = dialog.ForeColor; cancel.SetBounds(confirm ? 220 : 300, 158, 130, 42);
            dialog.Controls.Add(heading); dialog.Controls.Add(detail); dialog.Controls.Add(cancel); dialog.CancelButton = cancel;
            if (confirm) { Button accept = new Button(); accept.Text = "Continue"; accept.DialogResult = DialogResult.OK; accept.FlatStyle = FlatStyle.Flat; accept.FlatAppearance.BorderSize = 0; accept.BackColor = Color.FromArgb(181, 137, 52); accept.ForeColor = Color.FromArgb(12, 12, 10); accept.SetBounds(360, 158, 80, 42); dialog.Controls.Add(accept); dialog.AcceptButton = accept; }
            return (owner == null ? dialog.ShowDialog() : dialog.ShowDialog(owner)) == DialogResult.OK;
        }
    }
}

internal sealed class CliResult''', "Windows custom dialog component", 1)
    replace(transfer, '        long length = 0; string len; if (headers.TryGetValue("Content-Length", out len)) Int64.TryParse(len, out length);', '        long length = 0; string len; if (headers.TryGetValue("Content-Length", out len)) Int64.TryParse(len, out length);\n        string expect; if (headers.TryGetValue("Expect", out expect) && expect.IndexOf("100-continue", StringComparison.OrdinalIgnoreCase) >= 0) { byte[] interim=Encoding.ASCII.GetBytes("HTTP/1.1 100 Continue\\r\\n\\r\\n"); stream.Write(interim,0,interim.Length); stream.Flush(); }', "Windows Expect handshake", 1)
    replace(ui,
        '    public static void SetName(string name)',
        '''    public static void ForgetPeer(string id)
    {
        Checked("Could not remove this paired device.", "forget-peer", id);
    }

    public static void SetName(string name)''', "Windows forget runtime", 1)
    replace(ui,
        'List<TransferDeviceC> devices=LocalTransferManagerC.Shared.Nearby();if(devices.Count==0)',
        'HashSet<string> pairedNames=new HashSet<string>((latestState==null?new List<PeerState>():latestState.Peers).ConvertAll(p=>p.Name.Trim().ToLowerInvariant()));List<TransferDeviceC> devices=LocalTransferManagerC.Shared.Nearby().FindAll(d=>!pairedNames.Contains(d.Alias.Trim().ToLowerInvariant()));if(devices.Count==0)',
        "Windows hide paired nearby devices")
    replace(ui,
        'transferDevicePanel.SuspendLayout(); transferDevicePanel.Controls.Clear(); List<TransferDeviceC> devices = LocalTransferManagerC.Shared.Nearby();',
        'transferDevicePanel.SuspendLayout(); transferDevicePanel.Controls.Clear(); HashSet<string> pairedTransferNames = new HashSet<string>((latestState == null ? new List<PeerState>() : latestState.Peers).ConvertAll(p => p.Name.Trim().ToLowerInvariant())); List<TransferDeviceC> devices = LocalTransferManagerC.Shared.Nearby().FindAll(d => !pairedTransferNames.Contains(d.Alias.Trim().ToLowerInvariant()));',
        "Windows file list hides paired devices", 1)
    replace(ui,
        '            state.SetBounds(340, 5, 155, 24);',
        '            state.SetBounds(300, 5, 105, 24);\n            Button remove = MakeButton("Remove", false); remove.SetBounds(410, 1, 86, 32); string removeId = peer.Id; remove.Click += delegate { StopDaemon(); try { ClipMeshRuntime.ForgetPeer(removeId); StartDaemon(); RefreshHome(); } catch (Exception ex) { try { StartDaemon(); } catch {} ShowError(ex.Message); } };',
        "Windows individual peer removal", 1)
    replace(ui,
        '            row.Controls.Add(state);\n            peersPanel.Controls.Add(row);',
        '            row.Controls.Add(state);\n            row.Controls.Add(remove);\n            peersPanel.Controls.Add(row);',
        "Windows add remove control", 1)
    replace(ui, 'MessageBox.Show(this,"Type this code on "+device.Alias+":\\r\\n\\r\\n"+value,"Verification code",MessageBoxButtons.OK,MessageBoxIcon.Information);', 'ClipMeshDialogC.Show(this,"Verification code","Type this code on "+device.Alias+":\\r\\n\\r\\n"+value,false);', "Windows custom pairing code", 1)
    replace(ui, 'accepted=MessageBox.Show(this,sender+" wants to pair with this PC for encrypted clipboard sync.","Clipboard pairing request",MessageBoxButtons.YesNo,MessageBoxIcon.Information)==DialogResult.Yes;', 'accepted=ClipMeshDialogC.Show(this,"Clipboard pairing request",sender+" wants to pair with this PC for encrypted clipboard sync.",true);', "Windows custom pairing approval", 1)
    replace(ui, 'MessageBox.Show(this, ex.Message, "Couldn’t send", MessageBoxButtons.OK, MessageBoxIcon.Error);', 'ClipMeshDialogC.Show(this, "Couldn’t send", ex.Message, false);', "Windows custom integrated transfer error", 1)
    replace(ui, '''            accepted = MessageBox.Show(this, message,
                "Incoming ClipMesh transfer", MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes;''', '            accepted = ClipMeshDialogC.Show(this, "Incoming ClipMesh transfer", message, true);', "Windows custom incoming prompt", 1)
    replace(ui, '''        return MessageBox.Show(this,
            "This replaces this PC's current ClipMesh space and known-device list.",
            title, MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) == DialogResult.OK;''', '        return ClipMeshDialogC.Show(this, title, "This replaces this PC\'s current ClipMesh space and known-device list.", true);', "Windows custom replacement prompt", 1)
    replace(ui, 'MessageBox.Show(this, Limit(String.Join("\\r\\n", lines.ToArray()), 24000), "Current Clipboard", MessageBoxButtons.OK, MessageBoxIcon.Information);', 'ClipMeshDialogC.Show(this, "Current Clipboard", Limit(String.Join("\\r\\n", lines.ToArray()), 24000), false);', "Windows custom clipboard modal", 1)
    replace(ui, 'MessageBox.Show(this, "This creates a new device identity and private space and clears all remembered devices.", "Reset all ClipMesh pairing?", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) == DialogResult.OK', 'ClipMeshDialogC.Show(this, "Reset all ClipMesh pairing?", "This creates a new device identity and private space and clears all remembered devices.", true)', "Windows custom reset card", 1)
    replace(ui, '''MessageBox.Show(dialog,
                    "This creates a new device identity and private space, clears every remembered device, and forces all other devices to pair again.",
                    "Reset all ClipMesh pairing?", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK''', 'ClipMeshDialogC.Show(dialog, "Reset all ClipMesh pairing?", "This creates a new device identity and private space, clears every remembered device, and forces all other devices to pair again.", true) == false', "Windows custom settings reset", 1)
    replace(ui, 'MessageBox.Show(ex.Message, "ClipMesh", MessageBoxButtons.OK, MessageBoxIcon.Error);', 'ClipMeshDialogC.Show(null, "ClipMesh", ex.Message, false);', "Windows custom startup errors", 2)
    replace(transfer, 'MessageBox.Show(this,ex.Message,"Couldn’t send",MessageBoxButtons.OK,MessageBoxIcon.Error);', 'ClipMeshDialogC.Show(this,"Couldn’t send",ex.Message,false);', "Windows custom transfer error", 1)

else:
    raise SystemExit(f"unsupported platform {system}")

print(f"Applied ClipMesh v0.2.6 transfer/background/UI regression repairs on {system}")
