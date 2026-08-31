#!/usr/bin/env python3
from pathlib import Path
import os

root = Path(__file__).resolve().parents[1]
platform = os.environ.get("CLIPMESH_PLATFORM", "")
reconstruct = (root / "ci/reconstruct.py").read_text(encoding="utf-8")
release = (root / "ci/build-android-release.sh").read_text(encoding="utf-8")
final_entry = (root / "dev-test-final.sh").read_text(encoding="utf-8")

# Acceptance hooks must always be opt-in and must never become part of canonical
# release reconstruction.
for forbidden in (
    "patch-acceptance-dev.py",
    "patch-acceptance-v2.py",
    "patch-acceptance-v3.py",
    "patch-acceptance-v4.py",
    "patch-acceptance-v5.py",
    "patch-acceptance-chain.py",
):
    if forbidden in reconstruct:
        raise SystemExit(f"acceptance instrumentation leaked into canonical reconstruction: {forbidden}")

# The final physical entrypoint must refuse the exact failure mode that can waste
# several minutes: running stale or locally modified code after a failed pull.
for needle in (
    'status --porcelain --untracked-files=no',
    'fetch --quiet origin main',
    'rev-parse origin/main',
    'Local checkout is behind origin/main',
    'CLIPMESH_ACCEPTANCE_ALLOW_DIRTY',
    'CLIPMESH_ACCEPTANCE_SKIP_REMOTE_CHECK',
):
    if needle not in final_entry:
        raise SystemExit(f"final physical Git precheck guard missing: {needle}")

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
    secrets = root / "clipmesh/apps/desktop/src/secrets.rs"
    checks = {
        app: (
            "--dev-accept-set-favorite", "--dev-accept-command", "--dev-accept-state",
            "--dev-accept-send-files", "acceptance-command.txt", "acceptance-ack.txt",
            "acceptance-incoming-policy.txt", "last_prompt_decision=",
            "dev.ClipMesh.ClipMesh-Acceptance",
            "ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount",
        ),
        transfer: (
            "devAcceptanceSnapshotLines", "devAcceptanceSend(files:",
            "acceptance-incoming-policy.txt", "ClipMesh.Acceptance.LastPromptDecision",
            "alert.buttons[index].performClick(nil)", "DispatchQueue.main.sync",
            "Timer(timeInterval: 0.18",
            "RunLoop.main.add(acceptanceClickTimer, forMode: .modalPanel)",
        ),
        secrets: (
            "ACCEPTANCE-ONLY SECRET BACKEND", "0o700", "0o600",
        ),
    }
    for path, needles in checks.items():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                raise SystemExit(f"macOS acceptance guard missing: {path}: {needle}")

    transfer_text = transfer.read_text(encoding="utf-8")
    if "DispatchQueue.main.asyncAfter(deadline: .now() + 0.18)" in transfer_text:
        raise SystemExit("macOS acceptance prompt auto-click is not attached to the modal run loop")

    # The physical acceptance executable must never call the production macOS
    # Keychain API. Mentions in comments are harmless, so inspect executable API
    # forms rather than rejecting descriptive text.
    secret_text = secrets.read_text(encoding="utf-8")
    for forbidden in ("use keyring::Entry;", "Entry::new(", "set_password("):
        if forbidden in secret_text:
            raise SystemExit(f"macOS acceptance secret backend still uses Keychain API: {forbidden}")
else:
    raise SystemExit("CLIPMESH_PLATFORM must be Darwin or Linux")

# The release builder already bans the established debug components. The
# AcceptanceReceiver line is required before this self-test is considered green.
if "dev.clipmesh.AcceptanceReceiver" not in release:
    raise SystemExit("release APK guard does not yet ban AcceptanceReceiver")

print(f"ClipMesh comprehensive acceptance isolation self-test passed for {platform}")
