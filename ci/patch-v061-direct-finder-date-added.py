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
        r'''    private struct FinderAddedTimeBuffer {
        var added: timespec
    }

    private func setFinderDateAdded(_ date: Date, for path: String) -> Bool {
        var attributes = attrlist()
        attributes.bitmapcount = UInt16(ATTR_BIT_MAP_COUNT)
        attributes.reserved = 0
        attributes.commonattr = attrgroup_t(ATTR_CMN_ADDEDTIME)
        attributes.volattr = 0
        attributes.dirattr = 0
        attributes.fileattr = 0
        attributes.forkattr = 0

        let seconds = date.timeIntervalSince1970
        var buffer = FinderAddedTimeBuffer(
            added: timespec(
                tv_sec: Int(seconds),
                tv_nsec: Int((seconds - floor(seconds)) * 1_000_000_000)
            )
        )
        let size = MemoryLayout<FinderAddedTimeBuffer>.size
        let result = path.withCString { cPath in
            setattrlist(cPath, &attributes, &buffer, size, 0)
        }
        if result != 0 {
            NSLog("ClipMesh could not set Finder Date Added on receive folder (errno=%d)", errno)
            return false
        }
        return true
    }

    private func refreshDownloadsFolderRecency() {
        let manager = FileManager.default
        let folder = TransferPrefs.outputFolder.standardizedFileURL
        guard manager.fileExists(atPath: folder.path) else { return }

        let now = Date()
        try? manager.setAttributes([.modificationDate: now], ofItemAtPath: folder.path)

        // Finder's Downloads grouping uses Date Added (ATTR_CMN_ADDEDTIME), not
        // ordinary modification time. Update that filesystem metadata directly.
        // This changes only metadata on the ClipMesh directory itself: no rename,
        // no copy, no recreation, and no traversal or rewriting of child files.
        guard setFinderDateAdded(now, for: folder.path) else { return }

        // Ask Spotlight to notice the metadata change promptly. Finder can still
        // cache a view briefly, but no expensive re-index of the Downloads tree is
        // requested here.
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/mdimport")
        task.arguments = ["-f", folder.path]
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        try? task.run()
    }

    private func destinationURL''',
        "mac direct Finder Date Added metadata update",
    )

print(f"Applied ClipMesh v061 direct Finder Date Added fix on {SYSTEM}")
