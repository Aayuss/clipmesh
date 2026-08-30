package dev.clipmesh.testdriver

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.view.Gravity
import android.widget.TextView
import java.io.File

class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private var clipListener: ClipboardManager.OnPrimaryClipChangedListener? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        status = TextView(this).apply {
            textSize = 20f
            gravity = Gravity.CENTER
            setPadding(32, 32, 32, 32)
        }
        setContentView(status)
        handle(intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent?.let(::handle)
    }

    override fun onDestroy() {
        clearWaiter()
        super.onDestroy()
    }

    private fun handle(intent: Intent) {
        clearWaiter()
        when (intent.getStringExtra("mode")) {
            "set_text" -> setText(decode(intent.getStringExtra("value_b64")))
            "wait_text" -> waitText(decode(intent.getStringExtra("value_b64")))
            "set_image" -> setImage()
            "wait_image" -> waitImage()
            else -> write("FAIL unknown mode")
        }
    }

    private fun clipboard(): ClipboardManager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager

    private fun setText(value: String) {
        clipboard().setPrimaryClip(ClipData.newPlainText("ClipMesh E2E text", value))
        write("SET_TEXT")
    }

    private fun waitText(expected: String) {
        // The expected text contains a per-run nonce. Polling is therefore safe
        // against stale state and also catches shell/Shizuku writes on OEMs that
        // occasionally omit an app OnPrimaryClipChanged callback.
        armClipboardWait(20_000L, pollCurrent = true, predicate = {
            val clip = clipboard().primaryClip ?: return@armClipboardWait false
            clip.itemCount > 0 && clip.getItemAt(0).text?.toString() == expected
        }, pass = "PASS_TEXT")
        write("READY_TEXT")
    }

    private fun setImage() {
        val bitmap = Bitmap.createBitmap(3, 2, Bitmap.Config.ARGB_8888)
        bitmap.setPixels(
            intArrayOf(Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW, Color.MAGENTA, Color.CYAN),
            0, 3, 0, 0, 3, 2
        )
        val file = File(cacheDir, "clipmesh-e2e-image.png")
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        val uri = Uri.parse("content://dev.clipmesh.testdriver.image/clipmesh-e2e-image.png")
        clipboard().setPrimaryClip(ClipData.newUri(contentResolver, "ClipMesh E2E image", uri))
        write("SET_IMAGE")
    }

    private fun waitImage() {
        // The harness first replaces any prior image with unique text and waits
        // for that reset to propagate. After that, only a new image event can pass.
        armClipboardWait(25_000L, pollCurrent = false, predicate = {
            val clip = clipboard().primaryClip ?: return@armClipboardWait false
            if (clip.itemCount == 0) return@armClipboardWait false
            val uri = clip.getItemAt(0).uri ?: return@armClipboardWait false
            val bitmap = runCatching {
                contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) }
            }.getOrNull() ?: return@armClipboardWait false
            bitmap.width == 3 && bitmap.height == 2
        }, pass = "PASS_IMAGE 3x2")
        write("READY_IMAGE")
    }

    private fun armClipboardWait(
        timeoutMs: Long,
        pollCurrent: Boolean,
        predicate: () -> Boolean,
        pass: String
    ) {
        val manager = clipboard()
        lateinit var listener: ClipboardManager.OnPrimaryClipChangedListener

        fun check(): Boolean {
            if (clipListener !== listener) return false
            if (!runCatching(predicate).getOrDefault(false)) return false
            clearWaiter()
            write(pass)
            return true
        }

        listener = ClipboardManager.OnPrimaryClipChangedListener { check() }
        clipListener = listener
        manager.addPrimaryClipChangedListener(listener)

        if (pollCurrent) {
            val poller = object : Runnable {
                override fun run() {
                    if (clipListener !== listener) return
                    if (!check()) handler.postDelayed(this, 100L)
                }
            }
            handler.postDelayed(poller, 100L)
        }

        handler.postDelayed({
            if (clipListener === listener) {
                clearWaiter()
                write("FAIL timeout")
            }
        }, timeoutMs)
    }

    private fun clearWaiter() {
        handler.removeCallbacksAndMessages(null)
        clipListener?.let { runCatching { clipboard().removePrimaryClipChangedListener(it) } }
        clipListener = null
    }

    private fun decode(value: String?): String = String(
        Base64.decode(value.orEmpty(), Base64.DEFAULT), Charsets.UTF_8
    )

    private fun write(value: String) {
        status.text = value
        File(filesDir, "result.txt").writeText(value, Charsets.UTF_8)
    }
}
