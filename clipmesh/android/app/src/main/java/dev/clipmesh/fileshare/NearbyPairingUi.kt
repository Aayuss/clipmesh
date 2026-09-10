package dev.clipmesh.fileshare

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
