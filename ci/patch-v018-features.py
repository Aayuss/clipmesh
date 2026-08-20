from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_if_present(path: Path, old: str, new: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Desktop engine: hard reset means a new device UUID + a new private space/key.
# Old peers therefore cannot authenticate until explicitly paired again.
# ---------------------------------------------------------------------------
main_rs = project / "apps/desktop/src/main.rs"
replace_once(
    main_rs,
    '''    NewSpace { #[arg(long)] name: String },
    SetName { #[arg(long)] name: String },''',
    '''    NewSpace { #[arg(long)] name: String },
    Reset { #[arg(long)] name: String },
    SetName { #[arg(long)] name: String },''',
    "desktop reset command declaration",
)
replace_once(
    main_rs,
    '''        Command::NewSpace{name} => new_space(name),
        Command::SetName{name} => set_name(name),''',
    '''        Command::NewSpace{name} => new_space(name),
        Command::Reset{name} => reset_identity(name),
        Command::SetName{name} => set_name(name),''',
    "desktop reset command dispatch",
)
replace_once(
    main_rs,
    '''fn set_name(name:String)->Result<()> {''',
    '''fn reset_identity(name:String)->Result<()> {
    let existing = if Config::path()?.exists() { Some(Config::load()?) } else { None };
    let old_space=existing.as_ref().map(|cfg|cfg.space_id);
    let cfg=Config::new(sanitize_device_name(&name));
    let key=MasterKey::generate();
    secrets::save(cfg.space_id,&key)?;
    if let Err(error)=cfg.save() {
        let _=secrets::delete(cfg.space_id);
        return Err(error);
    }
    Config::clear_known_peers()?;
    if let Some(old)=old_space.filter(|old|*old!=cfg.space_id) { let _=secrets::delete(old); }
    println!("Reset ClipMesh identity. New device {} in space {}",cfg.device_id,cfg.space_id);
    Ok(())
}

fn set_name(name:String)->Result<()> {''',
    "desktop reset identity implementation",
)


# ---------------------------------------------------------------------------
# Android defaults and Shizuku state.
# ---------------------------------------------------------------------------
settings_store = project / "android/app/src/main/java/dev/clipmesh/SettingsStore.kt"
replace_once(
    settings_store,
    'get() = prefs.getBoolean("background_sync", false)',
    'get() = prefs.getBoolean("background_sync", true)',
    "Android background sync default on",
)

shizuku_manager = project / "android/app/src/main/java/dev/clipmesh/shizuku/ShizukuManager.kt"
replace_once(
    shizuku_manager,
    '''    fun requestPermission(): Boolean {''',
    '''    fun isBound(): Boolean = service?.let { svc ->
        runCatching { svc.asBinder().isBinderAlive }.getOrDefault(false)
    } == true

    fun requestPermission(): Boolean {''',
    "Android Shizuku bound state",
)

# ---------------------------------------------------------------------------
# Android settings UI: live Shizuku state + destructive pairing reset.
# Polling is only while this Settings Activity is visible, so it has no
# background/battery cost.
# ---------------------------------------------------------------------------
settings_activity = project / "android/app/src/main/java/dev/clipmesh/SettingsActivity.kt"
replace_once(
    settings_activity,
    '''import android.app.Activity
import android.content.Context''',
    '''import android.app.Activity
import android.app.AlertDialog
import android.content.Context''',
    "Android settings AlertDialog import",
)
replace_once(
    settings_activity,
    '''import android.os.Build
import android.os.Bundle''',
    '''import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper''',
    "Android settings Handler imports",
)
replace_once(
    settings_activity,
    '''import dev.clipmesh.shizuku.ShizukuManager
''',
    '''import dev.clipmesh.shizuku.ShizukuManager
import java.util.UUID
''',
    "Android settings UUID import",
)
replace_once(
    settings_activity,
    '''    private lateinit var shizuku: ShizukuManager

    private val pageBackground''',
    '''    private lateinit var shizuku: ShizukuManager
    private lateinit var shizukuStatus: TextView
    private lateinit var shizukuButton: Button
    private val shizukuUiHandler = Handler(Looper.getMainLooper())
    private val shizukuUiRefresh = object : Runnable {
        override fun run() {
            if (!isFinishing && ::shizukuButton.isInitialized) {
                refreshShizukuUi()
                shizukuUiHandler.postDelayed(this, 700L)
            }
        }
    }

    private val pageBackground''',
    "Android settings Shizuku UI state fields",
)
replace_once(
    settings_activity,
    '''    override fun onDestroy() {
        shizuku.close()
        super.onDestroy()
    }
''',
    '''    override fun onResume() {
        super.onResume()
        shizukuUiHandler.removeCallbacks(shizukuUiRefresh)
        shizukuUiHandler.post(shizukuUiRefresh)
    }

    override fun onPause() {
        shizukuUiHandler.removeCallbacks(shizukuUiRefresh)
        super.onPause()
    }

    override fun onDestroy() {
        shizukuUiHandler.removeCallbacks(shizukuUiRefresh)
        shizuku.close()
        super.onDestroy()
    }
''',
    "Android settings Shizuku lifecycle refresh",
)
old_access = '''        accessCard.addView(button("Request Shizuku permission") {
            when {
                !shizuku.isAvailable() -> toast("Start or install Shizuku first")
                shizuku.hasPermission() -> toast("Shizuku is authorized and connected to ClipMesh")
                else -> shizuku.requestPermission()
            }
        })
'''
new_access = '''        shizukuStatus = label("Checking Shizuku…", 13f, false, muted).apply { setPadding(0, 0, 0, dp(10)) }
        accessCard.addView(shizukuStatus)
        shizukuButton = button("Request Shizuku permission") {
            when {
                shizuku.isBound() -> toast("Shizuku is already connected")
                !shizuku.isAvailable() -> toast("Start or install Shizuku first")
                shizuku.hasPermission() -> {
                    shizuku.requestPermission()
                    toast("Connecting ClipMesh to Shizuku…")
                    shizukuUiHandler.postDelayed({ refreshShizukuUi() }, 400L)
                }
                else -> {
                    if (!shizuku.requestPermission()) toast("Could not request Shizuku permission")
                }
            }
        }
        accessCard.addView(shizukuButton)
'''
replace_once(settings_activity, old_access, new_access, "Android live Shizuku controls")
replace_once(
    settings_activity,
    '''        val securityCard = card(root)
        securityCard.addView(sectionTitle("SECURITY"))''',
    '''        val resetCard = card(root)
        resetCard.addView(sectionTitle("PAIRING RESET"))
        resetCard.addView(label(
            "Erase this installation's device identity, private space and known-device list. A fresh identity and private space will be created, and every other device must be paired again.",
            13f, false, muted
        ).apply { setPadding(0, dp(8), 0, dp(12)) })
        resetCard.addView(button("Reset all pairing", false) { confirmResetPairing() })

        val securityCard = card(root)
        securityCard.addView(sectionTitle("SECURITY"))''',
    "Android pairing reset settings card",
)
replace_once(
    settings_activity,
    '''    private fun restartSyncIfEnabled() {''',
    '''    private fun refreshShizukuUi() {
        when {
            shizuku.isBound() -> {
                shizukuStatus.text = "Connected - background clipboard access is ready"
                shizukuButton.text = "Shizuku connected"
                shizukuButton.isEnabled = false
            }
            shizuku.isAvailable() && shizuku.hasPermission() -> {
                shizukuStatus.text = "Authorized - connecting ClipMesh service…"
                shizukuButton.text = "Connect Shizuku"
                shizukuButton.isEnabled = true
                shizuku.requestPermission()
            }
            shizuku.isAvailable() -> {
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
        AlertDialog.Builder(this)
            .setTitle("Reset all ClipMesh pairing?")
            .setMessage("This permanently replaces this device's ClipMesh identity and private space, clears every remembered device and forces all devices to pair again.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Reset") { _, _ -> resetPairingNow() }
            .show()
    }

    private fun resetPairingNow() {
        stopService(Intent(this, SyncService::class.java))
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

    private fun restartSyncIfEnabled() {''',
    "Android reset and Shizuku helper methods",
)


# ---------------------------------------------------------------------------
# Android image capture. Foreground ClipboardManager previously serialized only
# text. Shizuku URI images also preserved arbitrary image MIME even though the
# desktop path is most reliable with canonical PNG. Convert both paths to PNG.
# ---------------------------------------------------------------------------
bridge = project / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
replace_once(
    bridge,
    '''import android.content.Context
import android.net.Uri''',
    '''import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri''',
    "Android image BitmapFactory import",
)
replace_once(
    bridge,
    '''import java.io.File
import java.util.Locale''',
    '''import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale''',
    "Android image ByteArrayOutputStream import",
)
old_fallback = '''        val clip = clipboard.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        val reps = mutableListOf<Representation>()
        val text = clip.getItemAt(0).coerceToText(context)?.toString()
        if (settings.syncText && !text.isNullOrEmpty()) reps += Representation("text/plain; charset=utf-8", text.toByteArray())
        return ClipPayload(reps, sourceApp = sourcePackage).takeIf { it.representations.isNotEmpty() }
'''
new_fallback = '''        val clip = clipboard.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        val reps = mutableListOf<Representation>()
        val first = clip.getItemAt(0)
        val uri = first.uri
        val declaredMime = uri?.let { runCatching { context.contentResolver.getType(it) }.getOrNull() }
            ?: clipboard.primaryClipDescription?.let { description ->
                (0 until description.mimeTypeCount).map { description.getMimeType(it) }
                    .firstOrNull { it.lowercase(Locale.ROOT).startsWith("image/") }
            }
        val isImage = declaredMime?.lowercase(Locale.ROOT)?.startsWith("image/") == true
        if (settings.syncImages && isImage && uri != null) {
            val bytes = readUriBytes(uri)
            val png = bytes?.let { imageToPng(it) }
            if (png != null) reps += Representation("image/png", png)
        }
        if (!isImage && settings.syncText) {
            val text = first.coerceToText(context)?.toString()
            if (!text.isNullOrEmpty()) reps += Representation("text/plain; charset=utf-8", text.toByteArray())
        }
        return ClipPayload(reps, sourceApp = sourcePackage).takeIf { it.representations.isNotEmpty() }
'''
replace_once(bridge, old_fallback, new_fallback, "Android foreground image capture")
replace_once(
    bridge,
    '''                    if (isImage && items.length() == 1) reps += Representation(mime, bytes)
                    else files += PortableFile(name, bytes, hash)''',
    '''                    if (isImage && items.length() == 1) {
                        val png = imageToPng(bytes)
                        if (png != null) reps += Representation("image/png", png)
                    } else files += PortableFile(name, bytes, hash)''',
    "Android Shizuku image canonical PNG",
)
replace_once(
    bridge,
    '''    private fun setFiles(files: List<PortableFile>) {''',
    '''    private fun readUriBytes(uri: Uri): ByteArray? = runCatching {
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
        val extras = android.os.PersistableBundle().apply {
            putBoolean("com.android.systemui.SUPPRESS_CLIPBOARD_OVERLAY", true)
            putBoolean("android.content.extra.IS_REMOTE_DEVICE", true)
        }
        clip.description.extras = extras
        return clip
    }

    private fun setFiles(files: List<PortableFile>) {''',
    "Android image helpers and remote clipboard metadata",
)
# Mark non-Shizuku remote clipboard writes too. Android may choose to ignore the
# hidden overlay suppression for an ordinary app, but the remote marker remains
# correct; Shizuku text writes below run as shell and are suppressible.
bridge_text = bridge.read_text(encoding="utf-8")
bridge_text = bridge_text.replace('clipboard.setPrimaryClip(ClipData.newHtmlText("ClipMesh", text, htmlText))', 'clipboard.setPrimaryClip(markRemote(ClipData.newHtmlText("ClipMesh", text, htmlText)))')
bridge_text = bridge_text.replace('clipboard.setPrimaryClip(ClipData.newPlainText("ClipMesh", text))', 'clipboard.setPrimaryClip(markRemote(ClipData.newPlainText("ClipMesh", text)))')
bridge_text = bridge_text.replace('clip?.let { clipboard.setPrimaryClip(it) }', 'clip?.let { clipboard.setPrimaryClip(markRemote(it)) }')
bridge_text = bridge_text.replace('clipboard.setPrimaryClip(ClipData("ClipMesh", arrayOf(mime), ClipData.Item(uri)))', 'clipboard.setPrimaryClip(markRemote(ClipData("ClipMesh", arrayOf(mime), ClipData.Item(uri))))')
bridge.write_text(bridge_text, encoding="utf-8")

user_service = project / "android/app/src/main/java/dev/clipmesh/shizuku/ClipboardUserService.kt"
replace_once(
    user_service,
    '''import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns''',
    '''import android.os.ParcelFileDescriptor
import android.os.PersistableBundle
import android.provider.OpenableColumns''',
    "Shizuku clipboard overlay PersistableBundle import",
)
replace_once(
    user_service,
    '''    override fun setPrimaryClipText(text: String): Boolean =
        invokeClipboard("setPrimaryClip", ClipData.newPlainText("ClipMesh", text)) != null
''',
    '''    override fun setPrimaryClipText(text: String): Boolean {
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
''',
    "Shizuku remote text overlay suppression",
)


# ---------------------------------------------------------------------------
# macOS: standard application menu/responder-chain keyboard shortcuts and a
# pairing reset in Settings.
# ---------------------------------------------------------------------------
mac_ui = root / "ci/ClipMeshApp.swift"
replace_once(
    mac_ui,
    '''    static func createNewSpace(name: String) throws {
        _ = try checked(["new-space", "--name", name], message: "Could not create a new ClipMesh space.")
    }
''',
    '''    static func createNewSpace(name: String) throws {
        _ = try checked(["new-space", "--name", name], message: "Could not create a new ClipMesh space.")
    }

    static func resetIdentity(name: String) throws {
        _ = try checked(["reset", "--name", name], message: "Could not reset ClipMesh pairing.")
    }
''',
    "macOS runtime reset command",
)
replace_once(
    mac_ui,
    '''        NSApp.setActivationPolicy(.regular)
        buildWindow()
        buildStatusItem()''',
    '''        NSApp.setActivationPolicy(.regular)
        buildMainMenu()
        buildWindow()
        buildStatusItem()''',
    "macOS install standard main menu",
)
replace_once(
    mac_ui,
    '''    private func buildStatusItem() {''',
    '''    private func buildMainMenu() {
        let main = NSMenu()

        let appRoot = NSMenuItem()
        let appMenu = NSMenu(title: "ClipMesh")
        appMenu.addItem(withTitle: "About ClipMesh", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide ClipMesh", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = NSMenuItem(title: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthers)
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit ClipMesh", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        appMenu.addItem(quit)
        main.addItem(appRoot)
        main.setSubmenu(appMenu, for: appRoot)

        let fileRoot = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        let close = NSMenuItem(title: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileMenu.addItem(close)
        main.addItem(fileRoot)
        main.setSubmenu(fileMenu, for: fileRoot)

        let editRoot = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = NSMenuItem(title: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redo)
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        main.addItem(editRoot)
        main.setSubmenu(editMenu, for: editRoot)

        let windowRoot = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        main.addItem(windowRoot)
        main.setSubmenu(windowMenu, for: windowRoot)
        NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = main
    }

    private func buildStatusItem() {''',
    "macOS standard application menu",
)
replace_once(
    mac_ui,
    '''        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")''',
    '''        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Reset All Pairing…")''',
    "macOS settings reset button",
)
replace_once(
    mac_ui,
    '''        alert.accessoryView = stack
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        mutateRuntime { try Runtime.setSync(send: send.state == .on, receive: receive.state == .on) }
''',
    '''        alert.accessoryView = stack
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
        }
''',
    "macOS settings reset behavior",
)


# ---------------------------------------------------------------------------
# Windows: matching pairing reset in Settings.
# ---------------------------------------------------------------------------
win_ui = root / "ci/ClipMeshWindows.cs"
replace_once(
    win_ui,
    '''    public static void NewSpace(string name)
    {
        Checked("Could not create a new ClipMesh space.", "new-space", "--name", name);
    }
''',
    '''    public static void NewSpace(string name)
    {
        Checked("Could not create a new ClipMesh space.", "new-space", "--name", name);
    }

    public static void ResetIdentity(string name)
    {
        Checked("Could not reset ClipMesh pairing.", "reset", "--name", name);
    }
''',
    "Windows runtime reset command",
)
replace_once(
    win_ui,
    '''            dialog.Height = 245;''',
    '''            dialog.Height = 325;''',
    "Windows settings dialog height",
)
replace_once(
    win_ui,
    '''            save.SetBounds(205, 151, 130, 42);
            Button cancel = MakeButton("Cancel", false);
            cancel.DialogResult = DialogResult.Cancel;
            cancel.SetBounds(65, 151, 130, 42);''',
    '''            save.SetBounds(205, 151, 130, 42);
            Button cancel = MakeButton("Cancel", false);
            cancel.DialogResult = DialogResult.Cancel;
            cancel.SetBounds(65, 151, 130, 42);
            Button reset = MakeButton("Reset all pairing", false);
            reset.SetBounds(65, 216, 270, 42);
            reset.Click += delegate
            {
                if (MessageBox.Show(dialog,
                    "This creates a new device identity and private space, clears every remembered device, and forces all other devices to pair again.",
                    "Reset all ClipMesh pairing?", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK) return;
                string name = latestState == null ? Environment.MachineName : latestState.DeviceName;
                dialog.DialogResult = DialogResult.Abort;
                dialog.Close();
                MutateRuntime(delegate { ClipMeshRuntime.ResetIdentity(name); });
            };''',
    "Windows settings reset button",
)
replace_once(
    win_ui,
    '''            dialog.Controls.Add(save);
            dialog.Controls.Add(cancel);''',
    '''            dialog.Controls.Add(save);
            dialog.Controls.Add(cancel);
            dialog.Controls.Add(reset);''',
    "Windows add reset control",
)

# Version metadata is stamped again by workflow, but keep native wrapper source
# internally consistent for direct/local builds too.
replace_if_present(win_ui, 'private const string Version = "0.1.7";', 'private const string Version = "0.1.8";')
replace_if_present(win_ui, 'private const string Version = "0.1.6";', 'private const string Version = "0.1.8";')
replace_if_present(win_ui, 'private const string Version = "0.1.3";', 'private const string Version = "0.1.8";')

android_gradle = project / "android/app/build.gradle.kts"
replace_once(android_gradle, 'versionCode = 7', 'versionCode = 8', "Android v0.1.8 versionCode")
replace_once(android_gradle, 'versionName = "0.1.7"', 'versionName = "0.1.8"', "Android v0.1.8 versionName")

mac_build = project / "scripts/build-macos.sh"
replace_if_present(mac_build, '<key>CFBundleShortVersionString</key><string>0.1.7</string>', '<key>CFBundleShortVersionString</key><string>0.1.8</string>')
replace_if_present(mac_build, '<key>CFBundleVersion</key><string>0.1.7</string>', '<key>CFBundleVersion</key><string>0.1.8</string>')

# Hard guards for this release.
final_bridge = bridge.read_text(encoding="utf-8")
for required in (
    'BitmapFactory.decodeByteArray',
    'Representation("image/png", png)',
    'SUPPRESS_CLIPBOARD_OVERLAY',
    'readUriBytes(uri)',
):
    if required not in final_bridge:
        raise SystemExit(f"v0.1.8 missing Android image/remote clipboard guard: {required}")

final_mac = mac_ui.read_text(encoding="utf-8")
for required in ('buildMainMenu()', 'Close Window', 'Paste', 'Reset All Pairing', 'Runtime.resetIdentity'):
    if required not in final_mac:
        raise SystemExit(f"v0.1.8 missing macOS UI guard: {required}")

print("Applied ClipMesh v0.1.8 pairing reset, live Shizuku state, background default, quiet remote clipboard, macOS shortcuts, and Android image sync fixes")
