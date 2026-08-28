package dev.clipmesh.fileshare

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Build
import dev.clipmesh.MainActivity
import dev.clipmesh.R

object TransferNotifications {
    private const val REQUEST_CHANNEL = "clipmesh_file_requests_v020"
    private const val COMPLETE_CHANNEL = "clipmesh_file_complete_v020"

    fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel(
            REQUEST_CHANNEL,
            "Incoming file requests",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Accept or reject file transfers from nearby devices"
            enableVibration(true)
            enableLights(true)
            lightColor = Color.WHITE
        })
        manager.createNotificationChannel(NotificationChannel(
            COMPLETE_CHANNEL,
            "Completed file transfers",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Shows when incoming files have been saved"
            enableVibration(false)
            setSound(null, null)
        })
    }

    fun showIncoming(context: Context, request: LocalTransferEngine.IncomingDecision) {
        ensureChannels(context)
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val open = PendingIntent.getActivity(
            context,
            request.requestId.hashCode(),
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        val accept = PendingIntent.getBroadcast(
            context,
            request.requestId.hashCode() xor 0x41,
            Intent(context, TransferActionReceiver::class.java)
                .setAction(TransferActionReceiver.ACTION_ACCEPT)
                .putExtra(TransferActionReceiver.EXTRA_REQUEST_ID, request.requestId),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        val reject = PendingIntent.getBroadcast(
            context,
            request.requestId.hashCode() xor 0x52,
            Intent(context, TransferActionReceiver::class.java)
                .setAction(TransferActionReceiver.ACTION_REJECT)
                .putExtra(TransferActionReceiver.EXTRA_REQUEST_ID, request.requestId),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        val summary = if (request.files.size == 1) request.files.first().fileName else "${request.files.size} files"
        val notification = android.app.Notification.Builder(context, REQUEST_CHANNEL)
            .setSmallIcon(R.drawable.ic_clipmesh_notification)
            .setContentTitle("${request.senderAlias} wants to send you $summary")
            .setContentText("Accept to save it in Downloads/ClipMesh")
            .setStyle(android.app.Notification.BigTextStyle().bigText(
                "${request.senderAlias} is trying to send $summary to this device. Accept to save it in Downloads/ClipMesh."
            ))
            .setContentIntent(open)
            .setAutoCancel(false)
            .setOngoing(true)
            .addAction(android.app.Notification.Action.Builder(null, "Reject", reject).build())
            .addAction(android.app.Notification.Action.Builder(null, "Accept", accept).build())
            .build()
        manager.notify(incomingId(request.requestId), notification)
    }

    fun cancelIncoming(context: Context, requestId: String) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancel(incomingId(requestId))
    }

    fun showCompleted(context: Context, sender: String, count: Int) {
        ensureChannels(context)
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val open = PendingIntent.getActivity(
            context,
            9902,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        val title = if (count == 1) "File received" else "$count files received"
        manager.notify(
            7332,
            android.app.Notification.Builder(context, COMPLETE_CHANNEL)
                .setSmallIcon(R.drawable.ic_clipmesh_notification)
                .setContentTitle(title)
                .setContentText("Saved from $sender to Downloads/ClipMesh")
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
        )
    }

    private fun incomingId(id: String): Int = 0x52000000 xor id.hashCode()
    private fun immutableFlag(): Int = if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0
}
