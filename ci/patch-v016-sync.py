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
# v0.1.6: never exclude ClipMesh itself from clipboard capture.
#
# Echoes are already prevented by content fingerprints. Keeping ClipMesh in the
# source-app exclusion list made foreground testing fail on Android and could make
# the macOS fallback miss a freshly copied item after the user switched back to
# ClipMesh. Migrate the stale self-exclusion out of existing installs as well as
# removing it from new defaults.
# ---------------------------------------------------------------------------
rust_config = project / "apps/desktop/src/config.rs"
replace_once(
    rust_config,
    '''        cfg.device_name = sanitize_device_name(&cfg.device_name);
        Ok(cfg)
''',
    '''        cfg.device_name = sanitize_device_name(&cfg.device_name);
        // v0.1.5 and earlier included ClipMesh itself in the source-app exclusion
        // list. That can suppress a legitimate copy when the UI becomes foreground
        // before the clipboard fallback observes the change. Echo protection is
        // handled by ClipboardState fingerprints, so self-exclusion is harmful.
        cfg.exclusions.retain(|item| !item.trim().eq_ignore_ascii_case("clipmesh"));
        Ok(cfg)
''',
    "desktop migrate obsolete ClipMesh self-exclusion",
)
replace_once(
    rust_config,
    '''        "windows credential manager", "keychain access", "clipmesh"
''',
    '''        "windows credential manager", "keychain access"
''',
    "desktop remove ClipMesh from default exclusions",
)

rust_clipboard = project / "apps/desktop/src/clipboard.rs"
replace_once(
    rust_clipboard,
    '''    let source=exclusions::active_app();
    if exclusions::is_excluded(source.as_deref(), &cfg.exclusions) {
        debug!(source=?source, "clipboard source excluded");
        return Ok(None);
    }
''',
    '''    let source=exclusions::active_app();
    // Never suppress ClipMesh itself. Remote echoes are already suppressed using
    // payload fingerprints, and source-app detection can observe ClipMesh after the
    // user switches back to the UI even though the copy happened in another app.
    let source_is_clipmesh = source.as_deref()
        .map(|value| value.to_ascii_lowercase().contains("clipmesh"))
        .unwrap_or(false);
    if !source_is_clipmesh && exclusions::is_excluded(source.as_deref(), &cfg.exclusions) {
        debug!(source=?source, "clipboard source excluded");
        return Ok(None);
    }
''',
    "desktop never self-exclude clipboard capture",
)

android_settings = project / "android/app/src/main/java/dev/clipmesh/SettingsStore.kt"
replace_once(
    android_settings,
    '''    var excludedPackages: Set<String>
        get() = prefs.getStringSet("excluded_packages", DEFAULT_EXCLUSIONS)?.toSet() ?: DEFAULT_EXCLUSIONS
        set(value) = prefs.edit().putStringSet("excluded_packages", value.map { it.trim() }.filter { it.isNotBlank() }.toSet()).apply()
''',
    '''    var excludedPackages: Set<String>
        get() = (prefs.getStringSet("excluded_packages", DEFAULT_EXCLUSIONS)?.toSet() ?: DEFAULT_EXCLUSIONS)
            .filterNot { it.equals("dev.clipmesh", ignoreCase = true) }
            .toSet()
        set(value) = prefs.edit().putStringSet(
            "excluded_packages",
            value.map { it.trim() }
                .filter { it.isNotBlank() && !it.equals("dev.clipmesh", ignoreCase = true) }
                .toSet()
        ).apply()
''',
    "Android migrate obsolete ClipMesh self-exclusion",
)
replace_once(
    android_settings,
    '''        val DEFAULT_EXCLUSIONS = setOf(
            "dev.clipmesh",
''',
    '''        val DEFAULT_EXCLUSIONS = setOf(
''',
    "Android remove ClipMesh from default exclusions",
)

android_bridge = project / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
replace_once(
    android_bridge,
    '''        val sourcePackage = ForegroundTracker.currentPackage
        if (sourcePackage != null && settings.excludedPackages.contains(sourcePackage)) return
''',
    '''        val sourcePackage = ForegroundTracker.currentPackage
        // Never exclude our own foreground window. The clipboard may have changed
        // just before the user returned to ClipMesh, and fingerprint suppression is
        // the correct mechanism for preventing remote echo loops.
        if (sourcePackage != null && sourcePackage != context.packageName && settings.excludedPackages.contains(sourcePackage)) return
''',
    "Android never self-exclude clipboard capture",
)

# Make the existing View Clipboard test action also request an immediate foreground
# capture. This does not replace automatic listeners; it simply gives the diagnostic
# button deterministic semantics while ClipMesh has clipboard access.
android_main = project / "android/app/src/main/java/dev/clipmesh/MainActivity.kt"
replace_once(
    android_main,
    '''    private fun showClipboard() {
        val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
''',
    '''    private fun showClipboard() {
        if (settings.backgroundSync && settings.sendEnabled) {
            runCatching {
                startService(Intent(this, SyncService::class.java).setAction(SyncService.ACTION_CAPTURE_CURRENT))
            }
        }
        val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
''',
    "Android View Clipboard foreground capture",
)

# ---------------------------------------------------------------------------
# Native package metadata.
# patch-v014-versions.py first normalizes old wrappers to v0.1.5. Some platform
# wrapper files only exist in their own native job, so these replacements are
# deliberately conditional outside the platform where the file is generated.
# ---------------------------------------------------------------------------
android_gradle = project / "android/app/build.gradle.kts"
replace_once(android_gradle, 'versionCode = 5', 'versionCode = 6', "Android v0.1.6 versionCode")
replace_once(android_gradle, 'versionName = "0.1.5"', 'versionName = "0.1.6"', "Android v0.1.6 versionName")

mac_build = project / "scripts/build-macos.sh"
replace_if_present(
    mac_build,
    '<key>CFBundleShortVersionString</key><string>0.1.5</string>',
    '<key>CFBundleShortVersionString</key><string>0.1.6</string>',
)
replace_if_present(
    mac_build,
    '<key>CFBundleVersion</key><string>0.1.5</string>',
    '<key>CFBundleVersion</key><string>0.1.6</string>',
)

replace_if_present(
    root / "ci/ClipMeshWindows.cs",
    'private const string Version = "0.1.5";',
    'private const string Version = "0.1.6";',
)

print("Applied ClipMesh v0.1.6 self-capture migration, foreground clipboard reliability, and native version fixes")
