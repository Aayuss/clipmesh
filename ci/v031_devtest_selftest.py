from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def listed(remote_receiver_live: bool, remote_ui_visible: bool, local_favorited_remote: bool) -> bool:
    return remote_receiver_live


assert listed(True, True, False)
assert listed(True, True, True)
assert listed(True, False, False)
assert listed(True, False, True)
assert not listed(False, True, True)
assert not listed(False, False, False)

if system == "Darwin":
    app = (root / "ci/ClipMeshApp.swift").read_text(encoding="utf-8")
    transfer = (root / "ci/ClipMeshTransfer.swift").read_text(encoding="utf-8")
    build = (root / "clipmesh/scripts/build-macos.sh").read_text(encoding="utf-8")
    assert 'static func acquireInstanceLock() throws -> Int32?' in app
    assert 'Darwin.lockf(descriptor, F_TLOCK, 0)' in app
    assert 'static func reclaimStaleDaemonListener() throws' in app
    assert 'return commandMatches && executableMatches' in app
    assert 'ClipMesh left that process untouched' in app
    assert 'try Runtime.reclaimStaleDaemonListener()' in app
    assert 'guard process.isRunning else' in app
    assert '--reclaim-stale-daemon-test' in app
    assert '--clipboard-preview-self-test' in app
    assert '--dev-test-transfer-fingerprint' in app
    assert '--dev-test-favorite' in app
    assert '--dev-test-send-file' in app
    assert 'func devTestFingerprint() -> String' in transfer
    assert 'func devTestSend(file: URL, address: String, fingerprint: String) throws' in transfer
    assert 'enum CMClipboardSnapshot' in app
    preview_start = app.index('@objc private func viewClipboard()')
    preview_end = app.index('@objc private func quitApp', preview_start)
    preview_handler = app[preview_start:preview_end]
    assert 'CMClipboardSnapshot.describe(NSPasteboard.general)' in preview_handler
    assert 'NSImage(pasteboard:' not in preview_handler
    assert 'readObjects(forClasses:' not in preview_handler
    assert 'LocalTransferManager.shared.setUIVisible(false)' in app
    assert 'private var visibleDevices = Set<String>()' in transfer
    assert '"visible": isUIVisible' in transfer
    assert 'private func registerBack(json:' in transfer
    assert '/api/clipmesh/v1/register' in transfer
    assert 'guard isRunning && isServerReady else' in transfer
    assert 'listener.stateUpdateHandler' in transfer
    assert '.filter { visibleDevices.contains($0.fingerprint) || favorites.contains($0.fingerprint) }' not in transfer
    assert 'CFBundleShortVersionString</key><string>0.2.9' in build
elif system == "Linux":
    gradle = (root / "clipmesh/android/app/build.gradle.kts").read_text(encoding="utf-8")
    runtime = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/BackgroundRuntime.kt").read_text(encoding="utf-8")
    engine = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/LocalTransferEngine.kt").read_text(encoding="utf-8")
    incoming = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/IncomingRequestUi.kt").read_text(encoding="utf-8")
    main = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/MainActivity.kt").read_text(encoding="utf-8")
    access = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/exclusion/ExclusionAccessibilityService.kt").read_text(encoding="utf-8")
    ci_path = root / "clipmesh/android/app/src/debug/java/dev/clipmesh/CiBackgroundCaptureReceiver.kt"
    dev_path = root / "clipmesh/android/app/src/debug/java/dev/clipmesh/DevTestReceiver.kt"
    debug_manifest = (root / "clipmesh/android/app/src/debug/AndroidManifest.xml").read_text(encoding="utf-8")
    main_ci_path = root / "clipmesh/android/app/src/main/java/dev/clipmesh/CiBackgroundCaptureReceiver.kt"
    ci_receiver = ci_path.read_text(encoding="utf-8")
    dev_receiver = dev_path.read_text(encoding="utf-8")
    driver = (root / "clipmesh/android/devdriver/src/main/java/dev/clipmesh/testdriver/MainActivity.kt").read_text(encoding="utf-8")
    settings = (root / "clipmesh/android/settings.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 19' in gradle
    assert 'versionName = "0.2.9"' in gradle
    assert 'ClipMesh-ClipboardWatch' in runtime
    assert '650L' in runtime
    assert 'shizuku.hasPermission()' in runtime
    assert 'bridge.captureNowForForeground()' in runtime
    assert 'fun captureAccessibility' in runtime
    assert 'last_outgoing_at' in runtime
    assert 'private fun stopClipboardRuntime()' in runtime
    assert 'private object ClipMeshUiVisibility' in runtime
    assert 'Application.ActivityLifecycleCallbacks' in runtime
    assert 'BackgroundRuntime.captureAccessibility(clip)' in access
    assert 'BackgroundRuntime.captureAccessibility' in ci_receiver
    assert not main_ci_path.exists()
    assert '.CiBackgroundCaptureReceiver' in debug_manifest
    assert '.DevTestReceiver' in debug_manifest
    assert 'android.permission.DUMP' in debug_manifest
    assert 'ACTION_SEND_FILE' in dev_receiver
    assert 'ShizukuManager(app)' in dev_receiver
    assert 'include(":devdriver")' in settings
    assert 'dev.clipmesh.testdriver' in driver
    assert 'wait_image' in driver and 'wait_text' in driver
    assert 'LocalTransferEngine.setUiVisible(' not in incoming
    assert 'val visible: Boolean = true' in engine
    assert 'put("visible", uiVisible)' in engine
    assert '/api/clipmesh/v1/register' in engine
    assert 'serverReady.set(true)' in engine
    assert 'if (!serverReady.get()) return' in engine
    assert '.filter { it.visible || isFavorite(requireContext(), it.fingerprint) }' not in engine
    assert main.count('override fun onCreate(savedInstanceState: Bundle?) {') == 1
    assert 'clipmesh_ci_favorite' in main
elif system == "Windows":
    ui = (root / "ci/ClipMeshWindows.cs").read_text(encoding="utf-8")
    transfer = (root / "ci/ClipMeshTransfer.cs").read_text(encoding="utf-8")
    assert 'private const string Version = "0.2.9";' in ui
    assert '/api/clipmesh/v1/register' in transfer
else:
    raise AssertionError(f"unsupported platform {system}")

print(f"ClipMesh v0.2.9 physical development harness self-test passed on {system}")
