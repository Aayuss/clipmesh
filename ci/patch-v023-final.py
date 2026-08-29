from pathlib import Path
import platform
import re
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = platform.system()


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all_required(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count < 1:
        raise SystemExit(f"{label}: no matches in {path}")
    path.write_text(text.replace(old, new), encoding="utf-8")


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    gradle = project / "android/app/build.gradle.kts"
    manifest_path = project / "android/app/src/main/AndroidManifest.xml"

    replace_once(gradle, "versionCode = 12", "versionCode = 13", "Android versionCode")
    replace_once(gradle, 'versionName = "0.2.2"', 'versionName = "0.2.3"', "Android versionName")

    # A single connected-device foreground service keeps both the encrypted clipboard
    # mesh and the LocalSend-style listener alive after the UI is dismissed. Android
    # requires a foreground service for this kind of continuous background network
    # interaction. connectedDevice avoids Android 15's six-hour dataSync timeout and
    # is valid for network-connected peer interaction when CHANGE_WIFI_MULTICAST_STATE
    # is declared.
    (java / "BackgroundService.kt").write_text(r'''package dev.clipmesh

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
        val message = if (settings.backgroundSync) {
            "Clipboard sync + nearby file receiving active"
        } else {
            "Nearby file receiving active"
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
''', encoding="utf-8")

    # Reuse the existing boot receiver class so package upgrades/boots restore the
    # connected-device service. Android 15's BOOT_COMPLETED ban applies to dataSync,
    # not connectedDevice foreground services.
    boot = java / "fileshare/TransferBootReceiver.kt"
    boot.write_text(r'''package dev.clipmesh.fileshare

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import dev.clipmesh.BackgroundService

class TransferBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED && intent?.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        BackgroundService.start(context)
    }
}
''', encoding="utf-8")

    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    ANDROID = "{http://schemas.android.com/apk/res/android}"
    tree = ET.parse(manifest_path)
    manifest = tree.getroot()
    application = manifest.find("application")
    if application is None:
        raise SystemExit("Android application node missing")

    permissions = {node.get(ANDROID + "name") for node in manifest.findall("uses-permission")}
    def add_permission(name: str) -> None:
        if name in permissions:
            return
        node = ET.Element("uses-permission")
        node.set(ANDROID + "name", name)
        insert_at = 0
        for i, child in enumerate(list(manifest)):
            if child.tag == "uses-permission": insert_at = i + 1
        manifest.insert(insert_at, node)
        permissions.add(name)

    for permission in (
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "android.permission.CHANGE_WIFI_MULTICAST_STATE",
    ):
        add_permission(permission)

    # Remove obsolete service declarations if an older patch ever reintroduces them.
    for child in list(application):
        if child.tag == "service" and child.get(ANDROID + "name") in {".SyncService", ".fileshare.FileTransferService"}:
            application.remove(child)

    components = {(child.tag, child.get(ANDROID + "name")): child for child in application}
    service = components.get(("service", ".BackgroundService"))
    if service is None:
        service = ET.SubElement(application, "service")
        service.set(ANDROID + "name", ".BackgroundService")
    service.set(ANDROID + "exported", "false")
    service.set(ANDROID + "stopWithTask", "false")
    service.set(ANDROID + "foregroundServiceType", "connectedDevice")

    receiver = components.get(("receiver", ".fileshare.TransferBootReceiver"))
    if receiver is None:
        receiver = ET.SubElement(application, "receiver")
        receiver.set(ANDROID + "name", ".fileshare.TransferBootReceiver")
    receiver.set(ANDROID + "enabled", "true")
    receiver.set(ANDROID + "exported", "true")
    # Rebuild the receiver filter deterministically.
    for child in list(receiver):
        receiver.remove(child)
    filt = ET.SubElement(receiver, "intent-filter")
    for action_name in ("android.intent.action.BOOT_COMPLETED", "android.intent.action.MY_PACKAGE_REPLACED"):
        action = ET.SubElement(filt, "action")
        action.set(ANDROID + "name", action_name)

    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)

    def ensure_activity_start(path: Path, needs_import: bool) -> None:
        text = path.read_text(encoding="utf-8")
        if needs_import and "import dev.clipmesh.BackgroundService" not in text:
            package_end = text.find("\n", text.find("package "))
            text = text[:package_end + 1] + "\nimport dev.clipmesh.BackgroundService\n" + text[package_end + 1:]
        if "BackgroundService.start(this)" not in text:
            pattern = r"(override\s+fun\s+onCreate\s*\(savedInstanceState:\s*Bundle\?\)\s*\{\s*\n\s*super\.onCreate\(savedInstanceState\)\s*\n)"
            text, count = re.subn(pattern, r"\1        BackgroundService.start(this)\n", text, count=1)
            if count != 1:
                raise SystemExit(f"Could not inject BackgroundService start into {path}")
        path.write_text(text, encoding="utf-8")

    ensure_activity_start(java / "MainActivity.kt", False)
    ensure_activity_start(java / "fileshare/FileShareActivity.kt", True)

    accessibility = java / "exclusion/ExclusionAccessibilityService.kt"
    if accessibility.is_file():
        text = accessibility.read_text(encoding="utf-8")
        if "import dev.clipmesh.BackgroundService" not in text:
            package_end = text.find("\n", text.find("package "))
            text = text[:package_end + 1] + "\nimport dev.clipmesh.BackgroundService\n" + text[package_end + 1:]
        text = text.replace("BackgroundRuntime.start(this)", "BackgroundService.start(this)")
        if "BackgroundService.start(this)" not in text:
            marker = "super.onServiceConnected()"
            if marker not in text:
                raise SystemExit("Accessibility onServiceConnected anchor missing")
            text = text.replace(marker, marker + "\n        BackgroundService.start(this)", 1)
        accessibility.write_text(text, encoding="utf-8")

    manifest_text = manifest_path.read_text(encoding="utf-8")
    for required in (
        "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
        ".BackgroundService",
        'android:foregroundServiceType="connectedDevice"',
        ".fileshare.TransferBootReceiver",
        "android.intent.action.BOOT_COMPLETED",
    ):
        if required not in manifest_text:
            raise SystemExit(f"Android v0.2.3 background guard missing: {required}")
    service_text = (java / "BackgroundService.kt").read_text(encoding="utf-8")
    for required in ("START_STICKY", "FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE", "BackgroundRuntime.start(this)"):
        if required not in service_text:
            raise SystemExit(f"Android v0.2.3 service guard missing: {required}")

elif system == "Darwin":
    build = project / "scripts/build-macos.sh"
    replace_all_required(build, "0.2.2", "0.2.3", "macOS v0.2.3 package version")

elif system == "Windows":
    build = project / "scripts/build-windows.ps1"
    replace_all_required(build, "0.2.2", "0.2.3", "Windows v0.2.3 package version")

else:
    raise SystemExit(f"Unsupported platform: {system}")

print(f"Applied ClipMesh v0.2.3 final background/runtime patch on {system}")
