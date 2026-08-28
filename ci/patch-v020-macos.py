from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


mac = root / "ci/ClipMeshApp.swift"
replace_once(
    mac,
    '''        buildWindow()
        buildStatusItem()
        showWindow()

        do {''',
    '''        buildWindow()
        buildStatusItem()
        NSApp.servicesProvider = self
        NSUpdateDynamicServices()
        LocalTransferManager.shared.incomingPrompt = { sender, files in
            TransferDialogs.ask(sender: sender, files: files)
        }
        LocalTransferManager.shared.start(aliasProvider: { [weak self] in
            self?.latestState?.deviceName ?? Runtime.deviceName()
        })
        showWindow()

        do {''',
    "macOS file transfer startup",
)
replace_once(
    mac,
    '''        quitting = true
        stopDaemon()
        logHandle?.closeFile()''',
    '''        quitting = true
        LocalTransferManager.shared.stop()
        stopDaemon()
        logHandle?.closeFile()''',
    "macOS file transfer shutdown",
)
replace_once(
    mac,
    '''        window.title = "ClipMesh"
        window.isReleasedWhenClosed = false''',
    '''        window.title = "ClipMesh"
        window.appearance = NSAppearance(named: .darkAqua)
        window.titlebarAppearsTransparent = true
        window.isReleasedWhenClosed = false''',
    "macOS warm dark window",
)
replace_once(
    mac,
    '''        quick.addArrangedSubview(button("Copy Pairing Code", action: #selector(copyPairingLink)))
        quick.addArrangedSubview(button("View Clipboard", action: #selector(viewClipboard)))
        quick.addArrangedSubview(button("Pair Device", action: #selector(togglePairPanel)))
        root.addArrangedSubview(quick)''',
    '''        quick.addArrangedSubview(button("Copy Pairing Code", action: #selector(copyPairingLink)))
        quick.addArrangedSubview(button("View Clipboard", action: #selector(viewClipboard)))
        quick.addArrangedSubview(button("Send Files", action: #selector(sendFiles)))
        quick.addArrangedSubview(button("Pair Device", action: #selector(togglePairPanel)))
        root.addArrangedSubview(quick)''',
    "macOS send files quick action",
)
replace_once(
    mac,
    '''        let pair = NSMenuItem(title: "Copy Pairing Code", action: #selector(copyPairingLink), keyEquivalent: "")
        pair.target = self
        menu.addItem(pair)
        menu.addItem(.separator())''',
    '''        let pair = NSMenuItem(title: "Copy Pairing Code", action: #selector(copyPairingLink), keyEquivalent: "")
        pair.target = self
        menu.addItem(pair)
        let send = NSMenuItem(title: "Send Files…", action: #selector(sendFiles), keyEquivalent: "")
        send.target = self
        menu.addItem(send)
        menu.addItem(.separator())''',
    "macOS menu bar send files",
)
replace_once(
    mac,
    '''    @objc private func showFromMenu() { showWindow() }
    @objc private func refreshClicked() { refreshHome() }
''',
    '''    @objc private func showFromMenu() { showWindow() }
    @objc private func refreshClicked() { refreshHome() }
    @objc private func sendFiles() { TransferChooserController.shared.show(files: []) }

    @objc func shareFiles(_ pasteboard: NSPasteboard, userData: String, error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        let urls = (pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        guard !urls.isEmpty else {
            error.pointee = "Select one or more files in Finder first." as NSString
            return
        }
        TransferChooserController.shared.show(files: urls)
    }
''',
    "macOS Finder service handler",
)
replace_once(
    mac,
    '''    @objc private func quitApp() {
        quitting = true
        stopDaemon()
        NSApp.terminate(nil)
    }''',
    '''    @objc private func quitApp() {
        quitting = true
        LocalTransferManager.shared.stop()
        stopDaemon()
        NSApp.terminate(nil)
    }''',
    "macOS explicit transfer shutdown",
)
replace_once(
    mac,
    '''        guard let content = window.contentView else { return }
        content.addSubview(root)''',
    '''        guard let content = window.contentView else { return }
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor(calibratedRed: 0.14, green: 0.13, blue: 0.11, alpha: 1).cgColor
        root.wantsLayer = true
        root.layer?.cornerRadius = 24
        root.layer?.backgroundColor = NSColor(calibratedRed: 0.27, green: 0.25, blue: 0.20, alpha: 0.90).cgColor
        root.edgeInsets = NSEdgeInsets(top: 20, left: 20, bottom: 20, right: 20)
        content.addSubview(root)''',
    "macOS glass canvas",
)

mac_build = project / "scripts/build-macos.sh"
text = mac_build.read_text(encoding="utf-8")
text, short_count = re.subn(
    r'<key>CFBundleShortVersionString</key><string>[^<]+</string>',
    '<key>CFBundleShortVersionString</key><string>0.2.0</string>',
    text,
    count=1,
)
text, build_count = re.subn(
    r'<key>CFBundleVersion</key><string>[^<]+</string>',
    '<key>CFBundleVersion</key><string>0.2.0</string>',
    text,
    count=1,
)
if short_count != 1 or build_count != 1:
    raise SystemExit("macOS version plist anchors missing")
mac_build.write_text(text, encoding="utf-8")

replace_once(
    mac_build,
    'LAUNCHER_SRC="../ci/ClipMeshApp.swift"\nDMG_ROOT=',
    'LAUNCHER_SRC="../ci/ClipMeshApp.swift"\nTRANSFER_SRC="../ci/ClipMeshTransfer.swift"\nDMG_ROOT=',
    "macOS transfer source variable",
)
replace_once(
    mac_build,
    'swiftc -O "$LAUNCHER_SRC" -o "$APP/Contents/MacOS/ClipMesh" -framework Cocoa',
    'swiftc -O "$LAUNCHER_SRC" "$TRANSFER_SRC" -o "$APP/Contents/MacOS/ClipMesh" -framework Cocoa -framework Network -framework UniformTypeIdentifiers',
    "macOS compile transfer source",
)
replace_once(
    mac_build,
    '''  <key>NSHighResolutionCapable</key><true/>
</dict></plist>''',
    '''  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key><dict><key>default</key><string>Share with ClipMesh</string></dict>
      <key>NSMessage</key><string>shareFiles</string>
      <key>NSPortName</key><string>ClipMesh</string>
      <key>NSSendTypes</key>
      <array><string>public.file-url</string><string>NSFilenamesPboardType</string></array>
    </dict>
  </array>
</dict></plist>''',
    "macOS Finder Services plist",
)

print("Applied ClipMesh v0.2.0 macOS file-transfer, Finder Service, warm-glass UI, and native version metadata")
