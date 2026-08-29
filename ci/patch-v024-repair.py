from pathlib import Path
import platform
import re
import os

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace(path: Path, old: str, new: str, label: str, count: int | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found == 0 or (count is not None and found != count):
        raise SystemExit(f"{label}: expected {count or 'at least one'} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def regex(path: Path, pattern: str, new: str, label: str, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8")
    result, found = re.subn(pattern, lambda _m: new, text, count=1, flags=flags)
    if found != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {found}")
    path.write_text(result, encoding="utf-8")


def isolate_transport(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("53317", "53421")
    text = text.replace("/api/localsend/v2/", "/api/clipmesh/v1/")
    text = text.replace("LocalSend-style", "ClipMesh")
    text = text.replace("LocalSend protocol v2 semantics", "ClipMesh LAN protocol semantics")
    text = text.replace("LocalSend-compatible", "ClipMesh")
    path.write_text(text, encoding="utf-8")


if system == "Darwin":
    app = root / "ci/ClipMeshApp.swift"
    transfer = root / "ci/ClipMeshTransfer.swift"
    build = project / "scripts/build-macos.sh"
    isolate_transport(app)
    isolate_transport(transfer)

    # A drop anywhere in the content window selects the files and opens File Transfer.
    replace(app,
        "let root = NSView(); root.wantsLayer = true",
        """let root = CMFileDropView(); root.wantsLayer = true
        root.onFiles = { [weak self] urls in
            guard let self, !urls.isEmpty else { return }
            self.transferFiles = urls
            self.updateTransferSelection()
            self.selectTab(1, animated: true)
            LocalTransferManager.shared.discoverNow()
            self.refreshTransferDevices()
        }""",
        "macOS whole-window drop target", 1)
    replace(app,
        "let b = NSButton(title: title, target: self, action: selector); b.isBordered = false; b.alignment = .left;",
        "let b = NSButton(title: \"   \" + title, target: self, action: selector); b.isBordered = false; b.alignment = .left;",
        "macOS sidebar padding", 1)
    replace(app,
        "private var transferFileLabel: NSTextField!",
        "private var transferFileLabel: NSTextField!\n    private var transferFilesStack: NSStackView!",
        "macOS selected-file strip property", 1)

    regex(app, r"    private func buildClipboardPage\(\) -> NSView \{.*?\n    \}\n\n    private func buildTransferPage", r'''    private func buildClipboardPage() -> NSView {
        let (scroll, stack) = makePage(title: "Clipboard", subtitle: "")
        statusLabel = NSTextField(labelWithString: "Starting…"); statusLabel.textColor = .secondaryLabelColor; statusLabel.font = .systemFont(ofSize: 12); stack.addArrangedSubview(statusLabel)

        let device = glassCard(); device.addArrangedSubview(sectionLabel("THIS DEVICE NAME:")); let row = NSStackView(); row.orientation = .horizontal; row.alignment = .centerY; row.spacing = 10; let text = NSStackView(); text.orientation = .vertical; text.alignment = .leading; deviceNameLabel = NSTextField(labelWithString: "Mac"); deviceNameLabel.font = .systemFont(ofSize: 21, weight: .semibold); deviceIDLabel = NSTextField(labelWithString: ""); deviceIDLabel.font = .monospacedSystemFont(ofSize: 10, weight: .regular); deviceIDLabel.textColor = .secondaryLabelColor; text.addArrangedSubview(deviceNameLabel); text.addArrangedSubview(deviceIDLabel); row.addArrangedSubview(text); row.addArrangedSubview(spacer()); row.addArrangedSubview(button("Rename", action: #selector(renameDevice))); device.addArrangedSubview(row); row.widthAnchor.constraint(equalTo: device.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(device); device.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        let peers = glassCard(); let peersHeader = NSStackView(); peersHeader.orientation = .horizontal; peersHeader.alignment = .centerY; peersHeader.addArrangedSubview(sectionLabel("PAIRED DEVICES")); peersHeader.addArrangedSubview(spacer()); peersHeader.addArrangedSubview(closureButton("Refresh", primary: false) { [weak self] in self?.refreshHome() }); peers.addArrangedSubview(peersHeader); peersHeader.widthAnchor.constraint(equalTo: peers.widthAnchor, constant: -36).isActive = true; peersStack = NSStackView(); peersStack.orientation = .vertical; peersStack.alignment = .leading; peersStack.spacing = 8; peers.addArrangedSubview(peersStack); peersStack.widthAnchor.constraint(equalTo: peers.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(peers); peers.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        let actions = NSStackView(); actions.orientation = .horizontal; actions.spacing = 10; actions.addArrangedSubview(button("View current clipboard", action: #selector(viewClipboard))); actions.addArrangedSubview(closureButton("Pair new device", primary: true) { [weak self] in self?.selectTab(2, animated: true); self?.pairField?.becomeFirstResponder() }); stack.addArrangedSubview(actions)
        return scroll
    }

    private func buildTransferPage''', "macOS clipboard layout")

    regex(app, r"    private func buildTransferPage\(\) -> NSView \{.*?\n    \}\n\n    private func buildSettingsPage", r'''    private func buildTransferPage() -> NSView {
        let (scroll, stack) = makePage(title: "File Transfer", subtitle: "")
        let actions = NSStackView(); actions.orientation = .horizontal; actions.alignment = .centerY; actions.addArrangedSubview(NSTextField(labelWithString: "Selected files")); actions.addArrangedSubview(spacer()); actions.addArrangedSubview(closureButton("Choose file manually", primary: true) { [weak self] in self?.chooseTransferFiles() }); stack.addArrangedSubview(actions); actions.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true

        transferFilesStack = NSStackView(); transferFilesStack.orientation = .horizontal; transferFilesStack.alignment = .top; transferFilesStack.spacing = 10
        let fileScroll = NSScrollView(); fileScroll.drawsBackground = false; fileScroll.hasHorizontalScroller = true; fileScroll.autohidesScrollers = true; fileScroll.documentView = transferFilesStack; fileScroll.translatesAutoresizingMaskIntoConstraints = false; fileScroll.heightAnchor.constraint(equalToConstant: 112).isActive = true; transferFilesStack.translatesAutoresizingMaskIntoConstraints = false; transferFilesStack.leadingAnchor.constraint(equalTo: fileScroll.contentView.leadingAnchor).isActive = true; transferFilesStack.topAnchor.constraint(equalTo: fileScroll.contentView.topAnchor).isActive = true; stack.addArrangedSubview(fileScroll); fileScroll.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
        transferFileLabel = NSTextField(labelWithString: "Drop files anywhere in the ClipMesh window"); transferFileLabel.textColor = .secondaryLabelColor; stack.addArrangedSubview(transferFileLabel)

        let nearby = glassCard(); let nh = NSStackView(); nh.orientation = .horizontal; nh.alignment = .centerY; let nt = NSTextField(labelWithString: "Available devices"); nt.font = .systemFont(ofSize: 19, weight: .semibold); nh.addArrangedSubview(nt); nh.addArrangedSubview(spacer()); nh.addArrangedSubview(closureButton("Refresh", primary: false) { LocalTransferManager.shared.discoverNow(); self.refreshTransferDevices() }); nearby.addArrangedSubview(nh); nh.widthAnchor.constraint(equalTo: nearby.widthAnchor, constant: -36).isActive = true; transferDeviceStack = NSStackView(); transferDeviceStack.orientation = .vertical; transferDeviceStack.alignment = .leading; transferDeviceStack.spacing = 9; nearby.addArrangedSubview(transferDeviceStack); transferDeviceStack.widthAnchor.constraint(equalTo: nearby.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(nearby); nearby.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
        transferStatusLabel = NSTextField(labelWithString: "Looking on this Wi-Fi…"); transferStatusLabel.textColor = .secondaryLabelColor; stack.addArrangedSubview(transferStatusLabel)
        return scroll
    }

    private func buildSettingsPage''', "macOS file-transfer layout")

    replace(app, '    private func updateTransferSelection() { transferFileLabel?.stringValue = transferFiles.isEmpty ? "No files selected" : transferFiles.count == 1 ? transferFiles[0].lastPathComponent : "\\(transferFiles.count) files selected" }', r'''    private func updateTransferSelection() {
        guard let transferFilesStack else { return }
        transferFilesStack.arrangedSubviews.forEach { transferFilesStack.removeArrangedSubview($0); $0.removeFromSuperview() }
        if transferFiles.isEmpty {
            let empty = NSTextField(labelWithString: "No files selected"); empty.textColor = .secondaryLabelColor; transferFilesStack.addArrangedSubview(empty)
            transferFileLabel.stringValue = "Drop files anywhere in the ClipMesh window"
            return
        }
        transferFileLabel.stringValue = "\(transferFiles.count) file\(transferFiles.count == 1 ? "" : "s") ready"
        for url in transferFiles {
            let chip = NSStackView(); chip.orientation = .vertical; chip.alignment = .centerX; chip.spacing = 4; chip.edgeInsets = NSEdgeInsets(top: 8, left: 8, bottom: 8, right: 8); chip.wantsLayer = true; chip.layer?.cornerRadius = 12; chip.layer?.backgroundColor = NSColor(calibratedWhite: 1, alpha: 0.07).cgColor
            let icon = NSImageView(); icon.image = NSWorkspace.shared.icon(forFile: url.path); icon.imageScaling = .scaleProportionallyUpOrDown; icon.translatesAutoresizingMaskIntoConstraints = false; icon.widthAnchor.constraint(equalToConstant: 52).isActive = true; icon.heightAnchor.constraint(equalToConstant: 52).isActive = true; chip.addArrangedSubview(icon)
            let name = NSTextField(labelWithString: url.lastPathComponent); name.font = .systemFont(ofSize: 10, weight: .medium); name.alignment = .center; name.lineBreakMode = .byTruncatingMiddle; name.translatesAutoresizingMaskIntoConstraints = false; name.widthAnchor.constraint(equalToConstant: 92).isActive = true; chip.addArrangedSubview(name)
            chip.addArrangedSubview(CMClosureButton("×") { [weak self] in self?.transferFiles.removeAll { $0 == url }; self?.updateTransferSelection() })
            transferFilesStack.addArrangedSubview(chip)
        }
    }
'''.rstrip(), "macOS visual selected-file strip", 1)
    replace(app,
        "let b = CMClosureButton(title, handler: handler); b.bezelStyle = .rounded; b.controlSize = .large;",
        "let b = CMClosureButton(title, handler: handler); b.bezelStyle = .rounded; b.controlSize = .large; b.translatesAutoresizingMaskIntoConstraints = false; b.heightAnchor.constraint(greaterThanOrEqualToConstant: 38).isActive = true; b.widthAnchor.constraint(greaterThanOrEqualToConstant: max(84, CGFloat(title.count * 8 + 28))).isActive = true;",
        "macOS button padding", 1)
    replace(app, "        if index == 0 { refreshClipboardPreviewInline() }\n", "", "macOS clipboard stays hidden until requested", 1)

    # True black/neutral surfaces; gold is reserved for actions and active state.
    text = app.read_text(encoding="utf-8")
    text = text.replace("18/255, green: 17/255, blue: 16/255", "7/255, green: 8/255, blue: 10/255")
    text = text.replace("232/255, green: 145/255, blue: 60/255", "214/255, green: 161/255, blue: 46/255")
    text = text.replace("244/255, green: 169/255, blue: 78/255", "235/255, green: 184/255, blue: 62/255")
    app.write_text(text, encoding="utf-8")

    replace(build, "0.2.3", "0.2.4", "macOS package version")

elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    transfer = root / "ci/ClipMeshTransfer.cs"
    isolate_transport(ui)
    isolate_transport(transfer)
    replace(ui, 'private const string Version = "0.2.3";', 'private const string Version = "0.2.4";', "Windows runtime version", 1)
    replace(ui, "private readonly Label transferFileLabel;", "private readonly Label transferFileLabel;\n    private readonly FlowLayoutPanel transferFilePanel;", "Windows file strip property", 1)
    replace(ui,
        "Button b = MakeButton(nav[i], false); b.TextAlign = ContentAlignment.MiddleLeft;",
        "Button b = MakeButton(\"   \" + nav[i], false); b.TextAlign = ContentAlignment.MiddleLeft; b.Padding = new Padding(10, 0, 8, 0);",
        "Windows sidebar padding", 1)
    replace(ui,
        'Label csub = MakeLabel("Instant encrypted sync between your paired devices", 10, FontStyle.Regular, Muted);',
        'Label csub = MakeLabel("", 10, FontStyle.Regular, Muted);',
        "Windows clipboard subtitle", 1)
    regex(ui, r"        Panel previewCard = MakeCard\(230\);.*?flow\.Controls\.Add\(previewCard\);\n", r'''        clipboardPreview = new Panel(); Panel previewCard = MakeCard(72); previewCard.Width = 650; Button viewClipboard = MakeButton("View current clipboard", true); viewClipboard.SetBounds(18, 14, 210, 42); viewClipboard.Click += delegate { ViewClipboard(); }; previewCard.Controls.Add(viewClipboard); flow.Controls.Add(previewCard);
''', "Windows hidden clipboard preview")
    replace(ui, 'Label deviceCaption = MakeLabel("THIS DEVICE",', 'Label deviceCaption = MakeLabel("THIS DEVICE NAME:",', "Windows device heading", 1)
    replace(ui, 'deviceCard.Controls.Add(deviceId); flow.Controls.Add(deviceCard);', 'deviceCard.Controls.Add(deviceId); Button renameHome = MakeButton("Rename", false); renameHome.SetBounds(536, 43, 95, 42); renameHome.Click += delegate { RenameDevice(); }; deviceCard.Controls.Add(renameHome); flow.Controls.Add(deviceCard);', "Windows home rename", 1)
    replace(ui, 'peersCard.Controls.Add(peersPanel); flow.Controls.Add(peersCard);', 'peersCard.Controls.Add(peersPanel); flow.Controls.Add(peersCard); Panel pairAction = MakeCard(72); pairAction.Width = 650; Button pairNew = MakeButton("Pair new device", true); pairNew.SetBounds(18, 14, 180, 42); pairNew.Click += delegate { SwitchTab(2); pairInput.Focus(); }; pairAction.Controls.Add(pairNew); flow.Controls.Add(pairAction);', "Windows pair-new shortcut", 1)
    regex(ui, r'''        Label ftitle = MakeLabel\("File transfer".*?tf\.Controls\.Add\(transferFileLabel\);''', r'''        Panel transferTop = new Panel(); transferTop.Width = 650; transferTop.Height = 54; transferTop.BackColor = Page; Label ftitle = MakeLabel("File Transfer", 25, FontStyle.Bold, Ink); ftitle.SetBounds(0,0,380,42); Button choose = MakeButton("Choose file manually", true); choose.SetBounds(455,0,195,42); choose.Click += delegate { ChooseTransferFiles(); }; transferTop.Controls.Add(ftitle); transferTop.Controls.Add(choose); tf.Controls.Add(transferTop);
        transferFilePanel = new FlowLayoutPanel(); transferFilePanel.Width = 650; transferFilePanel.Height = 118; transferFilePanel.AutoScroll = true; transferFilePanel.WrapContents = false; transferFilePanel.FlowDirection = FlowDirection.LeftToRight; transferFilePanel.BackColor = Page; tf.Controls.Add(transferFilePanel);
        transferFileLabel = MakeLabel("Drop files anywhere in the ClipMesh window", 9, FontStyle.Regular, Muted); transferFileLabel.Width = 650; transferFileLabel.Height = 28; tf.Controls.Add(transferFileLabel);''', "Windows transfer header and file strip")
    replace(ui, "private void UpdateTransferFiles() { transferFileLabel.Text = transferFiles.Count == 0 ? \"No files selected\" : transferFiles.Count == 1 ? Path.GetFileName(transferFiles[0]) : transferFiles.Count + \" files selected\"; }", r'''private void UpdateTransferFiles()
    {
        transferFilePanel.Controls.Clear();
        transferFileLabel.Text = transferFiles.Count == 0 ? "Drop files anywhere in the ClipMesh window" : transferFiles.Count + " file" + (transferFiles.Count == 1 ? "" : "s") + " ready";
        foreach (string path in new List<string>(transferFiles))
        {
            Panel chip = new Panel(); chip.Width = 112; chip.Height = 92; chip.BackColor = Card; chip.Margin = new Padding(0,0,10,0);
            PictureBox icon = new PictureBox(); Icon fileIcon = Icon.ExtractAssociatedIcon(path); if (fileIcon != null) icon.Image = fileIcon.ToBitmap(); icon.SizeMode = PictureBoxSizeMode.Zoom; icon.SetBounds(10,9,44,44);
            Label name = MakeLabel(Path.GetFileName(path), 7, FontStyle.Bold, Ink); name.SetBounds(8,59,94,24); name.TextAlign = ContentAlignment.MiddleCenter;
            Button remove = MakeButton("×", false); remove.SetBounds(70,8,32,30); remove.Click += delegate { transferFiles.Remove(path); UpdateTransferFiles(); };
            chip.Controls.Add(icon); chip.Controls.Add(name); chip.Controls.Add(remove); transferFilePanel.Controls.Add(chip);
        }
    }''', "Windows visual selected-file strip", 1)
    # Black, neutral surfaces instead of brown-tinted near-black.
    text = ui.read_text(encoding="utf-8")
    for old, new in {
        "Color.FromArgb(18, 17, 16)": "Color.FromArgb(7, 8, 10)",
        "Color.FromArgb(33, 31, 29)": "Color.FromArgb(17, 18, 22)",
        "Color.FromArgb(25, 23, 21)": "Color.FromArgb(11, 12, 15)",
        "Color.FromArgb(43, 41, 37)": "Color.FromArgb(24, 25, 30)",
        "Color.FromArgb(72, 49, 31)": "Color.FromArgb(46, 38, 18)",
        "Color.FromArgb(232, 145, 60)": "Color.FromArgb(214, 161, 46)",
        "Color.FromArgb(244, 169, 78)": "Color.FromArgb(235, 184, 62)",
    }.items(): text = text.replace(old, new)
    ui.write_text(text, encoding="utf-8")

elif system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    main = java / "MainActivity.kt"
    share = java / "fileshare/FileShareActivity.kt"
    settings = java / "SettingsActivity.kt"
    store = java / "SettingsStore.kt"
    engine = java / "fileshare/LocalTransferEngine.kt"
    runtime = java / "BackgroundRuntime.kt"
    service = java / "BackgroundService.kt"
    boot = java / "fileshare/TransferBootReceiver.kt"
    gradle = project / "android/app/build.gradle.kts"
    for path in (main, share, settings, engine): isolate_transport(path)
    replace(gradle, "versionCode = 13", "versionCode = 14", "Android version code", 1)
    replace(gradle, 'versionName = "0.2.3"', 'versionName = "0.2.4"', "Android version name", 1)
    replace(store, "    var autoAcceptFavoriteFiles: Boolean", """    var receiveFilesInBackground: Boolean
        get() = prefs.getBoolean("receive_files_in_background", true)
        set(value) = prefs.edit().putBoolean("receive_files_in_background", value).apply()

    var autoAcceptFavoriteFiles: Boolean""", "Android background receive setting", 1)

    # The foreground service owns the file listener only when the user opts in.
    replace(runtime, "        LocalTransferEngine.start(app)", "        if (SettingsStore(app).receiveFilesInBackground) LocalTransferEngine.start(app) else LocalTransferEngine.stop()", "Android conditional background listener", 1)
    replace(service, "        BackgroundRuntime.start(this)\n    }", """        BackgroundRuntime.start(this)
        val settings = SettingsStore(this)
        if (!settings.backgroundSync && !settings.receiveFilesInBackground) stopSelf()
    }""", "Android service opt-out", 1)
    replace(service, "        fun start(context: Context, captureCurrent: Boolean = false) {\n            val app = context.applicationContext", """        fun start(context: Context, captureCurrent: Boolean = false) {
            val app = context.applicationContext
            val settings = SettingsStore(app)
            if (!settings.backgroundSync && !settings.receiveFilesInBackground) return""", "Android avoid disabled foreground service", 1)
    replace(service, """        val message = if (settings.backgroundSync) {
            "Clipboard sync + nearby file receiving active"
        } else {
            "Nearby file receiving active"
        }""", """        val message = when {
            settings.backgroundSync && settings.receiveFilesInBackground -> "Clipboard sync + nearby file receiving active"
            settings.backgroundSync -> "Clipboard sync active"
            else -> "Nearby file receiving active"
        }""", "Android accurate service status", 1)
    replace(boot, "        BackgroundService.start(context)", """        val settings = dev.clipmesh.SettingsStore(context)
        if (settings.backgroundSync || settings.receiveFilesInBackground) BackgroundService.start(context)""", "Android boot opt-out", 1)

    # All sections participate in discovery while visible and use the same fade transition.
    replace(main, "        super.onResume()\n        BackgroundRuntime.start(this)", "        super.onResume()\n        IncomingRequestUi.attach(this)\n        BackgroundRuntime.start(this)\n        LocalTransferEngine.start(this)\n        LocalTransferEngine.discoverNow()", "Android Clipboard foreground discovery", 1)
    replace(main, "    private fun render() {", "    override fun onPause() { IncomingRequestUi.detach(this); if (!settings.receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }\n\n    private fun render() {", "Android Clipboard incoming UI lifecycle", 1)
    replace(share, "    override fun onDestroy() {", """    override fun onResume() { super.onResume(); IncomingRequestUi.attach(this); LocalTransferEngine.start(this); LocalTransferEngine.discoverNow() }
    override fun onPause() { IncomingRequestUi.detach(this); if (!dev.clipmesh.SettingsStore(this).receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }

    override fun onDestroy() {""", "Android File Transfer incoming UI lifecycle", 1)
    replace(settings, "        super.onResume()", "        super.onResume()\n        IncomingRequestUi.attach(this)\n        LocalTransferEngine.start(this)\n        LocalTransferEngine.discoverNow()", "Android Settings discovery", 1)
    replace(settings, "        super.onPause()", "        IncomingRequestUi.detach(this)\n        if (!settingsStore.receiveFilesInBackground) LocalTransferEngine.stop()\n        super.onPause()", "Android Settings incoming UI lifecycle", 1)
    replace(settings, "import dev.clipmesh.fileshare.LocalTransferEngine", "import dev.clipmesh.fileshare.LocalTransferEngine\nimport dev.clipmesh.fileshare.IncomingRequestUi", "Android Settings incoming UI import", 1)
    replace(main, "import dev.clipmesh.fileshare.LocalTransferEngine", "import dev.clipmesh.fileshare.LocalTransferEngine\nimport dev.clipmesh.fileshare.IncomingRequestUi", "Android Clipboard incoming UI import", 1)

    # Clipboard content stays hidden until explicitly requested.
    regex(main, r'''        val clipCard = card\(root\).*?        clipCard\.addView\(clipboardPreviewContainer\)''', r'''        val clipCard = card(root)
        clipboardPreviewContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE; setPadding(0, dp(12), 0, 0) }
        clipCard.addView(button("View current clipboard") {
            val opening = clipboardPreviewContainer.visibility != View.VISIBLE
            clipboardPreviewContainer.visibility = if (opening) View.VISIBLE else View.GONE
            if (opening) { BackgroundRuntime.captureNow(); renderClipboardContent() }
        }, fullWidthParams(dp(50)))
        clipCard.addView(clipboardPreviewContainer)''', "Android hidden clipboard preview")
    replace(main, "        renderClipboardContent()\n    }", "    }", "Android initial clipboard reveal", 1)
    replace(main, 'deviceCard.addView(label("THIS DEVICE",', 'deviceCard.addView(label("THIS DEVICE NAME:",', "Android device heading", 1)
    replace(main, "        deviceCard.addView(deviceIdText)", "        deviceCard.addView(deviceIdText)\n        deviceCard.addView(button(\"Rename device\", false) { renameDevice() }, fullWidthParams(dp(48)).apply { topMargin = dp(10) })", "Android home rename", 1)
    replace(main, "        root.addView(label(\"Pairing, device identity, clipboard permissions and content rules are in Settings.\", 12f, false, muted).apply {\n            setPadding(dp(4), dp(2), dp(4), 0)\n        })", """        root.addView(button("Pair new device") {
            startActivity(Intent(this, SettingsActivity::class.java).putExtra("open_pairing", true))
            overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
        }, fullWidthParams(dp(50)))""", "Android pair-new shortcut", 1)

    # File Transfer heading, Android type chooser, and removable visual file chips.
    replace(share, "    private lateinit var fileSummary: TextView", "    private lateinit var fileSummary: TextView\n    private lateinit var selectedStrip: LinearLayout", "Android selected strip property", 1)
    regex(share, r'''        val eyebrow = text\("CLIPMESH DROP".*?        root\.addView\(filesCard, fullWidth\(ViewGroup\.LayoutParams\.WRAP_CONTENT\)\.apply \{ bottomMargin = dp\(14\) \}\)''', r'''        val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        top.addView(text("File Transfer", 30f, true, ink), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val choose = pillButton("Choose file manually", true) { showChooseMenu() }
        top.addView(choose, LinearLayout.LayoutParams(dp(184), dp(48)))
        root.addView(top)
        selectedStrip = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(16), 0, dp(8)) }
        val selectedScroll = android.widget.HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = true; addView(selectedStrip) }
        root.addView(selectedScroll, fullWidth(dp(120)))
        fileSummary = text("Drop or choose files", 13f, false, muted).apply { setPadding(0, 0, 0, dp(14)) }
        root.addView(fileSummary)''', "Android File Transfer header")
    replace(share, "    private fun refreshFiles() {\n        fileSummary.text = when (selected.size) {\n            0 -> \"No files selected\"\n            1 -> displayName(selected.first())\n            else -> \"${selected.size} files selected\"\n        }\n        renderDevices()\n    }", r'''    private fun refreshFiles() {
        fileSummary.text = if (selected.isEmpty()) "Choose files to send" else "${selected.size} file${if (selected.size == 1) "" else "s"} ready"
        if (::selectedStrip.isInitialized) {
            selectedStrip.removeAllViews()
            selected.toList().forEach { uri ->
                val chip = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setPadding(dp(7),dp(7),dp(7),dp(7)); background = round(glass2, dp(14).toFloat(), line) }
                val preview = ImageView(this).apply { scaleType = ImageView.ScaleType.CENTER_CROP; setImageURI(uri); if (drawable == null) setImageResource(android.R.drawable.ic_menu_save) }
                chip.addView(preview, LinearLayout.LayoutParams(dp(58),dp(58)))
                val remove = text("×", 18f, true, ink).apply { gravity = Gravity.CENTER; setOnClickListener { selected.remove(uri); refreshFiles() } }
                chip.addView(remove, LinearLayout.LayoutParams(dp(58),dp(30)))
                selectedStrip.addView(chip, LinearLayout.LayoutParams(dp(78),dp(102)).apply { rightMargin=dp(9) })
            }
        }
        renderDevices()
    }''', "Android visual selected-file strip", 1)
    replace(share, "    private fun chooseFiles() {\n        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {\n            type = \"*/*\"", """    private fun showChooseMenu() {
        val options = arrayOf("Image", "Video", "File")
        AlertDialog.Builder(this).setTitle("Choose file type").setItems(options) { _, which ->
            chooseFiles(when (which) { 0 -> "image/*"; 1 -> "video/*"; else -> "*/*" })
        }.show()
    }

    private fun chooseFiles(mime: String = "*/*") {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = mime""", "Android typed picker", 1)
    replace(share, "startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); finish()", "startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out); finish()", "Android File to Clipboard fade", 1)
    replace(share, "startActivity(Intent(this, SettingsActivity::class.java)); finish()", "startActivity(Intent(this, SettingsActivity::class.java)); overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out); finish()", "Android File to Settings fade", 1)
    replace(settings, "startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); finish()", "startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out); finish()", "Android Settings to Clipboard fade", 1)
    replace(settings, "LocalTransferEngine.discoverNow(); startActivity(Intent(this, FileShareActivity::class.java)); finish()", "LocalTransferEngine.discoverNow(); startActivity(Intent(this, FileShareActivity::class.java)); overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out); finish()", "Android Settings to File fade", 1)

    replace(settings, "        receiveCard.addView(sectionTitle(\"FILE TRANSFER - RECEIVE\"))", """        receiveCard.addView(sectionTitle("FILE TRANSFER - RECEIVE"))
        receiveCard.addView(toggle("Receive files when the app is not opened", settingsStore.receiveFilesInBackground) {
            settingsStore.receiveFilesInBackground = it
            if (it) BackgroundService.start(this) else { BackgroundRuntime.restart(this); LocalTransferEngine.start(this) }
        })""", "Android background receive toggle", 1)
    replace(settings, "port 53421", "ClipMesh port 53421", "Android network copy", 1)
    replace(settings, """        setContentView(shell)

        intent.getStringExtra(EXTRA_PAIR_URI)""", """        setContentView(shell)

        if (intent.getBooleanExtra("open_pairing", false)) {
            intent.removeExtra("open_pairing")
            root.post { joinPairingCode(null) }
        }
        intent.getStringExtra(EXTRA_PAIR_URI)""", "Android open-pairing shortcut", 1)

    # Visible activities use a bottom-sheet decision dialog; background requests keep notification actions.
    replace(engine, "            TransferNotifications.showIncoming(requireContext(), request)", "            if (!IncomingRequestUi.show(request)) TransferNotifications.showIncoming(requireContext(), request)", "Android in-app incoming prompt", 1)
    (java / "fileshare/IncomingRequestUi.kt").write_text(r'''package dev.clipmesh.fileshare

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.lang.ref.WeakReference

object IncomingRequestUi {
    @Volatile private var visible = WeakReference<Activity?>(null)
    fun attach(activity: Activity) { visible = WeakReference<Activity?>(activity) }
    fun detach(activity: Activity) { if (visible.get() === activity) visible.clear() }
    fun show(request: LocalTransferEngine.IncomingDecision): Boolean {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return false
        activity.runOnUiThread {
            val dialog = Dialog(activity)
            val density = activity.resources.displayMetrics.density
            fun dp(v:Int)=(v*density+.5f).toInt()
            val body = LinearLayout(activity).apply {
                orientation=LinearLayout.VERTICAL; setPadding(dp(24),dp(24),dp(24),dp(28))
                background=GradientDrawable().apply { setColor(Color.rgb(17,18,22)); cornerRadii=floatArrayOf(dp(26).toFloat(),dp(26).toFloat(),dp(26).toFloat(),dp(26).toFloat(),0f,0f,0f,0f) }
            }
            body.addView(TextView(activity).apply { text="Incoming files"; textSize=23f; setTextColor(Color.WHITE) })
            val names=request.files.take(5).joinToString("\n") { "• ${it.fileName}" } + if(request.files.size>5) "\n• +${request.files.size-5} more" else ""
            body.addView(TextView(activity).apply { text="${request.senderAlias} is trying to send:\n\n$names"; textSize=15f; setTextColor(Color.rgb(205,205,201)); setPadding(0,dp(12),0,dp(20)) })
            val actions=LinearLayout(activity).apply { orientation=LinearLayout.HORIZONTAL }
            val reject=Button(activity).apply { text="Reject"; isAllCaps=false; setOnClickListener { LocalTransferEngine.resolveIncoming(request.requestId,false); dialog.dismiss() } }
            val accept=Button(activity).apply { text="Accept"; isAllCaps=false; setOnClickListener { LocalTransferEngine.resolveIncoming(request.requestId,true); dialog.dismiss() } }
            actions.addView(reject,LinearLayout.LayoutParams(0,dp(52),1f).apply{rightMargin=dp(6)}); actions.addView(accept,LinearLayout.LayoutParams(0,dp(52),1f).apply{leftMargin=dp(6)}); body.addView(actions)
            dialog.setContentView(body); dialog.setOnCancelListener { LocalTransferEngine.resolveIncoming(request.requestId,false) }
            dialog.window?.apply { setBackgroundDrawableResource(android.R.color.transparent); setLayout(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT); setGravity(Gravity.BOTTOM); addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND); attributes=attributes.apply{dimAmount=.72f}; if(Build.VERSION.SDK_INT>=31){addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND); attributes=attributes.apply{blurBehindRadius=28}} }
            dialog.show(); dialog.window?.setLayout(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT)
        }
        return true
    }
}
''', encoding="utf-8")

    # Neutral black/gold palette.
    for path in (main, share, settings):
        text = path.read_text(encoding="utf-8")
        for old, new in {
            "Color.rgb(18, 17, 16)": "Color.rgb(7, 8, 10)",
            "Color.rgb(18,17,16)": "Color.rgb(7,8,10)",
            "Color.rgb(33, 31, 29)": "Color.rgb(17, 18, 22)",
            "Color.rgb(33,31,29)": "Color.rgb(17,18,22)",
            "Color.rgb(24, 22, 20)": "Color.rgb(12, 13, 16)",
            "Color.rgb(24,22,20)": "Color.rgb(12,13,16)",
            "Color.rgb(43, 41, 37)": "Color.rgb(24, 25, 30)",
            "Color.rgb(232, 145, 60)": "Color.rgb(214, 161, 46)",
            "Color.rgb(244, 169, 78)": "Color.rgb(235, 184, 62)",
            "Color.rgb(241,235,221)": "Color.rgb(224, 174, 55)",
            "Color.rgb(241, 235, 221)": "Color.rgb(224, 174, 55)",
        }.items(): text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")

else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh v0.2.4 repair patch on {system}: isolated transport, professional black/gold UI, file selection and Android lifecycle fixes")
