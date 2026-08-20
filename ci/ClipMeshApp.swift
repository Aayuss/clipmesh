import Cocoa
import Foundation

struct CLIResult {
    let status: Int32
    let output: String
    let error: String
}

enum Runtime {
    static let fileManager = FileManager.default

    static var executableDirectory: URL {
        if let executable = Bundle.main.executableURL {
            return executable.deletingLastPathComponent()
        }
        return URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
    }

    static var cli: URL { executableDirectory.appendingPathComponent("clipmesh-bin") }

    static var support: URL {
        fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("dev.ClipMesh.ClipMesh", isDirectory: true)
    }

    static var config: URL { support.appendingPathComponent("config.json") }
    static var log: URL { support.appendingPathComponent("clipmesh.log") }

    static func run(_ arguments: [String]) throws -> CLIResult {
        let process = Process()
        process.executableURL = cli
        process.arguments = arguments
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        process.waitUntilExit()
        return CLIResult(
            status: process.terminationStatus,
            output: String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "",
            error: String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        )
    }

    static func deviceName() -> String {
        let candidate = Host.current().localizedName ?? ProcessInfo.processInfo.hostName
        let value = candidate.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "Mac" : value
    }

    static func initialize() throws {
        let result = try run(["init", "--name", deviceName()])
        guard result.status == 0 else {
            let detail = result.error.isEmpty ? result.output : result.error
            throw NSError(domain: "ClipMesh", code: Int(result.status), userInfo: [
                NSLocalizedDescriptionKey: "Could not initialize ClipMesh.\n\(detail)"
            ])
        }
    }

    static func verifyReady() throws {
        let result = try run(["status"])
        guard result.status == 0 else {
            let detail = result.error.isEmpty ? result.output : result.error
            throw NSError(domain: "ClipMesh", code: Int(result.status), userInfo: [
                NSLocalizedDescriptionKey: "ClipMesh configuration exists, but its encryption key could not be loaded.\n\(detail)"
            ])
        }
    }

    static func prepareFirstRun() throws {
        try fileManager.createDirectory(at: support, withIntermediateDirectories: true)

        if fileManager.fileExists(atPath: config.path) {
            let status = try run(["status"])
            if status.status == 0 { return }

            let detail = status.error + "\n" + status.output
            let missingKey = detail.localizedCaseInsensitiveContains("No matching entry found in secure storage") ||
                detail.localizedCaseInsensitiveContains("read space key from OS keyring")

            guard missingKey else {
                throw NSError(domain: "ClipMesh", code: Int(status.status), userInfo: [
                    NSLocalizedDescriptionKey: "ClipMesh could not read its existing configuration.\n\(detail)"
                ])
            }

            // v0.1.1 accidentally used keyring's in-memory mock backend, so config.json
            // survived but the encryption key did not. Preserve that unusable config and
            // create a new real Keychain-backed space instead of failing forever.
            let stamp = Int(Date().timeIntervalSince1970)
            let backup = support.appendingPathComponent("config.unrecoverable-v0.1.1-\(stamp).bak")
            try fileManager.moveItem(at: config, to: backup)
        }

        try initialize()
        try verifyReady()
    }

    static func pairingLink() throws -> String {
        let result = try run(["pairing-uri"])
        guard result.status == 0 else {
            let detail = result.error.isEmpty ? result.output : result.error
            throw NSError(domain: "ClipMesh", code: Int(result.status), userInfo: [
                NSLocalizedDescriptionKey: "Could not create the pairing link.\n\(detail)"
            ])
        }
        return result.output.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

if CommandLine.arguments.contains("--smoke-test") {
    do {
        try Runtime.prepareFirstRun()
        try Runtime.verifyReady()
        print("ClipMesh native macOS first-run smoke test passed")
        exit(0)
    } catch {
        fputs("ClipMesh smoke test failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var status: NSTextField!
    private var detail: NSTextField!
    private var daemon: Process?
    private var logHandle: FileHandle?
    private var statusItem: NSStatusItem?
    private var quitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildWindow()
        buildStatusItem()
        showWindow()

        do {
            try Runtime.prepareFirstRun()
            try startDaemon()
        } catch {
            showError(error.localizedDescription)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        if daemon?.isRunning == true { daemon?.terminate() }
        logHandle?.closeFile()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 510, height: 360),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "ClipMesh"
        window.isReleasedWhenClosed = false
        window.center()

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false

        let icon = NSImageView(image: NSApp.applicationIconImage)
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.translatesAutoresizingMaskIntoConstraints = false
        icon.widthAnchor.constraint(equalToConstant: 96).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 96).isActive = true

        let title = NSTextField(labelWithString: "ClipMesh")
        title.font = .systemFont(ofSize: 27, weight: .semibold)

        status = NSTextField(labelWithString: "Starting…")
        status.font = .systemFont(ofSize: 16, weight: .medium)

        detail = NSTextField(wrappingLabelWithString: "Private encrypted clipboard sync on your local network.")
        detail.alignment = .center
        detail.textColor = .secondaryLabelColor
        detail.maximumNumberOfLines = 4
        detail.preferredMaxLayoutWidth = 430

        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.spacing = 10
        let pair = NSButton(title: "Copy Pairing Link", target: self, action: #selector(copyPairingLink))
        let background = NSButton(title: "Run in Background", target: self, action: #selector(hideWindow))
        let quit = NSButton(title: "Quit", target: self, action: #selector(quitApp))
        buttons.addArrangedSubview(pair)
        buttons.addArrangedSubview(background)
        buttons.addArrangedSubview(quit)

        [icon, title, status, detail, buttons].forEach { stack.addArrangedSubview($0) }
        guard let content = window.contentView else { return }
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            stack.leadingAnchor.constraint(greaterThanOrEqualTo: content.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: content.trailingAnchor, constant: -28)
        ])
    }

    private func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "arrow.left.arrow.right", accessibilityDescription: "ClipMesh")
        let menu = NSMenu()
        let show = NSMenuItem(title: "Show ClipMesh", action: #selector(showFromMenu), keyEquivalent: "")
        show.target = self
        menu.addItem(show)
        let pair = NSMenuItem(title: "Copy Pairing Link", action: #selector(copyPairingLink), keyEquivalent: "")
        pair.target = self
        menu.addItem(pair)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit ClipMesh", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        item.menu = menu
        statusItem = item
    }

    private func startDaemon() throws {
        try FileManager.default.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: Runtime.log.path) {
            FileManager.default.createFile(atPath: Runtime.log.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: Runtime.log)
        handle.seekToEndOfFile()
        logHandle = handle

        let process = Process()
        process.executableURL = Runtime.cli
        process.arguments = ["run"]
        process.standardOutput = handle
        process.standardError = handle
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self, !self.quitting else { return }
                self.status.stringValue = "ClipMesh stopped"
                self.status.textColor = .systemRed
                self.detail.stringValue = "The sync engine exited with code \(process.terminationStatus). Log: \(Runtime.log.path)"
                self.showWindow()
            }
        }
        try process.run()
        daemon = process

        status.stringValue = "ClipMesh is running"
        status.textColor = .systemGreen
        detail.stringValue = "Clipboard sync is active. You can close this window - ClipMesh keeps running from the menu bar."
    }

    private func showWindow() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func showError(_ message: String) {
        status.stringValue = "ClipMesh could not start"
        status.textColor = .systemRed
        detail.stringValue = message
        showWindow()
    }

    @objc private func showFromMenu() { showWindow() }
    @objc private func hideWindow() { window.orderOut(nil) }

    @objc private func copyPairingLink() {
        do {
            let link = try Runtime.pairingLink()
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(link, forType: .string)
            status.stringValue = "Pairing link copied"
            status.textColor = .systemBlue
            detail.stringValue = "Paste it into ClipMesh on the device you trust. The link contains the private space key, so do not share it publicly."
        } catch {
            showError(error.localizedDescription)
        }
    }

    @objc private func quitApp() {
        quitting = true
        if daemon?.isRunning == true { daemon?.terminate() }
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
