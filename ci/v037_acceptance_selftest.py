#!/usr/bin/env python3
from pathlib import Path
import os

root = Path(__file__).resolve().parents[1]
platform = os.environ.get("CLIPMESH_PLATFORM", "")
reconstruct = (root / "ci/reconstruct.py").read_text(encoding="utf-8")
release = (root / "ci/build-android-release.sh").read_text(encoding="utf-8")

# Acceptance hooks must always be opt-in and must never become part of canonical
# release reconstruction.
for forbidden in ("patch-acceptance-dev.py", "patch-acceptance-v2.py"):
    if forbidden in reconstruct:
        raise SystemExit(f"acceptance instrumentation leaked into canonical reconstruction: {forbidden}")

if platform == "Linux":
    debug = root / "clipmesh/android/app/src/debug/java/dev/clipmesh/AcceptanceReceiver.kt"
    main = root / "clipmesh/android/app/src/main/java/dev/clipmesh/AcceptanceReceiver.kt"
    manifest = root / "clipmesh/android/app/src/debug/AndroidManifest.xml"
    engine = root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/LocalTransferEngine.kt"
    incoming = root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/IncomingRequestUi.kt"
    main_ui = root / "clipmesh/android/app/src/main/java/dev/clipmesh/MainActivity.kt"
    file_ui = root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare/FileShareActivity.kt"
    if not debug.is_file():
        raise SystemExit("acceptance receiver missing from Android debug source")
    if main.exists():
        raise SystemExit("acceptance receiver leaked into Android main source")
    checks = {
        debug: (
            "ACTION_SET_FAVORITE", "ACTION_CHECK_FAVORITE", "ACTION_SET_POLICY",
            "ACTION_SET_BACKGROUND_RECEIVE", "ACTION_SEND_GENERATED", "ACTION_RESOLVE_PENDING",
        ),
        manifest: (".AcceptanceReceiver", "android.permission.DUMP"),
        engine: ("devAcceptancePendingRequestIds", "devAcceptanceClearNearby"),
        incoming: ("incoming_policy", "accept.performClick()", "reject.performClick()"),
        main_ui: ("clipboard_nearby_count",),
        file_ui: ("file_nearby_count",),
    }
    for path, needles in checks.items():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                raise SystemExit(f"Android acceptance guard missing: {path}: {needle}")

elif platform == "Darwin":
    app = root / "ci/ClipMeshApp.swift"
    transfer = root / "ci/ClipMeshTransfer.swift"
    checks = {
        app: (
            "--dev-accept-set-favorite", "--dev-accept-command", "--dev-accept-state",
            "--dev-accept-send-files", "ClipMesh.Acceptance.WindowVisible",
            "ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount",
        ),
        transfer: (
            "devAcceptanceSnapshotLines", "devAcceptanceSend(files:",
            "ClipMesh.Acceptance.IncomingPolicy", "alert.buttons[index].performClick",
            "DispatchQueue.main.sync",
        ),
    }
    for path, needles in checks.items():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                raise SystemExit(f"macOS acceptance guard missing: {path}: {needle}")
else:
    raise SystemExit("CLIPMESH_PLATFORM must be Darwin or Linux")

# The release builder already bans the established debug components. The
# AcceptanceReceiver line is required before this self-test is considered green.
if "dev.clipmesh.AcceptanceReceiver" not in release:
    raise SystemExit("release APK guard does not yet ban AcceptanceReceiver")

print(f"ClipMesh comprehensive acceptance isolation self-test passed for {platform}")
