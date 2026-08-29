from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
manifest_path = root / "clipmesh/android/app/src/main/AndroidManifest.xml"
ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
ANDROID = "{http://schemas.android.com/apk/res/android}"
tree = ET.parse(manifest_path)
manifest = tree.getroot()
application = manifest.find("application")
if application is None:
    raise SystemExit("Android application node missing")

# Remove every spelling of the legacy foreground services. v0.2.3 deliberately
# consolidates them into BackgroundService so exactly one persistent runtime owns
# clipboard + LocalTransferEngine lifecycle.
for child in list(application):
    if child.tag != "service":
        continue
    name = (child.get(ANDROID + "name") or "").strip()
    if name.endswith(".SyncService") or name == "SyncService" or name.endswith(".FileTransferService") or name == "FileTransferService":
        application.remove(child)

tree.write(manifest_path, encoding="utf-8", xml_declaration=True)

# Parse back rather than relying on formatting.
tree = ET.parse(manifest_path)
manifest = tree.getroot()
application = manifest.find("application")
services = [node for node in application if node.tag == "service"]
service_names = [(node.get(ANDROID + "name") or "") for node in services]
background = [node for node in services if (node.get(ANDROID + "name") or "").endswith("BackgroundService")]
if len(background) != 1:
    raise SystemExit(f"Expected exactly one BackgroundService declaration, got {len(background)}: {service_names}")
if background[0].get(ANDROID + "foregroundServiceType") != "connectedDevice":
    raise SystemExit("BackgroundService is not connectedDevice type")
for legacy in ("SyncService", "FileTransferService"):
    if any(name.endswith(legacy) for name in service_names):
        raise SystemExit(f"Legacy {legacy} still declared: {service_names}")

permissions = {node.get(ANDROID + "name") for node in manifest.findall("uses-permission")}
for required in (
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
    "android.permission.CHANGE_WIFI_MULTICAST_STATE",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.RECEIVE_BOOT_COMPLETED",
):
    if required not in permissions:
        raise SystemExit(f"Missing Android v0.2.3 permission: {required}")

receivers = [(node.get(ANDROID + "name") or "") for node in application if node.tag == "receiver"]
if not any(name.endswith("TransferBootReceiver") for name in receivers):
    raise SystemExit("TransferBootReceiver declaration missing")

print("Android v0.2.3 manifest normalized: one connected-device BackgroundService, boot restore enabled")
