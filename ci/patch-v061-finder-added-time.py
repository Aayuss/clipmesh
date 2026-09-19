from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = __import__("os").environ.get("CLIPMESH_PLATFORM", __import__("platform").system())

def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")

def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=re.S)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")

if SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    build = PROJECT / "scripts/build-macos.sh"

    replace(
        transfer,
        "import Darwin\n",
        """import Darwin

@_silgen_name("clipmesh_set_date_added_now")
private func clipmeshSetDateAddedNow(_ path: UnsafePointer<CChar>) -> Int32
""",
        "macOS Date Added native bridge",
    )

    regex(
        transfer,
        r'''    private func refreshDownloadsFolderRecency\(\) \{.*?\n    \}\n\n    private func destinationURL''',
        r'''    private func refreshDownloadsFolderRecency() {
        let manager = FileManager.default
        let folder = TransferPrefs.outputFolder.standardizedFileURL
        guard manager.fileExists(atPath: folder.path) else { return }

        // Keep ordinary Date Modified fresh as well.
        try? manager.setAttributes([.modificationDate: Date()], ofItemAtPath: folder.path)

        // Finder's Downloads grouping is based on the filesystem Date Added
        // attribute (ATTR_CMN_ADDEDTIME), not merely the directory mtime.
        // Set that metadata directly for the default Downloads/ClipMesh folder.
        let downloads = manager.urls(for: .downloadsDirectory, in: .userDomainMask)[0].standardizedFileURL
        guard folder.deletingLastPathComponent().standardizedFileURL == downloads else { return }

        let result = folder.path.withCString { clipmeshSetDateAddedNow($0) }
        if result != 0 {
            NSLog("ClipMesh could not refresh Finder Date Added for receive folder (errno=%d)", errno)
            return
        }

        // Prompt Finder/Workspace to invalidate any cached metadata for the path.
        NSWorkspace.shared.noteFileSystemChanged(folder.path)
    }

    private func destinationURL''',
        "macOS direct Finder Date Added refresh",
    )

    replace(
        build,
        'command -v swiftc >/dev/null || { echo "Swift compiler is required"; exit 1; }',
        'command -v swiftc >/dev/null || { echo "Swift compiler is required"; exit 1; }\ncommand -v clang >/dev/null || { echo "Clang is required"; exit 1; }',
        "macOS Clang requirement",
    )

    replace(
        build,
        'TRANSFER_SRC="../ci/ClipMeshTransfer.swift"\nDMG_ROOT=',
        'TRANSFER_SRC="../ci/ClipMeshTransfer.swift"\nDATE_ADDED_SRC="../ci/ClipMeshDateAdded.c"\nDMG_ROOT=',
        "macOS Date Added helper source",
    )

    replace(
        build,
        'MAIN_SRC="$OUT/main.swift"\ncp "$LAUNCHER_SRC" "$MAIN_SRC"',
        'MAIN_SRC="$OUT/main.swift"\nDATE_ADDED_OBJ="$OUT/ClipMeshDateAdded.o"\ncp "$LAUNCHER_SRC" "$MAIN_SRC"\nclang -O2 -c "$DATE_ADDED_SRC" -o "$DATE_ADDED_OBJ"',
        "macOS Date Added helper compile",
    )
    replace(
        build,
        'swiftc -O "$MAIN_SRC" "$TRANSFER_SRC"',
        'swiftc -O "$MAIN_SRC" "$TRANSFER_SRC" "$DATE_ADDED_OBJ"',
        "macOS Date Added helper link",
    )
    replace(
        build,
        'rm -f "$MAIN_SRC"',
        'rm -f "$MAIN_SRC" "$DATE_ADDED_OBJ"',
        "macOS Date Added helper cleanup",
    )

print(f"Applied ClipMesh v061 direct Finder Date Added fix on {SYSTEM}")
