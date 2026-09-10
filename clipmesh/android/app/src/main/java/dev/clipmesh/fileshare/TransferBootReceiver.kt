package dev.clipmesh.fileshare

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import dev.clipmesh.BackgroundService

class TransferBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED && intent?.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        val settings = dev.clipmesh.SettingsStore(context)
        if (settings.backgroundSync || settings.receiveFilesInBackground) BackgroundService.start(context)
    }
}
