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
    private const string Version = "0.1.3";

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
    private readonly Color Page = Color.FromArgb(246, 247, 249);
    private readonly Color Card = Color.White;
    private readonly Color Ink = Color.FromArgb(28, 30, 34);
    private readonly Color Muted = Color.FromArgb(105, 110, 120);
    private readonly Color Primary = Color.FromArgb(31, 35, 42);
    private readonly Color Border = Color.FromArgb(224, 227, 232);
    private readonly Color Good = Color.FromArgb(31, 138, 76);

    private readonly NotifyIcon tray;
    private readonly Icon trayIcon;
    private readonly FlowLayoutPanel flow;
    private readonly Label status;
    private readonly Label deviceName;
    private readonly Label deviceId;
    private readonly FlowLayoutPanel peersPanel;
    private readonly Panel pairPanel;
    private readonly TextBox pairInput;
    private readonly object logLock = new object();
    private Process daemon;
    private bool quitting;
    private UiState latestState;

    public ClipMeshForm()
    {
        Text = "ClipMesh";
        Width = 650;
        Height = 690;
        MinimumSize = new Size(600, 620);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Page;
        AutoScaleMode = AutoScaleMode.Dpi;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        Panel scroller = new Panel();
        scroller.Dock = DockStyle.Fill;
        scroller.AutoScroll = true;
        scroller.BackColor = Page;
        Controls.Add(scroller);

        flow = new FlowLayoutPanel();
        flow.FlowDirection = FlowDirection.TopDown;
        flow.WrapContents = false;
        flow.AutoSize = true;
        flow.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        flow.Padding = new Padding(24, 22, 24, 30);
        flow.BackColor = Page;
        flow.Width = 610;
        scroller.Controls.Add(flow);

        Panel header = new Panel();
        header.Width = 558;
        header.Height = 66;
        header.BackColor = Page;
        Label title = MakeLabel("ClipMesh", 24, FontStyle.Bold, Ink);
        title.SetBounds(0, 0, 350, 36);
        Label subtitle = MakeLabel("Private clipboard sync", 10, FontStyle.Regular, Muted);
        subtitle.SetBounds(2, 38, 300, 22);
        Button settings = MakeButton("Settings", false);
        settings.SetBounds(452, 6, 104, 42);
        settings.Click += delegate { ShowSettings(); };
        header.Controls.Add(title);
        header.Controls.Add(subtitle);
        header.Controls.Add(settings);
        flow.Controls.Add(header);

        status = MakeLabel("Starting…", 9, FontStyle.Regular, Muted);
        status.Width = 558;
        status.Height = 28;
        flow.Controls.Add(status);

        Panel deviceCard = MakeCard(124);
        Label deviceCaption = MakeLabel("THIS DEVICE", 8, FontStyle.Bold, Muted);
        deviceCaption.SetBounds(18, 15, 300, 20);
        deviceName = MakeLabel("Windows PC", 16, FontStyle.Bold, Ink);
        deviceName.SetBounds(18, 39, 390, 30);
        deviceId = MakeLabel("", 8, FontStyle.Regular, Muted);
        deviceId.SetBounds(18, 70, 360, 22);
        Button rename = MakeButton("Rename", false);
        rename.SetBounds(430, 50, 108, 42);
        rename.Click += delegate { RenameDevice(); };
        deviceCard.Controls.Add(deviceCaption);
        deviceCard.Controls.Add(deviceName);
        deviceCard.Controls.Add(deviceId);
        deviceCard.Controls.Add(rename);
        flow.Controls.Add(deviceCard);

        Panel peersCard = MakeCard(150);
        Label peersCaption = MakeLabel("DEVICES", 8, FontStyle.Bold, Muted);
        peersCaption.SetBounds(18, 15, 300, 20);
        Button refresh = MakeButton("Refresh", false);
        refresh.SetBounds(444, 10, 94, 38);
        refresh.Click += delegate { RefreshHome(); };
        peersPanel = new FlowLayoutPanel();
        peersPanel.FlowDirection = FlowDirection.TopDown;
        peersPanel.WrapContents = false;
        peersPanel.AutoSize = false;
        peersPanel.SetBounds(18, 50, 520, 88);
        peersPanel.BackColor = Card;
        peersCard.Controls.Add(peersCaption);
        peersCard.Controls.Add(refresh);
        peersCard.Controls.Add(peersPanel);
        flow.Controls.Add(peersCard);

        Panel quick = MakeCard(104);
        Label quickCaption = MakeLabel("QUICK ACTIONS", 8, FontStyle.Bold, Muted);
        quickCaption.SetBounds(18, 14, 300, 20);
        Button copyPairing = MakeButton("Copy pairing code", true);
        copyPairing.SetBounds(18, 47, 165, 42);
        copyPairing.Click += delegate { CopyPairingLink(); };
        Button clipboard = MakeButton("View clipboard", false);
        clipboard.SetBounds(193, 47, 160, 42);
        clipboard.Click += delegate { ViewClipboard(); };
        Button pair = MakeButton("Pair device", false);
        pair.SetBounds(363, 47, 175, 42);
        pair.Click += delegate { TogglePairPanel(); };
        quick.Controls.Add(quickCaption);
        quick.Controls.Add(copyPairing);
        quick.Controls.Add(clipboard);
        quick.Controls.Add(pair);
        flow.Controls.Add(quick);

        pairPanel = MakeCard(185);
        pairPanel.Visible = false;
        Label pairCaption = MakeLabel("PAIR DEVICE", 8, FontStyle.Bold, Muted);
        pairCaption.SetBounds(18, 14, 300, 20);
        Label pairHint = MakeLabel("Paste a pairing code from another trusted ClipMesh device, or create a new private space.", 9, FontStyle.Regular, Muted);
        pairHint.SetBounds(18, 37, 520, 34);
        pairInput = new TextBox();
        pairInput.SetBounds(18, 75, 520, 30);
        pairInput.Font = new Font("Consolas", 9);
        Button join = MakeButton("Join", true);
        join.SetBounds(18, 121, 110, 42);
        join.Click += delegate { JoinDevice(); };
        Button create = MakeButton("Create new", false);
        create.SetBounds(138, 121, 130, 42);
        create.Click += delegate { CreateNewSpace(); };
        Button copyMine = MakeButton("Copy my code", false);
        copyMine.SetBounds(278, 121, 145, 42);
        copyMine.Click += delegate { CopyPairingLink(); };
        pairPanel.Controls.Add(pairCaption);
        pairPanel.Controls.Add(pairHint);
        pairPanel.Controls.Add(pairInput);
        pairPanel.Controls.Add(join);
        pairPanel.Controls.Add(create);
        pairPanel.Controls.Add(copyMine);
        flow.Controls.Add(pairPanel);

        Label privacy = MakeLabel("Pairing codes contain the private space key. Only share them directly with devices you trust.", 8, FontStyle.Regular, Muted);
        privacy.Width = 558;
        privacy.Height = 35;
        flow.Controls.Add(privacy);

        ContextMenuStrip menu = new ContextMenuStrip();
        ToolStripMenuItem show = new ToolStripMenuItem("Show ClipMesh");
        show.Click += delegate { RestoreFromTray(); };
        menu.Items.Add(show);
        ToolStripMenuItem copy = new ToolStripMenuItem("Copy Pairing Code");
        copy.Click += delegate { CopyPairingLink(); };
        menu.Items.Add(copy);
        menu.Items.Add(new ToolStripSeparator());
        ToolStripMenuItem quit = new ToolStripMenuItem("Quit ClipMesh");
        quit.Click += delegate { QuitCompletely(); };
        menu.Items.Add(quit);

        trayIcon = CreateTrayIcon();
        tray = new NotifyIcon();
        tray.Icon = trayIcon;
        tray.Text = "ClipMesh";
        tray.Visible = true;
        tray.ContextMenuStrip = menu;
        tray.MouseClick += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) RestoreFromTray(); };

        FormClosing += OnFormClosing;
        Shown += OnShown;
        Resize += delegate { flow.Width = Math.Max(580, ClientSize.Width - 24); };
    }

    private void OnShown(object sender, EventArgs e)
    {
        Task.Run(delegate
        {
            try
            {
                ClipMeshRuntime.PrepareFirstRun();
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
            dialog.Height = 245;
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
            dialog.Controls.Add(title);
            dialog.Controls.Add(send);
            dialog.Controls.Add(receive);
            dialog.Controls.Add(save);
            dialog.Controls.Add(cancel);
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
        button.BackColor = primaryStyle ? Primary : Color.FromArgb(249, 250, 251);
        button.ForeColor = primaryStyle ? Color.White : Ink;
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
