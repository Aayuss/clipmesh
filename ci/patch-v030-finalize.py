from pathlib import Path
import os
import platform
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


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
        raise SystemExit(f"{label}: expected at least one match in {path}")
    path.write_text(text.replace(old, new), encoding="utf-8")


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    gradle = project / "android/app/build.gradle.kts"
    manifest_path = project / "android/app/src/main/AndroidManifest.xml"

    replace_once(gradle, "versionCode = 17", "versionCode = 19", "Android v0.2.9 versionCode")
    replace_once(gradle, 'versionName = "0.2.7"', 'versionName = "0.2.9"', "Android v0.2.9 versionName")

    # Restarting clipboard transport must not tear down the independent LAN file
    # receiver. The old stop/start sequence closed LocalTransferEngine and raced
    # its old server thread's finally block against the new listener. A hidden-UI
    # clipboard reinitialization could therefore make the next incoming transfer
    # disappear until the Activity restarted the engine again.
    replace_once(
        runtime,
        '''    @Synchronized fun stop() {
        clipboardWatchdog?.shutdownNow()
        clipboardWatchdog = null
        clipboard?.stop(); clipboard = null
        network?.stop(); network = null
        shizuku?.close(); shizuku = null
        LocalTransferEngine.stop(); status = "Stopped"
    }
    @Synchronized fun restart(context: Context) { stop(); start(context) }
''',
        '''    private fun stopClipboardRuntime() {
        clipboardWatchdog?.shutdownNow()
        clipboardWatchdog = null
        clipboard?.stop(); clipboard = null
        network?.stop(); network = null
        shizuku?.close(); shizuku = null
    }

    @Synchronized fun stop() {
        stopClipboardRuntime()
        LocalTransferEngine.stop()
        status = "Stopped"
    }

    @Synchronized fun restart(context: Context) {
        stopClipboardRuntime()
        status = "Stopped"
        // start() independently reconciles file receiving with its setting. If
        // it is already enabled, LocalTransferEngine.start() is intentionally a
        // no-op and the live listener is preserved.
        start(context)
    }
''',
        "Android independent clipboard/file runtime restart",
    )

    # Record the point where a locally captured Android clipboard payload reaches
    # the outgoing network callback. This marker exists only in debug builds and
    # lets the Android 15 emulator prove that capture still works after HOME hides
    # every ClipMesh Activity. It does not bypass or replace the real network send.
    replace_once(
        runtime,
        "        bridge = ClipboardBridge(app, settings, sh) { payload -> net.sendClipboard(payload) }\n",
        '''        bridge = ClipboardBridge(app, settings, sh) { payload ->
            if (BuildConfig.DEBUG) {
                app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                    .putLong("last_outgoing_at", System.currentTimeMillis())
                    .putInt("last_outgoing_representation_count", payload.representations.size)
                    .apply()
            }
            net.sendClipboard(payload)
        }
''',
        "Android outgoing clipboard CI observation",
    )

    # Debug-only, shell-protected trigger for the emulator. Requiring the platform
    # DUMP permission means ordinary third-party apps cannot invoke this exported
    # receiver. Production logic still enters through Accessibility/Shizuku.
    # A clean emulator has never paired, so seed a deterministic debug-only space
    # before restarting BackgroundRuntime; otherwise the runtime correctly exits
    # before constructing ClipboardBridge and the outgoing path cannot be tested.
    (java / "CiBackgroundCaptureReceiver.kt").write_text(r'''package dev.clipmesh

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
        BackgroundRuntime.captureAccessibility(ClipData.newPlainText("ClipMesh CI", text))
    }

    companion object {
        const val ACTION = "dev.clipmesh.action.CI_BACKGROUND_CAPTURE"
        const val EXTRA_TEXT = "text"
        private const val CI_SPACE_ID = "00000000-0000-4000-8000-000000000028"
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
    for child in list(application):
        if child.tag == "receiver" and child.get(ANDROID + "name") == ".CiBackgroundCaptureReceiver":
            application.remove(child)
    receiver = ET.SubElement(application, "receiver")
    receiver.set(ANDROID + "name", ".CiBackgroundCaptureReceiver")
    receiver.set(ANDROID + "enabled", "true")
    receiver.set(ANDROID + "exported", "true")
    receiver.set(ANDROID + "permission", "android.permission.DUMP")
    intent_filter = ET.SubElement(receiver, "intent-filter")
    action = ET.SubElement(intent_filter, "action")
    action.set(ANDROID + "name", "dev.clipmesh.action.CI_BACKGROUND_CAPTURE")
    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)

    final_runtime = runtime.read_text(encoding="utf-8")
    final_manifest = manifest_path.read_text(encoding="utf-8")
    receiver_text = (java / "CiBackgroundCaptureReceiver.kt").read_text(encoding="utf-8")
    for required in (
        'putLong("last_outgoing_at"',
        'payload.representations.size',
        'net.sendClipboard(payload)',
    ):
        if required not in final_runtime:
            raise SystemExit(f"Android v0.2.9 outgoing capture guard missing: {required}")
    for required in (
        "private fun stopClipboardRuntime()",
        "LocalTransferEngine.stop()",
        "start(context)",
    ):
        if required not in final_runtime:
            raise SystemExit(f"Android v0.2.9 lifecycle guard missing: {required}")
    for required in (
        ".CiBackgroundCaptureReceiver",
        "dev.clipmesh.action.CI_BACKGROUND_CAPTURE",
        "android.permission.DUMP",
    ):
        if required not in final_manifest:
            raise SystemExit(f"Android v0.2.9 CI receiver manifest guard missing: {required}")
    for required in (
        "BackgroundRuntime.restart(app)",
        "BackgroundRuntime.captureAccessibility",
        "java.util.UUID.fromString(CI_SPACE_ID)",
        "saveSpaceKey(ByteArray(32)",
        'putLong("receiver_seen_at"',
    ):
        if required not in receiver_text:
            raise SystemExit(f"Android v0.2.9 CI trigger guard missing: {required}")

elif system == "Darwin":
    build = project / "scripts/build-macos.sh"
    replace_all_required(build, "0.2.7", "0.2.9", "macOS v0.2.9 package version")

elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    replace_once(ui, 'private const string Version = "0.2.7";', 'private const string Version = "0.2.9";', "Windows v0.2.9 runtime version")

else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh v0.2.9 finalization, independent Android runtimes, and background-outgoing regression hook on {system}")
