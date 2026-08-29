package dev.clipmesh.fileshare

import android.app.Activity
import android.app.AlertDialog
import android.text.InputType
import android.widget.EditText
import java.lang.ref.WeakReference
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object NearbyPairingUi {
    @Volatile private var visible=WeakReference<Activity?>(null)
    fun attach(activity:Activity){visible=WeakReference<Activity?>(activity)}
    fun detach(activity:Activity){if(visible.get()===activity)visible.clear()}
    fun approve(sender:String):Boolean{val activity=visible.get()?.takeUnless{it.isFinishing||it.isDestroyed}?:return false;val latch=CountDownLatch(1);var accepted=false;activity.runOnUiThread{AlertDialog.Builder(activity).setTitle("Clipboard pairing request").setMessage("$sender wants to pair with this device for encrypted clipboard sync.").setNegativeButton("Reject"){_,_->latch.countDown()}.setPositiveButton("Accept"){_,_->accepted=true;latch.countDown()}.setOnCancelListener{latch.countDown()}.show()};latch.await(60,TimeUnit.SECONDS);return accepted}
    fun promptCode(sender:String,submit:(String?)->Unit){val activity=visible.get()?.takeUnless{it.isFinishing||it.isDestroyed}?:return submit(null);activity.runOnUiThread{val input=EditText(activity).apply{hint="6-digit code";inputType=InputType.TYPE_CLASS_NUMBER;maxLines=1};AlertDialog.Builder(activity).setTitle("Verify $sender").setMessage("Type the six-digit code shown on $sender. The code authenticates the encrypted connection.").setView(input).setNegativeButton("Cancel"){_,_->submit(null)}.setPositiveButton("Pair"){_,_->submit(input.text.toString())}.setOnCancelListener{submit(null)}.show()}}
}
