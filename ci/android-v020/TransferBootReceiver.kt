package dev.clipmesh.fileshare

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class TransferBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED && intent?.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        // Android 15+ may restrict dataSync foreground services launched directly
        // from BOOT_COMPLETED. A later normal app/share launch will start it again.
        runCatching { FileTransferService.start(context) }
    }
}
