from pathlib import Path
import platform
import shutil

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = platform.system()

if system == "Darwin":
    app_path = root / "ci/ClipMeshApp.swift"
    text = app_path.read_text(encoding="utf-8")
    old_drag = 'registerForDraggedTypes([.fileURL, .init(NSFilenamesPboardType)])'
    if old_drag in text:
        text = text.replace(old_drag, 'registerForDraggedTypes([.fileURL])', 1)

    if 'private func buildMainMenu()' not in text:
        anchor = '    private func buildWindow() {'
        if anchor not in text:
            raise SystemExit('macOS buildMainMenu insertion anchor missing')
        menu = '''    private func buildMainMenu() {
        let main = NSMenu()

        let appRoot = NSMenuItem()
        let appMenu = NSMenu(title: "ClipMesh")
        appMenu.addItem(withTitle: "About ClipMesh", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide ClipMesh", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = NSMenuItem(title: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthers)
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit ClipMesh", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        appMenu.addItem(quit)
        main.addItem(appRoot)
        main.setSubmenu(appMenu, for: appRoot)

        let fileRoot = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        fileMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        main.addItem(fileRoot)
        main.setSubmenu(fileMenu, for: fileRoot)

        let editRoot = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = NSMenuItem(title: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redo)
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        main.addItem(editRoot)
        main.setSubmenu(editMenu, for: editRoot)

        let windowRoot = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        main.addItem(windowRoot)
        main.setSubmenu(windowMenu, for: windowRoot)
        NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = main
    }

'''
        text = text.replace(anchor, menu + anchor, 1)
    app_path.write_text(text, encoding="utf-8")

    transfer_path = root / "ci/ClipMeshTransfer.swift"
    transfer = transfer_path.read_text(encoding="utf-8")

    # Use a separate strongly-retained NSObject target. NSControl does not retain
    # its target, so the button owns this sleeve and AppKit dispatch stays valid.
    class_start = transfer.find('private final class CMActionButton: NSButton {')
    class_end = transfer.find('\nfinal class TransferChooserController', class_start)
    if class_start < 0 or class_end < 0:
        raise SystemExit('macOS CMActionButton replacement anchors missing')
    button_class = '''private final class CMActionTarget: NSObject {
    let handler: () -> Void

    init(handler: @escaping () -> Void) {
        self.handler = handler
        super.init()
    }

    @objc func invoke(_ sender: Any?) {
        handler()
    }
}

private final class CMActionButton: NSButton {
    private var retainedActionTarget: CMActionTarget?

    convenience init(title: String, handler: @escaping () -> Void) {
        self.init(frame: .zero)
        self.title = title
        let actionTarget = CMActionTarget(handler: handler)
        retainedActionTarget = actionTarget
        target = actionTarget
        action = #selector(CMActionTarget.invoke(_:))
    }
}
'''
    transfer = transfer[:class_start] + button_class + transfer[class_end:]
    transfer = transfer.replace(
        'let button = CMActionButton(title: text, target: nil, action: nil); button.handler = handler;',
        'let button = CMActionButton(title: text, handler: handler);',
        1,
    )

    old_selftest_1 = '''        button.performClick(nil)
        guard fired else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button handler did not fire"]) }'''
    old_selftest_2 = '''        guard let action = button.action, button.target === button else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button target/action was not retained"]) }
        guard button.sendAction(action, to: button.target), fired else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button handler did not fire"]) }'''
    new_selftest = '''        guard let action = button.action, let target = button.target else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button target/action was not retained"]) }
        guard NSApp.sendAction(action, to: target, from: button), fired else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button handler did not fire"]) }'''
    if old_selftest_1 in transfer:
        transfer = transfer.replace(old_selftest_1, new_selftest, 1)
    if old_selftest_2 in transfer:
        transfer = transfer.replace(old_selftest_2, new_selftest, 1)
    transfer_path.write_text(transfer, encoding="utf-8")
    for required in (
        'convenience init(title: String, handler:',
        'private var retainedActionTarget: CMActionTarget?',
        'target = actionTarget',
        'action = #selector(CMActionTarget.invoke(_:))',
        'NSApp.sendAction(action, to: target, from: button)',
    ):
        if required not in transfer:
            raise SystemExit(f'macOS transfer-button hotfix missing: {required}')
    for required in ('registerForDraggedTypes([.fileURL])', 'private func buildMainMenu()', 'hasVerticalScroller = true'):
        if required not in text:
            raise SystemExit(f'macOS compile hotfix guard missing: {required}')

elif system == "Windows":
    source = project / ".v022/macos/clipboard.rs"
    target = project / "apps/desktop/src/clipboard.rs"
    if not source.is_file():
        raise SystemExit(f'Windows shared clipboard overlay missing: {source}')
    shutil.copy2(source, target)
    text = target.read_text(encoding="utf-8")
    if 'clipmesh://pair?' not in text:
        raise SystemExit('Windows pairing-link clipboard exclusion missing after hotfix')
    ui_path = root / "ci/ClipMeshWindows.cs"
    ui = ui_path.read_text(encoding="utf-8")
    old_version = 'private const string Version = "0.2.1";'
    if old_version in ui:
        ui = ui.replace(old_version, 'private const string Version = "0.2.2";', 1)
    ui_path.write_text(ui, encoding="utf-8")
    if 'private const string Version = "0.2.2";' not in ui:
        raise SystemExit('Windows v0.2.2 runtime version hotfix missing')

elif system == "Linux":
    manifest = project / "android/app/src/main/AndroidManifest.xml"
    text = manifest.read_text(encoding="utf-8")
    for required in ('android:usesCleartextTraffic="true"', '.fileshare.FileShareActivity', '.fileshare.TransferActionReceiver'):
        if required not in text:
            raise SystemExit(f'Android hotfix guard missing: {required}')
else:
    raise SystemExit(f'unsupported platform for v0.2.2 hotfix: {system}')

print(f'Applied ClipMesh v0.2.2 compile/validation hotfix for {system}')
