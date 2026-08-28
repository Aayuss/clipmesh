from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_if(path: Path, old: str, new: str, required: bool = True) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if required:
            raise SystemExit(f"v0.2.0 anchor missing in {path}: {old[:100]!r}")
        return
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Android: install the LocalSend-v2-compatible LAN file transfer subsystem.
# ---------------------------------------------------------------------------
android_src = root / "ci" / "android-v020"
android_dst = project / "android/app/src/main/java/dev/clipmesh/fileshare"
android_dst.mkdir(parents=True, exist_ok=True)
for source in sorted(android_src.glob("*.kt")):
    shutil.copyfile(source, android_dst / source.name)

manifest = project / "android/app/src/main/AndroidManifest.xml"
ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
ANDROID = "{http://schemas.android.com/apk/res/android}"
tree = ET.parse(manifest)
manifest_root = tree.getroot()
application = manifest_root.find("application")
if application is None:
    raise SystemExit("Android application node missing")

permissions = {
    node.get(ANDROID + "name")
    for node in manifest_root.findall("uses-permission")
}

def add_permission(name: str, max_sdk: str | None = None):
    if name in permissions:
        return
    node = ET.Element("uses-permission")
    node.set(ANDROID + "name", name)
    if max_sdk is not None:
        node.set(ANDROID + "maxSdkVersion", max_sdk)
    insert_at = 0
    children = list(manifest_root)
    for i, child in enumerate(children):
        if child.tag == "uses-permission":
            insert_at = i + 1
    manifest_root.insert(insert_at, node)
    permissions.add(name)

for permission in (
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.ACCESS_WIFI_STATE",
    "android.permission.CHANGE_WIFI_MULTICAST_STATE",
    "android.permission.RECEIVE_BOOT_COMPLETED",
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
):
    add_permission(permission)
add_permission("android.permission.WRITE_EXTERNAL_STORAGE", "28")

application.set(ANDROID + "requestLegacyExternalStorage", "true")

existing_components = {
    node.get(ANDROID + "name")
    for node in application
    if node.tag in {"activity", "service", "receiver"}
}

if ".fileshare.FileTransferService" not in existing_components:
    service = ET.SubElement(application, "service")
    service.set(ANDROID + "name", ".fileshare.FileTransferService")
    service.set(ANDROID + "exported", "false")
    service.set(ANDROID + "foregroundServiceType", "dataSync")

if ".fileshare.TransferActionReceiver" not in existing_components:
    receiver = ET.SubElement(application, "receiver")
    receiver.set(ANDROID + "name", ".fileshare.TransferActionReceiver")
    receiver.set(ANDROID + "exported", "false")

if ".fileshare.TransferBootReceiver" not in existing_components:
    receiver = ET.SubElement(application, "receiver")
    receiver.set(ANDROID + "name", ".fileshare.TransferBootReceiver")
    receiver.set(ANDROID + "enabled", "true")
    receiver.set(ANDROID + "exported", "true")
    intent_filter = ET.SubElement(receiver, "intent-filter")
    for action_name in ("android.intent.action.BOOT_COMPLETED", "android.intent.action.MY_PACKAGE_REPLACED"):
        action = ET.SubElement(intent_filter, "action")
        action.set(ANDROID + "name", action_name)

if ".fileshare.FileShareActivity" not in existing_components:
    activity = ET.SubElement(application, "activity")
    activity.set(ANDROID + "name", ".fileshare.FileShareActivity")
    activity.set(ANDROID + "exported", "true")
    activity.set(ANDROID + "label", "Send with ClipMesh")
    intent_filter = ET.SubElement(activity, "intent-filter")
    for action_name in ("android.intent.action.SEND", "android.intent.action.SEND_MULTIPLE"):
        action = ET.SubElement(intent_filter, "action")
        action.set(ANDROID + "name", action_name)
    category = ET.SubElement(intent_filter, "category")
    category.set(ANDROID + "name", "android.intent.category.DEFAULT")
    data = ET.SubElement(intent_filter, "data")
    data.set(ANDROID + "mimeType", "*/*")

tree.write(manifest, encoding="utf-8", xml_declaration=True)

main = project / "android/app/src/main/java/dev/clipmesh/MainActivity.kt"
main_text = main.read_text(encoding="utf-8")
if "dev.clipmesh.fileshare.FileTransferService" not in main_text:
    main_text = main_text.replace(
        "import java.util.concurrent.TimeUnit",
        "import java.util.concurrent.TimeUnit\nimport dev.clipmesh.fileshare.FileTransferService\nimport dev.clipmesh.fileshare.FileShareActivity",
        1,
    )
if "FileTransferService.start(this)" not in main_text:
    main_text = main_text.replace(
        "        secrets = SecretStore(this)\n        requestNotificationPermission()",
        "        secrets = SecretStore(this)\n        FileTransferService.start(this)\n        requestNotificationPermission()",
        1,
    )
main_text = main_text.replace("Private clipboard sync", "Clipboard sync + nearby file drop")
main_text = main_text.replace(
    "private val pageBackground = Color.rgb(246, 247, 249)\n    private val cardBackground = Color.WHITE\n    private val ink = Color.rgb(28, 30, 34)\n    private val muted = Color.rgb(105, 110, 120)\n    private val primary = Color.rgb(31, 35, 42)\n    private val border = Color.rgb(224, 227, 232)\n    private val good = Color.rgb(31, 138, 76)",
    "private val pageBackground = Color.rgb(35, 34, 29)\n    private val cardBackground = Color.rgb(69, 66, 56)\n    private val ink = Color.rgb(249, 247, 239)\n    private val muted = Color.rgb(194, 189, 171)\n    private val primary = Color.rgb(91, 86, 70)\n    private val border = Color.rgb(111, 105, 86)\n    private val good = Color.rgb(184, 224, 164)",
)
main_text = main_text.replace(
    "if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR",
    "if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = 0",
)
main_text = main_text.replace("Color.rgb(248, 249, 250)", "Color.rgb(82, 78, 65)")
main_text = main_text.replace("Color.rgb(250, 250, 251)", "Color.rgb(61, 59, 51)")
if 'button("Send files"' not in main_text:
    anchor = '''        actions.addView(horizontal(
            button("Copy pairing code") { copyPairingCode() },
            button("View clipboard", primaryStyle = false) { showClipboard() }
        ).apply { setPadding(0, dp(10), 0, 0) })
'''
    if anchor not in main_text:
        raise SystemExit("Android quick actions anchor missing")
    main_text = main_text.replace(
        anchor,
        anchor + '''        actions.addView(button("Send files", primaryStyle = false) {
            startActivity(Intent(this@MainActivity, FileShareActivity::class.java))
        }, fullWidthParams(dp(48)).apply { topMargin = dp(9) })
''',
        1,
    )
main.write_text(main_text, encoding="utf-8")

settings = project / "android/app/src/main/java/dev/clipmesh/SettingsActivity.kt"
settings_text = settings.read_text(encoding="utf-8")
settings_text = settings_text.replace(
    "private val pageBackground = Color.rgb(246, 247, 249)\n    private val cardBackground = Color.WHITE\n    private val ink = Color.rgb(28, 30, 34)\n    private val muted = Color.rgb(105, 110, 120)\n    private val primary = Color.rgb(31, 35, 42)\n    private val border = Color.rgb(224, 227, 232)",
    "private val pageBackground = Color.rgb(35, 34, 29)\n    private val cardBackground = Color.rgb(69, 66, 56)\n    private val ink = Color.rgb(249, 247, 239)\n    private val muted = Color.rgb(194, 189, 171)\n    private val primary = Color.rgb(91, 86, 70)\n    private val border = Color.rgb(111, 105, 86)",
)
settings_text = settings_text.replace(
    "if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR",
    "if (Build.VERSION.SDK_INT >= 23) window.decorView.systemUiVisibility = 0",
)
settings_text = settings_text.replace("Color.rgb(248, 249, 250)", "Color.rgb(82, 78, 65)")
settings_text = settings_text.replace("Color.rgb(250, 250, 251)", "Color.rgb(61, 59, 51)")
settings.write_text(settings_text, encoding="utf-8")

android_gradle = project / "android/app/build.gradle.kts"
replace_if(android_gradle, "versionCode = 9", "versionCode = 10")
replace_if(android_gradle, 'versionName = "0.1.9"', 'versionName = "0.2.0"')

# ---------------------------------------------------------------------------
# Desktop version metadata. Native transfer source files are compiled directly
# from ci/ by the patched native packaging scripts.
# ---------------------------------------------------------------------------
mac_build = project / "scripts/build-macos.sh"
replace_if(mac_build, "<key>CFBundleShortVersionString</key><string>0.1.9</string>", "<key>CFBundleShortVersionString</key><string>0.2.0</string>")
replace_if(mac_build, "<key>CFBundleVersion</key><string>0.1.9</string>", "<key>CFBundleVersion</key><string>0.2.0</string>")

windows = root / "ci/ClipMeshWindows.cs"
replace_if(windows, 'private const string Version = "0.1.9";', 'private const string Version = "0.2.0";')

print("Applied ClipMesh v0.2.0 LocalSend-compatible file transfer, Android share sheet/background receiving, and warm-glass Android theme")
