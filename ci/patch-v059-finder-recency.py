from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = __import__("os").environ.get("CLIPMESH_PLATFORM", __import__("platform").system())

def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=re.S)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")

if SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    regex(
        transfer,
        r'''    private func refreshDownloadsFolderRecency\(\) \{.*?\n    \}\n\n    private func destinationURL''',
        r'''    private func refreshDownloadsFolderRecency() {
        let manager = FileManager.default
        let folder = TransferPrefs.outputFolder.standardizedFileURL
        guard manager.fileExists(atPath: folder.path) else { return }

        // Always refresh Date Modified for views sorted by modification time.
        try? manager.setAttributes([.modificationDate: Date()], ofItemAtPath: folder.path)

        // Finder's default Downloads grouping is based on Date Added, not Date
        // Modified. Foundation exposes addedToDirectoryDate as read-only; Apple
        // defines it as the time an item was created or renamed into/within its
        // parent. For the default Downloads folder only, do a same-directory
        // POSIX rename out-and-back after the complete receive session closes.
        //
        // This is a directory-entry metadata operation on APFS. It does not copy,
        // rewrite, remove, or recreate any file inside ClipMesh.
        let downloads = manager.urls(for: .downloadsDirectory, in: .userDomainMask)[0].standardizedFileURL
        guard folder.deletingLastPathComponent().standardizedFileURL == downloads else { return }

        let temporary = downloads.appendingPathComponent(".ClipMesh-recency-\(UUID().uuidString)", isDirectory: true)
        let originalPath = folder.path
        let temporaryPath = temporary.path

        let renamedOut = originalPath.withCString { source in
            temporaryPath.withCString { destination in
                Darwin.rename(source, destination)
            }
        }
        guard renamedOut == 0 else {
            NSLog("ClipMesh could not refresh Finder Date Added for receive folder (rename out errno=%d)", errno)
            return
        }

        var restored = false
        for _ in 0..<5 {
            let result = temporaryPath.withCString { source in
                originalPath.withCString { destination in
                    Darwin.rename(source, destination)
                }
            }
            if result == 0 {
                restored = true
                break
            }
            usleep(10_000)
        }

        if !restored {
            NSLog("ClipMesh could not restore receive folder name after Date Added refresh (errno=%d)", errno)
            // Last-resort recovery through FileManager uses the same same-volume
            // directory-entry rename semantics; it still does not copy children.
            try? manager.moveItem(at: temporary, to: folder)
        }
    }

    private func destinationURL''',
        "mac Finder Date Added recency refresh",
    )

print(f"Applied ClipMesh v059 Finder recency fix on {SYSTEM}")
