using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

internal sealed class CliResult
{
    public int ExitCode;
    public string Output = "";
    public string Error = "";
}

internal static class ClipMeshRuntime
{
    private const string Version = "0.1.2";

    public static string RuntimeDirectory
    {
        get
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ClipMesh", "Runtime", Version);
        }
    }

    public static string EnginePath
    {
        get { return Path.Combine(RuntimeDirectory, "clipmesh-bin.exe"); }
    }

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
            if (source == null)
                throw new InvalidOperationException("The embedded ClipMesh sync engine is missing.");

            using (FileStream target = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None))
                source.CopyTo(target);
        }

        if (File.Exists(EnginePath))
            File.Delete(EnginePath);
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
            if (process == null)
                throw new InvalidOperationException("Could not start the ClipMesh sync engine.");

            string output = process.StandardOutput.ReadToEnd();
            string error = process.StandardError.ReadToEnd();
            process.WaitForExit();
            return new CliResult { ExitCode = process.ExitCode, Output = output, Error = error };
        }
    }

    public static void PrepareFirstRun()
    {
        EnsureEngine();

        CliResult status = Run("status");
        if (status.ExitCode == 0)
            return;

        string detail = (status.Error + "\n" + status.Output).Trim();
        bool missingKey = Contains(detail, "read space key from OS keyring") ||
                          Contains(detail, "No matching entry found in secure storage");
        bool missingConfig = Contains(detail, "config.json") &&
                             (Contains(detail, "os error 2") ||
                              Contains(detail, "cannot find the file") ||
                              Contains(detail, "cannot find the path") ||
                              Contains(detail, "No such file or directory"));

        if (missingKey)
        {
            bool moved = false;
            foreach (string config in ConfigCandidates)
            {
                if (!File.Exists(config))
                    continue;

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

        CliResult init = Run("init", "--name", Environment.MachineName);
        if (init.ExitCode != 0)
            throw new InvalidOperationException("Could not initialize ClipMesh.\n" + PreferredError(init));

        CliResult verify = Run("status");
        if (verify.ExitCode != 0)
            throw new InvalidOperationException("ClipMesh initialized, but its secure key could not be loaded.\n" + PreferredError(verify));
    }

    public static string PairingLink()
    {
        CliResult result = Run("pairing-uri");
        if (result.ExitCode != 0)
            throw new InvalidOperationException("Could not create the pairing link.\n" + PreferredError(result));
        return result.Output.Trim();
    }

    public static Process StartDaemon(Action<string> logLine, Action<int> exited)
    {
        string logDir = Path.GetDirectoryName(LogPath);
        if (!String.IsNullOrEmpty(logDir))
            Directory.CreateDirectory(logDir);

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
        process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e)
        {
            if (e.Data != null) logLine(e.Data);
        };
        process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
        {
            if (e.Data != null) logLine(e.Data);
        };
        process.Exited += delegate
        {
            exited(process.ExitCode);
        };

        if (!process.Start())
            throw new InvalidOperationException("Could not start ClipMesh in the background.");
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
        for (int i = 0; i < args.Length; i++)
            quoted[i] = Quote(args[i]);
        return String.Join(" ", quoted);
    }

    private static string Quote(string value)
    {
        if (value.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0)
            return value;
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}

internal sealed class ClipMeshForm : Form
{
    private readonly NotifyIcon tray;
    private readonly Label status;
    private readonly Label detail;
    private readonly Button pairing;
    private readonly Button background;
    private readonly object logLock = new object();
    private Process daemon;
    private bool quitting;

    public ClipMeshForm()
    {
        Text = "ClipMesh";
        Width = 520;
        Height = 390;
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        PictureBox icon = new PictureBox();
        icon.Image = Icon.ToBitmap();
        icon.SizeMode = PictureBoxSizeMode.Zoom;
        icon.SetBounds(210, 32, 88, 88);
        Controls.Add(icon);

        Label title = new Label();
        title.Text = "ClipMesh";
        title.Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 22, FontStyle.Bold);
        title.TextAlign = ContentAlignment.MiddleCenter;
        title.SetBounds(40, 128, 425, 40);
        Controls.Add(title);

        status = new Label();
        status.Text = "Starting…";
        status.Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 11, FontStyle.Bold);
        status.TextAlign = ContentAlignment.MiddleCenter;
        status.SetBounds(40, 175, 425, 28);
        Controls.Add(status);

        detail = new Label();
        detail.Text = "Private encrypted clipboard sync on your local network.";
        detail.ForeColor = SystemColors.GrayText;
        detail.TextAlign = ContentAlignment.MiddleCenter;
        detail.SetBounds(55, 209, 395, 55);
        Controls.Add(detail);

        pairing = new Button();
        pairing.Text = "Copy Pairing Link";
        pairing.SetBounds(105, 285, 145, 34);
        pairing.Enabled = false;
        pairing.Click += delegate { CopyPairingLink(); };
        Controls.Add(pairing);

        background = new Button();
        background.Text = "Run in Background";
        background.SetBounds(260, 285, 145, 34);
        background.Click += delegate { HideToTray(); };
        Controls.Add(background);

        ContextMenuStrip menu = new ContextMenuStrip();
        ToolStripMenuItem show = new ToolStripMenuItem("Show ClipMesh");
        show.Click += delegate { RestoreFromTray(); };
        menu.Items.Add(show);
        ToolStripMenuItem copy = new ToolStripMenuItem("Copy Pairing Link");
        copy.Click += delegate { CopyPairingLink(); };
        menu.Items.Add(copy);
        menu.Items.Add(new ToolStripSeparator());
        ToolStripMenuItem quit = new ToolStripMenuItem("Quit ClipMesh");
        quit.Click += delegate { QuitCompletely(); };
        menu.Items.Add(quit);

        tray = new NotifyIcon();
        tray.Icon = Icon;
        tray.Text = "ClipMesh";
        tray.Visible = true;
        tray.ContextMenuStrip = menu;
        tray.MouseClick += delegate(object sender, MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left)
                RestoreFromTray();
        };

        FormClosing += OnFormClosing;
        Shown += OnShown;
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
                    status.Text = "ClipMesh is running";
                    status.ForeColor = Color.ForestGreen;
                    detail.Text = "Clipboard sync is active. Closing this window keeps ClipMesh running in the system tray.";
                    pairing.Enabled = true;
                });
            }
            catch (Exception ex)
            {
                Invoke((MethodInvoker)delegate
                {
                    status.Text = "ClipMesh could not start";
                    status.ForeColor = Color.Firebrick;
                    detail.Text = ex.Message;
                    pairing.Enabled = false;
                    RestoreFromTray();
                });
            }
        });
    }

    private void StartDaemon()
    {
        daemon = ClipMeshRuntime.StartDaemon(WriteLog, delegate(int exitCode)
        {
            if (quitting || IsDisposed) return;
            try
            {
                BeginInvoke((MethodInvoker)delegate
                {
                    if (quitting) return;
                    status.Text = "ClipMesh stopped";
                    status.ForeColor = Color.Firebrick;
                    detail.Text = "The background sync engine exited with code " + exitCode + ". Log: " + ClipMeshRuntime.LogPath;
                    RestoreFromTray();
                });
            }
            catch { }
        });
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
        if (e.CloseReason == CloseReason.WindowsShutDown || e.CloseReason == CloseReason.TaskManagerClosing)
            return;

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
    }

    private void CopyPairingLink()
    {
        try
        {
            string link = ClipMeshRuntime.PairingLink();
            Clipboard.SetText(link);
            status.Text = "Pairing link copied";
            status.ForeColor = Color.RoyalBlue;
            detail.Text = "Paste it into ClipMesh on the device you trust. The link contains the private space key, so do not share it publicly.";
        }
        catch (Exception ex)
        {
            status.Text = "Could not copy pairing link";
            status.ForeColor = Color.Firebrick;
            detail.Text = ex.Message;
            RestoreFromTray();
        }
    }

    private void QuitCompletely()
    {
        quitting = true;
        tray.Visible = false;
        if (daemon != null)
        {
            try
            {
                if (!daemon.HasExited)
                    daemon.Kill();
            }
            catch { }
        }
        Application.Exit();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            tray.Visible = false;
            tray.Dispose();
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
        if (!created)
            return 0;

        try
        {
            if (Array.IndexOf(args, "--smoke-test") >= 0)
            {
                ClipMeshRuntime.PrepareFirstRun();
                CliResult status = ClipMeshRuntime.Run("status");
                if (status.ExitCode != 0)
                {
                    Console.Error.WriteLine(status.Error);
                    return 1;
                }
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
