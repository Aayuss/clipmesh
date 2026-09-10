package dev.clipmesh

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.Dialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.BitmapFactory
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import android.provider.OpenableColumns
import java.util.concurrent.TimeUnit
import dev.clipmesh.fileshare.FileShareActivity
import dev.clipmesh.fileshare.LocalTransferEngine
import dev.clipmesh.fileshare.IncomingRequestUi
import dev.clipmesh.fileshare.NearbyPairingManager
import dev.clipmesh.fileshare.NearbyPairingUi

class MainActivity : Activity() {
    private lateinit var settings: SettingsStore
    private lateinit var secrets: SecretStore
    private lateinit var status: TextView
    private lateinit var deviceNameText: TextView
    private lateinit var deviceIdText: TextView
    private lateinit var peersContainer: LinearLayout
    private lateinit var nearbyPairContainer: LinearLayout
    private lateinit var pairPanel: LinearLayout
    private lateinit var pairInput: EditText
    private lateinit var clipboardPreviewContainer: LinearLayout

    private val pageBackground = Color.rgb(7, 8, 10)
    private val cardBackground = Color.rgb(17, 18, 22)
    private val ink = Color.rgb(246, 242, 233)
    private val muted = Color.rgb(174, 169, 160)
    private val primary = Color.rgb(181, 137, 52)
    private val border = Color.argb(34, 255, 255, 255)
    private val good = Color.rgb(235, 184, 62)

        override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (BuildConfig.DEBUG) {
            intent.getStringExtra("clipmesh_ci_favorite")?.takeIf { it.isNotBlank() }?.let {
                LocalTransferEngine.setFavorite(this, it, true)
            }
        }
        BackgroundService.start(this)
        settings = SettingsStore(this)
        secrets = SecretStore(this)
        BackgroundRuntime.start(this)
        requestNotificationPermission()
        render()
        consumePairingIntent(intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        consumePairingIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        IncomingRequestUi.attach(this)
        NearbyPairingUi.attach(this)
        BackgroundRuntime.start(this)
        LocalTransferEngine.start(this)
        LocalTransferEngine.discoverNow()
        BackgroundRuntime.captureNow()
        if (::status.isInitialized) { refreshHome(); renderClipboardContent() }
    }

    override fun onPause() { IncomingRequestUi.detach(this); NearbyPairingUi.detach(this); if (!settings.receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }

    private fun render() {
        window.statusBarColor = pageBackground
        window.navigationBarColor = pageBackground
        if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = 0

        val shell = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(pageBackground)
        }
        val outer = ScrollView(this).apply {
            isFillViewport = true
            clipToPadding = false
            setBackgroundColor(pageBackground)
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(22), dp(18), dp(26))
        }
        outer.addView(root)
        shell.addView(outer, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        root.addView(label("Clipboard", 31f, true, ink))
        root.addView(label("Instant encrypted sync between paired devices", 14f, false, muted).apply {
            setPadding(0, dp(4), 0, dp(14))
        })
        status = label("Starting…", 13f, false, muted).apply { setPadding(dp(2), 0, dp(2), dp(14)) }
        root.addView(status)

        val clipCard = card(root)
        clipboardPreviewContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE; setPadding(0, dp(12), 0, 0) }
        clipCard.addView(button("View current clipboard") {
            val opening = clipboardPreviewContainer.visibility != View.VISIBLE
            clipboardPreviewContainer.visibility = if (opening) View.VISIBLE else View.GONE
            if (opening) { BackgroundRuntime.captureNow(); renderClipboardContent() }
        }, fullWidthParams(dp(50)))
        clipCard.addView(clipboardPreviewContainer)

        val deviceCard = card(root)
        deviceCard.addView(label("THIS DEVICE NAME:", 11f, true, muted).apply { letterSpacing = .12f })
        deviceNameText = label("", 22f, true, ink).apply { setPadding(0, dp(7), 0, 0) }
        deviceCard.addView(deviceNameText)
        deviceIdText = label("", 12f, false, muted).apply { setPadding(0, dp(3), 0, 0) }
        deviceCard.addView(deviceIdText)
        deviceCard.addView(button("Rename device", false) { renameDevice() }, fullWidthParams(dp(48)).apply { topMargin = dp(10) })

        val peersCard = card(root)
        val peersHeader = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        peersHeader.addView(label("PAIRED DEVICES", 11f, true, muted).apply { letterSpacing = .12f }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        peersHeader.addView(button("Refresh", false) { refreshHome() }, LinearLayout.LayoutParams(dp(92), dp(42)))
        peersCard.addView(peersHeader)
        peersContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dp(8), 0, 0) }
        peersCard.addView(peersContainer)

        val nearbyCard=card(root)
        val nearbyHeader=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL}
        nearbyHeader.addView(label("AVAILABLE NEARBY DEVICES",11f,true,muted).apply{letterSpacing=.12f},LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f))
        nearbyHeader.addView(button("Rescan",false){LocalTransferEngine.discoverNow();nearbyHeader.postDelayed({renderNearbyPairDevices()},450)},LinearLayout.LayoutParams(dp(92),dp(42)))
        nearbyCard.addView(nearbyHeader)
        nearbyPairContainer=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(0,dp(8),0,0)}
        nearbyCard.addView(nearbyPairContainer)

        root.addView(button("Pair new device") {
            startActivity(Intent(this, SettingsActivity::class.java).putExtra("open_pairing", true))
            overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
        }, fullWidthParams(dp(50)))

        shell.addView(bottomNav(0), LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(72)))
        setContentView(shell)
        refreshHome()
    }

    private fun renderClipboardContent() {
        if (!::clipboardPreviewContainer.isInitialized) return
        clipboardPreviewContainer.removeAllViews()
        clipboardPreviewContainer.addView(buildClipboardPreview(), fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT))
    }

    private fun bottomNav(selected: Int): View {
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(dp(10), dp(8), dp(10), dp(8))
            background = rounded(Color.rgb(12, 13, 16), dp(24).toFloat(), border)
        }
        fun item(title: String, index: Int, click: () -> Unit): TextView = TextView(this).apply {
            text = title
            gravity = Gravity.CENTER
            textSize = 12f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (selected == index) Color.rgb(13, 12, 10) else muted)
            background = rounded(if (selected == index) Color.rgb(188, 145, 57) else Color.TRANSPARENT, dp(18).toFloat(), Color.TRANSPARENT)
            setOnClickListener { click() }
        }
        bar.addView(item("Clipboard", 0) {}, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { rightMargin = dp(6) })
        bar.addView(item("File transfer", 1) {
            LocalTransferEngine.discoverNow()
            startActivity(Intent(this@MainActivity, FileShareActivity::class.java))
            overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { leftMargin = dp(3); rightMargin = dp(3) })
        bar.addView(item("Settings", 2) {
            startActivity(Intent(this@MainActivity, SettingsActivity::class.java))
            overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { leftMargin = dp(6) })
        return bar
    }

    private fun refreshHome() {
        val paired = settings.spaceId != null && secrets.loadSpaceKey() != null
        deviceNameText.text = settings.deviceName
        val id = settings.deviceId.toString()
        deviceIdText.text = "Device ID  ${id.take(8)}…${id.takeLast(4)}"
        status.text = when {
            !paired -> "Not paired yet"
            settings.backgroundSync -> "Background sync enabled  •  ${BackgroundRuntime.status}"
            else -> "Paired  •  Background sync is off"
        }
        renderPeers()
        renderNearbyPairDevices()
    }

    private fun renderNearbyPairDevices(){if(!::nearbyPairContainer.isInitialized)return;nearbyPairContainer.removeAllViews();val pairedNames=settings.knownPeers().map{it.name.trim().lowercase()}.toSet();val devices=LocalTransferEngine.nearbyDevices().filterNot{pairedNames.contains(it.alias.trim().lowercase())};if(devices.isEmpty()){nearbyPairContainer.addView(label("No unpaired ClipMesh devices visible on this network.",14f,false,muted));return};devices.forEach{device->val row=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL};row.addView(label(device.alias,16f,true,ink),LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));row.addView(button("Pair"){startNearbyPair(device)},LinearLayout.LayoutParams(dp(96),dp(44)));nearbyPairContainer.addView(row)}}
    private fun startNearbyPair(device:LocalTransferEngine.TransferDevice){val space=settings.spaceId?:run{toast("Create or join a clipboard space first");return};val key=secrets.loadSpaceKey()?:run{toast("Clipboard key is unavailable");return};val credential=Pairing.toUri(Pairing.PairingData(space,key,settings.deviceName,settings.deviceId));status.text="Waiting for ${device.alias}…";NearbyPairingManager.pairClipboard(this,device,credential,{value->runOnUiThread{ClipMeshDialog.info(this, "Verification code", "Type this code on ${device.alias}:\n\n$value")}},{result->runOnUiThread{result.fold({status.text="Paired with ${device.alias}";refreshHome()},{toast(it.message?:"Pairing failed")})}})}

    private fun renderPeers() {
        peersContainer.removeAllViews()
        val peers = settings.knownPeers()
        if (peers.isEmpty()) {
            peersContainer.addView(label(
                "No other devices discovered yet. Keep ClipMesh running on both devices on the same local network, then tap Refresh.",
                14f, false, muted
            ).apply { setPadding(0, dp(5), 0, dp(5)) })
            return
        }
        val now = System.currentTimeMillis()
        peers.forEachIndexed { index, peer ->
            if (index > 0) peersContainer.addView(View(this).apply { setBackgroundColor(border) },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)).apply { topMargin = dp(10); bottomMargin = dp(10) })
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
            val texts = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
            texts.addView(label(peer.name, 16f, true, ink))
            texts.addView(label(peer.deviceId.toString().take(8) + "…", 12f, false, muted))
            row.addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            val online = peer.lastSeenMs > 0 && now - peer.lastSeenMs < 90_000L
            val state = if (online) "●  Online" else if (peer.lastSeenMs == 0L) "○  Paired" else "○  ${lastSeen(peer.lastSeenMs)}"
            row.addView(label(state, 13f, online, if (online) good else muted).apply { gravity = Gravity.END })
            row.addView(button("Remove", false) {
                settings.forgetPeer(peer.deviceId)
                BackgroundRuntime.restart(this)
                renderPeers(); renderNearbyPairDevices()
            }, LinearLayout.LayoutParams(dp(92), dp(42)).apply { leftMargin = dp(8) })
            peersContainer.addView(row)
        }
    }

    private fun lastSeen(timestamp: Long): String {
        val elapsed = (System.currentTimeMillis() - timestamp).coerceAtLeast(0L)
        return when {
            elapsed < 60_000L -> "Just now"
            elapsed < TimeUnit.HOURS.toMillis(1) -> "${elapsed / 60_000L}m ago"
            elapsed < TimeUnit.DAYS.toMillis(1) -> "${elapsed / TimeUnit.HOURS.toMillis(1)}h ago"
            else -> "${elapsed / TimeUnit.DAYS.toMillis(1)}d ago"
        }
    }

    private fun renameDevice() {
        ClipMeshDialog.prompt(this, "Rename this device", "Choose the name shown to nearby ClipMesh devices.", settings.deviceName) { value ->
            if (value != null) { settings.deviceName = value; refreshHome(); toast("Device name updated") }
        }
    }

    private fun consumePairingIntent(incoming: Intent?) {
        val data = incoming?.dataString ?: return
        if (data.startsWith("clipmesh://pair")) {
            startActivity(Intent(this, SettingsActivity::class.java).putExtra(SettingsActivity.EXTRA_PAIR_URI, data))
            toast("Pairing code received. Review it in Settings.")
        }
    }

    private fun createSpace() {
        confirmSpaceReplacement("Create a new private space?") { createSpaceNow() }
    }

    private fun createSpaceNow() {
        val restart = settings.backgroundSync
        if (restart) BackgroundRuntime.stop()
        val data = Pairing.createSpace(settings.deviceName, settings.deviceId)
        settings.spaceId = data.spaceId
        secrets.saveSpaceKey(data.key)
        settings.clearKnownPeers()
        if (restart) BackgroundRuntime.start(this)
        pairInput.setText("")
        refreshHome()
        toast("New private space created")
    }

    private fun joinSpace() {
        val parsed = runCatching { Pairing.parse(pairInput.text.toString()) }
            .getOrElse { toast(it.message ?: "Invalid pairing code"); return }
        confirmSpaceReplacement("Join this private space?") { joinSpaceNow(parsed) }
    }

    private fun joinSpaceNow(data: Pairing.PairingData) {
        val restart = settings.backgroundSync
        if (restart) BackgroundRuntime.stop()
        settings.spaceId = data.spaceId
        secrets.saveSpaceKey(data.key)
        settings.clearKnownPeers()
        val sourceId = data.deviceId
        if (sourceId != null && sourceId != settings.deviceId) settings.seedPeer(sourceId, data.name)
        if (restart) BackgroundRuntime.start(this)
        refreshHome()
        toast("Joined private space")
    }

    private fun confirmSpaceReplacement(title: String, action: () -> Unit) {
        val alreadyPaired = settings.spaceId != null && secrets.loadSpaceKey() != null
        if (!alreadyPaired) {
            action()
            return
        }
        ClipMeshDialog.confirm(this, title, "This device is already paired. Continuing will replace its current ClipMesh space and known-device list.") { accepted -> if (accepted) action() }
    }

    private fun copyPairingCode() {
        val space = settings.spaceId ?: run { toast("Create or join a space first"); return }
        val key = secrets.loadSpaceKey() ?: run { toast("Space key missing"); return }
        val uri = Pairing.toUri(Pairing.PairingData(space, key, settings.deviceName, settings.deviceId))
        (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
            .setPrimaryClip(ClipData.newPlainText("ClipMesh pairing code", uri))
        toast("Pairing code copied")
    }

    private fun showClipboard(){
        BackgroundRuntime.captureNow();val dialog=Dialog(this);val root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(20),dp(20),dp(18));background=rounded(Color.rgb(30,28,26),dp(26).toFloat(),border)};root.addView(label("Clipboard",23f,true,ink));root.addView(label("Current local content",12f,false,muted).apply{setPadding(0,dp(2),0,dp(16))});root.addView(buildClipboardPreview(),fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT));root.addView(button("Done",false){dialog.dismiss()},fullWidthParams(dp(48)).apply{topMargin=dp(16)});dialog.setContentView(root);dialog.window?.apply{setBackgroundDrawableResource(android.R.color.transparent);setDimAmount(.72f);addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND)};dialog.show();dialog.window?.setLayout((resources.displayMetrics.widthPixels*.90f).toInt(),ViewGroup.LayoutParams.WRAP_CONTENT)
    }
    private fun buildClipboardPreview():View{
        val manager=getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager;val clip=runCatching{manager.primaryClip}.getOrNull();val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(16),dp(15),dp(16),dp(15));background=rounded(Color.rgb(26,24,21),dp(18).toFloat(),border)};if(clip==null||clip.itemCount==0){box.addView(label("EMPTY",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});box.addView(label("Nothing is on the clipboard.",14f,false,muted).apply{setPadding(0,dp(8),0,0)});return box};var imageUri:android.net.Uri?=null;for(i in 0 until clip.itemCount){val uri=clip.getItemAt(i).uri?:continue;val mime=runCatching{contentResolver.getType(uri)}.getOrNull();if(mime?.startsWith("image/")==true||(clip.description.mimeTypeCount>0&&(0 until clip.description.mimeTypeCount).any{clip.description.getMimeType(it).startsWith("image/")})){imageUri=uri;break}};if(imageUri!=null){box.addView(label("IMAGE",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});val bitmap=runCatching{contentResolver.openInputStream(imageUri!!)?.use{BitmapFactory.decodeStream(it)}}.getOrNull();if(bitmap!=null)box.addView(ImageView(this).apply{setImageBitmap(bitmap);adjustViewBounds=true;scaleType=ImageView.ScaleType.CENTER_INSIDE;background=rounded(Color.rgb(13,12,10),dp(14).toFloat(),Color.TRANSPARENT);setPadding(dp(4),dp(4),dp(4),dp(4))},fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT).apply{topMargin=dp(10)})else box.addView(label("Image preview unavailable on this clipboard provider.",14f,false,muted).apply{setPadding(0,dp(8),0,0)});return box};val first=clip.getItemAt(0);val actualText=first.text?.toString()?:runCatching{first.coerceToText(this).toString()}.getOrNull();if(!actualText.isNullOrBlank()){box.addView(label("TEXT",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});box.addView(label(actualText.take(16000),15f,false,ink).apply{setTextIsSelectable(true);setPadding(0,dp(9),0,0)});return box};val names=(0 until clip.itemCount).mapNotNull{i->val uri=clip.getItemAt(i).uri?:return@mapNotNull null;runCatching{contentResolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use{c->if(c.moveToFirst())c.getString(0)else null}}.getOrNull()?:"File ${i+1}"};box.addView(label("FILES",11f,true,Color.rgb(232,145,60)).apply{letterSpacing=.14f});box.addView(label(if(names.isEmpty())"Clipboard content" else names.joinToString("\n"),15f,false,ink).apply{setPadding(0,dp(9),0,0)});return box
    }

    private fun startSyncService() { BackgroundRuntime.start(this) }

    private fun card(root: LinearLayout): LinearLayout {
        val view = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(17), dp(18), dp(17))
            background = rounded(cardBackground, dp(26).toFloat(), border)
            elevation = dp(1).toFloat()
        }
        root.addView(view, fullWidthParams(ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(14) })
        return view
    }

    private fun label(text: String, size: Float, bold: Boolean, color: Int) = TextView(this).apply {
        this.text = text
        textSize = size
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun button(text: String, primaryStyle: Boolean = true, clicked: () -> Unit) = Button(this).apply {
        this.text = text
        isAllCaps = false
        textSize = 14f
        setTypeface(typeface, Typeface.BOLD)
        setTextColor(if (primaryStyle) Color.rgb(13,12,10) else ink)
        background = rounded(if (primaryStyle) Color.rgb(188, 145, 57) else Color.rgb(43,41,37), dp(24).toFloat(), if (primaryStyle) Color.TRANSPARENT else border)
        setPadding(dp(12), 0, dp(12), 0)
        minHeight = dp(46)
        setOnClickListener {
            performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP)
            animate().scaleX(.97f).scaleY(.97f).setDuration(55).withEndAction {
                animate().scaleX(1f).scaleY(1f).setDuration(90).start()
            }.start()
            clicked()
        }
    }

    private fun horizontal(vararg views: View): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        views.forEachIndexed { index, view ->
            addView(view, LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                if (index > 0) leftMargin = dp(8)
            })
        }
    }

    private fun rounded(fill: Int, radius: Float, stroke: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        setColor(fill)
        cornerRadius = radius
        setStroke(dp(1), stroke)
    }

    private fun fullWidthParams(height: Int) = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, height)

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 200)
        }
    }

    private fun toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
