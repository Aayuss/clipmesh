#!/usr/bin/env python3
"""Static guards for Android work-profile-safe startup."""

from pathlib import Path
import os, platform

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    store = (java / "SettingsStore.kt").read_text(encoding="utf-8")
    main = (java / "MainActivity.kt").read_text(encoding="utf-8")
    share = (java / "fileshare/FileShareActivity.kt").read_text(encoding="utf-8")
    service = (java / "BackgroundService.kt").read_text(encoding="utf-8")

    for needle in (
        "fun isManagedProfile(context: Context): Boolean",
        "android.os.UserManager::class.java",
        'prefs.getBoolean("receive_files_in_background", !isManagedProfile(appContext))',
    ):
        assert needle in store, needle

    assert "super.onCreate(savedInstanceState)\n        BackgroundService.start(this)" not in main
    assert "if (settings.backgroundSync || settings.receiveFilesInBackground) BackgroundService.start(this)" in main

    assert "val backgroundSettings = dev.clipmesh.SettingsStore(this)" in share
    assert "backgroundSettings.backgroundSync || backgroundSettings.receiveFilesInBackground" in share

    for needle in (
        'runCatching {\n            promoteToForeground()',
        '"Background service unavailable in this profile"',
        "if (!promoted) {",
        "stopSelf()",
        '"Foreground service start rejected"',
    ):
        assert needle in service, needle

    denied = service.split('fun start(context: Context, captureCurrent: Boolean = false)',1)[1]
    assert "BackgroundRuntime.start(app)" not in denied.split("}",1)[0], "denied FGS path must not fake background runtime"
elif SYSTEM in ("Darwin", "Windows"):
    pass
else:
    raise SystemExit(f"Unsupported platform: {SYSTEM}")

print(f"v063 work-profile startup self-test passed on {SYSTEM}")
