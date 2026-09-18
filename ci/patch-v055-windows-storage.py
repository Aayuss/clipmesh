from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"


def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8"); found = text.count(old)
    if found != count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")

def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8"); updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=flags)
    if found != count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")

ui = ROOT / "ci/ClipMeshWindows.cs"; transfer = ROOT / "ci/ClipMeshTransfer.cs"
replace(transfer,"    public string Fingerprint\n    {","""    public string OutputFolder
    {
        get
        {
            string file = Path.Combine(StoreDir, "output-folder.txt");
            if (File.Exists(file)) { string found = File.ReadAllText(file).Trim(); if (found.Length > 0) return found; }
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "ClipMesh");
        }
        set
        {
            string selected = Path.GetFullPath(value); Directory.CreateDirectory(selected); File.WriteAllText(Path.Combine(StoreDir, "output-folder.txt"), selected);
        }
    }

    public string Fingerprint
    {""","windows output folder preference")
regex(transfer,r"    private string Destination\(TransferFileMetaC meta\)\n    \{.*?\n    \}",r'''    private string Destination(TransferFileMetaC meta)
    {
        string folder = OutputFolder;
        if (meta.Mime.StartsWith("image/", StringComparison.OrdinalIgnoreCase)) folder = Path.Combine(folder, "images");
        else if (meta.Mime.StartsWith("video/", StringComparison.OrdinalIgnoreCase)) folder = Path.Combine(folder, "video");
        Directory.CreateDirectory(folder); string name = SafeName(meta.Name); string path = Path.Combine(folder, name); int i = 2; string stem = Path.GetFileNameWithoutExtension(name), ext = Path.GetExtension(name);
        while (File.Exists(path)) { path = Path.Combine(folder, stem + " (" + i + ")" + ext); i++; } return path;
    }''',"windows selected output destination")
replace(ui,'        transferFileLabel = MakeLabel("Drop files anywhere in the ClipMesh window", 9, FontStyle.Regular, Muted); transferFileLabel.Width = 650; transferFileLabel.Height = 28; tf.Controls.Add(transferFileLabel);','''        transferFileLabel = MakeLabel("Drop files anywhere in the ClipMesh window", 9, FontStyle.Regular, Muted); transferFileLabel.Width = 650; transferFileLabel.Height = 28; tf.Controls.Add(transferFileLabel);
        Panel outputRow = MakeCard(76); outputRow.Width = 650; Label outputTitle = MakeLabel("Receive folder", 9, FontStyle.Bold, Ink); outputTitle.SetBounds(18, 10, 420, 22); Label outputPath = MakeLabel(LocalTransferManagerC.Shared.OutputFolder, 8, FontStyle.Regular, Muted); outputPath.SetBounds(18, 35, 450, 24); Button chooseOutput = MakeButton("Choose folder", false); chooseOutput.SetBounds(500, 17, 132, 40); chooseOutput.Click += delegate { ChooseOutputFolder(outputPath); }; outputRow.Controls.Add(outputTitle); outputRow.Controls.Add(outputPath); outputRow.Controls.Add(chooseOutput); tf.Controls.Add(outputRow);''',"windows receive folder UI")
replace(ui,"    private void ChooseTransferFiles()","""    private void ChooseOutputFolder(Label label)
    {
        using (FolderBrowserDialog picker = new FolderBrowserDialog())
        {
            picker.Description = "Choose ClipMesh receive folder"; picker.SelectedPath = LocalTransferManagerC.Shared.OutputFolder; picker.ShowNewFolderButton = true;
            if (picker.ShowDialog(this) != DialogResult.OK || String.IsNullOrWhiteSpace(picker.SelectedPath)) return;
            try { LocalTransferManagerC.Shared.OutputFolder = picker.SelectedPath; label.Text = LocalTransferManagerC.Shared.OutputFolder; }
            catch (Exception ex) { ShowError(ex.Message); }
        }
    }

    private void ChooseTransferFiles()""","windows output folder chooser")
