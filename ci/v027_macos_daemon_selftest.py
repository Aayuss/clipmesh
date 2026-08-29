from pathlib import Path
import os
import platform


root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

if system == "Darwin":
    app = (root / "ci/ClipMeshApp.swift").read_text(encoding="utf-8")
    build = (root / "clipmesh/scripts/build-macos.sh").read_text(encoding="utf-8")
    assert 'static func acquireInstanceLock() throws -> Int32?' in app
    assert 'Darwin.flock(descriptor, LOCK_EX | LOCK_NB)' in app
    assert 'static func reclaimStaleDaemonListener() throws' in app
    assert 'return commandMatches && executableMatches' in app
    assert 'ClipMesh left that process untouched' in app
    assert 'try Runtime.reclaimStaleDaemonListener()' in app
    assert 'guard process.isRunning else' in app
    assert '--reclaim-stale-daemon-test' in app
    assert 'CFBundleShortVersionString</key><string>0.2.7' in build
elif system == "Windows":
    ui = (root / "ci/ClipMeshWindows.cs").read_text(encoding="utf-8")
    assert 'private const string Version = "0.2.7";' in ui
elif system == "Linux":
    gradle = (root / "clipmesh/android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 17' in gradle
    assert 'versionName = "0.2.7"' in gradle
else:
    raise AssertionError(f"unsupported platform {system}")

print(f"ClipMesh v0.2.7 daemon ownership self-test passed on {system}")
