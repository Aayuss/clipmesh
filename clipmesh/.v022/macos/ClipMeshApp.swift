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

    static func resetIdentity(name: String) throws {
        _ = try checked(["reset", "--name", name], message: "Could not reset ClipMesh pairing.")
    }

    static func uiState() throws -> UIState {
        let output = try checked(["ui-state"], message: "Could not read ClipMesh state.")
        var deviceID = ""
        var deviceName = "Mac"
        var spaceID = ""
        var send = true
        var receive = true
        var peers: [PeerState] = []

        for line in output.split(whereSeparator: { $0.isNewline }) {
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
        try TransferSelfTest.run()
        print("ClipMesh native macOS first-run + transfer UI smoke test passed")
        exit(0)
    } catch {
        fputs("ClipMesh smoke test failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}


private final class CMClosureButton: NSButton {
    private var closure: (() -> Void)?
    convenience init(_ title: String, handler: @escaping () -> Void) {
        self.init(frame: .zero)
        self.title = title
        self.closure = handler
        self.target = self
        self.action = #selector(fire)
    }
    @objc private func fire() { closure?() }
}

private final class CMFlippedView: NSView { override var isFlipped: Bool { true } }

private final class CMFileDropView: NSView {
    var onFiles: (([URL]) -> Void)?
    private var active = false { didSet { needsDisplay = true } }
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        registerForDraggedTypes([.fileURL, .init(NSFilenamesPboardType)])
        wantsLayer = true
        layer?.cornerRadius = 20
    }
    required init?(coder: NSCoder) { super.init(coder: coder) }
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        active = true
        return .copy
    }
    override func draggingExited(_ sender: NSDraggingInfo?) { active = false }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        active = false
        let urls = (sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        let files = urls.filter { url in var isDir: ObjCBool = false; return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir) && !isDir.boolValue }
        guard !files.isEmpty else { return false }
        onFiles?(files)
        return true
    }
    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let fill = active ? NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 0.14) : NSColor(calibratedWhite: 1, alpha: 0.055)
        fill.setFill(); NSBezierPath(roundedRect: bounds, xRadius: 20, yRadius: 20).fill()
        let stroke = active ? NSColor(calibratedRed: 244/255, green: 169/255, blue: 78/255, alpha: 0.9) : NSColor(calibratedWhite: 1, alpha: 0.12)
        stroke.setStroke(); let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 20, yRadius: 20); path.lineWidth = 1; path.stroke()
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
    private var clipboardPanel: NSStackView?
    private var filePanel: NSStackView?
    private var clipboardWindow: NSWindow?
    private var contentHost: NSView!
    private var navButtons: [NSButton] = []
    private var pages: [NSView] = []
    private var selectedTab = 0
    private var clipboardPreviewStack: NSStackView!
    private var transferDeviceStack: NSStackView!
    private var transferFileLabel: NSTextField!
    private var transferStatusLabel: NSTextField!
    private var transferFiles: [URL] = []
    private var transferTimer: Timer?
    private var sendSwitch: NSSwitch!
    private var receiveSwitch: NSSwitch!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMainMenu()
        buildWindow()
        buildStatusItem()
        NSApp.servicesProvider = self
        NSUpdateDynamicServices()
        registerShareExtension()
        LocalTransferManager.shared.incomingPrompt = { sender, files in
            TransferDialogs.ask(sender: sender, files: files)
        }
        LocalTransferManager.shared.start(aliasProvider: { [weak self] in
            self?.latestState?.deviceName ?? Runtime.deviceName()
        })
        showWindow()

        do {
            try Runtime.prepareFirstRun()
            try startDaemon()
            refreshHome()
        } catch {
            showError(error.localizedDescription)
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
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

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        transferTimer?.invalidate()
        LocalTransferManager.shared.stop()
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
            contentRect: NSRect(x: 0, y: 0, width: 940, height: 680),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "ClipMesh"
        window.appearance = NSAppearance(named: .darkAqua)
        window.titlebarAppearsTransparent = true
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 760, height: 560)
        window.center(); window.delegate = self

        let root = NSView(); root.wantsLayer = true
        root.layer?.backgroundColor = NSColor(calibratedRed: 18/255, green: 17/255, blue: 16/255, alpha: 1).cgColor
        window.contentView = root

        let sidebar = NSStackView(); sidebar.orientation = .vertical; sidebar.alignment = .leading; sidebar.spacing = 8; sidebar.edgeInsets = NSEdgeInsets(top: 28, left: 18, bottom: 22, right: 18); sidebar.translatesAutoresizingMaskIntoConstraints = false; sidebar.wantsLayer = true; sidebar.layer?.backgroundColor = NSColor(calibratedWhite: 1, alpha: 0.045).cgColor
        let logo = NSTextField(labelWithString: "ClipMesh"); logo.font = .systemFont(ofSize: 25, weight: .bold); logo.textColor = .labelColor; sidebar.addArrangedSubview(logo)
        let sub = NSTextField(labelWithString: "PRIVATE • LOCAL"); sub.font = .systemFont(ofSize: 9, weight: .semibold); sub.textColor = .tertiaryLabelColor; sidebar.addArrangedSubview(sub)
        sidebar.setCustomSpacing(28, after: sub)
        let navItems: [(String, Selector)] = [("Clipboard", #selector(showClipboardTab)), ("File transfer", #selector(showTransferTab)), ("Settings", #selector(showSettingsTab))]
        for (title, selector) in navItems {
            let b = NSButton(title: title, target: self, action: selector); b.isBordered = false; b.alignment = .left; b.font = .systemFont(ofSize: 14, weight: .semibold); b.contentTintColor = .secondaryLabelColor; b.wantsLayer = true; b.layer?.cornerRadius = 12; b.translatesAutoresizingMaskIntoConstraints = false; b.heightAnchor.constraint(equalToConstant: 46).isActive = true; b.widthAnchor.constraint(equalToConstant: 174).isActive = true; sidebar.addArrangedSubview(b); navButtons.append(b)
        }
        sidebar.addArrangedSubview(spacer())
        let foot = NSTextField(wrappingLabelWithString: "Clipboard sync stays encrypted. File transfer stays on your LAN."); foot.font = .systemFont(ofSize: 10); foot.textColor = .tertiaryLabelColor; foot.preferredMaxLayoutWidth = 170; sidebar.addArrangedSubview(foot)

        contentHost = NSView(); contentHost.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(sidebar); root.addSubview(contentHost)
        NSLayoutConstraint.activate([
            sidebar.leadingAnchor.constraint(equalTo: root.leadingAnchor), sidebar.topAnchor.constraint(equalTo: root.topAnchor), sidebar.bottomAnchor.constraint(equalTo: root.bottomAnchor), sidebar.widthAnchor.constraint(equalToConstant: 210),
            contentHost.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor), contentHost.trailingAnchor.constraint(equalTo: root.trailingAnchor), contentHost.topAnchor.constraint(equalTo: root.topAnchor), contentHost.bottomAnchor.constraint(equalTo: root.bottomAnchor)
        ])

        pages = [buildClipboardPage(), buildTransferPage(), buildSettingsPage()]
        for page in pages { page.translatesAutoresizingMaskIntoConstraints = false; contentHost.addSubview(page); NSLayoutConstraint.activate([page.leadingAnchor.constraint(equalTo: contentHost.leadingAnchor), page.trailingAnchor.constraint(equalTo: contentHost.trailingAnchor), page.topAnchor.constraint(equalTo: contentHost.topAnchor), page.bottomAnchor.constraint(equalTo: contentHost.bottomAnchor)]) }
        selectTab(0, animated: false)
    }

    private func makePage(title: String, subtitle: String) -> (NSScrollView, NSStackView) {
        let document = CMFlippedView(); document.translatesAutoresizingMaskIntoConstraints = false
        let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 14; stack.edgeInsets = NSEdgeInsets(top: 30, left: 30, bottom: 34, right: 30); stack.translatesAutoresizingMaskIntoConstraints = false
        document.addSubview(stack)
        let scroll = NSScrollView(); scroll.drawsBackground = false; scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true; scroll.documentView = document
        NSLayoutConstraint.activate([
            document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
            stack.leadingAnchor.constraint(equalTo: document.leadingAnchor), stack.trailingAnchor.constraint(equalTo: document.trailingAnchor), stack.topAnchor.constraint(equalTo: document.topAnchor), stack.bottomAnchor.constraint(equalTo: document.bottomAnchor),
        ])
        let h = NSTextField(labelWithString: title); h.font = .systemFont(ofSize: 31, weight: .bold); stack.addArrangedSubview(h)
        let sh = NSTextField(labelWithString: subtitle); sh.font = .systemFont(ofSize: 13); sh.textColor = .secondaryLabelColor; stack.addArrangedSubview(sh); stack.setCustomSpacing(20, after: sh)
        return (scroll, stack)
    }

    private func glassCard() -> NSStackView {
        let card = NSStackView(); card.orientation = .vertical; card.alignment = .leading; card.spacing = 10; card.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18); card.wantsLayer = true; card.layer?.cornerRadius = 22; card.layer?.backgroundColor = NSColor(calibratedWhite: 1, alpha: 0.065).cgColor; card.layer?.borderWidth = 1; card.layer?.borderColor = NSColor(calibratedWhite: 1, alpha: 0.11).cgColor; card.translatesAutoresizingMaskIntoConstraints = false; return card
    }

    private func buildClipboardPage() -> NSView {
        let (scroll, stack) = makePage(title: "Clipboard", subtitle: "Instant encrypted sync between your paired devices")
        statusLabel = NSTextField(labelWithString: "Starting…"); statusLabel.textColor = .secondaryLabelColor; statusLabel.font = .systemFont(ofSize: 12); stack.addArrangedSubview(statusLabel)
        let preview = glassCard(); let ph = NSStackView(); ph.orientation = .horizontal; ph.alignment = .centerY; let ptitle = NSTextField(labelWithString: "Current clipboard"); ptitle.font = .systemFont(ofSize: 18, weight: .semibold); ph.addArrangedSubview(ptitle); ph.addArrangedSubview(spacer()); ph.addArrangedSubview(closureButton("Refresh", primary: false) { [weak self] in self?.refreshClipboardPreviewInline() }); preview.addArrangedSubview(ph); ph.widthAnchor.constraint(equalTo: preview.widthAnchor, constant: -36).isActive = true
        clipboardPreviewStack = NSStackView(); clipboardPreviewStack.orientation = .vertical; clipboardPreviewStack.alignment = .leading; clipboardPreviewStack.spacing = 9; preview.addArrangedSubview(clipboardPreviewStack); clipboardPreviewStack.widthAnchor.constraint(equalTo: preview.widthAnchor, constant: -36).isActive = true
        stack.addArrangedSubview(preview); preview.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        let device = glassCard(); device.addArrangedSubview(sectionLabel("THIS DEVICE")); let row = NSStackView(); row.orientation = .horizontal; row.alignment = .centerY; let text = NSStackView(); text.orientation = .vertical; text.alignment = .leading; deviceNameLabel = NSTextField(labelWithString: "Mac"); deviceNameLabel.font = .systemFont(ofSize: 20, weight: .semibold); deviceIDLabel = NSTextField(labelWithString: ""); deviceIDLabel.font = .monospacedSystemFont(ofSize: 11, weight: .regular); deviceIDLabel.textColor = .secondaryLabelColor; text.addArrangedSubview(deviceNameLabel); text.addArrangedSubview(deviceIDLabel); row.addArrangedSubview(text); row.addArrangedSubview(spacer()); device.addArrangedSubview(row); row.widthAnchor.constraint(equalTo: device.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(device); device.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        let peers = glassCard(); let peersHeader = NSStackView(); peersHeader.orientation = .horizontal; peersHeader.alignment = .centerY; peersHeader.addArrangedSubview(sectionLabel("PAIRED DEVICES")); peersHeader.addArrangedSubview(spacer()); peersHeader.addArrangedSubview(closureButton("Refresh", primary: false) { [weak self] in self?.refreshHome() }); peers.addArrangedSubview(peersHeader); peersHeader.widthAnchor.constraint(equalTo: peers.widthAnchor, constant: -36).isActive = true; peersStack = NSStackView(); peersStack.orientation = .vertical; peersStack.alignment = .leading; peersStack.spacing = 8; peers.addArrangedSubview(peersStack); peersStack.widthAnchor.constraint(equalTo: peers.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(peers); peers.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
        return scroll
    }

    private func buildTransferPage() -> NSView {
        let (scroll, stack) = makePage(title: "File transfer", subtitle: "LocalSend-style nearby transfer on this Wi-Fi")
        let drop = CMFileDropView(); drop.translatesAutoresizingMaskIntoConstraints = false; drop.heightAnchor.constraint(equalToConstant: 150).isActive = true; drop.onFiles = { [weak self] urls in self?.transferFiles = urls; self?.updateTransferSelection(); self?.refreshTransferDevices() }
        let dropStack = NSStackView(); dropStack.orientation = .vertical; dropStack.alignment = .centerX; dropStack.spacing = 7; dropStack.translatesAutoresizingMaskIntoConstraints = false; let dropTitle = NSTextField(labelWithString: "Drop files here"); dropTitle.font = .systemFont(ofSize: 20, weight: .semibold); let dropSub = NSTextField(labelWithString: "or choose them with Finder"); dropSub.textColor = .secondaryLabelColor; dropStack.addArrangedSubview(dropTitle); dropStack.addArrangedSubview(dropSub); dropStack.addArrangedSubview(closureButton("Choose files", primary: true) { [weak self] in self?.chooseTransferFiles() }); drop.addSubview(dropStack); NSLayoutConstraint.activate([dropStack.centerXAnchor.constraint(equalTo: drop.centerXAnchor), dropStack.centerYAnchor.constraint(equalTo: drop.centerYAnchor)]); stack.addArrangedSubview(drop); drop.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
        transferFileLabel = NSTextField(labelWithString: "No files selected"); transferFileLabel.textColor = .secondaryLabelColor; stack.addArrangedSubview(transferFileLabel)

        let nearby = glassCard(); let nh = NSStackView(); nh.orientation = .horizontal; nh.alignment = .centerY; let nt = NSTextField(labelWithString: "Nearby devices"); nt.font = .systemFont(ofSize: 19, weight: .semibold); nh.addArrangedSubview(nt); nh.addArrangedSubview(spacer()); nh.addArrangedSubview(closureButton("Rescan", primary: false) { LocalTransferManager.shared.discoverNow(); self.refreshTransferDevices() }); nearby.addArrangedSubview(nh); nh.widthAnchor.constraint(equalTo: nearby.widthAnchor, constant: -36).isActive = true; let hint = NSTextField(wrappingLabelWithString: "Send directly. Star trusted devices so future incoming files can save automatically."); hint.textColor = .secondaryLabelColor; hint.preferredMaxLayoutWidth = 560; nearby.addArrangedSubview(hint); transferDeviceStack = NSStackView(); transferDeviceStack.orientation = .vertical; transferDeviceStack.alignment = .leading; transferDeviceStack.spacing = 9; nearby.addArrangedSubview(transferDeviceStack); transferDeviceStack.widthAnchor.constraint(equalTo: nearby.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(nearby); nearby.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
        transferStatusLabel = NSTextField(labelWithString: "Looking on this Wi-Fi…"); transferStatusLabel.textColor = .secondaryLabelColor; stack.addArrangedSubview(transferStatusLabel)
        return scroll
    }

    private func buildSettingsPage() -> NSView {
        let (scroll, stack) = makePage(title: "Settings", subtitle: "Device, clipboard, receiving and integration")
        let general = glassCard(); general.addArrangedSubview(sectionLabel("GENERAL")); let grow = NSStackView(); grow.orientation = .horizontal; grow.alignment = .centerY; let nameText = NSStackView(); nameText.orientation = .vertical; nameText.alignment = .leading; let gname = NSTextField(labelWithString: "Device name"); gname.textColor = .secondaryLabelColor; nameText.addArrangedSubview(gname); let currentName = NSTextField(labelWithString: Runtime.deviceName()); currentName.font = .systemFont(ofSize: 17, weight: .semibold); nameText.addArrangedSubview(currentName); grow.addArrangedSubview(nameText); grow.addArrangedSubview(spacer()); grow.addArrangedSubview(button("Rename", action: #selector(renameDevice))); general.addArrangedSubview(grow); grow.widthAnchor.constraint(equalTo: general.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(general); general.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        let sync = glassCard(); sync.addArrangedSubview(sectionLabel("CLIPBOARD")); sendSwitch = NSSwitch(); receiveSwitch = NSSwitch(); sync.addArrangedSubview(switchRow("Send clipboard", sendSwitch)); sync.addArrangedSubview(switchRow("Receive clipboard", receiveSwitch)); sendSwitch.target = self; sendSwitch.action = #selector(syncSwitchChanged); receiveSwitch.target = self; receiveSwitch.action = #selector(syncSwitchChanged); stack.addArrangedSubview(sync); sync.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        let receive = glassCard(); receive.addArrangedSubview(sectionLabel("FILE TRANSFER - RECEIVE")); let r1 = NSTextField(labelWithString: "Favorites"); r1.font = .systemFont(ofSize: 15, weight: .semibold); receive.addArrangedSubview(r1); let r2 = NSTextField(wrappingLabelWithString: "Favorited devices save automatically. Unknown devices require Accept / Reject. Incoming files are saved under Downloads/ClipMesh with Images and Videos subfolders."); r2.textColor = .secondaryLabelColor; r2.preferredMaxLayoutWidth = 560; receive.addArrangedSubview(r2); stack.addArrangedSubview(receive); receive.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        let integration = glassCard(); integration.addArrangedSubview(sectionLabel("FINDER INTEGRATION")); let i = NSTextField(wrappingLabelWithString: "ClipMesh includes a macOS Share extension so selected Finder files can appear under Share → ClipMesh. macOS controls the exact contextual-menu placement."); i.textColor = .secondaryLabelColor; i.preferredMaxLayoutWidth = 560; integration.addArrangedSubview(i); integration.addArrangedSubview(closureButton("Refresh Share extension", primary: false) { [weak self] in self?.registerShareExtension(showResult: true) }); stack.addArrangedSubview(integration); integration.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        pairPanel = glassCard(); pairPanel.orientation = .vertical; pairPanel.addArrangedSubview(sectionLabel("PAIRING")); let ph = NSTextField(wrappingLabelWithString: "Pairing codes contain the private space key. Treat them like passwords; ClipMesh does not sync its own pairing links as normal clipboard text."); ph.textColor = .secondaryLabelColor; ph.preferredMaxLayoutWidth = 560; pairPanel.addArrangedSubview(ph); pairField = NSTextField(string: ""); pairField.placeholderString = "clipmesh://pair?..."; pairField.font = .monospacedSystemFont(ofSize: 11, weight: .regular); pairPanel.addArrangedSubview(pairField); pairField.widthAnchor.constraint(equalTo: pairPanel.widthAnchor, constant: -36).isActive = true; let actions = NSStackView(); actions.orientation = .horizontal; actions.spacing = 8; actions.addArrangedSubview(button("Join", action: #selector(joinDevice))); actions.addArrangedSubview(button("Create new", action: #selector(createNewSpace))); actions.addArrangedSubview(button("Copy my code", action: #selector(copyPairingLink))); pairPanel.addArrangedSubview(actions); stack.addArrangedSubview(pairPanel); pairPanel.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
        return scroll
    }

    private func switchRow(_ title: String, _ toggle: NSSwitch) -> NSView {
        let row = NSStackView(); row.orientation = .horizontal; row.alignment = .centerY; let label = NSTextField(labelWithString: title); label.font = .systemFont(ofSize: 14); row.addArrangedSubview(label); row.addArrangedSubview(spacer()); row.addArrangedSubview(toggle); return row
    }

    private func closureButton(_ title: String, primary: Bool, handler: @escaping () -> Void) -> NSButton {
        let b = CMClosureButton(title, handler: handler); b.bezelStyle = .rounded; b.controlSize = .large; b.font = .systemFont(ofSize: 12, weight: .semibold); b.contentTintColor = primary ? NSColor(calibratedRed: 13/255, green: 12/255, blue: 10/255, alpha: 1) : .labelColor; b.wantsLayer = true; if primary { b.layer?.backgroundColor = NSColor(calibratedRed: 241/255, green: 235/255, blue: 221/255, alpha: 1).cgColor; b.layer?.cornerRadius = 10; b.isBordered = false }; return b
    }

    @objc private func showClipboardTab() { selectTab(0) }
    @objc private func showTransferTab() { selectTab(1); LocalTransferManager.shared.discoverNow(); refreshTransferDevices() }
    @objc private func showSettingsTab() { selectTab(2); syncSettingsControls() }

    private func selectTab(_ index: Int, animated: Bool = true) {
        guard pages.indices.contains(index) else { return }; selectedTab = index
        for (i, page) in pages.enumerated() { if i == index { page.isHidden = false; if animated { page.alphaValue = 0; NSAnimationContext.runAnimationGroup { c in c.duration = 0.16; page.animator().alphaValue = 1 } } } else { page.isHidden = true } }
        for (i, b) in navButtons.enumerated() { let active = i == index; b.contentTintColor = active ? NSColor(calibratedRed: 244/255, green: 169/255, blue: 78/255, alpha: 1) : .secondaryLabelColor; b.layer?.backgroundColor = active ? NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 0.13).cgColor : NSColor.clear.cgColor }
        if index == 0 { refreshClipboardPreviewInline() }
        if index == 1 { startTransferTimer() } else { transferTimer?.invalidate(); transferTimer = nil }
    }

    private func refreshClipboardPreviewInline() {
        guard clipboardPreviewStack != nil else { return }; clipboardPreviewStack.arrangedSubviews.forEach { clipboardPreviewStack.removeArrangedSubview($0); $0.removeFromSuperview() }; let pb = NSPasteboard.general
        if let image = NSImage(pasteboard: pb) { let kind = sectionLabel("IMAGE"); kind.textColor = NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 1); clipboardPreviewStack.addArrangedSubview(kind); let iv = NSImageView(); iv.image = image; iv.imageScaling = .scaleProportionallyUpOrDown; iv.wantsLayer = true; iv.layer?.cornerRadius = 14; iv.heightAnchor.constraint(equalToConstant: 270).isActive = true; clipboardPreviewStack.addArrangedSubview(iv); iv.widthAnchor.constraint(equalTo: clipboardPreviewStack.widthAnchor).isActive = true }
        else if let urls = pb.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL], !urls.isEmpty { let kind = sectionLabel("FILES"); kind.textColor = NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 1); clipboardPreviewStack.addArrangedSubview(kind); clipboardPreviewStack.addArrangedSubview(NSTextField(wrappingLabelWithString: urls.prefix(30).map(\.lastPathComponent).joined(separator: "\n"))) }
        else if let text = pb.string(forType: .string), !text.isEmpty { let kind = sectionLabel("TEXT"); kind.textColor = NSColor(calibratedRed: 232/255, green: 145/255, blue: 60/255, alpha: 1); clipboardPreviewStack.addArrangedSubview(kind); let value = NSTextField(wrappingLabelWithString: String(text.prefix(16000))); value.isSelectable = true; value.preferredMaxLayoutWidth = 560; clipboardPreviewStack.addArrangedSubview(value) }
        else { let empty = NSTextField(labelWithString: "Clipboard is empty."); empty.textColor = .secondaryLabelColor; clipboardPreviewStack.addArrangedSubview(empty) }
    }

    private func chooseTransferFiles() { let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = true; panel.beginSheetModal(for: window) { response in if response == .OK { self.transferFiles = panel.urls; self.updateTransferSelection(); LocalTransferManager.shared.discoverNow(); self.refreshTransferDevices() } } }
    private func updateTransferSelection() { transferFileLabel?.stringValue = transferFiles.isEmpty ? "No files selected" : transferFiles.count == 1 ? transferFiles[0].lastPathComponent : "\(transferFiles.count) files selected" }
    private func startTransferTimer() { transferTimer?.invalidate(); transferTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.refreshTransferDevices() }; refreshTransferDevices() }
    private func refreshTransferDevices() {
        guard transferDeviceStack != nil else { return }; transferDeviceStack.arrangedSubviews.forEach { transferDeviceStack.removeArrangedSubview($0); $0.removeFromSuperview() }; let devices = LocalTransferManager.shared.nearbyDevices(); transferStatusLabel?.stringValue = devices.isEmpty ? "Looking on this Wi-Fi…" : "\(devices.count) device\(devices.count == 1 ? "" : "s") visible"
        if devices.isEmpty { let e = NSTextField(labelWithString: "No ClipMesh devices found yet."); e.textColor = .secondaryLabelColor; transferDeviceStack.addArrangedSubview(e); return }
        for d in devices { let row = NSStackView(); row.orientation = .horizontal; row.alignment = .centerY; row.spacing = 10; let txt = NSStackView(); txt.orientation = .vertical; txt.alignment = .leading; let n = NSTextField(labelWithString: d.alias); n.font = .systemFont(ofSize: 15, weight: .semibold); txt.addArrangedSubview(n); let sub = NSTextField(labelWithString: d.model.isEmpty ? d.type.capitalized : d.model); sub.textColor = .secondaryLabelColor; sub.font = .systemFont(ofSize: 11); txt.addArrangedSubview(sub); row.addArrangedSubview(txt); row.addArrangedSubview(spacer()); let favorite = LocalTransferManager.shared.isFavorite(d.fingerprint); row.addArrangedSubview(closureButton(favorite ? "★" : "☆", primary: false) { LocalTransferManager.shared.setFavorite(d.fingerprint, !favorite); self.refreshTransferDevices() }); row.addArrangedSubview(closureButton("Send", primary: true) { [weak self] in self?.sendTransfer(to: d) }); transferDeviceStack.addArrangedSubview(row); row.widthAnchor.constraint(equalTo: transferDeviceStack.widthAnchor).isActive = true }
    }
    private func sendTransfer(to device: TransferDevice) { if transferFiles.isEmpty { chooseTransferFiles(); return }; transferStatusLabel.stringValue = "Connecting to \(device.alias)…"; LocalTransferManager.shared.send(files: transferFiles, to: device, progress: { [weak self] t in self?.transferStatusLabel?.stringValue = t }) { [weak self] result in switch result { case .success: self?.transferStatusLabel?.stringValue = "Sent to \(device.alias)"; case .failure(let error): self?.transferStatusLabel?.stringValue = error.localizedDescription; let alert = NSAlert(); alert.messageText = "Couldn’t send"; alert.informativeText = error.localizedDescription; alert.runModal() } } }

    @objc private func syncSwitchChanged() { mutateRuntime { try Runtime.setSync(send: self.sendSwitch.state == .on, receive: self.receiveSwitch.state == .on) } }
    private func syncSettingsControls() { if let st = try? Runtime.uiState() { latestState = st; sendSwitch?.state = st.sendEnabled ? .on : .off; receiveSwitch?.state = st.receiveEnabled ? .on : .off } }

    private func registerShareExtension(showResult: Bool = false) {
        guard let plugIns = Bundle.main.builtInPlugInsURL else { return }; let appex = plugIns.appendingPathComponent("ClipMeshShare.appex"); guard FileManager.default.fileExists(atPath: appex.path) else { return }
        func run(_ args: [String]) -> Int32 { let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/pluginkit"); p.arguments = args; p.standardOutput = Pipe(); p.standardError = Pipe(); do { try p.run(); p.waitUntilExit(); return p.terminationStatus } catch { return -1 } }
        let a = run(["-a", appex.path]); let e = run(["-e", "use", "-i", "dev.clipmesh.private.Share"]); NSUpdateDynamicServices(); if showResult { let alert = NSAlert(); alert.messageText = (a == 0 && e == 0) ? "Finder Share refreshed" : "Finder controls Share extensions"; alert.informativeText = "Look under Finder → right-click a file → Share → ClipMesh. If macOS hides it, open Share → Edit Extensions and enable ClipMesh."; alert.addButton(withTitle: "OK"); alert.runModal() }
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
        let send = NSMenuItem(title: "Send Files…", action: #selector(sendFiles), keyEquivalent: "")
        send.target = self
        menu.addItem(send)
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
            if selectedTab == 0 { refreshClipboardPreviewInline() }
            if selectedTab == 2 { syncSettingsControls() }
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
        if latestState != nil { refreshHome() }
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
    @objc private func toggleClipboardPanel() { animatePanel(clipboardPanel) }
    @objc private func toggleFilePanel() { if filePanel?.isHidden == true { LocalTransferManager.shared.discoverNow() }; animatePanel(filePanel) }
    private func animatePanel(_ panel: NSStackView?) { guard let panel else { return }; if panel.isHidden { panel.alphaValue=0;panel.isHidden=false;NSAnimationContext.runAnimationGroup{c in c.duration=0.18;panel.animator().alphaValue=1} } else { NSAnimationContext.runAnimationGroup({c in c.duration=0.14;panel.animator().alphaValue=0},completionHandler:{panel.isHidden=true;panel.alphaValue=1}) } }
    @objc private func sendFiles() { TransferChooserController.shared.show(files: []) }

    @objc func shareFiles(_ pasteboard: NSPasteboard, userData: String, error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        let urls = (pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        guard !urls.isEmpty else {
            error.pointee = "Select one or more files in Finder first." as NSString
            return
        }
        TransferChooserController.shared.show(files: urls)
    }

    @objc private func togglePairPanel() {
        pairPanel.isHidden.toggle()
        if !pairPanel.isHidden { pairField.becomeFirstResponder() }
    }

    @objc private func renameDevice() {
        let alert = NSAlert()
        alert.messageText = "Rename this device"
        alert.informativeText = "This name is shown to your other ClipMesh devices."
        alert.addButton(withTitle: "Save")
        // Keep this dialog distinct from the Settings alert patch anchor.
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
        alert.addButton(withTitle: "Reset All Pairing…")

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
        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            mutateRuntime { try Runtime.setSync(send: send.state == .on, receive: receive.state == .on) }
            return
        }
        if response == .alertThirdButtonReturn {
            let confirm = NSAlert()
            confirm.alertStyle = .critical
            confirm.messageText = "Reset all ClipMesh pairing?"
            confirm.informativeText = "This creates a new device identity and private space, clears every remembered device, and forces all other devices to pair again."
            confirm.addButton(withTitle: "Reset")
            confirm.addButton(withTitle: "Cancel")
            guard confirm.runModal() == .alertFirstButtonReturn else { return }
            let name = current.deviceName
            mutateRuntime { try Runtime.resetIdentity(name: name) }
        }
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

    @objc private func quitApp() {
        quitting = true
        LocalTransferManager.shared.stop()
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
