from pathlib import Path
import platform
import re

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = platform.system()

if system == "Linux":
    user = project / "android/app/src/main/java/dev/clipmesh/shizuku/ClipboardUserService.kt"
    text = user.read_text(encoding="utf-8")
    text = text.replace("import android.content.Context\n", "")
    text = text.replace(
        "class ClipboardUserService private constructor(private val serviceContext: Context?) : IClipboardUserService.Stub() {\n"
        "    constructor() : this(null)\n"
        "    constructor(context: Context) : this(context.applicationContext)",
        "class ClipboardUserService : IClipboardUserService.Stub() {",
    )
    replacement = r'''    override fun copyPrimaryClipItemToFile(index: Int, destination: ParcelFileDescriptor): Boolean {
        val clip = lastClip ?: (invokeClipboard("getPrimaryClip") as? ClipData) ?: return false
        if (index !in 0 until clip.itemCount) return false
        val uri = clip.getItemAt(index).uri ?: return false
        return readUriAsShell(uri, destination) || readUriWithResolver(uri, destination)
    }

    private fun readUriAsShell(uri: Uri, destination: ParcelFileDescriptor): Boolean = runCatching {
        val process = ProcessBuilder("/system/bin/content", "read", "--uri", uri.toString())
            .redirectErrorStream(false)
            .start()
        var total = 0L
        ParcelFileDescriptor.dup(destination.fileDescriptor).use { duplicate ->
            process.inputStream.use { input ->
                FileOutputStream(duplicate.fileDescriptor).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        total += n
                        if (total > MAX_ITEM_BYTES) {
                            process.destroyForcibly()
                            return@runCatching false
                        }
                        output.write(buffer, 0, n)
                    }
                    output.flush()
                }
            }
        }
        process.waitFor() == 0 && total > 0L
    }.getOrDefault(false)

    private fun readUriWithResolver(uri: Uri, destination: ParcelFileDescriptor): Boolean = runCatching {
        val resolver = application()?.contentResolver ?: return@runCatching false
        resolver.openInputStream(uri)?.use { input ->
            ParcelFileDescriptor.dup(destination.fileDescriptor).use { duplicate ->
                FileOutputStream(duplicate.fileDescriptor).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        total += n
                        if (total > MAX_ITEM_BYTES) return@runCatching false
                        output.write(buffer, 0, n)
                    }
                    output.flush()
                    return@runCatching total > 0L
                }
            }
        }
        false
    }.getOrDefault(false)

    override fun setPrimaryClipText'''
    text, count = re.subn(
        r'''    override fun copyPrimaryClipItemToFile\(index: Int, destination: ParcelFileDescriptor\): Boolean \{.*?    override fun setPrimaryClipText''',
        lambda _m: replacement,
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("Could not repair ClipboardUserService copy method")
    for required in (
        "class ClipboardUserService : IClipboardUserService.Stub()",
        'ProcessBuilder("/system/bin/content", "read", "--uri"',
        "override fun setPrimaryClipText",
        "override fun destroy()",
    ):
        if required not in text:
            raise SystemExit(f"Android hotfix guard missing: {required}")
    user.write_text(text, encoding="utf-8")

elif system == "Darwin":
    app = root / "ci/ClipMeshApp.swift"
    text = app.read_text(encoding="utf-8")

    callback = r'''    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where url.scheme == "clipmesh-share" {
            guard
                let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
                let manifest = components.queryItems?.first(where: { $0.name == "manifest" })?.value
            else { continue }
            let manifestURL = URL(fileURLWithPath: manifest)
            guard let contents = try? String(contentsOf: manifestURL, encoding: .utf8) else { continue }
            let files = contents
                .split(separator: "\n")
                .map { URL(fileURLWithPath: String($0)) }
                .filter { FileManager.default.fileExists(atPath: $0.path) }
            try? FileManager.default.removeItem(at: manifestURL)
            if !files.isEmpty { TransferChooserController.shared.show(files: files) }
        }
    }

    func applicationWillTerminate'''
    text, count = re.subn(
        r'''    func application\(_ application: NSApplication, open urls: \[URL\]\) \{.*?    func applicationWillTerminate''',
        lambda _m: callback,
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("Could not repair macOS Share URL callback")

    clipboard = r'''    @objc private func viewClipboard() {
        let pasteboard = NSPasteboard.general
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 560, height: 500),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        panel.title = "Clipboard"
        panel.appearance = NSAppearance(named: .darkAqua)
        panel.titlebarAppearsTransparent = true

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 12
        root.translatesAutoresizingMaskIntoConstraints = false
        let background = NSView()
        background.wantsLayer = true
        background.layer?.backgroundColor = NSColor(calibratedRed: 18/255, green: 17/255, blue: 16/255, alpha: 1).cgColor
        panel.contentView = background
        background.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: background.leadingAnchor, constant: 24),
            root.trailingAnchor.constraint(equalTo: background.trailingAnchor, constant: -24),
            root.topAnchor.constraint(equalTo: background.topAnchor, constant: 24)
        ])

        let title = NSTextField(labelWithString: "Clipboard")
        title.font = .systemFont(ofSize: 26, weight: .bold)
        root.addArrangedSubview(title)

        if let image = NSImage(pasteboard:pasteboard) {
            let kind = NSTextField(labelWithString: "IMAGE")
            kind.textColor = NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 1)
            kind.font = .systemFont(ofSize: 11, weight: .bold)
            root.addArrangedSubview(kind)
            let imageView = NSImageView()
            imageView.image = image
            imageView.imageScaling = .scaleProportionallyUpOrDown
            imageView.wantsLayer = true
            imageView.layer?.cornerRadius = 16
            root.addArrangedSubview(imageView)
            imageView.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
            imageView.heightAnchor.constraint(equalToConstant: 330).isActive = true
        } else if let value = pasteboard.string(forType: .string), !value.isEmpty {
            let kind = NSTextField(labelWithString: "TEXT")
            kind.textColor = NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 1)
            root.addArrangedSubview(kind)
            let field = NSTextField(wrappingLabelWithString: String(value.prefix(16_000)))
            field.isSelectable = true
            field.preferredMaxLayoutWidth = 500
            root.addArrangedSubview(field)
        } else if let urls = pasteboard.readObjects(
            forClasses: [NSURL.self],
            options: [.urlReadingFileURLsOnly: true]
        ) as? [URL], !urls.isEmpty {
            let kind = NSTextField(labelWithString: "FILES")
            kind.textColor = NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 1)
            root.addArrangedSubview(kind)
            root.addArrangedSubview(NSTextField(
                wrappingLabelWithString: urls.prefix(30).map(\.lastPathComponent).joined(separator: "\n")
            ))
        } else {
            root.addArrangedSubview(NSTextField(labelWithString: "Clipboard is empty."))
        }

        clipboardWindow = panel
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func quitApp'''
    text, count = re.subn(
        r'''    @objc private func viewClipboard\(\) \{.*?    @objc private func quitApp''',
        lambda _m: clipboard,
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("Could not repair macOS clipboard preview")
    for required in (
        'split(separator: "\\n")',
        "NSImage(pasteboard:pasteboard)",
        "imageView.imageScaling = .scaleProportionallyUpOrDown",
    ):
        if required not in text:
            raise SystemExit(f"macOS hotfix guard missing: {required}")
    app.write_text(text, encoding="utf-8")

    build = project / "scripts/build-macos.sh"
    build_text = build.read_text(encoding="utf-8")
    old_callback = 'completionHandler:^(id<NSSecureCoding> value,NSError*e)'
    new_callback = 'completionHandler:^(id value,NSError*e)'
    if old_callback not in build_text:
        raise SystemExit("macOS Share extension callback anchor missing")
    build.write_text(build_text.replace(old_callback, new_callback, 1), encoding="utf-8")

elif system == "Windows":
    pass
else:
    raise SystemExit(f"Unsupported v0.2.1 hotfix platform: {system}")

print(f"Applied ClipMesh v0.2.1 compile hotfix for {system}")
