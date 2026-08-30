from pathlib import Path
import os
import platform


root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

# File Transfer lists every live ClipMesh receiver on the LAN. Window visibility
# and favorites affect presentation/trust, not whether a reachable recipient is
# hidden from the list.
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
    assert 'CFBundleShortVersionString</key><string>0.2.10' in build
elif system == "Windows":
    ui = (root / "ci/ClipMeshWindows.cs").read_text(encoding="utf-8")
    transfer = (root / "ci/ClipMeshTransfer.cs").read_text(encoding="utf-8")
    assert 'private const string Version = "0.2.10";' in ui
    assert 'LocalTransferManagerC.Shared.SetUiVisible(false);' in ui
    assert 'private readonly HashSet<string> visibleDevices' in transfer
    assert '{"visible", uiVisible}' in transfer
    assert 'private void RegisterBack(' in transfer
    assert '/api/clipmesh/v1/register' in transfer
    assert 'if (!serverReady) return;' in transfer
    assert '!IsFavorite(d.Fingerprint) && !visibleDevices.Contains(d.Fingerprint)' not in transfer
elif system == "Linux":
    gradle = (root / "clipmesh/android/app/build.gradle.kts").read_text(encoding="utf-8")
    runtime = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/BackgroundRuntime.kt").read_text(encoding="utf-8")
    engine = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/LocalTransferEngine.kt").read_text(encoding="utf-8")
    incoming = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/IncomingRequestUi.kt").read_text(encoding="utf-8")
    main = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/MainActivity.kt").read_text(encoding="utf-8")
    access = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/exclusion/ExclusionAccessibilityService.kt").read_text(encoding="utf-8")
    main_ci_receiver = root / "clipmesh/android/app/src/main/java/dev/clipmesh/CiBackgroundCaptureReceiver.kt"
    debug_ci_receiver = root / "clipmesh/android/app/src/debug/java/dev/clipmesh/CiBackgroundCaptureReceiver.kt"
    ci_receiver_path = debug_ci_receiver if debug_ci_receiver.is_file() else main_ci_receiver
    ci_receiver = ci_receiver_path.read_text(encoding="utf-8")
    assert 'versionCode = 20' in gradle
    assert 'versionName = "0.2.10"' in gradle
    assert 'ClipMesh-ClipboardWatch' in runtime
    assert '650L' in runtime
    assert 'shizuku.hasPermission()' in runtime
    assert 'bridge.captureNowForForeground()' in runtime
    assert 'fun captureAccessibility' in runtime
    assert 'last_outgoing_at' in runtime
    assert 'private fun stopClipboardRuntime()' in runtime
    assert 'private object ClipMeshUiVisibility' in runtime
    assert 'Application.ActivityLifecycleCallbacks' in runtime
    assert 'IdentityHashMap<android.app.Activity, Boolean>()' in runtime
    assert 'ClipMeshUiVisibility.install(context)' in runtime
    assert 'override fun onActivityStarted' in runtime
    assert 'override fun onActivityStopped' in runtime
    assert 'startedActivities.isEmpty()' in runtime
    assert 'LocalTransferEngine.setUiVisible(true)' in runtime
    assert 'LocalTransferEngine.setUiVisible(false)' in runtime
    assert '350L' in runtime
    assert 'BackgroundRuntime.captureAccessibility(clip)' in access
    assert 'BackgroundRuntime.captureAccessibility' in ci_receiver
    assert 'LocalTransferEngine.setUiVisible(' not in incoming
    assert 'val visible: Boolean = true' in engine
    assert 'put("visible", uiVisible)' in engine
    assert '/api/clipmesh/v1/register' in engine
    assert 'serverReady.set(true)' in engine
    assert 'if (!serverReady.get()) return' in engine
    assert '.filter { it.visible || isFavorite(requireContext(), it.fingerprint) }' not in engine
    assert '\\1        if (BuildConfig.DEBUG)' not in main
    assert main.count('override fun onCreate(savedInstanceState: Bundle?) {') == 1
    assert 'clipmesh_ci_favorite' in main
else:
    raise AssertionError(f"unsupported platform {system}")

print(f"ClipMesh v0.2.10 final background/transfer regression self-test passed on {system}")
