from pathlib import Path
import os
import platform
import shutil
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


if system == "Linux":
    android = project / "android"
    app = android / "app"
    main_java = app / "src/main/java/dev/clipmesh"
    main_manifest_path = app / "src/main/AndroidManifest.xml"
    debug_root = app / "src/debug"
    debug_java = debug_root / "java/dev/clipmesh"
    debug_manifest_path = debug_root / "AndroidManifest.xml"
    assets = root / "dev/android"

    # Keep all shell-controlled testing hooks out of the normal source set.
    ci_main = main_java / "CiBackgroundCaptureReceiver.kt"
    if not ci_main.is_file():
        raise SystemExit("v0.2.8 CI receiver is missing before debug-source relocation")
    debug_java.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ci_main), str(debug_java / "CiBackgroundCaptureReceiver.kt"))

    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    ANDROID = "{http://schemas.android.com/apk/res/android}"
    tree = ET.parse(main_manifest_path)
    manifest = tree.getroot()
    application = manifest.find("application")
    if application is None:
        raise SystemExit("Android application node missing")
    removed = 0
    for child in list(application):
        if child.tag == "receiver" and child.get(ANDROID + "name") == ".CiBackgroundCaptureReceiver":
            application.remove(child)
            removed += 1
    if removed != 1:
        raise SystemExit(f"expected one main-manifest CI receiver, removed {removed}")
    tree.write(main_manifest_path, encoding="utf-8", xml_declaration=True)

    debug_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    debug_manifest_path.write_text('''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application>
        <receiver android:name=".CiBackgroundCaptureReceiver" android:enabled="true" android:exported="true" android:permission="android.permission.DUMP">
            <intent-filter><action android:name="dev.clipmesh.action.CI_BACKGROUND_CAPTURE" /></intent-filter>
        </receiver>
        <receiver android:name=".DevTestReceiver" android:enabled="true" android:exported="true" android:permission="android.permission.DUMP">
            <intent-filter>
                <action android:name="dev.clipmesh.devtest.CONFIGURE" />
                <action android:name="dev.clipmesh.devtest.INFO" />
                <action android:name="dev.clipmesh.devtest.FAVORITE" />
                <action android:name="dev.clipmesh.devtest.REQUEST_SHIZUKU" />
                <action android:name="dev.clipmesh.devtest.SEND_FILE" />
            </intent-filter>
        </receiver>
        <provider android:name=".DevTestFileProvider" android:authorities="${applicationId}.devtest" android:enabled="true" android:exported="false" android:grantUriPermissions="true" />
    </application>
</manifest>
''', encoding="utf-8")
    shutil.copyfile(assets / "DevTestReceiver.kt", debug_java / "DevTestReceiver.kt")
    shutil.copyfile(assets / "DevTestFileProvider.kt", debug_java / "DevTestFileProvider.kt")

    settings = android / "settings.gradle.kts"
    text = settings.read_text(encoding="utf-8")
    if 'include(":devdriver")' not in text:
        settings.write_text(text.rstrip() + '\ninclude(":devdriver")\n', encoding="utf-8")
    driver = android / "devdriver"
    source = driver / "src/main/java/dev/clipmesh/testdriver"
    source.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(assets / "driver-build.gradle.kts", driver / "build.gradle.kts")
    (driver / "src/main").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(assets / "driver-AndroidManifest.xml", driver / "src/main/AndroidManifest.xml")
    shutil.copyfile(assets / "DriverMainActivity.kt", source / "MainActivity.kt")
    shutil.copyfile(assets / "TestImageProvider.kt", source / "TestImageProvider.kt")

elif system == "Darwin":
    transfer = root / "ci/ClipMeshTransfer.swift"
    app = root / "ci/ClipMeshApp.swift"
    replace_once(
        transfer,
        '''    func setFavorite(_ fingerprint: String, _ favorite: Bool) {
        var values = TransferPrefs.favorites
        if favorite { values.insert(fingerprint) } else { values.remove(fingerprint) }
        TransferPrefs.favorites = values
    }
''',
        '''    func setFavorite(_ fingerprint: String, _ favorite: Bool) {
        var values = TransferPrefs.favorites
        if favorite { values.insert(fingerprint) } else { values.remove(fingerprint) }
        TransferPrefs.favorites = values
    }

    func devTestFingerprint() -> String { TransferPrefs.fingerprint }

    func devTestSend(file: URL, address: String, fingerprint: String) throws {
        aliasProvider = { "ClipMesh Mac E2E" }
        let target = TransferDevice(alias: "ClipMesh Android E2E", fingerprint: fingerprint, address: address, port: Self.port, model: "Android", type: "mobile", lastSeen: Date())
        try sendSync(files: [file], to: target, progress: { _ in })
    }
''',
        "macOS physical E2E transfer hooks",
    )
    marker = 'if CommandLine.arguments.contains("--smoke-test") {'
    cli = r'''let clipMeshDevArgs = CommandLine.arguments
if clipMeshDevArgs.contains("--dev-test-transfer-fingerprint") {
    print(LocalTransferManager.shared.devTestFingerprint())
    exit(0)
}
if let index = clipMeshDevArgs.firstIndex(of: "--dev-test-favorite"), clipMeshDevArgs.count > index + 1 {
    let fingerprint = clipMeshDevArgs[index + 1]
    LocalTransferManager.shared.setFavorite(fingerprint, true)
    print("favorited \(fingerprint)")
    exit(0)
}
if let index = clipMeshDevArgs.firstIndex(of: "--dev-test-send-file"), clipMeshDevArgs.count > index + 3 {
    do {
        try LocalTransferManager.shared.devTestSend(
            file: URL(fileURLWithPath: clipMeshDevArgs[index + 1]),
            address: clipMeshDevArgs[index + 2],
            fingerprint: clipMeshDevArgs[index + 3]
        )
        print("ClipMesh macOS physical file send: PASS")
        exit(0)
    } catch {
        fputs("ClipMesh macOS physical file send failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

'''
    replace_once(app, marker, cli + marker, "macOS physical E2E command entrypoints")

elif system == "Windows":
    pass
else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh local physical-development harness on {system}")
