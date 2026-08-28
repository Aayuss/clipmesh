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


windows = root / "ci/ClipMeshWindows.cs"
text = windows.read_text(encoding="utf-8")
text, version_count = re.subn(
    r'private const string Version = "[^"]+";',
    'private const string Version = "0.2.0";',
    text,
    count=1,
)
if version_count != 1:
    raise SystemExit("Windows native version anchor missing")
windows.write_text(text, encoding="utf-8")

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
replace_once(
    windows,
    'Label subtitle = MakeLabel("Private clipboard sync", 10, FontStyle.Regular, Muted);',
    'Label subtitle = MakeLabel("Clipboard sync + nearby file drop", 10, FontStyle.Regular, Muted);',
    "Windows subtitle",
)
replace_once(windows, '        Panel quick = MakeCard(104);', '        Panel quick = MakeCard(156);', "Windows taller quick actions")
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
replace_once(
    windows,
    'button.BackColor = primaryStyle ? Primary : Color.FromArgb(249, 250, 251);',
    'button.BackColor = primaryStyle ? Primary : Color.FromArgb(242, 238, 218);',
    "Windows button surface",
)
replace_once(
    windows,
    'button.ForeColor = primaryStyle ? Color.White : Ink;',
    'button.ForeColor = primaryStyle ? Ink : Color.FromArgb(44, 42, 34);',
    "Windows button text",
)

# Explorer verbs use a lightweight second ClipMesh process for the chooser.
# Insert before whatever mutex/smoke-test logic earlier version patches have.
main_anchor = '''    [STAThread]
    private static int Main(string[] args)
    {
'''
main_insertion = '''    [STAThread]
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
'''
replace_once(windows, main_anchor, main_insertion, "Windows Explorer share launch")

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

print("Applied ClipMesh v0.2.0 Windows file-transfer, Explorer action, tray UI, warm theme, and native version metadata")
