from pathlib import Path
import os
import platform


root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

# AirDrop-like visibility policy: a background peer is listed only when the
# local device has favorited it. Receiver trust is independent and decides
# whether an incoming transfer can auto-save.
def listed(remote_ui_visible: bool, local_favorited_remote: bool) -> bool:
    return remote_ui_visible or local_favorited_remote

assert listed(True, False)
assert listed(True, True)
assert not listed(False, False)
assert listed(False, True)

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
    assert 'CFBundleShortVersionString</key><string>0.2.7' in build
elif system == "Windows":
    ui = (root / "ci/ClipMeshWindows.cs").read_text(encoding="utf-8")
    transfer = (root / "ci/ClipMeshTransfer.cs").read_text(encoding="utf-8")
    assert 'private const string Version = "0.2.7";' in ui
    assert 'LocalTransferManagerC.Shared.SetUiVisible(false);' in ui
    assert 'private readonly HashSet<string> visibleDevices' in transfer
    assert '{"visible", uiVisible}' in transfer
    assert 'private void RegisterBack(' in transfer
    assert '/api/clipmesh/v1/register' in transfer
    assert 'if (!serverReady) return;' in transfer
elif system == "Linux":
    gradle = (root / "clipmesh/android/app/build.gradle.kts").read_text(encoding="utf-8")
    runtime = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/BackgroundRuntime.kt").read_text(encoding="utf-8")
    engine = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/LocalTransferEngine.kt").read_text(encoding="utf-8")
    incoming = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/IncomingRequestUi.kt").read_text(encoding="utf-8")
    main = (root / "clipmesh/android/app/src/main/java/dev/clipmesh/MainActivity.kt").read_text(encoding="utf-8")
    assert 'versionCode = 17' in gradle
    assert 'versionName = "0.2.7"' in gradle
    assert 'ClipMesh-ClipboardWatch' in runtime
    assert '650L' in runtime
    assert 'shizuku.hasPermission()' in runtime
    assert 'bridge.captureNowForForeground()' in runtime
    assert 'val visible: Boolean = true' in engine
    assert 'put("visible", uiVisible)' in engine
    assert '/api/clipmesh/v1/register' in engine
    assert 'serverReady.set(true)' in engine
    assert 'if (!serverReady.get()) return' in engine
    assert 'LocalTransferEngine.setUiVisible(true)' in incoming
    assert 'LocalTransferEngine.setUiVisible(false)' in incoming
    assert '\\1        if (BuildConfig.DEBUG)' not in main
    assert 'clipmesh_ci_favorite' in main
else:
    raise AssertionError(f"unsupported platform {system}")

print(f"ClipMesh v0.2.7 background/transfer regression self-test passed on {system}")
