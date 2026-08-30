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

    private fun handle(intent: Intent) {
        handler.removeCallbacksAndMessages(null)
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
        // Waiting must not itself create a clipboard synchronization event.
        // Every expected text value contains a unique physical-test nonce.
        write("READY_TEXT")
        poll(15_000L, predicate = {
            val clip = clipboard().primaryClip ?: return@poll false
            clip.itemCount > 0 && clip.getItemAt(0).text?.toString() == expected
        }, onPass = { write("PASS_TEXT") })
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
        // The harness clears stale image state before arming this receiver.
        // Do not create an outgoing clipboard event here.
        write("READY_IMAGE")
        poll(20_000L, predicate = {
            val clip = clipboard().primaryClip ?: return@poll false
            if (clip.itemCount == 0) return@poll false
            val uri = clip.getItemAt(0).uri ?: return@poll false
            val bitmap = runCatching {
                contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) }
            }.getOrNull() ?: return@poll false
            bitmap.width == 3 && bitmap.height == 2
        }, onPass = { write("PASS_IMAGE 3x2") })
    }

    private fun poll(timeoutMs: Long, predicate: () -> Boolean, onPass: () -> Unit) {
        val deadline = System.currentTimeMillis() + timeoutMs
        fun tick() {
            if (runCatching(predicate).getOrDefault(false)) {
                onPass()
                return
            }
            if (System.currentTimeMillis() >= deadline) {
                write("FAIL timeout")
                return
            }
            handler.postDelayed(::tick, 120L)
        }
        handler.postDelayed(::tick, 120L)
    }

    private fun decode(value: String?): String = String(
        Base64.decode(value.orEmpty(), Base64.DEFAULT), Charsets.UTF_8
    )

    private fun write(value: String) {
        status.text = value
        File(filesDir, "result.txt").writeText(value, Charsets.UTF_8)
    }
}
