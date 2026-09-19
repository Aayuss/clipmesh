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


def remove_early_service_start(path: Path, before: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    pivot = text.find(before)
    if pivot < 0:
        raise SystemExit(f"{label}: missing pivot {before!r} in {path}")
    prefix, suffix = text[:pivot], text[pivot:]
    needle = "        BackgroundService.start(this)\n"
    # Older patch layers place this at slightly different positions inside
    # onCreate. Remove it wherever it appears before settings/UI initialization.
    prefix = prefix.replace(needle, "")
    path.write_text(prefix + suffix, encoding="utf-8")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    store = java / "SettingsStore.kt"
    main = java / "MainActivity.kt"
    share = java / "fileshare/FileShareActivity.kt"
    service = java / "BackgroundService.kt"

    replace(
        store,
        'class SettingsStore(context: Context) {\n    private val prefs = context.getSharedPreferences("clipmesh_settings", Context.MODE_PRIVATE)',
        '''class SettingsStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("clipmesh_settings", Context.MODE_PRIVATE)

    private fun isManagedProfile(): Boolean =
        android.os.Build.VERSION.SDK_INT >= 24 && runCatching {
            appContext.getSystemService(android.os.UserManager::class.java)?.isManagedProfile == true
        }.getOrDefault(false)''',
        "Android SettingsStore managed-profile context",
    )
    replace(
        store,
        '''    var receiveFilesInBackground: Boolean
        get() = prefs.getBoolean("receive_files_in_background", true)
        set(value) = prefs.edit().putBoolean("receive_files_in_background", value).apply()''',
        '''    var receiveFilesInBackground: Boolean
        get() = prefs.getBoolean("receive_files_in_background", !isManagedProfile())
        set(value) = prefs.edit().putBoolean("receive_files_in_background", value).apply()''',
        "managed-profile background receive default",
    )

    # v023/v027 layers can position this call differently in MainActivity.
    # Strip any pre-settings service start, then make the decision from the
    # managed-profile-aware settings.
    remove_early_service_start(main, "        settings = SettingsStore(this)", "MainActivity early FGS")
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

    # FileShareActivity can also receive the v023 service injection before its
    # selected-file initialization. Make that startup managed-profile-aware too.
    remove_early_service_start(share, "        selected += extractSharedUris(intent)", "FileShareActivity early FGS")
    replace(
        share,
        '''        super.onCreate(savedInstanceState)
''',
        '''        super.onCreate(savedInstanceState)
        val backgroundSettings = dev.clipmesh.SettingsStore(this)
        if (backgroundSettings.backgroundSync || backgroundSettings.receiveFilesInBackground) {
            BackgroundService.start(this)
        }
''',
        "conditional FileShareActivity background startup",
    )

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
                if (captureCurrent) runCatching { BackgroundRuntime.captureNow() }
            }''',
        "safe denied-FGS fallback",
    )

print(f"Applied ClipMesh v063 work-profile-safe startup on {SYSTEM}")
