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


def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8")
    updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=flags)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")


if SYSTEM == "Darwin":
    app = ROOT / "ci/ClipMeshApp.swift"

    replace(
        app,
        "    private var nearbyCodeAlert: NSAlert?",
        "    private var nearbyCodePanel: NSPanel?",
        "mac pairing panel property",
    )

    regex(
        app,
        r'''    private func showNearbyPairCode\(_ value: String, device: String\) \{.*?\n    private func approveNearbyPair''',
        r'''    private func showNearbyPairCode(_ value: String, device: String) {
        dismissNearbyPairCode()

        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 276),
            styleMask: [.titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.title = "ClipMesh"
        panel.titlebarAppearsTransparent = true
        panel.isMovableByWindowBackground = true
        panel.backgroundColor = NSColor(calibratedRed: 7/255, green: 8/255, blue: 10/255, alpha: 1)

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 12
        root.edgeInsets = NSEdgeInsets(top: 28, left: 28, bottom: 24, right: 28)
        root.translatesAutoresizingMaskIntoConstraints = false

        let heading = NSTextField(labelWithString: "Verification code")
        heading.font = .systemFont(ofSize: 22, weight: .bold)
        heading.textColor = .white
        root.addArrangedSubview(heading)

        let detail = NSTextField(wrappingLabelWithString: "Enter this code on \(device).")
        detail.font = .systemFont(ofSize: 14)
        detail.textColor = NSColor(calibratedWhite: 0.72, alpha: 1)
        detail.preferredMaxLayoutWidth = 404
        root.addArrangedSubview(detail)

        let codeBox = NSView()
        codeBox.wantsLayer = true
        codeBox.layer?.cornerRadius = 14
        codeBox.layer?.backgroundColor = NSColor(calibratedWhite: 0.10, alpha: 1).cgColor
        codeBox.layer?.borderWidth = 1
        codeBox.layer?.borderColor = NSColor(calibratedWhite: 0.23, alpha: 1).cgColor
        codeBox.translatesAutoresizingMaskIntoConstraints = false

        let code = NSTextField(labelWithString: value)
        code.font = .monospacedDigitSystemFont(ofSize: 46, weight: .bold)
        code.textColor = .white
        code.alignment = .center
        code.maximumNumberOfLines = 1
        code.lineBreakMode = .byClipping
        code.translatesAutoresizingMaskIntoConstraints = false
        codeBox.addSubview(code)

        NSLayoutConstraint.activate([
            codeBox.widthAnchor.constraint(equalToConstant: 404),
            codeBox.heightAnchor.constraint(equalToConstant: 82),
            code.leadingAnchor.constraint(equalTo: codeBox.leadingAnchor, constant: 16),
            code.trailingAnchor.constraint(equalTo: codeBox.trailingAnchor, constant: -16),
            code.centerYAnchor.constraint(equalTo: codeBox.centerYAnchor),
        ])
        root.addArrangedSubview(codeBox)

        let waiting = NSTextField(labelWithString: "Waiting for confirmation…")
        waiting.font = .systemFont(ofSize: 12, weight: .medium)
        waiting.textColor = NSColor(calibratedWhite: 0.48, alpha: 1)
        root.addArrangedSubview(waiting)

        panel.contentView = NSView()
        panel.contentView?.wantsLayer = true
        panel.contentView?.layer?.backgroundColor = panel.backgroundColor.cgColor
        panel.contentView?.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: panel.contentView!.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: panel.contentView!.trailingAnchor),
            root.topAnchor.constraint(equalTo: panel.contentView!.topAnchor),
            root.bottomAnchor.constraint(equalTo: panel.contentView!.bottomAnchor),
        ])

        nearbyCodePanel = panel
        NSApp.activate(ignoringOtherApps: true)
        if let window {
            window.beginSheet(panel)
        } else {
            panel.center()
            panel.makeKeyAndOrderFront(nil)
        }
    }

    private func dismissNearbyPairCode() {
        guard let panel = nearbyCodePanel else { return }
        nearbyCodePanel = nil
        if let parent = panel.sheetParent { parent.endSheet(panel) }
        else { panel.orderOut(nil) }
    }

    private func approveNearbyPair''',
        "mac fixed verification-code panel",
    )

    replace(
        app,
        '''            let input = NSTextField(string: "")
            input.placeholderString = "000000"
            input.alignment = .center
            input.font = .monospacedDigitSystemFont(ofSize: 34, weight: .bold)
            input.frame = NSRect(x: 0, y: 0, width: 280, height: 52)''',
        '''            let input = NSTextField(string: "")
            input.alignment = .center
            input.font = .monospacedDigitSystemFont(ofSize: 34, weight: .bold)
            input.frame = NSRect(x: 0, y: 0, width: 280, height: 52)
            input.placeholderString = "6-digit code"''',
        "mac subdued six-digit placeholder",
    )

elif SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    main = java / "MainActivity.kt"
    dialog = java / "ClipMeshDialog.kt"

    replace(
        dialog,
        '''setText(initial); setTextColor(INK); setHintTextColor(MUTED); textSize = if (emphasized) 34f else 15f; if (emphasized) { typeface = Typeface.MONOSPACE; gravity = Gravity.CENTER; letterSpacing = .16f; hint = "000000" }''',
        '''setText(initial); setTextColor(INK); setHintTextColor(if (emphasized) Color.argb(68, 166, 163, 156) else MUTED); textSize = if (emphasized) 34f else 15f; if (emphasized) { typeface = Typeface.MONOSPACE; gravity = Gravity.CENTER; letterSpacing = .16f; hint = "000000" }''',
        "android subdued six-digit placeholder",
    )

    replace(
        main,
        "        secrets = SecretStore(this)\n",
        "        secrets = SecretStore(this)\n        ensureLocalClipboardSpace()\n",
        "android first-run space initialization",
    )

    replace(
        main,
        "    private fun refreshHome() {",
        '''    private fun ensureLocalClipboardSpace() {
        if (settings.spaceId != null && secrets.loadSpaceKey() != null) return
        val data = Pairing.createSpace(settings.deviceName, settings.deviceId)
        settings.spaceId = data.spaceId
        secrets.saveSpaceKey(data.key)
        settings.clearKnownPeers()
    }

    private fun refreshHome() {''',
        "android local space helper",
    )

    replace(
        main,
        '''        val space=settings.spaceId?:run{toast("Create or join a clipboard space first");return}
        val key=secrets.loadSpaceKey()?:run{toast("Clipboard key is unavailable");return}''',
        '''        ensureLocalClipboardSpace()
        val space=settings.spaceId?:run{toast("ClipMesh could not prepare pairing");return}
        val key=secrets.loadSpaceKey()?:run{toast("ClipMesh could not prepare its encryption key");return}''',
        "android no manual-space prerequisite",
    )

print(f"Applied ClipMesh v057 pairing UX fixes on {SYSTEM}")
