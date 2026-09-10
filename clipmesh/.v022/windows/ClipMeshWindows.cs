using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

internal sealed class CliResult
{
    public int ExitCode;
    public string Output = "";
    public string Error = "";
}

internal sealed class PeerState
{
    public string Id = "";
    public string Name = "";
    public ulong LastSeenMs;
}

internal sealed class UiState
{
    public string DeviceId = "";
    public string DeviceName = "Windows PC";
    public string SpaceId = "";
    public bool SendEnabled = true;
    public bool ReceiveEnabled = true;
    public readonly List<PeerState> Peers = new List<PeerState>();
}

internal static class ClipMeshRuntime
{
    private const string Version = "0.2.1";

    public static string RuntimeDirectory
    {
        get
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ClipMesh", "Runtime", Version);
        }
    }

    public static string EnginePath { get { return Path.Combine(RuntimeDirectory, "clipmesh-bin.exe"); } }

    public static string LogPath
    {
        get
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ClipMesh", "clipmesh.log");
        }
    }

    private static string[] ConfigCandidates
    {
        get
        {
            string roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            return new string[]
            {
                Path.Combine(roaming, "ClipMesh", "ClipMesh", "config", "config.json"),
                Path.Combine(roaming, "ClipMesh", "ClipMesh", "config.json")
            };
        }
    }

    public static void EnsureEngine()
    {
        Directory.CreateDirectory(RuntimeDirectory);
        string temp = EnginePath + ".new";
        using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream("ClipMesh.Engine"))
        {
            if (source == null) throw new InvalidOperationException("The embedded ClipMesh sync engine is missing.");
            using (FileStream target = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None))
                source.CopyTo(target);
        }
        if (File.Exists(EnginePath)) File.Delete(EnginePath);
        File.Move(temp, EnginePath);
    }

    public static CliResult Run(params string[] arguments)
    {
        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = EnginePath;
        start.Arguments = JoinArguments(arguments);
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.WindowStyle = ProcessWindowStyle.Hidden;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        using (Process process = Process.Start(start))
        {
            if (process == null) throw new InvalidOperationException("Could not start the ClipMesh sync engine.");
            string output = process.StandardOutput.ReadToEnd();
            string error = process.StandardError.ReadToEnd();
            process.WaitForExit();
            return new CliResult { ExitCode = process.ExitCode, Output = output, Error = error };
        }
    }

    public static string Checked(string message, params string[] arguments)
    {
        CliResult result = Run(arguments);
        if (result.ExitCode != 0)
            throw new InvalidOperationException(message + Environment.NewLine + PreferredError(result));
        return result.Output.Trim();
    }

    public static void PrepareFirstRun()
    {
        EnsureEngine();
        CliResult status = Run("status");
        if (status.ExitCode == 0) return;

        string detail = (status.Error + "\n" + status.Output).Trim();
        bool missingKey = Contains(detail, "read space key from OS keyring") ||
                          Contains(detail, "No matching entry found in secure storage");
        bool missingConfig = Contains(detail, "config.json") &&
                             (Contains(detail, "os error 2") || Contains(detail, "cannot find the file") ||
                              Contains(detail, "cannot find the path") || Contains(detail, "No such file or directory"));

        if (missingKey)
        {
            bool moved = false;
            foreach (string config in ConfigCandidates)
            {
                if (!File.Exists(config)) continue;
                string backup = config + ".unrecoverable-v0.1.1-" + DateTimeOffset.UtcNow.ToUnixTimeSeconds() + ".bak";
                File.Move(config, backup);
                moved = true;
                break;
            }
            if (!moved)
                throw new InvalidOperationException("ClipMesh found an unusable v0.1.1 encryption key state, but could not locate config.json to repair it.\n" + detail);
        }
        else if (!missingConfig)
        {
            throw new InvalidOperationException("ClipMesh could not read its current configuration.\n" + detail);
        }

        Checked("Could not initialize ClipMesh.", "init", "--name", Environment.MachineName);
        Checked("ClipMesh initialized, but its secure key could not be loaded.", "status");
    }

    public static string PairingLink()
    {
        return Checked("Could not create the pairing code.", "pairing-uri");
    }

    public static void SetName(string name)
    {
        Checked("Could not rename this device.", "set-name", "--name", name);
    }

    public static void SetSync(bool send, bool receive)
    {
        Checked("Could not save sync settings.", "set-sync", "--send", send ? "true" : "false", "--receive", receive ? "true" : "false");
    }

    public static void JoinSpace(string uri, string name)
    {
        Checked("Could not join that ClipMesh space.", "join", uri, "--name", name, "--replace");
    }

    public static void NewSpace(string name)
    {
        Checked("Could not create a new ClipMesh space.", "new-space", "--name", name);
    }

    public static void ResetIdentity(string name)
    {
        Checked("Could not reset ClipMesh pairing.", "reset", "--name", name);
    }

    public static UiState GetUiState()
    {
        string output = Checked("Could not read ClipMesh state.", "ui-state");
        UiState state = new UiState();
        string[] lines = output.Replace("\r", "").Split('\n');
        foreach (string line in lines)
        {
            if (String.IsNullOrWhiteSpace(line)) continue;
            string[] parts = line.Split('\t');
            if (parts.Length == 0) continue;
            if (parts[0] == "DEVICE" && parts.Length >= 3)
            {
                state.DeviceId = parts[1];
                state.DeviceName = parts[2];
            }
            else if (parts[0] == "SPACE" && parts.Length >= 2)
            {
                state.SpaceId = parts[1];
            }
            else if (parts[0] == "SYNC" && parts.Length >= 3)
            {
                bool send, receive;
                if (Boolean.TryParse(parts[1], out send)) state.SendEnabled = send;
                if (Boolean.TryParse(parts[2], out receive)) state.ReceiveEnabled = receive;
            }
            else if (parts[0] == "PEER" && parts.Length >= 4)
            {
                ulong seen = 0;
                UInt64.TryParse(parts[2], out seen);
                state.Peers.Add(new PeerState { Id = parts[1], LastSeenMs = seen, Name = parts[3] });
            }
        }
        if (String.IsNullOrWhiteSpace(state.DeviceId) || String.IsNullOrWhiteSpace(state.SpaceId))
            throw new InvalidOperationException("ClipMesh returned incomplete device state.");
        return state;
    }

    public static Process StartDaemon(Action<string> logLine, Action<Process, int> exited)
    {
        string logDir = Path.GetDirectoryName(LogPath);
        if (!String.IsNullOrEmpty(logDir)) Directory.CreateDirectory(logDir);
        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = EnginePath;
        start.Arguments = "run";
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.WindowStyle = ProcessWindowStyle.Hidden;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        Process process = new Process();
        process.StartInfo = start;
        process.EnableRaisingEvents = true;
        process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) logLine(e.Data); };
        process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) logLine(e.Data); };
        process.Exited += delegate { exited(process, process.ExitCode); };
        if (!process.Start()) throw new InvalidOperationException("Could not start ClipMesh in the background.");
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        return process;
    }

    private static bool Contains(string value, string needle)
    {
        return value.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static string PreferredError(CliResult result)
    {
        return String.IsNullOrWhiteSpace(result.Error) ? result.Output.Trim() : result.Error.Trim();
    }

    private static string JoinArguments(string[] args)
    {
        string[] quoted = new string[args.Length];
        for (int i = 0; i < args.Length; i++) quoted[i] = Quote(args[i]);
        return String.Join(" ", quoted);
    }

    private static string Quote(string value)
    {
        if (value.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0) return value;
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}

internal sealed class ClipMeshForm : Form
{
    private readonly Color Page = Color.FromArgb(18, 17, 16);
    private readonly Color Card = Color.FromArgb(33, 31, 29);
    private readonly Color Ink = Color.FromArgb(246, 242, 233);
    private readonly Color Muted = Color.FromArgb(174, 169, 160);
    private readonly Color Primary = Color.FromArgb(232, 145, 60);
    private readonly Color Border = Color.FromArgb(70, 67, 62);
    private readonly Color Good = Color.FromArgb(244, 169, 78);

    private readonly NotifyIcon tray;
    private readonly Icon trayIcon;
    private readonly FlowLayoutPanel flow;
    private readonly Label status;
    private readonly Label deviceName;
    private readonly Label deviceId;
    private readonly FlowLayoutPanel peersPanel;
    private readonly Panel pairPanel;
    private readonly TextBox pairInput;
    private readonly Panel[] pages = new Panel[3];
    private readonly Button[] navButtons = new Button[3];
    private readonly FlowLayoutPanel transferDevicePanel;
    private readonly Label transferFileLabel;
    private readonly Label transferStatus;
    private readonly Panel clipboardPreview;
    private readonly List<string> transferFiles = new List<string>();
    private readonly System.Windows.Forms.Timer transferTimer;
    private readonly CheckBox settingsSend;
    private readonly CheckBox settingsReceive;
    private int selectedTab;
    private readonly object logLock = new object();
    private Process daemon;
    private bool quitting;
    private UiState latestState;

    public ClipMeshForm()
    {
        Text = "ClipMesh";
        Width = 960;
        Height = 700;
        MinimumSize = new Size(780, 570);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Page;
        AutoScaleMode = AutoScaleMode.Dpi;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        AllowDrop = true;

        Panel sidebar = new Panel(); sidebar.Dock = DockStyle.Left; sidebar.Width = 205; sidebar.BackColor = Color.FromArgb(25, 23, 21); Controls.Add(sidebar);
        Label brand = MakeLabel("ClipMesh", 21, FontStyle.Bold, Ink); brand.SetBounds(20, 28, 165, 34); sidebar.Controls.Add(brand);
        Label brandSub = MakeLabel("PRIVATE • LOCAL", 7, FontStyle.Bold, Muted); brandSub.SetBounds(22, 65, 160, 18); sidebar.Controls.Add(brandSub);
        string[] nav = new string[] { "Clipboard", "File transfer", "Settings" };
        for (int i = 0; i < nav.Length; i++)
        {
            int index = i;
            Button b = MakeButton(nav[i], false); b.TextAlign = ContentAlignment.MiddleLeft; b.SetBounds(16, 112 + i * 54, 173, 44); b.Click += delegate { SwitchTab(index); }; sidebar.Controls.Add(b); navButtons[i] = b;
        }
        Label privacyFoot = MakeLabel("Encrypted clipboard sync.\r\nDirect LAN file transfer.", 8, FontStyle.Regular, Muted); privacyFoot.SetBounds(20, 560, 165, 48); sidebar.Controls.Add(privacyFoot);

        Panel host = new Panel(); host.Dock = DockStyle.Fill; host.BackColor = Page; Controls.Add(host); host.BringToFront();

        // Clipboard page
        Panel clipboardPage = new Panel(); clipboardPage.Dock = DockStyle.Fill; clipboardPage.BackColor = Page; pages[0] = clipboardPage; host.Controls.Add(clipboardPage);
        flow = new FlowLayoutPanel(); flow.Dock = DockStyle.Fill; flow.AutoScroll = true; flow.FlowDirection = FlowDirection.TopDown; flow.WrapContents = false; flow.Padding = new Padding(30, 26, 30, 36); flow.BackColor = Page; clipboardPage.Controls.Add(flow);
        Label ctitle = MakeLabel("Clipboard", 25, FontStyle.Bold, Ink); ctitle.Width = 650; ctitle.Height = 38; flow.Controls.Add(ctitle);
        Label csub = MakeLabel("Instant encrypted sync between your paired devices", 10, FontStyle.Regular, Muted); csub.Width = 650; csub.Height = 28; flow.Controls.Add(csub);
        status = MakeLabel("Starting…", 9, FontStyle.Regular, Muted); status.Width = 650; status.Height = 26; flow.Controls.Add(status);

        Panel previewCard = MakeCard(230); previewCard.Width = 650; Label pvTitle = MakeLabel("CURRENT CLIPBOARD", 8, FontStyle.Bold, Muted); pvTitle.SetBounds(18, 15, 360, 20); previewCard.Controls.Add(pvTitle); Button pvRefresh = MakeButton("Refresh", false); pvRefresh.SetBounds(536, 10, 95, 38); pvRefresh.Click += delegate { RefreshClipboardPreview(); }; previewCard.Controls.Add(pvRefresh); clipboardPreview = new Panel(); clipboardPreview.SetBounds(18, 50, 613, 162); clipboardPreview.BackColor = Color.FromArgb(26, 24, 21); clipboardPreview.AutoScroll = true; previewCard.Controls.Add(clipboardPreview); flow.Controls.Add(previewCard);

        Panel deviceCard = MakeCard(124); deviceCard.Width = 650; Label deviceCaption = MakeLabel("THIS DEVICE", 8, FontStyle.Bold, Muted); deviceCaption.SetBounds(18, 15, 300, 20); deviceName = MakeLabel("Windows PC", 16, FontStyle.Bold, Ink); deviceName.SetBounds(18, 39, 390, 30); deviceId = MakeLabel("", 8, FontStyle.Regular, Muted); deviceId.SetBounds(18, 70, 360, 22); deviceCard.Controls.Add(deviceCaption); deviceCard.Controls.Add(deviceName); deviceCard.Controls.Add(deviceId); flow.Controls.Add(deviceCard);

        Panel peersCard = MakeCard(170); peersCard.Width = 650; Label peersCaption = MakeLabel("PAIRED DEVICES", 8, FontStyle.Bold, Muted); peersCaption.SetBounds(18, 15, 300, 20); Button refresh = MakeButton("Refresh", false); refresh.SetBounds(536, 10, 95, 38); refresh.Click += delegate { RefreshHome(); }; peersPanel = new FlowLayoutPanel(); peersPanel.FlowDirection = FlowDirection.TopDown; peersPanel.WrapContents = false; peersPanel.AutoSize = false; peersPanel.SetBounds(18, 50, 613, 102); peersPanel.BackColor = Card; peersCard.Controls.Add(peersCaption); peersCard.Controls.Add(refresh); peersCard.Controls.Add(peersPanel); flow.Controls.Add(peersCard);

        // File transfer page
        Panel transferPage = new Panel(); transferPage.Dock = DockStyle.Fill; transferPage.BackColor = Page; pages[1] = transferPage; host.Controls.Add(transferPage);
        FlowLayoutPanel tf = new FlowLayoutPanel(); tf.Dock = DockStyle.Fill; tf.AutoScroll = true; tf.FlowDirection = FlowDirection.TopDown; tf.WrapContents = false; tf.Padding = new Padding(30, 26, 30, 36); tf.BackColor = Page; transferPage.Controls.Add(tf);
        Label ftitle = MakeLabel("File transfer", 25, FontStyle.Bold, Ink); ftitle.Width = 650; ftitle.Height = 38; tf.Controls.Add(ftitle); Label fsub = MakeLabel("LocalSend-style nearby transfer on this Wi-Fi", 10, FontStyle.Regular, Muted); fsub.Width = 650; fsub.Height = 30; tf.Controls.Add(fsub);
        Panel drop = MakeCard(150); drop.Width = 650; drop.AllowDrop = true; Label dropTitle = MakeLabel("Drop files here", 17, FontStyle.Bold, Ink); dropTitle.TextAlign = ContentAlignment.MiddleCenter; dropTitle.SetBounds(18, 18, 613, 32); Label dropSub = MakeLabel("or choose them with Explorer", 9, FontStyle.Regular, Muted); dropSub.TextAlign = ContentAlignment.MiddleCenter; dropSub.SetBounds(18, 52, 613, 24); Button choose = MakeButton("Choose files", true); choose.SetBounds(246, 86, 158, 42); choose.Click += delegate { ChooseTransferFiles(); }; drop.Controls.Add(dropTitle); drop.Controls.Add(dropSub); drop.Controls.Add(choose); drop.DragEnter += FileDragEnter; drop.DragDrop += FileDragDrop; tf.Controls.Add(drop);
        transferFileLabel = MakeLabel("No files selected", 9, FontStyle.Regular, Muted); transferFileLabel.Width = 650; transferFileLabel.Height = 28; tf.Controls.Add(transferFileLabel);
        Panel nearbyCard = MakeCard(340); nearbyCard.Width = 650; Label nearby = MakeLabel("NEARBY DEVICES", 8, FontStyle.Bold, Muted); nearby.SetBounds(18, 15, 320, 20); Button rescan = MakeButton("Rescan", false); rescan.SetBounds(536, 10, 95, 38); rescan.Click += delegate { LocalTransferManagerC.Shared.DiscoverNow(); RefreshTransferDevices(); }; nearbyCard.Controls.Add(nearby); nearbyCard.Controls.Add(rescan); Label nhint = MakeLabel("Send directly. Star trusted devices so future incoming files can save automatically.", 9, FontStyle.Regular, Muted); nhint.SetBounds(18, 48, 610, 30); nearbyCard.Controls.Add(nhint); transferDevicePanel = new FlowLayoutPanel(); transferDevicePanel.FlowDirection = FlowDirection.TopDown; transferDevicePanel.WrapContents = false; transferDevicePanel.AutoScroll = true; transferDevicePanel.SetBounds(18, 82, 613, 238); transferDevicePanel.BackColor = Card; nearbyCard.Controls.Add(transferDevicePanel); tf.Controls.Add(nearbyCard); transferStatus = MakeLabel("Looking on this Wi-Fi…", 9, FontStyle.Regular, Muted); transferStatus.Width = 650; transferStatus.Height = 28; transferStatus.TextAlign = ContentAlignment.MiddleCenter; tf.Controls.Add(transferStatus);

        // Settings page
        Panel settingsPage = new Panel(); settingsPage.Dock = DockStyle.Fill; settingsPage.BackColor = Page; pages[2] = settingsPage; host.Controls.Add(settingsPage);
        FlowLayoutPanel sf = new FlowLayoutPanel(); sf.Dock = DockStyle.Fill; sf.AutoScroll = true; sf.FlowDirection = FlowDirection.TopDown; sf.WrapContents = false; sf.Padding = new Padding(30, 26, 30, 36); sf.BackColor = Page; settingsPage.Controls.Add(sf);
        Label stitle = MakeLabel("Settings", 25, FontStyle.Bold, Ink); stitle.Width = 650; stitle.Height = 38; sf.Controls.Add(stitle); Label ssub = MakeLabel("Device, clipboard, receiving and integration", 10, FontStyle.Regular, Muted); ssub.Width = 650; ssub.Height = 30; sf.Controls.Add(ssub);
        Panel general = MakeCard(118); general.Width = 650; Label generalTitle = MakeLabel("GENERAL", 8, FontStyle.Bold, Muted); generalTitle.SetBounds(18, 14, 250, 20); Label dn = MakeLabel("Device name", 9, FontStyle.Regular, Muted); dn.SetBounds(18, 43, 200, 20); Button rename = MakeButton("Rename", false); rename.SetBounds(536, 42, 95, 40); rename.Click += delegate { RenameDevice(); }; general.Controls.Add(generalTitle); general.Controls.Add(dn); general.Controls.Add(rename); sf.Controls.Add(general);
        Panel clipSettings = MakeCard(150); clipSettings.Width = 650; Label cs = MakeLabel("CLIPBOARD", 8, FontStyle.Bold, Muted); cs.SetBounds(18, 14, 250, 20); settingsSend = new CheckBox(); settingsSend.Text = "Send clipboard"; settingsSend.ForeColor = Ink; settingsSend.BackColor = Card; settingsSend.SetBounds(18, 44, 300, 30); settingsReceive = new CheckBox(); settingsReceive.Text = "Receive clipboard"; settingsReceive.ForeColor = Ink; settingsReceive.BackColor = Card; settingsReceive.SetBounds(18, 78, 300, 30); Button saveSync = MakeButton("Apply", true); saveSync.SetBounds(536, 65, 95, 42); saveSync.Click += delegate { MutateRuntime(delegate { ClipMeshRuntime.SetSync(settingsSend.Checked, settingsReceive.Checked); }); }; clipSettings.Controls.Add(cs); clipSettings.Controls.Add(settingsSend); clipSettings.Controls.Add(settingsReceive); clipSettings.Controls.Add(saveSync); sf.Controls.Add(clipSettings);
        Panel receive = MakeCard(120); receive.Width = 650; Label rt = MakeLabel("FILE TRANSFER - RECEIVE", 8, FontStyle.Bold, Muted); rt.SetBounds(18, 14, 300, 20); Label ri = MakeLabel("Favorited devices save automatically. Unknown devices require Accept / Reject. Files save under Downloads\\ClipMesh.", 9, FontStyle.Regular, Muted); ri.SetBounds(18, 45, 610, 52); receive.Controls.Add(rt); receive.Controls.Add(ri); sf.Controls.Add(receive);
        pairPanel = MakeCard(205); pairPanel.Width = 650; Label pairCaption = MakeLabel("PAIRING", 8, FontStyle.Bold, Muted); pairCaption.SetBounds(18, 14, 300, 20); Label pairHint = MakeLabel("Pairing codes contain the private space key and are not intended to sync as ordinary clipboard content.", 9, FontStyle.Regular, Muted); pairHint.SetBounds(18, 38, 610, 34); pairInput = new TextBox(); pairInput.SetBounds(18, 78, 613, 30); pairInput.Font = new Font("Consolas", 9); Button join = MakeButton("Join", true); join.SetBounds(18, 126, 110, 42); join.Click += delegate { JoinDevice(); }; Button create = MakeButton("Create new", false); create.SetBounds(138, 126, 130, 42); create.Click += delegate { CreateNewSpace(); }; Button copyMine = MakeButton("Copy my code", false); copyMine.SetBounds(278, 126, 145, 42); copyMine.Click += delegate { CopyPairingLink(); }; pairPanel.Controls.Add(pairCaption); pairPanel.Controls.Add(pairHint); pairPanel.Controls.Add(pairInput); pairPanel.Controls.Add(join); pairPanel.Controls.Add(create); pairPanel.Controls.Add(copyMine); sf.Controls.Add(pairPanel);
        Panel resetCard = MakeCard(104); resetCard.Width = 650; Label resetLabel = MakeLabel("Reset identity and pairing only if you want every device to pair again.", 9, FontStyle.Regular, Muted); resetLabel.SetBounds(18, 18, 420, 50); Button reset = MakeButton("Reset pairing", false); reset.SetBounds(500, 28, 131, 42); reset.Click += delegate { if (MessageBox.Show(this, "This creates a new device identity and private space and clears all remembered devices.", "Reset all ClipMesh pairing?", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) == DialogResult.OK) { string name = latestState == null ? Environment.MachineName : latestState.DeviceName; MutateRuntime(delegate { ClipMeshRuntime.ResetIdentity(name); }); } }; resetCard.Controls.Add(resetLabel); resetCard.Controls.Add(reset); sf.Controls.Add(resetCard);

        ContextMenuStrip menu = new ContextMenuStrip(); ToolStripMenuItem show = new ToolStripMenuItem("Show ClipMesh"); show.Click += delegate { RestoreFromTray(); }; menu.Items.Add(show); ToolStripMenuItem copy = new ToolStripMenuItem("Copy Pairing Code"); copy.Click += delegate { CopyPairingLink(); }; menu.Items.Add(copy); ToolStripMenuItem sendMenu = new ToolStripMenuItem("Send Files…"); sendMenu.Click += delegate { SwitchTab(1); RestoreFromTray(); }; menu.Items.Add(sendMenu); menu.Items.Add(new ToolStripSeparator()); ToolStripMenuItem quit = new ToolStripMenuItem("Quit ClipMesh"); quit.Click += delegate { QuitCompletely(); }; menu.Items.Add(quit);
        trayIcon = CreateTrayIcon(); tray = new NotifyIcon(); tray.Icon = trayIcon; tray.Text = "ClipMesh"; tray.Visible = true; tray.ContextMenuStrip = menu; tray.MouseClick += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) RestoreFromTray(); };

        transferTimer = new System.Windows.Forms.Timer(); transferTimer.Interval = 1500; transferTimer.Tick += delegate { if (selectedTab == 1) RefreshTransferDevices(); };
        DragEnter += FileDragEnter; DragDrop += FileDragDrop;
        FormClosing += OnFormClosing; Shown += OnShown;
        SwitchTab(0);
    }

    private void SwitchTab(int index)
    {
        if (index < 0 || index >= pages.Length) return; selectedTab = index;
        for (int i = 0; i < pages.Length; i++) { pages[i].Visible = i == index; if (i == index) pages[i].BringToFront(); navButtons[i].BackColor = i == index ? Color.FromArgb(72, 49, 31) : Color.FromArgb(43, 41, 37); navButtons[i].ForeColor = i == index ? Color.FromArgb(244, 169, 78) : Ink; }
        transferTimer.Enabled = index == 1;
        if (index == 0) { RefreshClipboardPreview(); if (latestState != null) RefreshHome(); }
        if (index == 1) { LocalTransferManagerC.Shared.DiscoverNow(); RefreshTransferDevices(); }
        if (index == 2 && latestState != null) { settingsSend.Checked = latestState.SendEnabled; settingsReceive.Checked = latestState.ReceiveEnabled; }
    }

    private void FileDragEnter(object sender, DragEventArgs e) { if (e.Data != null && e.Data.GetDataPresent(DataFormats.FileDrop)) e.Effect = DragDropEffects.Copy; }
    private void FileDragDrop(object sender, DragEventArgs e)
    {
        string[] paths = e.Data == null ? null : e.Data.GetData(DataFormats.FileDrop) as string[]; if (paths == null) return; transferFiles.Clear(); foreach (string path in paths) if (File.Exists(path)) transferFiles.Add(path); if (transferFiles.Count == 0) return; UpdateTransferFiles(); SwitchTab(1);
    }
    private void ChooseTransferFiles() { using (OpenFileDialog dialog = new OpenFileDialog()) { dialog.Multiselect = true; dialog.Title = "Send with ClipMesh"; if (dialog.ShowDialog(this) == DialogResult.OK) { transferFiles.Clear(); transferFiles.AddRange(dialog.FileNames); UpdateTransferFiles(); LocalTransferManagerC.Shared.DiscoverNow(); RefreshTransferDevices(); } } }
    private void UpdateTransferFiles() { transferFileLabel.Text = transferFiles.Count == 0 ? "No files selected" : transferFiles.Count == 1 ? Path.GetFileName(transferFiles[0]) : transferFiles.Count + " files selected"; }
    private void RefreshTransferDevices()
    {
        if (transferDevicePanel == null || transferDevicePanel.IsDisposed) return; transferDevicePanel.SuspendLayout(); transferDevicePanel.Controls.Clear(); List<TransferDeviceC> devices = LocalTransferManagerC.Shared.Nearby();
        if (devices.Count == 0) { Label empty = MakeLabel("No ClipMesh devices found yet.", 9, FontStyle.Regular, Muted); empty.Width = 580; empty.Height = 40; transferDevicePanel.Controls.Add(empty); transferStatus.Text = "Looking on this Wi-Fi…"; }
        else { transferStatus.Text = devices.Count + " device" + (devices.Count == 1 ? "" : "s") + " visible"; foreach (TransferDeviceC d in devices) { Panel row = new Panel(); row.Width = 580; row.Height = 58; row.BackColor = Card; Label name = MakeLabel(d.Alias, 10, FontStyle.Bold, Ink); name.SetBounds(4, 6, 270, 22); Label model = MakeLabel(String.IsNullOrWhiteSpace(d.Model) ? d.Type : d.Model, 8, FontStyle.Regular, Muted); model.SetBounds(4, 30, 270, 18); bool fav = LocalTransferManagerC.Shared.IsFavorite(d.Fingerprint); Button star = MakeButton(fav ? "★" : "☆", false); star.SetBounds(394, 9, 52, 38); star.ForeColor = fav ? Primary : Muted; star.Click += delegate { LocalTransferManagerC.Shared.SetFavorite(d.Fingerprint, !fav); RefreshTransferDevices(); }; Button send = MakeButton("Send", true); send.SetBounds(456, 9, 116, 38); send.Click += delegate { SendTransfer(d); }; row.Controls.Add(name); row.Controls.Add(model); row.Controls.Add(star); row.Controls.Add(send); transferDevicePanel.Controls.Add(row); } }
        transferDevicePanel.ResumeLayout();
    }
    private void SendTransfer(TransferDeviceC device) { if (transferFiles.Count == 0) { ChooseTransferFiles(); return; } transferStatus.Text = "Connecting to " + device.Alias + "…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(transferFiles, device, delegate(string text) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = text; })); }); if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = "Sent to " + device.Alias; })); } catch (Exception ex) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = ex.Message; MessageBox.Show(this, ex.Message, "Couldn’t send", MessageBoxButtons.OK, MessageBoxIcon.Error); })); } }); }
    private void RefreshClipboardPreview()
    {
        if (clipboardPreview == null || clipboardPreview.IsDisposed) return; clipboardPreview.Controls.Clear(); try { if (Clipboard.ContainsImage()) { Image image = Clipboard.GetImage(); PictureBox box = new PictureBox(); box.Image = image; box.SizeMode = PictureBoxSizeMode.Zoom; box.SetBounds(10, 10, 590, 140); clipboardPreview.Controls.Add(box); return; } if (Clipboard.ContainsFileDropList()) { ListBox list = new ListBox(); list.BackColor = Color.FromArgb(26,24,21); list.ForeColor = Ink; list.BorderStyle = BorderStyle.None; list.SetBounds(10, 10, 590, 140); foreach (string path in Clipboard.GetFileDropList()) list.Items.Add(Path.GetFileName(path)); clipboardPreview.Controls.Add(list); return; } if (Clipboard.ContainsText()) { TextBox text = new TextBox(); text.Multiline = true; text.ReadOnly = true; text.ScrollBars = ScrollBars.Vertical; text.BackColor = Color.FromArgb(26,24,21); text.ForeColor = Ink; text.BorderStyle = BorderStyle.None; text.Text = Limit(Clipboard.GetText(), 16000); text.SetBounds(10, 10, 590, 140); clipboardPreview.Controls.Add(text); return; } Label empty = MakeLabel("Clipboard is empty.", 9, FontStyle.Regular, Muted); empty.SetBounds(10, 10, 580, 30); clipboardPreview.Controls.Add(empty); } catch (Exception ex) { Label error = MakeLabel("Could not preview clipboard: " + ex.Message, 9, FontStyle.Regular, Muted); error.SetBounds(10,10,580,40); clipboardPreview.Controls.Add(error); }
    }

    private void OnShown(object sender, EventArgs e)
    {
        Task.Run(delegate
        {
            try
            {
                ClipMeshRuntime.PrepareFirstRun();
                UiState transferState = ClipMeshRuntime.GetUiState();
                ClipMeshShellIntegration.Register();
                LocalTransferManagerC.Shared.IncomingPrompt = AskIncomingFiles;
                LocalTransferManagerC.Shared.Start(transferState.DeviceName);
                Invoke((MethodInvoker)delegate
                {
                    StartDaemon();
                    RefreshHome();
                });
            }
            catch (Exception ex)
            {
                Invoke((MethodInvoker)delegate { ShowError(ex.Message); });
            }
        });
    }

    private void StartDaemon()
    {
        Process started = null;
        started = ClipMeshRuntime.StartDaemon(WriteLog, delegate(Process ended, int exitCode)
        {
            if (quitting || IsDisposed || daemon != ended) return;
            try
            {
                BeginInvoke((MethodInvoker)delegate
                {
                    if (quitting || daemon != ended) return;
                    daemon = null;
                    status.Text = "Background sync stopped (exit " + exitCode + ")";
                    status.ForeColor = Color.Firebrick;
                    RestoreFromTray();
                });
            }
            catch { }
        });
        daemon = started;
        status.Text = "Background sync is running";
        status.ForeColor = Muted;
    }

    private void StopDaemon()
    {
        Process process = daemon;
        daemon = null;
        if (process == null) return;
        try
        {
            if (!process.HasExited)
            {
                process.Kill();
                process.WaitForExit(3000);
            }
        }
        catch { }
        try { process.Dispose(); } catch { }
    }

    private void MutateRuntime(Action operation)
    {
        StopDaemon();
        try
        {
            operation();
            StartDaemon();
            RefreshHome();
        }
        catch (Exception ex)
        {
            try { StartDaemon(); } catch { }
            ShowError(ex.Message);
        }
    }

    private void RefreshHome()
    {
        try
        {
            UiState state = ClipMeshRuntime.GetUiState();
            latestState = state;
            deviceName.Text = state.DeviceName;
            deviceId.Text = "Device ID  " + ShortId(state.DeviceId);
            RenderPeers(state.Peers);
            if (settingsSend != null) settingsSend.Checked = state.SendEnabled;
            if (settingsReceive != null) settingsReceive.Checked = state.ReceiveEnabled;
            if (selectedTab == 0) RefreshClipboardPreview();
            if (daemon != null && !daemon.HasExited)
            {
                status.Text = "Background sync is running";
                status.ForeColor = Muted;
            }
        }
        catch (Exception ex) { ShowError(ex.Message); }
    }

    private void RenderPeers(List<PeerState> peers)
    {
        peersPanel.Controls.Clear();
        if (peers.Count == 0)
        {
            Label empty = MakeLabel("No other devices discovered yet. Keep ClipMesh running on both devices on the same local network, then click Refresh.", 9, FontStyle.Regular, Muted);
            empty.Width = 500;
            empty.Height = 48;
            peersPanel.Controls.Add(empty);
            return;
        }

        ulong now = (ulong)DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        int count = Math.Min(5, peers.Count);
        for (int i = 0; i < count; i++)
        {
            PeerState peer = peers[i];
            Panel row = new Panel();
            row.Width = 500;
            row.Height = 34;
            row.BackColor = Card;
            Label name = MakeLabel(peer.Name, 10, FontStyle.Bold, Ink);
            name.SetBounds(0, 0, 280, 19);
            Label id = MakeLabel(ShortId(peer.Id), 7, FontStyle.Regular, Muted);
            id.SetBounds(0, 18, 220, 15);
            bool online = peer.LastSeenMs > 0 && now >= peer.LastSeenMs && now - peer.LastSeenMs < 90000UL;
            string stateText = online ? "●  Online" : (peer.LastSeenMs == 0 ? "○  Paired" : "○  Known");
            Label state = MakeLabel(stateText, 9, online ? FontStyle.Bold : FontStyle.Regular, online ? Good : Muted);
            state.TextAlign = ContentAlignment.MiddleRight;
            state.SetBounds(340, 5, 155, 24);
            row.Controls.Add(name);
            row.Controls.Add(id);
            row.Controls.Add(state);
            peersPanel.Controls.Add(row);
        }
    }

    private bool AskIncomingFiles(string sender, List<TransferFileMetaC> files)
    {
        bool accepted = false;
        MethodInvoker prompt = delegate
        {
            string what = files.Count == 1 ? files[0].Name : files.Count + " files";
            string message = sender + " wants to send you " + what + "." + Environment.NewLine + Environment.NewLine
                + "Accept to save it in Downloads" + Path.DirectorySeparatorChar + "ClipMesh.";
            accepted = MessageBox.Show(this, message,
                "Incoming ClipMesh transfer", MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes;
        };
        if (InvokeRequired) Invoke(prompt); else prompt();
        return accepted;
    }

    private void OpenFileSender()
    {
        SwitchTab(1);
        RestoreFromTray();
    }

    private void RenameDevice()
    {
        string current = latestState == null ? Environment.MachineName : latestState.DeviceName;
        string value = Prompt("Rename this device", "This name is shown to your other ClipMesh devices.", current);
        if (value == null || String.IsNullOrWhiteSpace(value)) return;
        MutateRuntime(delegate { ClipMeshRuntime.SetName(value.Trim()); });
    }

    private void ShowSettings()
    {
        UiState state;
        try { state = ClipMeshRuntime.GetUiState(); }
        catch (Exception ex) { ShowError(ex.Message); return; }

        using (Form dialog = new Form())
        {
            dialog.Text = "ClipMesh Settings";
            dialog.Width = 390;
            dialog.Height = 325;
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.MaximizeBox = false;
            dialog.MinimizeBox = false;
            dialog.BackColor = Page;

            Label title = MakeLabel("Background sync", 15, FontStyle.Bold, Ink);
            title.SetBounds(24, 20, 300, 30);
            CheckBox send = new CheckBox();
            send.Text = "Send clipboard";
            send.Checked = state.SendEnabled;
            send.SetBounds(27, 65, 300, 30);
            CheckBox receive = new CheckBox();
            receive.Text = "Receive clipboard";
            receive.Checked = state.ReceiveEnabled;
            receive.SetBounds(27, 100, 300, 30);
            Button save = MakeButton("Save", true);
            save.DialogResult = DialogResult.OK;
            save.SetBounds(205, 151, 130, 42);
            Button cancel = MakeButton("Cancel", false);
            cancel.DialogResult = DialogResult.Cancel;
            cancel.SetBounds(65, 151, 130, 42);
            Button reset = MakeButton("Reset all pairing", false);
            reset.SetBounds(65, 216, 270, 42);
            reset.Click += delegate
            {
                if (MessageBox.Show(dialog,
                    "This creates a new device identity and private space, clears every remembered device, and forces all other devices to pair again.",
                    "Reset all ClipMesh pairing?", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK) return;
                string name = latestState == null ? Environment.MachineName : latestState.DeviceName;
                dialog.DialogResult = DialogResult.Abort;
                dialog.Close();
                MutateRuntime(delegate { ClipMeshRuntime.ResetIdentity(name); });
            };
            dialog.Controls.Add(title);
            dialog.Controls.Add(send);
            dialog.Controls.Add(receive);
            dialog.Controls.Add(save);
            dialog.Controls.Add(cancel);
            dialog.Controls.Add(reset);
            dialog.AcceptButton = save;
            dialog.CancelButton = cancel;

            if (dialog.ShowDialog(this) == DialogResult.OK)
                MutateRuntime(delegate { ClipMeshRuntime.SetSync(send.Checked, receive.Checked); });
        }
    }

    private void CopyPairingLink()
    {
        try
        {
            string link = ClipMeshRuntime.PairingLink();
            Clipboard.SetText(link);
            status.Text = "Pairing code copied";
            status.ForeColor = Color.RoyalBlue;
        }
        catch (Exception ex) { ShowError(ex.Message); }
    }

    private void TogglePairPanel()
    {
        pairPanel.Visible = !pairPanel.Visible;
        flow.PerformLayout();
        if (pairPanel.Visible) pairInput.Focus();
    }

    private void JoinDevice()
    {
        string uri = pairInput.Text.Trim();
        if (String.IsNullOrWhiteSpace(uri)) { ShowError("Paste a ClipMesh pairing code first."); return; }
        if (!ConfirmReplacement("Join this private space?")) return;
        string name = latestState == null ? Environment.MachineName : latestState.DeviceName;
        MutateRuntime(delegate { ClipMeshRuntime.JoinSpace(uri, name); });
    }

    private void CreateNewSpace()
    {
        if (!ConfirmReplacement("Create a new private space?")) return;
        string name = latestState == null ? Environment.MachineName : latestState.DeviceName;
        MutateRuntime(delegate { ClipMeshRuntime.NewSpace(name); });
    }

    private bool ConfirmReplacement(string title)
    {
        return MessageBox.Show(this,
            "This replaces this PC's current ClipMesh space and known-device list.",
            title, MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) == DialogResult.OK;
    }

    private void ViewClipboard()
    {
        try
        {
            List<string> lines = new List<string>();
            IDataObject data = Clipboard.GetDataObject();
            if (data == null) lines.Add("Clipboard is empty.");
            else
            {
                string[] formats = data.GetFormats(false);
                lines.Add("Formats: " + (formats.Length == 0 ? "none" : String.Join(", ", formats)));
                if (Clipboard.ContainsText()) lines.Add("\r\nText:\r\n" + Limit(Clipboard.GetText(), 16000));
                if (Clipboard.ContainsFileDropList())
                {
                    System.Collections.Specialized.StringCollection files = Clipboard.GetFileDropList();
                    List<string> paths = new List<string>();
                    foreach (string file in files) { paths.Add(file); if (paths.Count >= 20) break; }
                    lines.Add("\r\nFiles:\r\n" + String.Join("\r\n", paths.ToArray()));
                }
                if (Clipboard.ContainsImage())
                {
                    Image image = Clipboard.GetImage();
                    if (image != null) lines.Add("\r\nImage: " + image.Width + " × " + image.Height + " pixels");
                }
            }
            MessageBox.Show(this, Limit(String.Join("\r\n", lines.ToArray()), 24000), "Current Clipboard", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex) { ShowError("Could not read the clipboard: " + ex.Message); }
    }

    private void ShowError(string message)
    {
        status.Text = message;
        status.ForeColor = Color.Firebrick;
        RestoreFromTray();
    }

    private void WriteLog(string line)
    {
        try
        {
            lock (logLock)
                File.AppendAllText(ClipMeshRuntime.LogPath, DateTime.Now.ToString("s") + " " + line + Environment.NewLine);
        }
        catch { }
    }

    private void OnFormClosing(object sender, FormClosingEventArgs e)
    {
        if (quitting) return;
        if (e.CloseReason == CloseReason.WindowsShutDown || e.CloseReason == CloseReason.TaskManagerClosing) return;
        e.Cancel = true;
        HideToTray();
    }

    private void HideToTray()
    {
        Hide();
        ShowInTaskbar = false;
    }

    private void RestoreFromTray()
    {
        if (IsDisposed) return;
        ShowInTaskbar = true;
        if (!Visible) Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        BringToFront();
        Activate();
        if (latestState != null) RefreshHome();
    }

    private void QuitCompletely()
    {
        quitting = true;
        tray.Visible = false;
        LocalTransferManagerC.Shared.Stop();
        StopDaemon();
        Application.Exit();
    }

    private Panel MakeCard(int height)
    {
        Panel panel = new Panel();
        panel.Width = 558;
        panel.Height = height;
        panel.BackColor = Card;
        panel.Margin = new Padding(0, 0, 0, 12);
        panel.Paint += delegate(object sender, PaintEventArgs e)
        {
            using (Pen pen = new Pen(Border))
                e.Graphics.DrawRectangle(pen, 0, 0, panel.Width - 1, panel.Height - 1);
        };
        return panel;
    }

    private Label MakeLabel(string text, float size, FontStyle style, Color color)
    {
        Label label = new Label();
        label.Text = text;
        label.Font = new Font(SystemFonts.MessageBoxFont.FontFamily, size, style);
        label.ForeColor = color;
        label.AutoEllipsis = true;
        return label;
    }

    private Button MakeButton(string text, bool primaryStyle)
    {
        Button button = new Button();
        button.Text = text;
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 1;
        button.FlatAppearance.BorderColor = primaryStyle ? Primary : Border;
        button.BackColor = primaryStyle ? Primary : Color.FromArgb(43, 41, 37);
        button.ForeColor = primaryStyle ? Color.FromArgb(13, 12, 10) : Ink;
        button.Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 9, FontStyle.Bold);
        button.Cursor = Cursors.Hand;
        return button;
    }

    private static string Prompt(string title, string hint, string current)
    {
        using (Form dialog = new Form())
        {
            dialog.Text = title;
            dialog.Width = 410;
            dialog.Height = 205;
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.MaximizeBox = false;
            dialog.MinimizeBox = false;
            Label label = new Label();
            label.Text = hint;
            label.SetBounds(20, 18, 355, 32);
            TextBox input = new TextBox();
            input.Text = current;
            input.SetBounds(20, 57, 355, 28);
            Button ok = new Button();
            ok.Text = "Save";
            ok.DialogResult = DialogResult.OK;
            ok.SetBounds(215, 105, 90, 34);
            Button cancel = new Button();
            cancel.Text = "Cancel";
            cancel.DialogResult = DialogResult.Cancel;
            cancel.SetBounds(115, 105, 90, 34);
            dialog.Controls.Add(label);
            dialog.Controls.Add(input);
            dialog.Controls.Add(ok);
            dialog.Controls.Add(cancel);
            dialog.AcceptButton = ok;
            dialog.CancelButton = cancel;
            return dialog.ShowDialog() == DialogResult.OK ? input.Text : null;
        }
    }

    private static string ShortId(string value)
    {
        if (String.IsNullOrEmpty(value) || value.Length <= 13) return value;
        return value.Substring(0, 8) + "…" + value.Substring(value.Length - 4);
    }

    private static string Limit(string value, int max)
    {
        if (value == null) return "";
        return value.Length <= max ? value : value.Substring(0, max) + "\r\n…";
    }

    private static Icon CreateTrayIcon()
    {
        Bitmap bitmap = new Bitmap(32, 32, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(bitmap))
        {
            g.Clear(Color.Transparent);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            Point[] top = new Point[] { new Point(4, 10), new Point(25, 10), new Point(19, 4), new Point(25, 10), new Point(19, 16) };
            Point[] bottom = new Point[] { new Point(28, 22), new Point(7, 22), new Point(13, 16), new Point(7, 22), new Point(13, 28) };
            using (Pen outline = new Pen(Color.Black, 5.0f))
            using (Pen inside = new Pen(Color.White, 2.5f))
            {
                outline.StartCap = LineCap.Round; outline.EndCap = LineCap.Round; outline.LineJoin = LineJoin.Round;
                inside.StartCap = LineCap.Round; inside.EndCap = LineCap.Round; inside.LineJoin = LineJoin.Round;
                g.DrawLines(outline, top); g.DrawLines(outline, bottom);
                g.DrawLines(inside, top); g.DrawLines(inside, bottom);
            }
        }
        IntPtr handle = bitmap.GetHicon();
        try
        {
            using (Icon temp = Icon.FromHandle(handle)) return (Icon)temp.Clone();
        }
        finally
        {
            DestroyIcon(handle);
            bitmap.Dispose();
        }
    }

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    private static extern bool DestroyIcon(IntPtr handle);

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            tray.Visible = false;
            tray.Dispose();
            trayIcon.Dispose();
        }
        base.Dispose(disposing);
    }
}

internal static class Program
{
    private static Mutex singleInstance;

    [STAThread]
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
        singleInstance = new Mutex(true, "Local\\ClipMesh.Desktop", out created);
        if (!created) return 0;
        try
        {
            if (Array.IndexOf(args, "--smoke-test") >= 0)
            {
                ClipMeshRuntime.PrepareFirstRun();
                ClipMeshRuntime.GetUiState();
                Console.WriteLine("ClipMesh native Windows first-run smoke test passed");
                return 0;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new ClipMeshForm());
            return 0;
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "ClipMesh", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally
        {
            if (singleInstance != null)
            {
                singleInstance.ReleaseMutex();
                singleInstance.Dispose();
            }
        }
    }
}
