package dev.clipmesh

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder

/** Legacy service entry point retained for old intents. The process-wide
 * BackgroundRuntime is the sole clipboard/Shizuku owner. */
class SyncService : Service() {
    companion object {
        const val ACTION_STOP = "dev.clipmesh.STOP"
        const val ACTION_CAPTURE_CURRENT = "dev.clipmesh.CAPTURE_CURRENT"
        private const val CHANNEL_ID = "clipmesh_sync_quiet_v019"
        private const val NOTIFICATION_ID = 41474
        @Volatile var status: String = "Stopped"
    }

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(NOTIFICATION_ID, notification("Starting encrypted LAN sync…"))
        BackgroundRuntime.start(this)
        status = BackgroundRuntime.status
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            SettingsStore(this).backgroundSync = false
            BackgroundRuntime.stop()
            stopSelf()
            return START_NOT_STICKY
        }
        BackgroundRuntime.start(this)
        if (intent?.action == ACTION_CAPTURE_CURRENT) BackgroundRuntime.captureNow()
        status = BackgroundRuntime.status
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        status = "Stopped"
        super.onDestroy()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "ClipMesh background sync", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Keeps the private LAN clipboard bridge available in the background"
                    setShowBadge(false)
                },
            )
        }
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, SyncService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_clipmesh_notification)
            .setContentTitle("ClipMesh")
            .setContentText(text)
            .setOngoing(true)
            .setShowWhen(false)
            .setPriority(Notification.PRIORITY_MIN)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(
                android.graphics.drawable.Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                "Stop",
                stop,
            ).build())
            .build()
    }
}
