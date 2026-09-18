from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"


def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8")
    updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=flags)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")


if True:
    app = ROOT / "ci/ClipMeshApp.swift"
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    replace(transfer,'    static let favoritesKey = "ClipMesh.FileTransfer.Favorites"','    static let favoritesKey = "ClipMesh.FileTransfer.Favorites"\n    static let outputFolderKey = "ClipMesh.FileTransfer.OutputFolder"',"mac output folder preference key")
    replace(transfer,"    static var favorites: Set<String> {\n        get { Set(UserDefaults.standard.stringArray(forKey: favoritesKey) ?? []) }\n        set { UserDefaults.standard.set(Array(newValue).sorted(), forKey: favoritesKey) }\n    }\n}","""    static var favorites: Set<String> {
        get { Set(UserDefaults.standard.stringArray(forKey: favoritesKey) ?? []) }
        set { UserDefaults.standard.set(Array(newValue).sorted(), forKey: favoritesKey) }
    }

    static var outputFolder: URL {
        get {
            if let path = UserDefaults.standard.string(forKey: outputFolderKey), !path.isEmpty {
                return URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL
            }
            return FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0].appendingPathComponent("ClipMesh", isDirectory: true)
        }
        set { UserDefaults.standard.set(newValue.standardizedFileURL.path, forKey: outputFolderKey) }
    }
}""","mac output folder preference")
    replace(transfer,"    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }","""    var outputFolderURL: URL { TransferPrefs.outputFolder }

    func setOutputFolder(_ url: URL) throws {
        let selected = url.standardizedFileURL
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: selected.path, isDirectory: &isDirectory) {
            guard isDirectory.boolValue else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Choose a folder, not a file."]) }
        } else {
            try FileManager.default.createDirectory(at: selected, withIntermediateDirectories: true)
        }
        guard FileManager.default.isWritableFile(atPath: selected.path) else { throw NSError(domain: "ClipMesh", code: 71, userInfo: [NSLocalizedDescriptionKey: "ClipMesh cannot write to that folder."]) }
        TransferPrefs.outputFolder = selected
    }

    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }""","mac expose output folder")
    regex(transfer,r"    private func refreshDownloadsFolderRecency\(\) \{.*?\n    \}\n\n    private func destinationURL",r'''    private func refreshDownloadsFolderRecency() {
        let folder = TransferPrefs.outputFolder
        guard FileManager.default.fileExists(atPath: folder.path) else { return }
        try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: folder.path)
    }

    private func destinationURL''',"mac metadata-only output recency")
    regex(transfer,r"    private func destinationURL\(for meta: TransferMeta\) throws -> URL \{.*?\n    \}",r'''    private func destinationURL(for meta: TransferMeta) throws -> URL {
        var folder = TransferPrefs.outputFolder
        let mime = meta.mime.lowercased()
        if mime.hasPrefix("image/") { folder.appendPathComponent("images", isDirectory: true) }
        else if mime.hasPrefix("video/") { folder.appendPathComponent("video", isDirectory: true) }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let rawName = (meta.name as NSString).lastPathComponent.trimmingCharacters(in: .whitespacesAndNewlines)
        let safe = rawName.isEmpty ? "file" : String(rawName.prefix(180)).replacingOccurrences(of: ":", with: "_")
        var candidate = folder.appendingPathComponent(safe)
        let ext = candidate.pathExtension
        let stem = candidate.deletingPathExtension().lastPathComponent
        var index = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            let name = ext.isEmpty ? "\(stem) (\(index))" : "\(stem) (\(index)).\(ext)"
            candidate = folder.appendingPathComponent(name)
            index += 1
        }
        return candidate
    }''',"mac destination uses selected output folder")
    replace(app,'        transferStatusLabel = NSTextField(labelWithString: "Looking on this Wi-Fi…"); transferStatusLabel.textColor = .secondaryLabelColor; stack.addArrangedSubview(transferStatusLabel)','''        transferStatusLabel = NSTextField(labelWithString: "Looking on this Wi-Fi…"); transferStatusLabel.textColor = .secondaryLabelColor; stack.addArrangedSubview(transferStatusLabel)
        let outputCard = glassCard(); let outputRow = NSStackView(); outputRow.orientation = .horizontal; outputRow.alignment = .centerY; outputRow.spacing = 12
        let outputText = NSStackView(); outputText.orientation = .vertical; outputText.alignment = .leading; outputText.spacing = 3
        let outputTitle = NSTextField(labelWithString: "Receive folder"); outputTitle.font = .systemFont(ofSize: 13, weight: .semibold)
        let outputPath = NSTextField(labelWithString: LocalTransferManager.shared.outputFolderURL.path); outputPath.textColor = .secondaryLabelColor; outputPath.lineBreakMode = .byTruncatingMiddle
        outputText.addArrangedSubview(outputTitle); outputText.addArrangedSubview(outputPath); outputRow.addArrangedSubview(outputText); outputRow.addArrangedSubview(spacer()); outputRow.addArrangedSubview(closureButton("Choose folder", primary: false) { [weak self, weak outputPath] in self?.chooseOutputFolder(label: outputPath) })
        outputCard.addArrangedSubview(outputRow); outputRow.widthAnchor.constraint(equalTo: outputCard.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(outputCard); outputCard.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true''',"mac receive folder UI")
    replace(app,"    private func chooseTransferFiles() {","""    private func chooseOutputFolder(label: NSTextField?) {
        let panel = NSOpenPanel()
        panel.title = "Choose ClipMesh receive folder"
        panel.prompt = "Use Folder"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = LocalTransferManager.shared.outputFolderURL
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do { try LocalTransferManager.shared.setOutputFolder(url); label?.stringValue = LocalTransferManager.shared.outputFolderURL.path }
        catch { showError(error.localizedDescription) }
    }

    private func chooseTransferFiles() {""","mac output folder chooser")
