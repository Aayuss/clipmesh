from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# macOS native wrapper: warm dark UI, file-drop entry points, Finder Service,
# menu-bar action, favorite-aware incoming confirmation.
# ---------------------------------------------------------------------------
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

# Add a warm glass canvas behind the existing minimal AppKit layout.
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

# ---------------------------------------------------------------------------
# macOS packaging: compile transfer source and advertise a Finder Services item.
# ---------------------------------------------------------------------------
mac_build = project / "scripts/build-macos.sh"
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

# ---------------------------------------------------------------------------
# Windows wrapper: warm dark theme, quick/tray send actions, background receiver,
# trust prompt, and Explorer context-menu command.
# ---------------------------------------------------------------------------
windows = root / "ci/ClipMeshWindows.cs"
replace_once(
    windows,
    '''    private readonly Color Page = Color.FromArgb(246, 247, 249);
    private readonly Color Card = Color.White;
    private readonly Color Ink = Color.FromArgb(28, 30, 34);
    private readonly Color Muted = Color.FromArgb(105, 110, 120);
    private readonly Color Primary = Color.FromArgb(31, 35, 42);
    private readonly Color Border = Color.FromArgb(224, 227, 232);
    private readonly Color Good = Color.FromArgb(31, 138, 76);''',
    '''    private readonly Color Page = Color.FromArgb(35, 34, 29);
    private readonly Color Card = Color.FromArgb(69, 66, 56);
    private readonly Color Ink = Color.FromArgb(249, 247, 239);
    private readonly Color Muted = Color.FromArgb(194, 189, 171);
    private readonly Color Primary = Color.FromArgb(91, 86, 70);
    private readonly Color Border = Color.FromArgb(111, 105, 86);
    private readonly Color Good = Color.FromArgb(184, 224, 164);''',
    "Windows warm theme colors",
)
replace_once(windows, 'Label subtitle = MakeLabel("Private clipboard sync", 10, FontStyle.Regular, Muted);', 'Label subtitle = MakeLabel("Clipboard sync + nearby file drop", 10, FontStyle.Regular, Muted);', "Windows subtitle")
replace_once(
    windows,
    '''        Panel quick = MakeCard(104);''',
    '''        Panel quick = MakeCard(156);''',
    "Windows taller quick actions",
)
replace_once(
    windows,
    '''        quick.Controls.Add(copyPairing);
        quick.Controls.Add(clipboard);
        quick.Controls.Add(pair);
        flow.Controls.Add(quick);''',
    '''        quick.Controls.Add(copyPairing);
        quick.Controls.Add(clipboard);
        quick.Controls.Add(pair);
        Button sendFiles = MakeButton("Send files", false);
        sendFiles.SetBounds(18, 99, 520, 42);
        sendFiles.Click += delegate { OpenFileSender(); };
        quick.Controls.Add(sendFiles);
        flow.Controls.Add(quick);''',
    "Windows send files quick action",
)
replace_once(
    windows,
    '''        ToolStripMenuItem copy = new ToolStripMenuItem("Copy Pairing Code");
        copy.Click += delegate { CopyPairingLink(); };
        menu.Items.Add(copy);
        menu.Items.Add(new ToolStripSeparator());''',
    '''        ToolStripMenuItem copy = new ToolStripMenuItem("Copy Pairing Code");
        copy.Click += delegate { CopyPairingLink(); };
        menu.Items.Add(copy);
        ToolStripMenuItem sendMenu = new ToolStripMenuItem("Send Files…");
        sendMenu.Click += delegate { OpenFileSender(); };
        menu.Items.Add(sendMenu);
        menu.Items.Add(new ToolStripSeparator());''',
    "Windows tray send files",
)
replace_once(
    windows,
    '''                ClipMeshRuntime.PrepareFirstRun();
                Invoke((MethodInvoker)delegate
                {
                    StartDaemon();
                    RefreshHome();
                });''',
    '''                ClipMeshRuntime.PrepareFirstRun();
                UiState transferState = ClipMeshRuntime.GetUiState();
                ClipMeshShellIntegration.Register();
                LocalTransferManagerC.Shared.IncomingPrompt = AskIncomingFiles;
                LocalTransferManagerC.Shared.Start(transferState.DeviceName);
                Invoke((MethodInvoker)delegate
                {
                    StartDaemon();
                    RefreshHome();
                });''',
    "Windows file transfer startup",
)
replace_once(
    windows,
    '''    private void RenameDevice()
    {''',
    '''    private bool AskIncomingFiles(string sender, List<TransferFileMetaC> files)
    {
        bool accepted = false;
        MethodInvoker prompt = delegate
        {
            string what = files.Count == 1 ? files[0].Name : files.Count + " files";
            accepted = MessageBox.Show(this,
                sender + " wants to send you " + what + ".\r\n\r\nAccept to save it in Downloads\\ClipMesh.",
                "Incoming ClipMesh transfer", MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes;
        };
        if (InvokeRequired) Invoke(prompt); else prompt();
        return accepted;
    }

    private void OpenFileSender()
    {
        TransferChooserFormC picker = new TransferChooserFormC(new string[0]);
        picker.Show(this);
    }

    private void RenameDevice()
    {''',
    "Windows transfer methods",
)
replace_once(
    windows,
    '''    private void QuitCompletely()
    {
        quitting = true;
        tray.Visible = false;
        StopDaemon();
        Application.Exit();
    }''',
    '''    private void QuitCompletely()
    {
        quitting = true;
        tray.Visible = false;
        LocalTransferManagerC.Shared.Stop();
        StopDaemon();
        Application.Exit();
    }''',
    "Windows transfer shutdown",
)
replace_once(windows, 'button.BackColor = primaryStyle ? Primary : Color.FromArgb(249, 250, 251);', 'button.BackColor = primaryStyle ? Primary : Color.FromArgb(242, 238, 218);', "Windows button surface")
replace_once(windows, 'button.ForeColor = primaryStyle ? Color.White : Ink;', 'button.ForeColor = primaryStyle ? Ink : Color.FromArgb(44, 42, 34);', "Windows button text")

# Handle Explorer verbs in an independent lightweight chooser process, before
# the normal single-instance desktop mutex is acquired.
replace_once(
    windows,
    '''    [STAThread]
    private static int Main(string[] args)
    {
        bool created;
        singleInstance = new Mutex(true, "Local\\ClipMesh.Desktop", out created);''',
    '''    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length >= 2 && args[0] == "--share")
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                ClipMeshShellIntegration.Register();
                LocalTransferManagerC.Shared.Start(Environment.MachineName);
                List<string> paths = new List<string>();
                for (int i = 1; i < args.Length; i++) if (File.Exists(args[i])) paths.Add(args[i]);
                Application.Run(new TransferChooserFormC(paths));
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "ClipMesh", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            finally { LocalTransferManagerC.Shared.Stop(); }
        }
        bool created;
        singleInstance = new Mutex(true, "Local\\ClipMesh.Desktop", out created);''',
    "Windows Explorer share launch",
)

# ---------------------------------------------------------------------------
# Windows packaging: compile the transfer implementation and JSON serializer.
# ---------------------------------------------------------------------------
win_build = project / "scripts/build-windows.ps1"
replace_once(
    win_build,
    '''$source = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshWindows.cs'
$engine =''',
    '''$source = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshWindows.cs'
$transferSource = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshTransfer.cs'
$engine =''',
    "Windows transfer source variable",
)
replace_once(
    win_build,
    '''    /reference:System.Windows.Forms.dll `
    $source''',
    '''    /reference:System.Windows.Forms.dll `
    /reference:System.Web.Extensions.dll `
    $source `
    $transferSource''',
    "Windows transfer compile inputs",
)

print("Applied ClipMesh v0.2.0 native macOS/Windows file transfer integration, Explorer/Finder actions, and warm glass UI")
