package dev.clipmesh.fileshare

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import dev.clipmesh.MainActivity
import dev.clipmesh.R

class FileTransferService : Service() {
    override fun onCreate() {
        super.onCreate()
        createQuietChannel()
        startForeground(NOTIFICATION_ID, backgroundNotification())
        TransferNotifications.ensureChannels(this)
        LocalTransferEngine.start(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        LocalTransferEngine.start(this)
        return START_STICKY
    }

    override fun onDestroy() {
        LocalTransferEngine.stop()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createQuietChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel(
            CHANNEL_ID,
            "Nearby file transfer",
            NotificationManager.IMPORTANCE_MIN
        ).apply {
            description = "Keeps ClipMesh ready to receive nearby files while the app is closed"
            setSound(null, null)
            enableVibration(false)
            enableLights(false)
            setShowBadge(false)
        })
    }

    private fun backgroundNotification(): Notification {
        val open = PendingIntent.getActivity(
            this,
            7331,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0
        )
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL_ID) else Notification.Builder(this)
        return builder
            .setSmallIcon(R.drawable.ic_clipmesh_notification)
            .setContentTitle("ClipMesh")
            .setContentText("Ready for nearby file transfers")
            .setContentIntent(open)
            .setOngoing(true)
            .setShowWhen(false)
            .setPriority(Notification.PRIORITY_MIN)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "clipmesh_file_background_v020"
        private const val NOTIFICATION_ID = 7331

        fun start(context: Context) {
            val intent = Intent(context, FileTransferService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
        }
    }
}
