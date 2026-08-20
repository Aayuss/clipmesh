import Cocoa
import Foundation

struct CLIResult {
    let status: Int32
    let output: String
    let error: String
}

struct PeerState {
    let id: String
    let name: String
    let lastSeenMs: UInt64
}

struct UIState {
    let deviceID: String
    let deviceName: String
    let spaceID: String
    let sendEnabled: Bool
    let receiveEnabled: Bool
    let peers: [PeerState]
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

    static func checked(_ arguments: [String], message: String) throws -> String {
        let result = try run(arguments)
        guard result.status == 0 else {
            let detail = result.error.isEmpty ? result.output : result.error
            throw NSError(domain: "ClipMesh", code: Int(result.status), userInfo: [
                NSLocalizedDescriptionKey: "\(message)\n\(detail)"
            ])
        }
        return result.output.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func deviceName() -> String {
        let candidate = Host.current().localizedName ?? ProcessInfo.processInfo.hostName
        let value = candidate.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "Mac" : value
    }

    static func initialize() throws {
        _ = try checked(["init", "--name", deviceName()], message: "Could not initialize ClipMesh.")
    }

    static func verifyReady() throws {
        _ = try checked(["status"], message: "ClipMesh configuration exists, but its encryption key could not be loaded.")
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

            let stamp = Int(Date().timeIntervalSince1970)
            let backup = support.appendingPathComponent("config.unrecoverable-v0.1.1-\(stamp).bak")
            try fileManager.moveItem(at: config, to: backup)
        }

        try initialize()
        try verifyReady()
    }

    static func pairingLink() throws -> String {
        try checked(["pairing-uri"], message: "Could not create the pairing code.")
    }

    static func setName(_ name: String) throws {
        _ = try checked(["set-name", "--name", name], message: "Could not rename this device.")
    }

    static func setSync(send: Bool, receive: Bool) throws {
        _ = try checked([
            "set-sync", "--send", send ? "true" : "false",
            "--receive", receive ? "true" : "false"
        ], message: "Could not save sync settings.")
    }

    static func join(_ uri: String, name: String) throws {
        _ = try checked(["join", uri, "--name", name, "--replace"], message: "Could not join that ClipMesh space.")
    }

    static func createNewSpace(name: String) throws {
        _ = try checked(["new-space", "--name", name], message: "Could not create a new ClipMesh space.")
    }

    static func uiState() throws -> UIState {
        let output = try checked(["ui-state"], message: "Could not read ClipMesh state.")
        var deviceID = ""
        var deviceName = "Mac"
        var spaceID = ""
        var send = true
        var receive = true
        var peers: [PeerState] = []

        for line in output.split(whereSeparator: \ .isNewline) {
            let parts = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            guard let kind = parts.first else { continue }
            switch kind {
            case "DEVICE" where parts.count >= 3:
                deviceID = parts[1]
                deviceName = parts[2]
            case "SPACE" where parts.count >= 2:
                spaceID = parts[1]
            case "SYNC" where parts.count >= 3:
                send = parts[1].lowercased() == "true"
                receive = parts[2].lowercased() == "true"
            case "PEER" where parts.count >= 4:
                peers.append(PeerState(id: parts[1], name: parts[3], lastSeenMs: UInt64(parts[2]) ?? 0))
            default:
                continue
            }
        }

        guard !deviceID.isEmpty, !spaceID.isEmpty else {
            throw NSError(domain: "ClipMesh", code: 1, userInfo: [NSLocalizedDescriptionKey: "ClipMesh returned incomplete device state."])
        }
        return UIState(deviceID: deviceID, deviceName: deviceName, spaceID: spaceID, sendEnabled: send, receiveEnabled: receive, peers: peers)
    }
}

if CommandLine.arguments.contains("--smoke-test") {
    do {
        try Runtime.prepareFirstRun()
        try Runtime.verifyReady()
        _ = try Runtime.uiState()
        print("ClipMesh native macOS first-run smoke test passed")
        exit(0)
    } catch {
        fputs("ClipMesh smoke test failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private var statusLabel: NSTextField!
    private var deviceNameLabel: NSTextField!
    private var deviceIDLabel: NSTextField!
    private var peersStack: NSStackView!
    private var pairPanel: NSStackView!
    private var pairField: NSTextField!
    private var daemon: Process?
    private var logHandle: FileHandle?
    private var statusItem: NSStatusItem?
    private var statusMenu: NSMenu?
    private var quitting = false
    private var latestState: UIState?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildWindow()
        buildStatusItem()
        showWindow()

        do {
            try Runtime.prepareFirstRun()
            try startDaemon()
            refreshHome()
        } catch {
            showError(error.localizedDescription)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        stopDaemon()
        logHandle?.closeFile()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hideWindow()
        return false
    }

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 610),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "ClipMesh"
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 560, height: 560)
        window.center()
        window.delegate = self

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 12
        root.translatesAutoresizingMaskIntoConstraints = false

        let header = NSStackView()
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 10
        let title = NSTextField(labelWithString: "ClipMesh")
        title.font = .systemFont(ofSize: 30, weight: .bold)
        header.addArrangedSubview(title)
        header.addArrangedSubview(spacer())
        let settings = button("Settings", action: #selector(showSettings))
        header.addArrangedSubview(settings)
        root.addArrangedSubview(header)

        statusLabel = NSTextField(labelWithString: "Starting…")
        statusLabel.textColor = .secondaryLabelColor
        statusLabel.font = .systemFont(ofSize: 13)
        root.addArrangedSubview(statusLabel)

        root.addArrangedSubview(separator())
        root.addArrangedSubview(sectionLabel("THIS DEVICE"))

        let deviceRow = NSStackView()
        deviceRow.orientation = .horizontal
        deviceRow.alignment = .centerY
        deviceRow.spacing = 10
        let deviceText = NSStackView()
        deviceText.orientation = .vertical
        deviceText.alignment = .leading
        deviceText.spacing = 2
        deviceNameLabel = NSTextField(labelWithString: "Mac")
        deviceNameLabel.font = .systemFont(ofSize: 20, weight: .semibold)
        deviceIDLabel = NSTextField(labelWithString: "")
        deviceIDLabel.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        deviceIDLabel.textColor = .secondaryLabelColor
        deviceText.addArrangedSubview(deviceNameLabel)
        deviceText.addArrangedSubview(deviceIDLabel)
        deviceRow.addArrangedSubview(deviceText)
        deviceRow.addArrangedSubview(spacer())
        deviceRow.addArrangedSubview(button("Rename", action: #selector(renameDevice)))
        root.addArrangedSubview(deviceRow)

        root.addArrangedSubview(separator())
        let peersHeader = NSStackView()
        peersHeader.orientation = .horizontal
        peersHeader.alignment = .centerY
        peersHeader.addArrangedSubview(sectionLabel("DEVICES"))
        peersHeader.addArrangedSubview(spacer())
        peersHeader.addArrangedSubview(button("Refresh", action: #selector(refreshClicked)))
        root.addArrangedSubview(peersHeader)

        peersStack = NSStackView()
        peersStack.orientation = .vertical
        peersStack.alignment = .leading
        peersStack.spacing = 6
        root.addArrangedSubview(peersStack)

        root.addArrangedSubview(separator())
        root.addArrangedSubview(sectionLabel("QUICK ACTIONS"))
        let quick = NSStackView()
        quick.orientation = .horizontal
        quick.spacing = 9
        quick.addArrangedSubview(button("Copy Pairing Code", action: #selector(copyPairingLink)))
        quick.addArrangedSubview(button("View Clipboard", action: #selector(viewClipboard)))
        quick.addArrangedSubview(button("Pair Device", action: #selector(togglePairPanel)))
        root.addArrangedSubview(quick)

        pairPanel = NSStackView()
        pairPanel.orientation = .vertical
        pairPanel.alignment = .leading
        pairPanel.spacing = 8
        pairPanel.isHidden = true
        pairPanel.addArrangedSubview(sectionLabel("PAIR DEVICE"))
        let hint = NSTextField(wrappingLabelWithString: "Paste a pairing code from another trusted ClipMesh device, or create a new private space.")
        hint.textColor = .secondaryLabelColor
        hint.preferredMaxLayoutWidth = 540
        pairPanel.addArrangedSubview(hint)
        pairField = NSTextField(string: "")
        pairField.placeholderString = "clipmesh://pair?..."
        pairField.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        pairField.translatesAutoresizingMaskIntoConstraints = false
        pairField.widthAnchor.constraint(greaterThanOrEqualToConstant: 530).isActive = true
        pairPanel.addArrangedSubview(pairField)
        let pairActions = NSStackView()
        pairActions.orientation = .horizontal
        pairActions.spacing = 9
        pairActions.addArrangedSubview(button("Join", action: #selector(joinDevice)))
        pairActions.addArrangedSubview(button("Create New", action: #selector(createNewSpace)))
        pairActions.addArrangedSubview(button("Copy My Code", action: #selector(copyPairingLink)))
        pairPanel.addArrangedSubview(pairActions)
        root.addArrangedSubview(pairPanel)

        let privacy = NSTextField(wrappingLabelWithString: "Pairing codes contain the private space key. Only share them directly with devices you trust.")
        privacy.font = .systemFont(ofSize: 11)
        privacy.textColor = .tertiaryLabelColor
        privacy.preferredMaxLayoutWidth = 540
        root.addArrangedSubview(privacy)

        guard let content = window.contentView else { return }
        content.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            root.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            root.topAnchor.constraint(equalTo: content.topAnchor, constant: 24),
            header.widthAnchor.constraint(equalTo: root.widthAnchor),
            deviceRow.widthAnchor.constraint(equalTo: root.widthAnchor),
            peersHeader.widthAnchor.constraint(equalTo: root.widthAnchor)
        ])
    }

    private func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let image = NSImage(systemSymbolName: "arrow.left.arrow.right", accessibilityDescription: "ClipMesh") {
            image.isTemplate = true
            item.button?.image = image
        }
        item.button?.target = self
        item.button?.action = #selector(statusItemClicked(_:))
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])

        let menu = NSMenu()
        let show = NSMenuItem(title: "Show ClipMesh", action: #selector(showFromMenu), keyEquivalent: "")
        show.target = self
        menu.addItem(show)
        let pair = NSMenuItem(title: "Copy Pairing Code", action: #selector(copyPairingLink), keyEquivalent: "")
        pair.target = self
        menu.addItem(pair)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit ClipMesh", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusMenu = menu
        statusItem = item
    }

    private func startDaemon() throws {
        try FileManager.default.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: Runtime.log.path) {
            FileManager.default.createFile(atPath: Runtime.log.path, contents: nil)
        }
        if logHandle == nil {
            let handle = try FileHandle(forWritingTo: Runtime.log)
            handle.seekToEndOfFile()
            logHandle = handle
        }

        let process = Process()
        process.executableURL = Runtime.cli
        process.arguments = ["run"]
        process.standardOutput = logHandle
        process.standardError = logHandle
        process.terminationHandler = { [weak self, weak process] ended in
            DispatchQueue.main.async {
                guard let self, let process, !self.quitting, self.daemon === process else { return }
                self.daemon = nil
                self.statusLabel.stringValue = "Background sync stopped (exit \(ended.terminationStatus))"
                self.statusLabel.textColor = .systemRed
                self.showWindow()
            }
        }
        try process.run()
        daemon = process
        statusLabel.stringValue = "Background sync is running"
        statusLabel.textColor = .secondaryLabelColor
    }

    private func stopDaemon() {
        guard let process = daemon else { return }
        daemon = nil
        if process.isRunning {
            process.terminate()
            process.waitUntilExit()
        }
    }

    private func mutateRuntime(_ operation: () throws -> Void) {
        stopDaemon()
        do {
            try operation()
            try startDaemon()
            refreshHome()
        } catch {
            try? startDaemon()
            showError(error.localizedDescription)
        }
    }

    private func refreshHome() {
        do {
            let state = try Runtime.uiState()
            latestState = state
            deviceNameLabel.stringValue = state.deviceName
            deviceIDLabel.stringValue = "Device ID  \(shortID(state.deviceID))"
            renderPeers(state.peers)
            if daemon?.isRunning == true {
                statusLabel.stringValue = "Background sync is running"
                statusLabel.textColor = .secondaryLabelColor
            }
        } catch {
            showError(error.localizedDescription)
        }
    }

    private func renderPeers(_ peers: [PeerState]) {
        peersStack.arrangedSubviews.forEach {
            peersStack.removeArrangedSubview($0)
            $0.removeFromSuperview()
        }
        if peers.isEmpty {
            let empty = NSTextField(wrappingLabelWithString: "No other devices discovered yet. Keep ClipMesh running on both devices on the same local network, then click Refresh.")
            empty.textColor = .secondaryLabelColor
            empty.preferredMaxLayoutWidth = 540
            peersStack.addArrangedSubview(empty)
            return
        }

        let now = UInt64(max(0, Date().timeIntervalSince1970 * 1000))
        for peer in peers.prefix(8) {
            let row = NSStackView()
            row.orientation = .horizontal
            row.alignment = .centerY
            row.spacing = 8
            let name = NSTextField(labelWithString: peer.name)
            name.font = .systemFont(ofSize: 14, weight: .medium)
            row.addArrangedSubview(name)
            let id = NSTextField(labelWithString: shortID(peer.id))
            id.font = .monospacedSystemFont(ofSize: 10, weight: .regular)
            id.textColor = .tertiaryLabelColor
            row.addArrangedSubview(id)
            row.addArrangedSubview(spacer())
            let online = peer.lastSeenMs > 0 && now >= peer.lastSeenMs && now - peer.lastSeenMs < 90_000
            let stateText = online ? "●  Online" : (peer.lastSeenMs == 0 ? "○  Paired" : "○  Known")
            let state = NSTextField(labelWithString: stateText)
            state.font = .systemFont(ofSize: 12, weight: online ? .medium : .regular)
            state.textColor = online ? .systemGreen : .secondaryLabelColor
            row.addArrangedSubview(state)
            row.translatesAutoresizingMaskIntoConstraints = false
            row.widthAnchor.constraint(greaterThanOrEqualToConstant: 530).isActive = true
            peersStack.addArrangedSubview(row)
        }
        if peers.count > 8 {
            let more = NSTextField(labelWithString: "+ \(peers.count - 8) more known devices")
            more.textColor = .secondaryLabelColor
            peersStack.addArrangedSubview(more)
        }
    }

    private func showWindow() {
        NSApp.setActivationPolicy(.regular)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if window != nil { refreshHome() }
    }

    private func hideWindow() {
        window?.orderOut(nil)
        NSApp.setActivationPolicy(.accessory)
    }

    private func showError(_ message: String) {
        statusLabel?.stringValue = message
        statusLabel?.textColor = .systemRed
        showWindowWithoutRefresh()
    }

    private func showWindowWithoutRefresh() {
        NSApp.setActivationPolicy(.regular)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func statusItemClicked(_ sender: Any?) {
        guard let event = NSApp.currentEvent else { return }
        if event.type == .rightMouseUp {
            if let button = statusItem?.button, let menu = statusMenu {
                menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
            }
        } else {
            showWindow()
        }
    }

    @objc private func showFromMenu() { showWindow() }
    @objc private func refreshClicked() { refreshHome() }

    @objc private func togglePairPanel() {
        pairPanel.isHidden.toggle()
        if !pairPanel.isHidden { pairField.becomeFirstResponder() }
    }

    @objc private func renameDevice() {
        let alert = NSAlert()
        alert.messageText = "Rename this device"
        alert.informativeText = "This name is shown to your other ClipMesh devices."
        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")
        let input = NSTextField(string: latestState?.deviceName ?? Runtime.deviceName())
        input.frame = NSRect(x: 0, y: 0, width: 320, height: 24)
        alert.accessoryView = input
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let name = input.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        mutateRuntime { try Runtime.setName(name) }
    }

    @objc private func showSettings() {
        do { latestState = try Runtime.uiState() } catch { showError(error.localizedDescription); return }
        guard let current = latestState else { return }
        let alert = NSAlert()
        alert.messageText = "ClipMesh Settings"
        alert.informativeText = "These settings apply to background clipboard synchronization."
        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        let send = NSButton(checkboxWithTitle: "Send clipboard", target: nil, action: nil)
        send.state = current.sendEnabled ? .on : .off
        let receive = NSButton(checkboxWithTitle: "Receive clipboard", target: nil, action: nil)
        receive.state = current.receiveEnabled ? .on : .off
        stack.addArrangedSubview(send)
        stack.addArrangedSubview(receive)
        stack.frame = NSRect(x: 0, y: 0, width: 320, height: 60)
        alert.accessoryView = stack
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        mutateRuntime { try Runtime.setSync(send: send.state == .on, receive: receive.state == .on) }
    }

    @objc private func copyPairingLink() {
        do {
            let link = try Runtime.pairingLink()
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(link, forType: .string)
            statusLabel.stringValue = "Pairing code copied"
            statusLabel.textColor = .systemBlue
        } catch {
            showError(error.localizedDescription)
        }
    }

    @objc private func joinDevice() {
        let uri = pairField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !uri.isEmpty else { showError("Paste a ClipMesh pairing code first."); return }
        guard confirmSpaceReplacement(title: "Join this private space?") else { return }
        let name = latestState?.deviceName ?? Runtime.deviceName()
        mutateRuntime { try Runtime.join(uri, name: name) }
    }

    @objc private func createNewSpace() {
        guard confirmSpaceReplacement(title: "Create a new private space?") else { return }
        let name = latestState?.deviceName ?? Runtime.deviceName()
        mutateRuntime { try Runtime.createNewSpace(name: name) }
    }

    private func confirmSpaceReplacement(title: String) -> Bool {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = "This replaces this Mac's current ClipMesh space and known-device list."
        alert.addButton(withTitle: "Continue")
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn
    }

    @objc private func viewClipboard() {
        let pasteboard = NSPasteboard.general
        var lines: [String] = []
        let types = pasteboard.types?.map(\.rawValue) ?? []
        lines.append("Types: " + (types.isEmpty ? "none" : types.joined(separator: ", ")))

        if let text = pasteboard.string(forType: .string), !text.isEmpty {
            lines.append("\nText:\n" + String(text.prefix(16_000)))
        } else if let html = pasteboard.string(forType: .html), !html.isEmpty {
            lines.append("\nHTML:\n" + String(html.prefix(16_000)))
        }

        if let urls = pasteboard.readObjects(forClasses: [NSURL.self], options: nil) as? [URL], !urls.isEmpty {
            lines.append("\nURLs / files:\n" + urls.prefix(20).map(\.absoluteString).joined(separator: "\n"))
        }
        if let image = NSImage(pasteboard: pasteboard) {
            lines.append("\nImage: \(Int(image.size.width)) × \(Int(image.size.height)) points")
        }
        if types.isEmpty && lines.count == 1 { lines = ["Clipboard is empty."] }

        let alert = NSAlert()
        alert.messageText = "Current Clipboard"
        alert.informativeText = String(lines.joined(separator: "\n").prefix(24_000))
        alert.addButton(withTitle: "Done")
        alert.runModal()
    }

    @objc private func quitApp() {
        quitting = true
        stopDaemon()
        NSApp.terminate(nil)
    }

    private func button(_ title: String, action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        button.controlSize = .large
        return button
    }

    private func sectionLabel(_ text: String) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.font = .systemFont(ofSize: 11, weight: .semibold)
        label.textColor = .secondaryLabelColor
        return label
    }

    private func separator() -> NSBox {
        let box = NSBox()
        box.boxType = .separator
        return box
    }

    private func spacer() -> NSView {
        let view = NSView()
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return view
    }

    private func shortID(_ value: String) -> String {
        guard value.count > 13 else { return value }
        return String(value.prefix(8)) + "…" + String(value.suffix(4))
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
