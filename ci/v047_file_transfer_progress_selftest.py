#!/usr/bin/env python3
from pathlib import Path
import os

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", "")

def require(path: Path, *needles: str) -> None:
    text = path.read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, f"missing {needle!r} in {path}"

sizes = [131_072, 3_500_000, 17]
total = sum(sizes)
completed = 0
fractions = [0]
for size in sizes:
    for sent in (min(size, 131_072), size):
        fractions.append(min(1000, ((completed + sent) * 1000) // total))
    completed += size
assert fractions == sorted(fractions), fractions
assert fractions[0] == 0 and fractions[-1] == 1000, fractions

if system == "Linux":
    java = root / "clipmesh/android/app/src/main/java/dev/clipmesh/fileshare"
    require(java / "LocalTransferEngine.kt", "sentBytes: Long", "onProgress(sent)", "automaticallyAccepted", "showAutomaticallySaved")
    require(java / "FileShareActivity.kt", "transferProgress", "selected.clear()", "Continue intentionally remains on File Transfer", "showSending", "cancelSending")
    assert "{ done -> if (done) finish() }" not in (java / "FileShareActivity.kt").read_text(encoding="utf-8")
    require(java / "TransferNotifications.kt", '"File sending progress"', '.setProgress(100, percent.coerceIn(0, 100), false)', '"Saved automatically from $sender"', "FileShareActivity::class.java")
    require(root / "clipmesh/android/app/src/debug/java/dev/clipmesh/DevTestReceiver.kt", "{ _, _, _, _, _ -> }")
    require(root / "dev/android/AcceptanceReceiver.kt", "{ _, _, _, _, _ -> }")
    require(root / "dev/android/AcceptanceReceiverV2.kt", "{ _, _, _, _, _ -> }")
elif system == "Darwin":
    require(root / "ci/ClipMeshTransfer.swift", "progressValue", "countOfBytesSent", "NSProgressIndicator", "self?.files.removeAll(); self?.refreshFiles()")
elif system == "Windows":
    require(root / "ci/ClipMeshTransfer.cs", "Action<int> progressValue", "Action<long> onProgress", "ProgressBar transferProgress", "files.Clear();RefreshFiles()")
    require(root / "ci/ClipMeshWindows.cs", "ProgressBar transferProgress", "transferFiles.Clear(); UpdateTransferFiles()")
else:
    raise AssertionError(f"set CLIPMESH_PLATFORM for this test, got {system!r}")

print(f"v047 file-transfer progress self-test passed on {system}")
