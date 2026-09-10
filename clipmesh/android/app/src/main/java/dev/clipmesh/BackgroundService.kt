package dev.clipmesh

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import dev.clipmesh.fileshare.TransferNotifications

class BackgroundService : Service() {
    override fun onCreate() {
        super.onCreate()
        createChannel()
        promoteToForeground()
        TransferNotifications.ensureChannels(this)
        BackgroundRuntime.start(this)
        val settings = SettingsStore(this)
        if (!settings.backgroundSync && !settings.receiveFilesInBackground) stopSelf()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        BackgroundRuntime.start(this)
        if (intent?.action == ACTION_CAPTURE_CURRENT) BackgroundRuntime.captureNow()
        return START_STICKY
    }

    override fun onDestroy() {
        BackgroundRuntime.stop()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel(
            CHANNEL_ID,
            "Background sync and nearby receiving",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Keeps ClipMesh connected to your paired and nearby devices"
            setSound(null, null)
            enableVibration(false)
            enableLights(false)
            setShowBadge(false)
        })
    }

    private fun promoteToForeground() {
        val open = PendingIntent.getActivity(
            this,
            9230,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0
        )
        val settings = SettingsStore(this)
        val message = when {
            settings.backgroundSync && settings.receiveFilesInBackground -> "Clipboard sync + nearby file receiving active"
            settings.backgroundSync -> "Clipboard sync active"
            else -> "Nearby file receiving active"
        }
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL_ID) else Notification.Builder(this)
        val notification = builder
            .setSmallIcon(R.drawable.ic_clipmesh_notification)
            .setContentTitle("ClipMesh")
            .setContentText(message)
            .setContentIntent(open)
            .setOngoing(true)
            .setShowWhen(false)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setPriority(Notification.PRIORITY_LOW)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        private const val CHANNEL_ID = "clipmesh_background_v023"
        private const val NOTIFICATION_ID = 9230
        const val ACTION_CAPTURE_CURRENT = "dev.clipmesh.action.CAPTURE_CURRENT"

        fun start(context: Context, captureCurrent: Boolean = false) {
            val app = context.applicationContext
            val settings = SettingsStore(app)
            if (!settings.backgroundSync && !settings.receiveFilesInBackground) return
            val intent = Intent(app, BackgroundService::class.java).apply {
                if (captureCurrent) action = ACTION_CAPTURE_CURRENT
            }
            runCatching {
                if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(intent) else app.startService(intent)
            }.onFailure {
                // AccessibilityService is a system-bound fallback wake source. If the
                // OS denies a background FGS start, keep the event-driven runtime alive
                // in the already-running process rather than dropping clipboard/file events.
                BackgroundRuntime.start(app)
                if (captureCurrent) BackgroundRuntime.captureNow()
            }
        }
    }
}
