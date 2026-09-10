package dev.clipmesh

import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.Context
import android.content.Intent

class CiBackgroundCaptureReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (!BuildConfig.DEBUG || intent?.action != ACTION) return
        val text = intent.getStringExtra(EXTRA_TEXT)?.takeIf { it.isNotBlank() } ?: return
        val app = context.applicationContext
        app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
            .remove("last_outgoing_at")
            .remove("last_outgoing_representation_count")
            .putLong("receiver_seen_at", System.currentTimeMillis())
            .commit()

        val settings = SettingsStore(app)
        if (settings.spaceId == null || SecretStore(app).loadSpaceKey() == null) {
            settings.spaceId = java.util.UUID.fromString(CI_SPACE_ID)
            SecretStore(app).saveSpaceKey(ByteArray(32) { index -> (index + 1).toByte() })
        }
        settings.backgroundSync = true

        // Rebuild the singleton after the debug pairing state is present. This
        // mirrors the normal successful-pairing flow and guarantees ClipboardBridge
        // and NetworkEngine both exist before the hidden-UI capture is injected.
        BackgroundRuntime.restart(app)
        BackgroundRuntime.captureInjectedForTest(ClipData.newPlainText("ClipMesh CI", text))
    }

    companion object {
        const val ACTION = "dev.clipmesh.action.CI_BACKGROUND_CAPTURE"
        const val EXTRA_TEXT = "text"
        private const val CI_SPACE_ID = "00000000-0000-4000-8000-000000000028"
    }
}
