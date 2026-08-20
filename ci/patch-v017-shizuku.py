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

manifest = project / "android/app/src/main/AndroidManifest.xml"
manifest_text = manifest.read_text(encoding="utf-8")
provider_name = "rikka.shizuku.ShizukuProvider"
if provider_name not in manifest_text:
    app_start = manifest_text.find("<application")
    if app_start < 0:
        raise SystemExit("Android manifest is missing <application>")
    app_open_end = manifest_text.find(">", app_start)
    if app_open_end < 0:
        raise SystemExit("Android manifest has malformed <application>")
    provider = '''

        <!-- Required Shizuku Binder delivery endpoint. The provider dependency does
             not declare this component automatically. -->
        <provider
            android:name="rikka.shizuku.ShizukuProvider"
            android:authorities="${applicationId}.shizuku"
            android:multiprocess="false"
            android:enabled="true"
            android:exported="true"
            android:permission="android.permission.INTERACT_ACROSS_USERS_FULL" />'''
    manifest_text = manifest_text[: app_open_end + 1] + provider + manifest_text[app_open_end + 1 :]
    manifest.write_text(manifest_text, encoding="utf-8")

settings_activity = project / "android/app/src/main/java/dev/clipmesh/SettingsActivity.kt"
replace_once(
    settings_activity,
    '''                    toast("Shizuku is not connected. Start it, then return to ClipMesh and tap this button again.")''',
    '''                    toast("ClipMesh has not received the Shizuku connection yet. Keep Shizuku running, then return to ClipMesh and try again.")''',
    "Shizuku unavailable guidance",
)
replace_once(
    settings_activity,
    '''                shizuku.hasPermission() -> toast("Shizuku is authorized and ready")''',
    '''                shizuku.hasPermission() -> toast("Shizuku is authorized and connected to ClipMesh")''',
    "Shizuku connected guidance",
)

android_gradle = project / "android/app/build.gradle.kts"
replace_once(android_gradle, 'versionCode = 6', 'versionCode = 7', "Android v0.1.7 versionCode")
replace_once(android_gradle, 'versionName = "0.1.6"', 'versionName = "0.1.7"', "Android v0.1.7 versionName")

mac_build = project / "scripts/build-macos.sh"
replace_if_present(
    mac_build,
    '<key>CFBundleShortVersionString</key><string>0.1.6</string>',
    '<key>CFBundleShortVersionString</key><string>0.1.7</string>',
)
replace_if_present(
    mac_build,
    '<key>CFBundleVersion</key><string>0.1.6</string>',
    '<key>CFBundleVersion</key><string>0.1.7</string>',
)

replace_if_present(
    root / "ci/ClipMeshWindows.cs",
    'private const string Version = "0.1.6";',
    'private const string Version = "0.1.7";',
)

final_manifest = manifest.read_text(encoding="utf-8")
required_manifest_fragments = (
    'android:name="rikka.shizuku.ShizukuProvider"',
    'android:authorities="${applicationId}.shizuku"',
    'android:exported="true"',
    'android:permission="android.permission.INTERACT_ACROSS_USERS_FULL"',
    'moe.shizuku.manager.permission.API_V23',
)
for fragment in required_manifest_fragments:
    if fragment not in final_manifest:
        raise SystemExit(f"Missing required Shizuku manifest fragment: {fragment}")

print("Applied ClipMesh v0.1.7 Shizuku Binder-provider fix and native version metadata")
print("--- GENERATED ClipboardBridge.kt ---")
print((project / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt").read_text(encoding="utf-8"))
print("--- GENERATED ClipboardUserService.kt ---")
print((project / "android/app/src/main/java/dev/clipmesh/shizuku/ClipboardUserService.kt").read_text(encoding="utf-8"))
