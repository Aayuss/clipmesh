from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_if_present(path: Path, old: str, new: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Android setting: remote clipboard popups are OFF by default.
# When enabled, ClipMesh intentionally falls back to an app-originated clipboard
# write so Android/SystemUI can show its normal "Copied" UI.
# ---------------------------------------------------------------------------
store = project / "android/app/src/main/java/dev/clipmesh/SettingsStore.kt"
replace_once(
    store,
    '''    var compatibilityWatchdog: Boolean
        get() = prefs.getBoolean("compat_watchdog", false)
        set(value) = prefs.edit().putBoolean("compat_watchdog", value).apply()
''',
    '''    var compatibilityWatchdog: Boolean
        get() = prefs.getBoolean("compat_watchdog", false)
        set(value) = prefs.edit().putBoolean("compat_watchdog", value).apply()

    var showRemoteCopyOverlay: Boolean
        get() = prefs.getBoolean("show_remote_copy_overlay", false)
        set(value) = prefs.edit().putBoolean("show_remote_copy_overlay", value).apply()
''',
    "Android remote-copy overlay setting",
)

settings = project / "android/app/src/main/java/dev/clipmesh/SettingsActivity.kt"
replace_once(
    settings,
    '''        backgroundCard.addView(toggle("Send clipboard", settingsStore.sendEnabled) { settingsStore.sendEnabled = it })
        backgroundCard.addView(toggle("Receive clipboard", settingsStore.receiveEnabled) { settingsStore.receiveEnabled = it })
        backgroundCard.addView(toggle("Start after reboot", settingsStore.runAtBoot) { settingsStore.runAtBoot = it })
''',
    '''        backgroundCard.addView(toggle("Send clipboard", settingsStore.sendEnabled) { settingsStore.sendEnabled = it })
        backgroundCard.addView(toggle("Receive clipboard", settingsStore.receiveEnabled) { settingsStore.receiveEnabled = it })
        backgroundCard.addView(toggle("Show remote copy popup", settingsStore.showRemoteCopyOverlay) {
            settingsStore.showRemoteCopyOverlay = it
        })
        backgroundCard.addView(label(
            "Off by default. When off, ClipMesh uses the quiet Shizuku clipboard path for mirrored text so Android does not show the local Copied popup where SystemUI supports suppression.",
            12f, false, muted
        ).apply { setPadding(0, 0, 0, dp(6)) })
        backgroundCard.addView(toggle("Start after reboot", settingsStore.runAtBoot) { settingsStore.runAtBoot = it })
''',
    "Android remote-copy overlay Settings UI",
)


# ---------------------------------------------------------------------------
# Android -> desktop images.
#
# v0.1.8 only promoted a Shizuku image to image/png when the clipboard contained
# exactly one item. Samsung/Android apps can include an image URI plus metadata or
# another clip item, causing the image to be sent as a generic file instead.
# Always prioritize the first real image item as image/png, regardless of extra
# clipboard items. The ordinary ClipboardManager fallback now also scans all items
# rather than assuming item 0 is the image.
# ---------------------------------------------------------------------------
bridge = project / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
old_fallback = '''        val clip = clipboard.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        val reps = mutableListOf<Representation>()
        val first = clip.getItemAt(0)
        val uri = first.uri
        val declaredMime = uri?.let { runCatching { context.contentResolver.getType(it) }.getOrNull() }
            ?: clipboard.primaryClipDescription?.let { description ->
                (0 until description.mimeTypeCount).map { description.getMimeType(it) }
                    .firstOrNull { it.lowercase(Locale.ROOT).startsWith("image/") }
            }
        val isImage = declaredMime?.lowercase(Locale.ROOT)?.startsWith("image/") == true
        if (settings.syncImages && isImage && uri != null) {
            val bytes = readUriBytes(uri)
            val png = bytes?.let { imageToPng(it) }
            if (png != null) reps += Representation("image/png", png)
        }
        if (!isImage && settings.syncText) {
            val text = first.coerceToText(context)?.toString()
            if (!text.isNullOrEmpty()) reps += Representation("text/plain; charset=utf-8", text.toByteArray())
        }
        return ClipPayload(reps, sourceApp = sourcePackage).takeIf { it.representations.isNotEmpty() }
'''
new_fallback = '''        val clip = clipboard.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        val reps = mutableListOf<Representation>()
        val descriptionImageMime = clipboard.primaryClipDescription?.let { description ->
            (0 until description.mimeTypeCount)
                .map { description.getMimeType(it) }
                .firstOrNull { it.lowercase(Locale.ROOT).startsWith("image/") }
        }
        var imageAdded = false
        if (settings.syncImages) {
            for (index in 0 until clip.itemCount) {
                val item = clip.getItemAt(index)
                val uri = item.uri ?: continue
                val uriMime = runCatching { context.contentResolver.getType(uri) }.getOrNull()
                val mime = uriMime ?: descriptionImageMime
                if (mime?.lowercase(Locale.ROOT)?.startsWith("image/") != true) continue
                val png = readUriBytes(uri)?.let { imageToPng(it) } ?: continue
                reps += Representation("image/png", png)
                imageAdded = true
                break
            }
        }
        if (!imageAdded && settings.syncText) {
            val text = clip.getItemAt(0).coerceToText(context)?.toString()
            if (!text.isNullOrEmpty()) reps += Representation("text/plain; charset=utf-8", text.toByteArray())
        }
        return ClipPayload(reps, sourceApp = sourcePackage).takeIf { it.representations.isNotEmpty() }
'''
replace_once(bridge, old_fallback, new_fallback, "Android multi-item foreground image capture")

replace_once(
    bridge,
    '''                    if (isImage && items.length() == 1) {
                        val png = imageToPng(bytes)
                        if (png != null) reps += Representation("image/png", png)
                    } else files += PortableFile(name, bytes, hash)''',
    '''                    if (isImage && settings.syncImages && reps.none { it.mime.equals("image/png", ignoreCase = true) }) {
                        val png = imageToPng(bytes)
                        if (png != null) {
                            reps += Representation("image/png", png)
                        } else if (settings.syncFiles) {
                            files += PortableFile(name, bytes, hash)
                        }
                    } else if (settings.syncFiles) {
                        files += PortableFile(name, bytes, hash)
                    }''',
    "Android multi-item Shizuku image promotion",
)

replace_once(
    bridge,
    '''    private fun markRemote(clip: ClipData): ClipData {
        val extras = android.os.PersistableBundle().apply {''',
    '''    private fun markRemote(clip: ClipData): ClipData {
        if (settings.showRemoteCopyOverlay) return clip
        val extras = android.os.PersistableBundle().apply {''',
    "Android remote-copy overlay preference",
)

bridge_text = bridge.read_text(encoding="utf-8")
old_quiet = 'if (plain != null && html == null && shizuku.hasPermission()) {'
if old_quiet not in bridge_text:
    raise SystemExit("Android quiet Shizuku text receive anchor missing")
bridge.write_text(
    bridge_text.replace(
        old_quiet,
        'if (plain != null && html == null && shizuku.hasPermission() && !settings.showRemoteCopyOverlay) {',
        1,
    ),
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Foreground-service notification.
# Android requires a notification for a reliable foreground sync service; it
# cannot legally be removed while retaining this service architecture. Make the
# channel minimum-importance/silent and stop advertising the peer count.
# ---------------------------------------------------------------------------
sync = project / "android/app/src/main/java/dev/clipmesh/SyncService.kt"
sync_text = sync.read_text(encoding="utf-8")
if 'private const val CHANNEL_ID = "clipmesh_sync"' in sync_text:
    sync_text = sync_text.replace(
        'private const val CHANNEL_ID = "clipmesh_sync"',
        'private const val CHANNEL_ID = "clipmesh_sync_quiet_v019"',
        1,
    )
elif 'private const val CHANNEL_ID = "clipmesh_sync_quiet_v019"' not in sync_text:
    raise SystemExit("Android foreground notification channel id anchor missing")
if "NotificationManager.IMPORTANCE_LOW" in sync_text:
    sync_text = sync_text.replace(
        "NotificationManager.IMPORTANCE_LOW",
        "NotificationManager.IMPORTANCE_MIN",
        1,
    )
elif "NotificationManager.IMPORTANCE_MIN" not in sync_text:
    raise SystemExit("Android foreground notification importance anchor missing")
if ".setSilent(true)" not in sync_text:
    if ".setOngoing(true)" not in sync_text:
        raise SystemExit("Android foreground notification builder anchor missing")
    sync_text = sync_text.replace(
        ".setOngoing(true)",
        ".setOngoing(true)\n            .setSilent(true)\n            .setShowWhen(false)\n            .setPriority(android.app.Notification.PRIORITY_MIN)",
        1,
    )
sync.write_text(sync_text, encoding="utf-8")

network = project / "android/app/src/main/java/dev/clipmesh/network/NetworkEngine.kt"
network_text = network.read_text(encoding="utf-8")
peer_status_count = network_text.count('onStatus("Connected peers: ${peers.size}")')
if peer_status_count < 1:
    raise SystemExit("Android connected-peer notification status anchor missing")
network.write_text(
    network_text.replace('onStatus("Connected peers: ${peers.size}")', 'onStatus("Sync active")'),
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Version metadata.
# ---------------------------------------------------------------------------
android_gradle = project / "android/app/build.gradle.kts"
replace_once(android_gradle, "versionCode = 8", "versionCode = 9", "Android v0.1.9 versionCode")
replace_once(android_gradle, 'versionName = "0.1.8"', 'versionName = "0.1.9"', "Android v0.1.9 versionName")

mac_build = project / "scripts/build-macos.sh"
replace_if_present(
    mac_build,
    "<key>CFBundleShortVersionString</key><string>0.1.8</string>",
    "<key>CFBundleShortVersionString</key><string>0.1.9</string>",
)
replace_if_present(
    mac_build,
    "<key>CFBundleVersion</key><string>0.1.8</string>",
    "<key>CFBundleVersion</key><string>0.1.9</string>",
)
replace_if_present(
    root / "ci/ClipMeshWindows.cs",
    'private const string Version = "0.1.8";',
    'private const string Version = "0.1.9";',
)


# Release guards.
final_bridge = bridge.read_text(encoding="utf-8")
for required in (
    'for (index in 0 until clip.itemCount)',
    'reps.none { it.mime.equals("image/png", ignoreCase = true) }',
    'showRemoteCopyOverlay',
    '!settings.showRemoteCopyOverlay',
):
    if required not in final_bridge:
        raise SystemExit(f"v0.1.9 missing Android image/quiet-copy guard: {required}")

final_store = store.read_text(encoding="utf-8")
if 'prefs.getBoolean("show_remote_copy_overlay", false)' not in final_store:
    raise SystemExit("v0.1.9 remote-copy popup must default to off")

final_sync = sync.read_text(encoding="utf-8")
for required in ("NotificationManager.IMPORTANCE_MIN", ".setSilent(true)", "android.app.Notification.PRIORITY_MIN", "clipmesh_sync_quiet_v019"):
    if required not in final_sync:
        raise SystemExit(f"v0.1.9 missing quiet foreground notification guard: {required}")

print("Applied ClipMesh v0.1.9 Android multi-item image sync, remote-copy popup toggle, quiet service notification, and version metadata")
