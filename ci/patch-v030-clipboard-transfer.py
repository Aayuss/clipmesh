from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())

# Temporary source probe while the v0.2.8 regression repair is being built.
# The final version of this file replaces these probes with guarded transforms.
def probe(path: Path, needles: list[str], radius: int = 14) -> None:
    if not path.is_file():
        print(f"V030_PROBE missing {path}")
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"V030_PROBE_FILE {path}")
    emitted = set()
    for needle in needles:
        for idx, line in enumerate(lines):
            if needle in line:
                lo = max(0, idx - radius); hi = min(len(lines), idx + radius + 1)
                key = (lo, hi)
                if key in emitted: continue
                emitted.add(key)
                print(f"V030_PROBE_MATCH {needle!r} lines {lo+1}-{hi}")
                for n in range(lo, hi): print(f"{n+1:04d}: {lines[n]}")
                print("V030_PROBE_END")
                break

if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    probe(java / "clipboard/ClipboardBridge.kt", [
        "suppressedFingerprint", "captureAsync", "stableFingerprint", "fun applyRemote", "onLocal(", "captureNowForForeground"
    ], 22)
    probe(java / "fileshare/FileShareActivity.kt", ["nearbyDevices", "pairedNames", "Waiting for"], 18)
    probe(java / "fileshare/LocalTransferEngine.kt", ["DEVICE_TTL_MS", "fun nearbyDevices", "handlePrepare", "isFavorite", "sendUris"], 18)
    probe(java / "fileshare/IncomingRequestUi.kt", ["fun show(request", "Accept", "Reject"], 18)
else:
    probe(project / "apps/desktop/src/clipboard.rs", ["last", "suppress", "fingerprint", "apply", "write"], 12)
    if system == "Darwin":
        probe(root / "ci/ClipMeshApp.swift", ["refreshTransferDevices", "pairedNames", "viewClipboard"], 18)
        probe(root / "ci/ClipMeshTransfer.swift", ["nearbyDevices", "prepare-upload", "isFavorite", "accept"], 18)
    elif system == "Windows":
        probe(root / "ci/ClipMeshWindows.cs", ["RefreshTransferDevices", "pairedTransferNames", "ViewClipboard"], 18)
        probe(root / "ci/ClipMeshTransfer.cs", ["Nearby()", "prepare-upload", "IsFavorite", "accept"], 18)

print(f"Applied ClipMesh v0.2.8 diagnostic probe on {system}")
