#!/usr/bin/env python3
"""ClipMesh v063: work-profile-safe Android startup and foreground-service fallback."""

from pathlib import Path
import os
import platform

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    store = java / "SettingsStore.kt"
    main = java / "MainActivity.kt"
    share = java / "fileshare/FileShareActivity.kt"
    service = java / "BackgroundService.kt"

    # Work profiles are managed users. Samsung/Shelter may apply policy that
    # rejects connectedDevice foreground services even though foreground LAN
    # transfer remains usable. Fresh work-profile installs therefore default
    # background receive OFF, while personal-profile behavior remains unchanged.
    replace(
        store,
        'class SettingsStore(context: Context) {\n    private val prefs = context.getSharedPreferences("clipmesh_settings", Context.MODE_PRIVATE)',
        '''class SettingsStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("clipmesh_settings", Context.MODE_PRIVATE)''',
        "Android SettingsStore retains application context",
    )
    replace(
        store,
        '''    var receiveFilesInBackground: Boolean
        get() = prefs.getBoolean("receive_files_in_background", true)
        set(value) = prefs.edit().putBoolean("receive_files_in_background", value).apply()''',
        '''    var receiveFilesInBackground: Boolean
        get() = prefs.getBoolean("receive_files_in_background", !isManagedProfile(appContext))
        set(value) = prefs.edit().putBoolean("receive_files_in_background", value).apply()''',
        "managed-profile background receive default",
    )
    replace(
        store,
        '''    companion object {
        fun sanitizeDeviceName(value: String): String {''',
        '''    companion object {
        fun isManagedProfile(context: Context): Boolean =
            android.os.Build.VERSION.SDK_INT >= 24 && runCatching {
                context.getSystemService(android.os.UserManager::class.java)?.isManagedProfile == true
            }.getOrDefault(false)

        fun sanitizeDeviceName(value: String): String {''',
        "managed-profile detector",
    )

    # Do not launch the connected-device FGS before settings are known. A fresh
    # managed profile can use ClipMesh fully while visible without any FGS.
    replace(
        main,
        '''        super.onCreate(savedInstanceState)
        BackgroundService.start(this)''',
        '''        super.onCreate(savedInstanceState)''',
        "remove unconditional MainActivity FGS startup",
    )
    replace(
        main,
        '''        settings = SettingsStore(this)
        secrets = SecretStore(this)
        ensureLocalClipboardSpace()''',
        '''        settings = SettingsStore(this)
        secrets = SecretStore(this)
        ensureLocalClipboardSpace()
        if (settings.backgroundSync || settings.receiveFilesInBackground) BackgroundService.start(this)''',
        "conditional MainActivity background startup",
    )

    # File Transfer is foreground-capable through LocalTransferEngine.onResume;
    # only start the persistent service when the user actually enabled it.
    replace(
        share,
        '''        super.onCreate(savedInstanceState)
        BackgroundService.start(this)''',
        '''        super.onCreate(savedInstanceState)
        val backgroundSettings = dev.clipmesh.SettingsStore(this)
        if (backgroundSettings.backgroundSync || backgroundSettings.receiveFilesInBackground) {
            BackgroundService.start(this)
        }''',
        "conditional FileShareActivity background startup",
    )

    # FGS promotion can be rejected by work-profile/Knox policy. Never let that
    # exception terminate the ClipMesh process. Foreground activity discovery and
    # transfers continue via LocalTransferEngine even when persistent background
    # receiving is unavailable to the managed profile.
    replace(
        service,
        '''        createChannel()
        promoteToForeground()
        TransferNotifications.ensureChannels(this)
        BackgroundRuntime.start(this)''',
        '''        createChannel()
        val promoted = runCatching {
            promoteToForeground()
            true
        }.getOrElse { error ->
            android.util.Log.w("ClipMesh", "Background service unavailable in this profile", error)
            false
        }
        if (!promoted) {
            stopSelf()
            return
        }
        TransferNotifications.ensureChannels(this)
        BackgroundRuntime.start(this)''',
        "non-crashing foreground-service promotion",
    )
    replace(
        service,
        '''            runCatching {
                if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(intent) else app.startService(intent)
            }.onFailure {
                // AccessibilityService is a system-bound fallback wake source. If the
                // OS denies a background FGS start, keep the event-driven runtime alive
                // in the already-running process rather than dropping clipboard/file events.
                BackgroundRuntime.start(app)
                if (captureCurrent) BackgroundRuntime.captureNow()
            }''',
        '''            runCatching {
                if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(intent) else app.startService(intent)
            }.onFailure { error ->
                android.util.Log.w("ClipMesh", "Foreground service start rejected", error)
                // Do not emulate a persistent background service without an FGS.
                // If an Activity/AccessibilityService is alive, their lifecycle
                // already owns the event-driven runtime safely.
                if (captureCurrent) runCatching { BackgroundRuntime.captureNow() }
            }''',
        "safe denied-FGS fallback",
    )

print(f"Applied ClipMesh v063 work-profile-safe startup on {SYSTEM}")
