import Cocoa
import Foundation

struct CommandResult {
    let status: Int32
    let stdout: String
    let stderr: String
}

enum ClipMeshRuntime {
    static var executableDirectory: URL {
        if let executable = Bundle.main.executableURL {
            return executable.deletingLastPathComponent()
        }
        return URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
    }

    static var cliURL: URL {
        executableDirectory.appendingPathComponent("clipmesh-bin")
    }

    static var supportDirectory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("dev.ClipMesh.ClipMesh", isDirectory: true)
    }

    static var configURL: URL {
        supportDirectory.appendingPathComponent("config.json")
    }

    static var logURL: URL {
        supportDirectory.appendingPathComponent("clipmesh.log")
    }

    static func runCLI(_ arguments: [String]) throws -> CommandResult {
        let process = Process()
        process.executableURL = cliURL
        process.arguments = arguments

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        try process.run()
        process.waitUntilExit()

        let stdout = String(data: stdoutPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let stderr = String(data: stderrPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return CommandResult(status: process.terminationStatus, stdout: stdout, stderr: stderr)
    }

    static func initializeIfNeeded() throws {
        try FileManager.default.createDirectory(at: supportDirectory, withIntermediateDirectories: true)
        guard !FileManager.default.fileExists(atPath: configURL.path) else { return }

        let rawName = Host.current().localizedName ?? ProcessInfo.processInfo.hostName
        let name = rawName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Mac" : rawName
        let result = try runCLI(["init", "--name", name])
        guard result.status == 0 else {
            let detail = result.stderr.isEmpty ? result.stdout : result.stderr
            throw NSError(
                domain: "ClipMesh",
                code: Int(result.status),
                userInfo: [NSLocalizedDescriptionKey: "Could not initialize ClipMesh.\n\(detail)"]
            )
        }

        guard FileManager.default.fileExists(atPath: configURL.path) else {
            throw NSError(
                domain: "ClipMesh",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "ClipMesh initialized without creating its configuration file."]
            )
        }
    }

    static func pairingURI() throws -> String {
        let result = try runCLI(["pairing-uri"])
        guard result.status == 0 else {
            let detail = result.stderr.isEmpty ? result.stdout : result.stderr
            throw NSError(
                domain: "ClipMesh",
                code: Int(result.status),
                userInfo: [NSLocalizedDescriptionKey: "Could not read the pairing link.\n\(detail)"]
            )
        }
        return result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

if CommandLine.arguments.contains("--smoke-test") {
    do {
        try ClipMeshRuntime.initializeIfNeeded()
        let status = try ClipMeshRuntime.runCLI(["status"])
        guard status.status == 0 else {
            fputs("ClipMesh status failed: \(status.stderr)\n", stderr)
            exit(1)
        }
        print("ClipMesh macOS first-run smoke test passed")
        exit(0)
    } catch {
        fputs("ClipMesh first-run smoke test failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private var statusLabel: NSTextField!
    private var detailLabel: NSTextField!
    private var statusItem: NSStatusItem?
    private var daemon: Process?
    private var logHandle: FileHandle?
    private var intentionallyStopping = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMenuBar()
        buildWindow()
        showWindow()

        do {
            try ClipMeshRuntime.initializeIfNeeded()
            try startDaemon()
        } catch {
            showFailure(error.localizedDescription)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        intentionallyStopping = true
        daemon?.terminate()
        logHandle?.closeFile()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 350),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "ClipMesh"
        window.isReleasedWhenClosed = false
        window.center()
        window.delegate = self

        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .centerX
        container.spacing = 14
        container.translatesAutoresizingMaskIntoConstraints = false

        let icon = NSImageView()
        icon.image = NSApp.applicationIconImage
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            icon.widthAnchor.constraint(equalToConstant: 92),
            icon.heightAnchor.constraint(equalToConstant: 92)
        ])

        let title = NSTextField(labelWithString: "ClipMesh")
        title.font = NSFont.systemFont(ofSize: 26, weight: .semibold)
        title.alignment = .center

        statusLabel = NSTextField(labelWithString: "Starting ClipMesh…")
        statusLabel.font = NSFont.systemFont(ofSize: 16, weight: .medium)
        statusLabel.alignment = .center

        detailLabel = NSTextField(wrappingLabelWithString: "Private encrypted clipboard sync on your local network.")
        detailLabel.font = NSFont.systemFont(ofSize: 13)
        detailLabel.textColor = .secondaryLabelColor
        detailLabel.alignment = .center
        detailLabel.maximumNumberOfLines = 3
        detailLabel.preferredMaxLayoutWidth = 420

        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.spacing = 10
        buttons.alignment = .centerY

        let pairingButton = NSButton(title: "Copy Pairing Link", target: self, action: #selector(copyPairingLink))
        pairingButton.bezelStyle = .rounded
        pairingButton.keyEquivalent = "p"

        let hideButton = NSButton(title: "Run in Background", target: self, action: #selector(hideWindow))
        hideButton.bezelStyle = .rounded

        let quitButton = NSButton(title: "Quit", target: self, action: #selector(quitApp))
        quitButton.bezelStyle = .rounded

        buttons.addArrangedSubview(pairingButton)
        buttons.addArrangedSubview(hideButton)
        buttons.addArrangedSubview(quitButton)

        container.addArrangedSubview(icon)
        container.addArrangedSubview(title)
        container.addArrangedSubview(statusLabel)
        container.addArrangedSubview(detailLabel)
        container.addArrangedSubview(buttons)

        guard let content = window.contentView else { return }
        content.addSubview(container)
        NSLayoutConstraint.activate([
            container.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            container.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            container.leadingAnchor.constraint(greaterThanOrEqualTo: content.leadingAnchor, constant: 28),
            container.trailingAnchor.constraint(lessThanOrEqualTo: content.trailingAnchor, constant: -28)
        ])
    }

    private func buildMenuBar() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            button.image = NSImage(systemSymbolName: "arrow.left.arrow.right", accessibilityDescription: "ClipMesh")
        }

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Show ClipMesh", action: #selector(showWindowFromMenu), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Copy Pairing Link", action: #selector(copyPairingLink), keyEquivalent: ""))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit ClipMesh", action: #selector(quitApp), keyEquivalent: "q"))
        for item in menu.items { item.target = self }
        item.menu = menu
        statusItem = item
    }

    private func startDaemon() throws {
        if let daemon, daemon.isRunning { return }

        try FileManager.default.createDirectory(at: ClipMeshRuntime.supportDirectory, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: ClipMeshRuntime.logURL.path) {
            FileManager.default.createFile(atPath: ClipMeshRuntime.logURL.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: ClipMeshRuntime.logURL)
        handle.seekToEndOfFile()
        logHandle = handle

        let process = Process()
        process.executableURL = ClipMeshRuntime.cliURL
        process.arguments = ["run"]
        process.standardOutput = handle
        process.standardError = handle
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self else { return }
                if !self.intentionallyStopping {
                    self.statusLabel.stringValue = "ClipMesh stopped"
                    self.statusLabel.textColor = .systemRed
                    self.detailLabel.stringValue = "The background sync process exited with code \(process.terminationStatus). Check \(ClipMeshRuntime.logURL.path)."
                }
            }
        }

        try process.run()
        daemon = process
        statusLabel.stringValue = "ClipMesh is running"
        statusLabel.textColor = .systemGreen
        detailLabel.stringValue = "Clipboard sync is active on this Mac. Close this window or choose Run in Background - ClipMesh will keep running from the menu bar."
    }

    private func showFailure(_ message: String) {
        statusLabel.stringValue = "ClipMesh could not start"
        statusLabel.textColor = .systemRed
        detailLabel.stringValue = message
        NSApp.activate(ignoringOtherApps: true)
    }

    private func showWindow() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func showWindowFromMenu() {
        showWindow()
    }

    @objc private func hideWindow() {
        window.orderOut(nil)
    }

    @objc private func copyPairingLink() {
        do {
            let uri = try ClipMeshRuntime.pairingURI()
            let pasteboard = NSPasteboard.general
            pasteboard.clearContents()
            pasteboard.setString(uri, forType: .string)
            statusLabel.stringValue = "Pairing link copied"
            statusLabel.textColor = .systemBlue
            detailLabel.stringValue = "Paste it into ClipMesh on the device you want to pair. The link contains your private space key, so share it only with a device you trust."
        } catch {
            showFailure(error.localizedDescription)
        }
    }

    @objc private func quitApp() {
        intentionallyStopping = true
        daemon?.terminate()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
