from pathlib import Path
import os, platform, re

root = Path(__file__).resolve().parents[1]
project = Path(os.environ.get('CLIPMESH_PROJECT', str(root / 'clipmesh')))
system = os.environ.get('CLIPMESH_PLATFORM', platform.system())


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match in {path}, found {count}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def regex_once(path: Path, pattern: str, repl: str, label: str, flags=re.S):
    text = path.read_text(encoding='utf-8')
    out, count = re.subn(pattern, lambda _m: repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 regex match in {path}, found {count}')
    path.write_text(out, encoding='utf-8')


if system == 'Linux':
    java = project / 'android/app/src/main/java/dev/clipmesh'
    manifest = project / 'android/app/src/main/AndroidManifest.xml'
    gradle = project / 'android/app/build.gradle.kts'
    replace_once(gradle, 'versionCode = 10', 'versionCode = 11', 'Android versionCode')
    replace_once(gradle, 'versionName = "0.2.0"', 'versionName = "0.2.1"', 'Android versionName')

    (java / 'BackgroundRuntime.kt').write_text(r'''package dev.clipmesh

import android.content.Context
import dev.clipmesh.clipboard.ClipboardBridge
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.network.NetworkEngine
import dev.clipmesh.shizuku.ShizukuManager

/** Notification-free, event-driven runtime. Android foreground services always require
 * a permanent notification, so v0.2.1 uses the system-bound Accessibility helper as
 * the background wake signal and Shizuku for privileged clipboard bytes. Network
 * listeners block while idle instead of polling. */
object BackgroundRuntime {
    @Volatile var status: String = "Stopped"
        private set
    private var shizuku: ShizukuManager? = null
    private var network: NetworkEngine? = null
    private var clipboard: ClipboardBridge? = null

    @Synchronized fun start(context: Context) {
        val app = context.applicationContext
        LocalTransferEngine.start(app)
        val settings = SettingsStore(app)
        if (!settings.backgroundSync) { status = "Clipboard sync off - nearby file receive ready"; return }
        val space = settings.spaceId
        val key = SecretStore(app).loadSpaceKey()
        if (space == null || key == null) { status = "Not paired - nearby file receive ready"; return }
        if (network != null && clipboard != null) return
        val sh = ShizukuManager(app)
        lateinit var bridge: ClipboardBridge
        val net = NetworkEngine(settings, key, { payload -> bridge.applyRemote(payload) }, { text -> status = text })
        bridge = ClipboardBridge(app, settings, sh) { payload -> net.sendClipboard(payload) }
        shizuku = sh; network = net; clipboard = bridge
        bridge.start(); net.start()
        status = if (sh.hasPermission()) "Clipboard sync ready" else "Shizuku permission needed for background clipboard"
    }

    @Synchronized fun stop() {
        clipboard?.stop(); clipboard = null
        network?.stop(); network = null
        shizuku?.close(); shizuku = null
        LocalTransferEngine.stop(); status = "Stopped"
    }
    @Synchronized fun restart(context: Context) { stop(); start(context) }
    fun captureNow() { clipboard?.captureNowForForeground() }
}
''', encoding='utf-8')

    tracker = java / 'exclusion/ForegroundTracker.kt'
    replace_once(tracker,
'''object ForegroundTracker {
    @Volatile var currentPackage: String? = null
    @Volatile var clipboardChanged: (() -> Unit)? = null
}''',
'''object ForegroundTracker {
    @Volatile var currentPackage: String? = null
    @Volatile var clipboardChanged: (() -> Unit)? = null
    @Volatile var accessibilityConnected: Boolean = false
}''', 'Accessibility state tracker')

    access = java / 'exclusion/ExclusionAccessibilityService.kt'
    replace_once(access, 'import android.view.accessibility.AccessibilityEvent', 'import android.view.accessibility.AccessibilityEvent\nimport dev.clipmesh.BackgroundRuntime', 'Accessibility runtime import')
    replace_once(access, '        clipboard = getSystemService(ClipboardManager::class.java)\n        clipboard?.addPrimaryClipChangedListener(clipboardListener)', '        ForegroundTracker.accessibilityConnected = true\n        BackgroundRuntime.start(this)\n        clipboard = getSystemService(ClipboardManager::class.java)\n        clipboard?.addPrimaryClipChangedListener(clipboardListener)', 'Accessibility runtime startup')
    replace_once(access, '        clipboard?.removePrimaryClipChangedListener(clipboardListener)\n        clipboard = null\n        super.onDestroy()', '        ForegroundTracker.accessibilityConnected = false\n        clipboard?.removePrimaryClipChangedListener(clipboardListener)\n        clipboard = null\n        super.onDestroy()', 'Accessibility state shutdown')

    user = java / 'shizuku/ClipboardUserService.kt'
    replace_once(user, 'import android.content.ClipData', 'import android.content.ClipData\nimport android.content.Context', 'UserService Context import')
    replace_once(user, 'class ClipboardUserService : IClipboardUserService.Stub() {', 'class ClipboardUserService private constructor(private val serviceContext: Context?) : IClipboardUserService.Stub() {\n    constructor() : this(null)\n    constructor(context: Context) : this(context.applicationContext)', 'UserService constructors')
    replace_once(user,
'''        val resolver = application()?.contentResolver ?: return false
        return runCatching {
            resolver.openInputStream(uri)?.use { input ->
                FileOutputStream(destination.fileDescriptor).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        total += n
                        if (total > MAX_ITEM_BYTES) return false
                        output.write(buffer, 0, n)
                    }
                }
            } ?: return false
            true
        }.getOrDefault(false)''',
'''        return readUriAsShell(uri, destination) || readUriWithResolver(uri, destination)
    }

    private fun readUriAsShell(uri: Uri, destination: ParcelFileDescriptor): Boolean = runCatching {
        val process = ProcessBuilder("/system/bin/content", "read", "--uri", uri.toString()).redirectErrorStream(false).start()
        var total = 0L
        process.inputStream.use { input -> FileOutputStream(destination.fileDescriptor).use { output ->
            val buffer = ByteArray(64 * 1024)
            while (true) { val n = input.read(buffer); if (n < 0) break; total += n; if (total > MAX_ITEM_BYTES) { process.destroyForcibly(); return@runCatching false }; output.write(buffer, 0, n) }
            output.flush()
        } }
        process.waitFor() == 0 && total > 0L
    }.getOrDefault(false)

    private fun readUriWithResolver(uri: Uri, destination: ParcelFileDescriptor): Boolean = runCatching {
        val resolver = serviceContext?.contentResolver ?: application()?.contentResolver ?: return@runCatching false
        resolver.openInputStream(uri)?.use { input -> FileOutputStream(destination.fileDescriptor).use { output ->
            val buffer = ByteArray(64 * 1024); var total = 0L
            while (true) { val n = input.read(buffer); if (n < 0) break; total += n; if (total > MAX_ITEM_BYTES) return@runCatching false; output.write(buffer, 0, n) }
            output.flush(); return@runCatching total > 0L
        } }
        false
    }.getOrDefault(false)''', 'Shizuku shell URI copy')
    shizuku = java / 'shizuku/ShizukuManager.kt'
    replace_once(shizuku, '.version(3)', '.version(4)', 'Shizuku service generation')

    net = java / 'network/NetworkEngine.kt'
    replace_once(net, 'soTimeout = 1000', 'soTimeout = 0', 'blocking clipboard discovery')
    replace_once(net, 'delay(if (peers.isEmpty()) 12_000L else 45_000L)', 'delay(if (peers.isEmpty()) 60_000L else 180_000L)', 'clipboard discovery interval')
    replace_once(net, 'delay(20_000L)', 'delay(120_000L)', 'static peer interval')
    replace_once(net, 'delay(30_000L)', 'delay(120_000L)', 'keepalive interval')

    transfer = java / 'fileshare/LocalTransferEngine.kt'
    replace_once(transfer, 'private const val DEVICE_TTL_MS = 22_000L', 'private const val DEVICE_TTL_MS = 180_000L', 'nearby TTL')
    replace_once(transfer, 'soTimeout = 1_500', 'soTimeout = 0', 'blocking LocalSend discovery')
    regex_once(transfer, r'''    private fun runAnnouncer\(\) \{.*?\n    \}\n\n    private fun runDiscovery''', r'''    private fun runAnnouncer() {
        while (started.get()) {
            runCatching { sendAnnouncement(true) }
            repeat(240) { if (!started.get()) return; try { Thread.sleep(500) } catch (_: InterruptedException) { return } }
        }
    }

    fun discoverNow() {
        if (!started.get()) return
        executor.execute { repeat(3) { index -> if (!started.get()) return@execute; runCatching { sendAnnouncement(true) }; if (index < 2) try { Thread.sleep(180) } catch (_: InterruptedException) { return@execute } } }
    }

    private fun runDiscovery''', 'event-driven LocalSend announcer')

    share = java / 'fileshare/FileShareActivity.kt'
    replace_once(share, 'import dev.clipmesh.R', 'import dev.clipmesh.R\nimport dev.clipmesh.BackgroundRuntime', 'file sender runtime import')
    replace_once(share, '        FileTransferService.start(this)', '        BackgroundRuntime.start(this)\n        LocalTransferEngine.discoverNow()', 'file sender runtime start')
    for a,b in {
        'Color.rgb(34, 33, 28)':'Color.rgb(18, 17, 16)', 'Color.argb(232, 78, 74, 61)':'Color.argb(22, 255, 255, 255)',
        'Color.argb(225, 94, 89, 73)':'Color.argb(30, 255, 255, 255)', 'Color.rgb(250, 248, 241)':'Color.rgb(246, 242, 233)',
        'Color.rgb(196, 191, 173)':'Color.rgb(174, 169, 160)', 'Color.argb(105, 232, 226, 202)':'Color.argb(34, 255, 255, 255)',
        'Color.rgb(242, 238, 218)':'Color.rgb(232, 145, 60)', 'Color.rgb(44, 42, 34)':'Color.rgb(13, 12, 10)', 'Color.rgb(186, 224, 166)':'Color.rgb(244, 169, 78)'
    }.items():
        replace_once(share, a, b, 'file sender theme')

    main = java / 'MainActivity.kt'
    text = main.read_text(encoding='utf-8')
    text = text.replace('import android.app.AlertDialog', 'import android.app.AlertDialog\nimport android.app.Dialog')
    text = text.replace('import android.graphics.Color', 'import android.graphics.Color\nimport android.graphics.BitmapFactory')
    text = text.replace('import android.widget.*', 'import android.widget.*\nimport android.provider.OpenableColumns')
    text = text.replace('import dev.clipmesh.fileshare.FileTransferService\n', '')
    text = text.replace('import dev.clipmesh.fileshare.FileShareActivity', 'import dev.clipmesh.fileshare.FileShareActivity\nimport dev.clipmesh.fileshare.LocalTransferEngine')
    text = text.replace('    private lateinit var pairInput: EditText\n', '    private lateinit var pairInput: EditText\n    private lateinit var clipboardBody: LinearLayout\n    private lateinit var transferBody: LinearLayout\n')
    palette = {'Color.rgb(35, 34, 29)':'Color.rgb(18, 17, 16)','Color.rgb(69, 66, 56)':'Color.rgb(33, 31, 29)','Color.rgb(249, 247, 239)':'Color.rgb(246, 242, 233)','Color.rgb(194, 189, 171)':'Color.rgb(174, 169, 160)','Color.rgb(91, 86, 70)':'Color.rgb(232, 145, 60)','Color.rgb(111, 105, 86)':'Color.argb(34, 255, 255, 255)','Color.rgb(184, 224, 164)':'Color.rgb(244, 169, 78)'}
    for a,b in palette.items(): text = text.replace(a,b)
    text = text.replace('        FileTransferService.start(this)', '        BackgroundRuntime.start(this)')
    old_resume = '''        if (::status.isInitialized) refreshHome()
        if (settings.backgroundSync && settings.spaceId != null && secrets.loadSpaceKey() != null) {
            window.decorView.postDelayed({
                runCatching {
                    startService(Intent(this, SyncService::class.java).setAction(SyncService.ACTION_CAPTURE_CURRENT))
                }
            }, 250L)
        }'''
    new_resume = '''        BackgroundRuntime.start(this)
        BackgroundRuntime.captureNow()
        if (::status.isInitialized) refreshHome()'''
    if old_resume not in text: raise SystemExit('MainActivity onResume anchor missing')
    text = text.replace(old_resume, new_resume, 1)
    start = text.index('    private fun render() {'); end = text.index('    private fun refreshHome() {')
    new_render = r'''    private fun render() {
        window.statusBarColor = pageBackground; if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = 0; window.navigationBarColor = pageBackground
        val outer = ScrollView(this).apply { isFillViewport = true; setBackgroundColor(pageBackground); clipToPadding = false }
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(22), dp(18), dp(34)) }; outer.addView(root)
        val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(dp(2),0,dp(2),dp(18)) }
        header.addView(LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; addView(label("ClipMesh",31f,true,ink)); addView(label("Private clipboard + nearby drop",14f,false,muted)) }, LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f))
        header.addView(button("Settings",false){startActivity(Intent(this@MainActivity,SettingsActivity::class.java))},LinearLayout.LayoutParams(dp(104),dp(46))); root.addView(header)
        status=label("Starting…",13f,false,muted).apply{setPadding(dp(4),0,dp(4),dp(12))}; root.addView(status)
        val deviceCard=card(root); deviceCard.addView(label("THIS DEVICE",11f,true,muted).apply{letterSpacing=.12f}); deviceNameText=label("",22f,true,ink).apply{setPadding(0,dp(7),0,0)}; deviceCard.addView(deviceNameText); deviceIdText=label("",12f,false,muted).apply{setPadding(0,dp(3),0,dp(13))}; deviceCard.addView(deviceIdText); deviceCard.addView(button("Rename device",false){renameDevice()})
        val clip=accordion(root,"Clipboard","Instant encrypted sync between paired devices"); clipboardBody=clip.second; clipboardBody.addView(label("Type + actual content only. Images render as images - no URI or debug metadata.",13f,false,muted).apply{setPadding(0,0,0,dp(10))}); clipboardBody.addView(button("View current clipboard"){showClipboard()},fullWidthParams(dp(50))); clipboardBody.addView(button("Copy pairing code",false){copyPairingCode()},fullWidthParams(dp(48)).apply{topMargin=dp(8)})
        val transfer=accordion(root,"File Transfer","LocalSend-style nearby transfer on this Wi-Fi"); transferBody=transfer.second; transferBody.addView(label("Nearby devices",16f,true,ink).apply{setPadding(0,0,0,dp(8))}); transferBody.addView(label("Send files, star trusted devices, or review incoming transfers.",13f,false,muted).apply{setPadding(0,0,0,dp(10))}); transferBody.addView(button("Open file transfer"){LocalTransferEngine.discoverNow();startActivity(Intent(this@MainActivity,FileShareActivity::class.java))},fullWidthParams(dp(50)))
        val peersCard=card(root); val peersHeader=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL}; peersHeader.addView(label("PAIRED DEVICES",11f,true,muted).apply{letterSpacing=.12f},LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f)); peersHeader.addView(button("Refresh",false){refreshHome()},LinearLayout.LayoutParams(dp(92),dp(42))); peersCard.addView(peersHeader); peersContainer=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(0,dp(8),0,0)}; peersCard.addView(peersContainer)
        root.addView(button("Pair another device"){togglePanel(pairPanel)},fullWidthParams(dp(50)).apply{bottomMargin=dp(14)}); pairPanel=card(root).apply{visibility=View.GONE}; pairPanel.addView(label("PAIR DEVICE",11f,true,muted).apply{letterSpacing=.12f}); pairPanel.addView(label("Paste a pairing code from another trusted ClipMesh device, or create a new private space.",14f,false,muted).apply{setPadding(0,dp(8),0,dp(10))}); pairInput=EditText(this).apply{hint="clipmesh://pair?...";inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS or InputType.TYPE_TEXT_FLAG_MULTI_LINE;minLines=2;maxLines=4;setTextColor(ink);setHintTextColor(muted);setPadding(dp(14),dp(11),dp(14),dp(11));background=rounded(Color.rgb(26,24,21),dp(14).toFloat(),border)}; pairPanel.addView(pairInput,fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT).apply{bottomMargin=dp(10)}); pairPanel.addView(horizontal(button("Join"){joinSpace()},button("Create new",false){createSpace()})); root.addView(label("Pairing codes contain the private space key. Only share them with devices you trust.",12f,false,muted).apply{setPadding(dp(4),dp(3),dp(4),0)})
        setContentView(outer); refreshHome()
    }

    private fun accordion(root:LinearLayout,title:String,subtitle:String):Pair<LinearLayout,LinearLayout>{
        val shell=card(root); val header=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL;isClickable=true;isFocusable=true}; val copy=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;addView(label(title,19f,true,ink));addView(label(subtitle,12f,false,muted).apply{setPadding(0,dp(3),0,0)})}; val chevron=label("⌄",22f,false,muted).apply{gravity=Gravity.CENTER}; header.addView(copy,LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));header.addView(chevron,LinearLayout.LayoutParams(dp(42),dp(42)));val body=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;visibility=View.GONE;alpha=0f;translationY=-dp(6).toFloat();setPadding(0,dp(14),0,0)};header.setOnClickListener{val opening=body.visibility!=View.VISIBLE;if(opening){body.visibility=View.VISIBLE;chevron.text="⌃";body.animate().alpha(1f).translationY(0f).setDuration(180L).start();if(title=="File Transfer")LocalTransferEngine.discoverNow()}else{chevron.text="⌄";body.animate().alpha(0f).translationY(-dp(6).toFloat()).setDuration(140L).withEndAction{body.visibility=View.GONE}.start()}};shell.addView(header);shell.addView(body);return Pair(shell,body)
    }
    private fun togglePanel(view:View){val opening=view.visibility!=View.VISIBLE;if(opening){view.visibility=View.VISIBLE;view.alpha=0f;view.translationY=-dp(6).toFloat();view.animate().alpha(1f).translationY(0f).setDuration(180L).start()}else view.animate().alpha(0f).translationY(-dp(6).toFloat()).setDuration(140L).withEndAction{view.visibility=View.GONE}.start()}

'''
    text = text[:start] + new_render + text[end:]
    text = text.replace('${SyncService.status}', '${BackgroundRuntime.status}')
    text = text.replace('if (restart) stopService(Intent(this, SyncService::class.java))', 'if (restart) BackgroundRuntime.stop()').replace('if (restart) startSyncService()', 'if (restart) BackgroundRuntime.start(this)')
    show_start=text.index('    private fun showClipboard() {');show_end=text.index('    private fun startSyncService() {')
    show_new=r'''    private fun showClipboard(){
        BackgroundRuntime.captureNow();val dialog=Dialog(this);val root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(20),dp(20),dp(18));background=rounded(Color.rgb(30,28,26),dp(26).toFloat(),border)};root.addView(label("Clipboard",23f,true,ink));root.addView(label("Current local content",12f,false,muted).apply{setPadding(0,dp(2),0,dp(16))});root.addView(buildClipboardPreview(),fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT));root.addView(button("Done",false){dialog.dismiss()},fullWidthParams(dp(48)).apply{topMargin=dp(16)});dialog.setContentView(root);dialog.window?.apply{setBackgroundDrawableResource(android.R.color.transparent);setDimAmount(.72f);addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND)};dialog.show();dialog.window?.setLayout((resources.displayMetrics.widthPixels*.90f).toInt(),ViewGroup.LayoutParams.WRAP_CONTENT)
    }
    private fun buildClipboardPreview():View{
        val manager=getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager;val clip=runCatching{manager.primaryClip}.getOrNull();val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(16),dp(15),dp(16),dp(15));background=rounded(Color.rgb(26,24,21),dp(18).toFloat(),border)};if(clip==null||clip.itemCount==0){box.addView(label("EMPTY",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});box.addView(label("Nothing is on the clipboard.",14f,false,muted).apply{setPadding(0,dp(8),0,0)});return box};var imageUri:android.net.Uri?=null;for(i in 0 until clip.itemCount){val uri=clip.getItemAt(i).uri?:continue;val mime=runCatching{contentResolver.getType(uri)}.getOrNull();if(mime?.startsWith("image/")==true||(clip.description.mimeTypeCount>0&&(0 until clip.description.mimeTypeCount).any{clip.description.getMimeType(it).startsWith("image/")})){imageUri=uri;break}};if(imageUri!=null){box.addView(label("IMAGE",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});val bitmap=runCatching{contentResolver.openInputStream(imageUri!!)?.use{BitmapFactory.decodeStream(it)}}.getOrNull();if(bitmap!=null)box.addView(ImageView(this).apply{setImageBitmap(bitmap);adjustViewBounds=true;scaleType=ImageView.ScaleType.CENTER_INSIDE;background=rounded(Color.rgb(13,12,10),dp(14).toFloat(),Color.TRANSPARENT);setPadding(dp(4),dp(4),dp(4),dp(4))},fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT).apply{topMargin=dp(10)})else box.addView(label("Image preview unavailable on this clipboard provider.",14f,false,muted).apply{setPadding(0,dp(8),0,0)});return box};val first=clip.getItemAt(0);val actualText=first.text?.toString()?:runCatching{first.coerceToText(this).toString()}.getOrNull();if(!actualText.isNullOrBlank()){box.addView(label("TEXT",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});box.addView(label(actualText.take(16000),15f,false,ink).apply{setTextIsSelectable(true);setPadding(0,dp(9),0,0)});return box};val names=(0 until clip.itemCount).mapNotNull{i->val uri=clip.getItemAt(i).uri?:return@mapNotNull null;runCatching{contentResolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use{c->if(c.moveToFirst())c.getString(0)else null}}.getOrNull()?:"File ${i+1}"};box.addView(label("FILES",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});box.addView(label(if(names.isEmpty())"Clipboard content" else names.joinToString("\n"),15f,false,ink).apply{setPadding(0,dp(9),0,0)});return box
    }

'''
    text=text[:show_start]+show_new+text[show_end:]
    text,n=re.subn(r'''    private fun startSyncService\(\) \{.*?\n    \}\n\n    private fun card''','    private fun startSyncService() { BackgroundRuntime.start(this) }\n\n    private fun card',text,count=1,flags=re.S)
    if n!=1: raise SystemExit('MainActivity startSyncService replacement failed')
    text=text.replace('background = rounded(cardBackground, dp(18).toFloat(), border)','background = rounded(cardBackground, dp(26).toFloat(), border)').replace('setTextColor(if (primaryStyle) Color.WHITE else ink)','setTextColor(if (primaryStyle) Color.rgb(13,12,10) else ink)').replace('background = rounded(if (primaryStyle) primary else Color.rgb(82, 78, 65), dp(12).toFloat(), if (primaryStyle) primary else border)','background = rounded(if (primaryStyle) Color.rgb(241,235,221) else Color.rgb(43,41,37), dp(24).toFloat(), if (primaryStyle) Color.TRANSPARENT else border)')
    main.write_text(text,encoding='utf-8')

    settings=java/'SettingsActivity.kt';s=settings.read_text(encoding='utf-8').replace('shizukuUiHandler.postDelayed(this, 700L)','shizukuUiHandler.postDelayed(this, 1_500L)')
    for a,b in palette.items():s=s.replace(a,b)
    s=s.replace('if (checked) startSyncService() else stopService(Intent(this, SyncService::class.java))','if (checked) BackgroundRuntime.start(this) else BackgroundRuntime.restart(this)').replace('"Shizuku lets ClipMesh read and write the clipboard from the background without continuous polling. On non-rooted phones it may need to be started again after a reboot."','"For notification-free background sync, enable the ClipMesh Accessibility helper and authorize Shizuku. Accessibility provides event wake-ups; Shizuku reads the clipboard bytes. There is no 1-second background clipboard polling."').replace('"The compatibility watchdog is off by default. Leave it off unless your phone suppresses clipboard callbacks."','"Leave the compatibility watchdog off for minimum battery use. The Accessibility helper is the preferred event-driven path."').replace('stopService(Intent(this, SyncService::class.java))','BackgroundRuntime.stop()')
    s=re.sub(r'''    private fun startSyncService\(\) \{.*?\n    \}''','    private fun startSyncService() { BackgroundRuntime.start(this) }',s,flags=re.S);settings.write_text(s,encoding='utf-8')

    m=manifest.read_text(encoding='utf-8')
    for perm in ['    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />\n','    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_SPECIAL_USE" />\n','    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" />','    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />\n']:m=m.replace(perm,'')
    m=re.sub(r'''\n        <service android:name="\.SyncService".*?</service>\n''','\n',m,count=1,flags=re.S);m=re.sub(r'''<service android:name="\.fileshare\.FileTransferService"[^>]*/>''','',m,count=1);m=re.sub(r'''<receiver android:name="\.fileshare\.TransferBootReceiver".*?</receiver>''','',m,count=1);m=re.sub(r'''\n        <receiver android:name="\.BootReceiver".*?</receiver>\n''','\n',m,count=1,flags=re.S);manifest.write_text(m,encoding='utf-8')

    final_main=main.read_text(encoding='utf-8');final_manifest=manifest.read_text(encoding='utf-8');final_user=user.read_text(encoding='utf-8');final_transfer=transfer.read_text(encoding='utf-8');final_network=net.read_text(encoding='utf-8')
    for required in ['Clipboard','File Transfer','buildClipboardPreview','IMAGE','View.GONE','BackgroundRuntime.start(this)']:
        if required not in final_main:raise SystemExit(f'v0.2.1 Android UI guard missing {required}')
    for forbidden in ['startForeground(','FileTransferService"','SyncService"','FOREGROUND_SERVICE_DATA_SYNC']:
        if forbidden in final_manifest:raise SystemExit(f'Persistent service guard failed: {forbidden}')
    if 'ProcessBuilder("/system/bin/content", "read", "--uri"' not in final_user:raise SystemExit('Android image shell read missing')
    if 'soTimeout = 0' not in final_network or '180_000L' not in final_transfer or 'fun discoverNow()' not in final_transfer:raise SystemExit('Battery/discovery guards missing')

elif system == 'Darwin':
    app=root/'ci/ClipMeshApp.swift';transfer=root/'ci/ClipMeshTransfer.swift';build=project/'scripts/build-macos.sh'
    replace_once(app,'    private var latestState: UIState?\n','    private var latestState: UIState?\n    private var clipboardPanel: NSStackView?\n    private var filePanel: NSStackView?\n    private var clipboardWindow: NSWindow?\n','mac accordion state')
    old='''        root.addArrangedSubview(separator())
        root.addArrangedSubview(sectionLabel("QUICK ACTIONS"))
        let quick = NSStackView()
        quick.orientation = .horizontal
        quick.spacing = 9
        quick.addArrangedSubview(button("Copy Pairing Code", action: #selector(copyPairingLink)))
        quick.addArrangedSubview(button("View Clipboard", action: #selector(viewClipboard)))
        quick.addArrangedSubview(button("Send Files", action: #selector(sendFiles)))
        quick.addArrangedSubview(button("Pair Device", action: #selector(togglePairPanel)))
        root.addArrangedSubview(quick)'''
    new='''        root.addArrangedSubview(separator())
        root.addArrangedSubview(sectionLabel("WORKSPACE"))
        let clipHeader = button("Clipboard   ·   encrypted sync                                      ⌄", action: #selector(toggleClipboardPanel)); clipHeader.alignment = .left; root.addArrangedSubview(clipHeader); clipHeader.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        let clipBody = NSStackView(); clipBody.orientation = .vertical; clipBody.alignment = .leading; clipBody.spacing = 8; clipBody.isHidden = true
        let clipHint = NSTextField(wrappingLabelWithString: "Actual clipboard content only. Images render as images; file entries show names instead of pasteboard paths."); clipHint.textColor = .secondaryLabelColor; clipHint.preferredMaxLayoutWidth = 520; clipBody.addArrangedSubview(clipHint); clipBody.addArrangedSubview(button("View current clipboard", action: #selector(viewClipboard))); clipBody.addArrangedSubview(button("Copy pairing code", action: #selector(copyPairingLink))); root.addArrangedSubview(clipBody); clipboardPanel = clipBody
        let fileHeader = button("File Transfer   ·   nearby drop                                      ⌄", action: #selector(toggleFilePanel)); fileHeader.alignment = .left; root.addArrangedSubview(fileHeader); fileHeader.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        let fileBody = NSStackView(); fileBody.orientation = .vertical; fileBody.alignment = .leading; fileBody.spacing = 8; fileBody.isHidden = true
        let fileHint = NSTextField(wrappingLabelWithString: "Discover nearby ClipMesh devices, star trusted devices, and send directly over this Wi-Fi."); fileHint.textColor = .secondaryLabelColor; fileHint.preferredMaxLayoutWidth = 520; fileBody.addArrangedSubview(fileHint); fileBody.addArrangedSubview(button("Open file transfer", action: #selector(sendFiles))); fileBody.addArrangedSubview(button("Pair Device", action: #selector(togglePairPanel))); root.addArrangedSubview(fileBody); filePanel = fileBody'''
    replace_once(app,old,new,'mac workspace accordions')
    replace_once(app,'    @objc private func showFromMenu() { showWindow() }\n    @objc private func refreshClicked() { refreshHome() }','''    @objc private func showFromMenu() { showWindow() }
    @objc private func refreshClicked() { refreshHome() }
    @objc private func toggleClipboardPanel() { animatePanel(clipboardPanel) }
    @objc private func toggleFilePanel() { if filePanel?.isHidden == true { LocalTransferManager.shared.discoverNow() }; animatePanel(filePanel) }
    private func animatePanel(_ panel: NSStackView?) { guard let panel else { return }; if panel.isHidden { panel.alphaValue=0;panel.isHidden=false;NSAnimationContext.runAnimationGroup{c in c.duration=0.18;panel.animator().alphaValue=1} } else { NSAnimationContext.runAnimationGroup({c in c.duration=0.14;panel.animator().alphaValue=0},completionHandler:{panel.isHidden=true;panel.alphaValue=1}) } }''','mac accordion actions')
    regex_once(app,r'''    @objc private func viewClipboard\(\) \{.*?\n    \}\n\n    @objc private func quitApp''',r'''    @objc private func viewClipboard() {
        let pasteboard=NSPasteboard.general;let panel=NSWindow(contentRect:NSRect(x:0,y:0,width:560,height:500),styleMask:[.titled,.closable],backing:.buffered,defer:false);panel.title="Clipboard";panel.appearance=NSAppearance(named:.darkAqua);panel.titlebarAppearsTransparent=true
        let root=NSStackView();root.orientation=.vertical;root.alignment=.leading;root.spacing=12;root.translatesAutoresizingMaskIntoConstraints=false;let bg=NSView();bg.wantsLayer=true;bg.layer?.backgroundColor=NSColor(calibratedRed:18/255,green:17/255,blue:16/255,alpha:1).cgColor;panel.contentView=bg;bg.addSubview(root);NSLayoutConstraint.activate([root.leadingAnchor.constraint(equalTo:bg.leadingAnchor,constant:24),root.trailingAnchor.constraint(equalTo:bg.trailingAnchor,constant:-24),root.topAnchor.constraint(equalTo:bg.topAnchor,constant:24)])
        let title=NSTextField(labelWithString:"Clipboard");title.font=.systemFont(ofSize:26,weight:.bold);root.addArrangedSubview(title)
        if let image=NSImage(pasteboard:pasteboard){let kind=NSTextField(labelWithString:"IMAGE");kind.textColor=NSColor(calibratedRed:232/255,green:145/255,blue:60/255,alpha:1);kind.font=.systemFont(ofSize:11,weight:.bold);root.addArrangedSubview(kind);let iv=NSImageView();iv.image=image;iv.imageScaling=.scaleProportionallyUpOrDown;iv.wantsLayer=true;iv.layer?.cornerRadius=16;root.addArrangedSubview(iv);iv.widthAnchor.constraint(equalTo:root.widthAnchor).isActive=true;iv.heightAnchor.constraint(equalToConstant:330).isActive=true}
        else if let text=pasteboard.string(forType:.string),!text.isEmpty{let kind=NSTextField(labelWithString:"TEXT");kind.textColor=NSColor(calibratedRed:232/255,green:145/255,blue:60/255,alpha:1);root.addArrangedSubview(kind);let value=NSTextField(wrappingLabelWithString:String(text.prefix(16000)));value.isSelectable=true;value.preferredMaxLayoutWidth=500;root.addArrangedSubview(value)}
        else if let urls=pasteboard.readObjects(forClasses:[NSURL.self],options:[.urlReadingFileURLsOnly:true]) as? [URL],!urls.isEmpty{let kind=NSTextField(labelWithString:"FILES");kind.textColor=NSColor(calibratedRed:232/255,green:145/255,blue:60/255,alpha:1);root.addArrangedSubview(kind);root.addArrangedSubview(NSTextField(wrappingLabelWithString:urls.prefix(30).map(\.lastPathComponent).joined(separator:"\n")))} else {root.addArrangedSubview(NSTextField(labelWithString:"Clipboard is empty."))}
        clipboardWindow=panel;panel.center();panel.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
    }

    @objc private func quitApp''','mac clipboard preview')
    replace_once(app,'    func applicationWillTerminate(_ notification: Notification) {','''    func application(_ application: NSApplication, open urls: [URL]) { for url in urls where url.scheme == "clipmesh-share" { guard let c=URLComponents(url:url,resolvingAgainstBaseURL:false),let manifest=c.queryItems?.first(where:{$0.name=="manifest"})?.value else { continue };let m=URL(fileURLWithPath:manifest);if let text=try? String(contentsOf:m,encoding:.utf8){let files=text.split(separator:"\n").map{URL(fileURLWithPath:String($0))}.filter{FileManager.default.fileExists(atPath:$0.path)};try? FileManager.default.removeItem(at:m);if !files.isEmpty{TransferChooserController.shared.show(files:files)}} } }

    func applicationWillTerminate(_ notification: Notification) {''','mac share URL handler')
    t=transfer.read_text(encoding='utf-8').replace('let cutoff = Date().addingTimeInterval(-22)','let cutoff = Date().addingTimeInterval(-180)').replace('source.schedule(deadline: .now() + 0.2, repeating: 5.0)','source.schedule(deadline: .now() + 0.2, repeating: 120.0)')
    anchor='    func setFavorite(_ fingerprint: String, _ favorite: Bool) {';idx=t.index(anchor);t=t[:idx]+'''    func discoverNow() { queue.async { [weak self] in guard let self else { return }; self.sendAnnouncement(announce:true);self.queue.asyncAfter(deadline:.now()+0.18){self.sendAnnouncement(announce:true)};self.queue.asyncAfter(deadline:.now()+0.36){self.sendAnnouncement(announce:true)} } }

'''+t[idx:];t=t.replace('            self.refreshFiles()\n            self.refreshDevices()','            self.refreshFiles()\n            LocalTransferManager.shared.discoverNow()\n            self.refreshDevices()').replace('effect.material = .hudWindow','effect.material = .underWindowBackground').replace('window.title = "Send with ClipMesh"; window.minSize','window.title = "Send with ClipMesh"; window.appearance = NSAppearance(named: .darkAqua); window.titlebarAppearsTransparent = true; window.minSize');transfer.write_text(t,encoding='utf-8')
    clipboard_rs=project/'apps/desktop/src/clipboard.rs'
    if clipboard_rs.is_file():clipboard_rs.write_text(clipboard_rs.read_text(encoding='utf-8').replace('Duration::from_millis(350)','Duration::from_millis(1500)'),encoding='utf-8')
    b=build.read_text(encoding='utf-8').replace('<key>CFBundleShortVersionString</key><string>0.2.0</string>','<key>CFBundleShortVersionString</key><string>0.2.1</string>').replace('<key>CFBundleVersion</key><string>0.2.0</string>','<key>CFBundleVersion</key><string>0.2.1</string>')
    b=b.replace('  <key>NSServices</key>','  <key>CFBundleURLTypes</key><array><dict><key>CFBundleURLName</key><string>ClipMesh Share</string><key>CFBundleURLSchemes</key><array><string>clipmesh-share</string></array></dict></array>\n  <key>NSServices</key>',1)
    sign='if command -v codesign >/dev/null 2>&1; then\n  codesign --force --deep --sign - "$APP" || true\nfi'
    extension=r'''APPEX="$APP/Contents/PlugIns/ClipMeshShare.appex"
mkdir -p "$APPEX/Contents/MacOS"
cat > "$OUT/ClipMeshShare.m" <<'OBJC'
#import <Cocoa/Cocoa.h>
@interface ClipMeshShareController : NSViewController
@property(nonatomic,strong) NSMutableArray<NSURL *> *files;
@end
@implementation ClipMeshShareController
- (void)loadView { NSView *v=[[NSView alloc]initWithFrame:NSMakeRect(0,0,380,150)];NSTextField*t=[NSTextField labelWithString:@"Send with ClipMesh"];t.font=[NSFont systemFontOfSize:20 weight:NSFontWeightSemibold];t.frame=NSMakeRect(22,102,330,30);[v addSubview:t];NSTextField*s=[NSTextField labelWithString:@"Choose the nearby device in ClipMesh."];s.textColor=NSColor.secondaryLabelColor;s.frame=NSMakeRect(22,73,330,24);[v addSubview:s];NSButton*b=[NSButton buttonWithTitle:@"Open ClipMesh" target:self action:@selector(send:)];b.bezelStyle=NSBezelStyleRounded;b.frame=NSMakeRect(22,24,150,38);[v addSubview:b];self.view=v;self.files=[NSMutableArray array]; }
- (void)viewDidAppear { [super viewDidAppear];for(NSExtensionItem*i in self.extensionContext.inputItems)for(NSItemProvider*p in i.attachments)if([p hasItemConformingToTypeIdentifier:@"public.file-url"])[p loadItemForTypeIdentifier:@"public.file-url" options:nil completionHandler:^(id<NSSecureCoding> value,NSError*e){if([value isKindOfClass:NSURL.class]&&[(NSURL*)value isFileURL])@synchronized(self.files){[self.files addObject:(NSURL*)value];}}]; }
- (void)send:(id)sender { if(self.files.count==0)return;NSString*path=[NSTemporaryDirectory() stringByAppendingPathComponent:[NSString stringWithFormat:@"clipmesh-share-%@.txt",NSUUID.UUID.UUIDString]];NSMutableString*body=[NSMutableString string];for(NSURL*u in self.files)[body appendFormat:@"%@\n",u.path];[body writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];NSURLComponents*c=[NSURLComponents componentsWithString:@"clipmesh-share://send"];c.queryItems=@[[NSURLQueryItem queryItemWithName:@"manifest" value:path]];[self.extensionContext openURL:c.URL completionHandler:^(BOOL ok){[self.extensionContext completeRequestReturningItems:@[] completionHandler:nil];}]; }
@end
OBJC
cat > "$APPEX/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>dev.ClipMesh.ClipMesh.Share</string><key>CFBundleName</key><string>ClipMesh</string><key>CFBundleDisplayName</key><string>ClipMesh</string><key>CFBundleExecutable</key><string>ClipMeshShare</string><key>CFBundlePackageType</key><string>XPC!</string><key>CFBundleShortVersionString</key><string>0.2.1</string><key>CFBundleVersion</key><string>0.2.1</string><key>NSExtension</key><dict><key>NSExtensionPointIdentifier</key><string>com.apple.share-services</string><key>NSExtensionPrincipalClass</key><string>ClipMeshShareController</string><key>NSExtensionAttributes</key><dict><key>NSExtensionActivationRule</key><dict><key>NSExtensionActivationSupportsFileWithMaxCount</key><integer>100</integer></dict></dict></dict></dict></plist>
PLIST
clang -fobjc-arc -framework Cocoa -bundle -o "$APPEX/Contents/MacOS/ClipMeshShare" "$OUT/ClipMeshShare.m"
plutil -lint "$APPEX/Contents/Info.plist"
if command -v codesign >/dev/null 2>&1; then codesign --force --sign - "$APPEX" || true; codesign --force --deep --sign - "$APP" || true; fi'''
    if sign not in b:raise SystemExit('macOS codesign anchor missing')
    build.write_text(b.replace(sign,extension,1),encoding='utf-8')

elif system == 'Windows':
    ui=root/'ci/ClipMeshWindows.cs';transfer=root/'ci/ClipMeshTransfer.cs';build=project/'scripts/build-windows.ps1';u=ui.read_text(encoding='utf-8')
    for a,b in {'Color.FromArgb(35, 34, 29)':'Color.FromArgb(18, 17, 16)','Color.FromArgb(69, 66, 56)':'Color.FromArgb(33, 31, 29)','Color.FromArgb(249, 247, 239)':'Color.FromArgb(246, 242, 233)','Color.FromArgb(194, 189, 171)':'Color.FromArgb(174, 169, 160)','Color.FromArgb(91, 86, 70)':'Color.FromArgb(232, 145, 60)'}.items():u=u.replace(a,b)
    ui.write_text(u.replace('0.2.0','0.2.1'),encoding='utf-8');transfer.write_text(transfer.read_text(encoding='utf-8').replace('0.2.0','0.2.1').replace('TimeSpan.FromSeconds(5)','TimeSpan.FromSeconds(120)').replace('22000','180000'),encoding='utf-8');build.write_text(build.read_text(encoding='utf-8').replace('0.2.0','0.2.1'),encoding='utf-8')
else:raise SystemExit(f'unsupported v0.2.1 platform: {system}')

print(f'Applied ClipMesh v0.2.1 final remake + battery pass for {system}')
