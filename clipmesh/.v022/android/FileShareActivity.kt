package dev.clipmesh.fileshare

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.DragEvent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import dev.clipmesh.R
import dev.clipmesh.BackgroundRuntime
import dev.clipmesh.MainActivity
import dev.clipmesh.SettingsActivity
import java.util.concurrent.Executors

class FileShareActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private val selected = mutableListOf<Uri>()
    private lateinit var deviceList: LinearLayout
    private lateinit var fileSummary: TextView
    private lateinit var status: TextView
    private var sending = false

    private val bg = Color.rgb(18, 17, 16)
    private val glass = Color.argb(22, 255, 255, 255)
    private val glass2 = Color.argb(30, 255, 255, 255)
    private val ink = Color.rgb(246, 242, 233)
    private val muted = Color.rgb(174, 169, 160)
    private val line = Color.argb(34, 255, 255, 255)
    private val accent = Color.rgb(232, 145, 60)
    private val darkInk = Color.rgb(13, 12, 10)
    private val good = Color.rgb(244, 169, 78)

    private val refresh = object : Runnable {
        override fun run() {
            if (!isFinishing && !sending) renderDevices()
            if (!isFinishing) main.postDelayed(this, 1_000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BackgroundRuntime.start(this)
        LocalTransferEngine.discoverNow()
        selected += extractSharedUris(intent)
        buildUi()
        refreshFiles()
        main.post(refresh)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        if (intent != null) {
            selected.clear()
            selected += extractSharedUris(intent)
            refreshFiles()
        }
    }

    override fun onDestroy() {
        main.removeCallbacks(refresh)
        io.shutdownNow()
        super.onDestroy()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != PICK_FILES || resultCode != RESULT_OK || data == null) return
        selected.clear()
        data.clipData?.let { clip ->
            for (i in 0 until clip.itemCount) selected += clip.getItemAt(i).uri
        }
        data.data?.let { selected += it }
        selected.distinct().forEach { uri ->
            runCatching { contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        }
        refreshFiles()
    }

    private fun buildUi() {
        window.statusBarColor = bg
        window.navigationBarColor = bg
        if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = 0

        val shell = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(bg) }
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(bg)
            clipToPadding = false
            setOnDragListener { _, event ->
                when (event.action) {
                    DragEvent.ACTION_DRAG_STARTED -> true
                    DragEvent.ACTION_DROP -> {
                        val clip = event.clipData
                        var added = false
                        if (clip != null) for (i in 0 until clip.itemCount) {
                            clip.getItemAt(i).uri?.let { uri -> selected += uri; added = true }
                        }
                        if (added) { refreshFiles(); LocalTransferEngine.discoverNow() }
                        added
                    }
                    else -> true
                }
            }
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(38))
        }
        scroll.addView(root)

        val eyebrow = text("CLIPMESH DROP", 12f, true, muted).apply { letterSpacing = 0.14f }
        root.addView(eyebrow)
        root.addView(text("Send without\nbreaking your flow.", 34f, false, ink).apply {
            setLineSpacing(0f, 0.94f)
            setPadding(0, dp(9), 0, dp(7))
        })
        root.addView(text("Nearby, private, direct. No cloud in the middle.", 14f, false, muted).apply {
            setPadding(0, 0, 0, dp(18))
        })

        val filesCard = card(glass)
        val fileHeader = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val fileTitles = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        fileTitles.addView(text("Ready to send", 13f, true, muted))
        fileSummary = text("No files selected", 19f, true, ink).apply { setPadding(0, dp(3), 0, 0) }
        fileTitles.addView(fileSummary)
        fileHeader.addView(fileTitles, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        fileHeader.addView(pillButton("Choose files", false) { chooseFiles() }, LinearLayout.LayoutParams(dp(122), dp(43)))
        filesCard.addView(fileHeader)
        root.addView(filesCard, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(14) })

        val nearbyCard = card(glass2)
        val nearbyHeader = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        nearbyHeader.addView(text("Nearby devices", 20f, true, ink), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        nearbyHeader.addView(pillButton("Rescan", true) { LocalTransferEngine.discoverNow(); renderDevices() }, LinearLayout.LayoutParams(dp(86), dp(38)))
        nearbyCard.addView(nearbyHeader)
        nearbyCard.addView(text("Tap a device to send. Star a device to trust it for future incoming files.", 13f, false, muted).apply {
            setPadding(0, dp(5), 0, dp(12))
        })
        deviceList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        nearbyCard.addView(deviceList)
        root.addView(nearbyCard, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(14) })

        status = text("Looking on this Wi‑Fi…", 13f, false, muted).apply {
            gravity = Gravity.CENTER
            setPadding(dp(8), dp(7), dp(8), dp(7))
        }
        root.addView(status, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        shell.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        shell.addView(bottomNav(), LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(72)))
        setContentView(shell)
    }

    private fun refreshFiles() {
        fileSummary.text = when (selected.size) {
            0 -> "No files selected"
            1 -> displayName(selected.first())
            else -> "${selected.size} files selected"
        }
        renderDevices()
    }

    private fun renderDevices() {
        if (!::deviceList.isInitialized) return
        deviceList.removeAllViews()
        val devices = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())
        if (devices.isEmpty()) {
            deviceList.addView(text("No devices yet. Keep ClipMesh open or running in the background on another device connected to the same LAN.", 14f, false, muted).apply {
                setPadding(0, dp(8), 0, dp(8))
            })
            status.text = "Looking on this Wi‑Fi…"
            return
        }
        status.text = "${devices.size} device${if (devices.size == 1) "" else "s"} visible"
        devices.forEachIndexed { index, device ->
            if (index > 0) deviceList.addView(View(this).apply { setBackgroundColor(line) }, fullWidth(dp(1)).apply {
                topMargin = dp(8); bottomMargin = dp(8)
            })
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(2), dp(8), dp(2), dp(8))
                isClickable = true
                isFocusable = true
                setOnClickListener { sendTo(device) }
            }
            val bubble = TextView(this).apply {
                text = if (device.deviceType == "mobile") "▯" else "▰"
                textSize = 22f
                gravity = Gravity.CENTER
                setTextColor(darkInk)
                background = round(accent, dp(20).toFloat(), Color.TRANSPARENT)
            }
            row.addView(bubble, LinearLayout.LayoutParams(dp(48), dp(48)).apply { rightMargin = dp(12) })
            val labels = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
            labels.addView(text(device.alias, 16f, true, ink))
            labels.addView(text(device.deviceModel.ifBlank { if (device.deviceType == "mobile") "Mobile" else "Desktop" }, 12f, false, muted))
            row.addView(labels, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            val favorite = LocalTransferEngine.isFavorite(this, device.fingerprint)
            row.addView(TextView(this).apply {
                text = if (favorite) "★" else "☆"
                textSize = 24f
                gravity = Gravity.CENTER
                setTextColor(if (favorite) accent else muted)
                setPadding(dp(8), 0, dp(4), 0)
                setOnClickListener {
                    LocalTransferEngine.setFavorite(this@FileShareActivity, device.fingerprint, !favorite)
                    renderDevices()
                }
            }, LinearLayout.LayoutParams(dp(48), dp(48)))
            deviceList.addView(row, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        }
    }

    private fun sendTo(device: LocalTransferEngine.TransferDevice) {
        if (selected.isEmpty()) {
            chooseFiles()
            return
        }
        if (sending) return
        sending = true
        status.text = "Connecting to ${device.alias}…"
        io.execute {
            runCatching {
                LocalTransferEngine.sendUris(this, selected.toList(), device) { completed, total, message ->
                    main.post { status.text = message }
                }
            }.onSuccess {
                main.post {
                    sending = false
                    status.text = "Sent to ${device.alias}"
                    AlertDialog.Builder(this)
                        .setTitle("Sent")
                        .setMessage("${if (selected.size == 1) displayName(selected.first()) else "${selected.size} files"} was sent to ${device.alias}.")
                        .setPositiveButton("Done") { _, _ -> finish() }
                        .setNegativeButton("Send again", null)
                        .show()
                }
            }.onFailure { error ->
                main.post {
                    sending = false
                    status.text = error.message ?: "Transfer failed"
                    AlertDialog.Builder(this)
                        .setTitle("Couldn’t send")
                        .setMessage(error.message ?: "The transfer failed.")
                        .setPositiveButton("OK", null)
                        .show()
                }
            }
        }
    }

    private fun chooseFiles() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "*/*"
            addCategory(Intent.CATEGORY_OPENABLE)
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }, PICK_FILES)
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
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0) return cursor.getString(index) ?: "File"
            }
        }
        return uri.lastPathSegment ?: "File"
    }

    private fun bottomNav(): View {
        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER; setPadding(dp(10), dp(8), dp(10), dp(8)); background = round(Color.rgb(24,22,20), dp(24).toFloat(), line) }
        fun item(title: String, selectedTab: Boolean, click: () -> Unit): TextView = TextView(this).apply {
            text = title; gravity = Gravity.CENTER; textSize = 12f; setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (selectedTab) darkInk else muted)
            background = round(if (selectedTab) Color.rgb(241,235,221) else Color.TRANSPARENT, dp(18).toFloat(), Color.TRANSPARENT)
            setOnClickListener { click() }
        }
        bar.addView(item("Clipboard", false) { startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); finish() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { rightMargin=dp(6) })
        bar.addView(item("File transfer", true) {}, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { leftMargin=dp(3); rightMargin=dp(3) })
        bar.addView(item("Settings", false) { startActivity(Intent(this, SettingsActivity::class.java)); finish() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { leftMargin=dp(6) })
        return bar
    }

    private fun card(color: Int) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18), dp(17), dp(18), dp(17))
        background = round(color, dp(24).toFloat(), line)
        elevation = dp(7).toFloat()
    }

    private fun text(value: String, size: Float, bold: Boolean, color: Int) = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun pillButton(value: String, primary: Boolean, action: () -> Unit) = Button(this).apply {
        text = value
        isAllCaps = false
        textSize = 13f
        setTypeface(typeface, Typeface.BOLD)
        setTextColor(if (primary) ink else darkInk)
        background = round(if (primary) glass2 else accent, dp(22).toFloat(), Color.TRANSPARENT)
        setOnClickListener { action() }
        stateListAnimator = null
    }

    private fun round(fill: Int, radius: Float, stroke: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = radius
        setColor(fill)
        if (stroke != Color.TRANSPARENT) setStroke(dp(1), stroke)
    }

    private fun fullWidth(height: Int) = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, height)
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density + 0.5f).toInt()

    companion object { private const val PICK_FILES = 2201 }
}
