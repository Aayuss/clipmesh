package dev.clipmesh.fileshare

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class TransferActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val requestId = intent.getStringExtra(EXTRA_REQUEST_ID) ?: return
        when (intent.action) {
            ACTION_ACCEPT -> LocalTransferEngine.resolveIncoming(requestId, true)
            ACTION_REJECT -> LocalTransferEngine.resolveIncoming(requestId, false)
        }
        TransferNotifications.cancelIncoming(context, requestId)
    }

    companion object {
        const val ACTION_ACCEPT = "dev.clipmesh.fileshare.ACCEPT"
        const val ACTION_REJECT = "dev.clipmesh.fileshare.REJECT"
        const val EXTRA_REQUEST_ID = "request_id"
    }
}
