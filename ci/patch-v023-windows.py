from pathlib import Path

root = Path(__file__).resolve().parents[1]
ui = root / "ci" / "ClipMeshWindows.cs"
text = ui.read_text(encoding="utf-8")
old = 'private const string Version = "0.2.2";'
new = 'private const string Version = "0.2.3";'
if text.count(old) != 1:
    raise SystemExit(f"Windows v0.2.3 version anchor mismatch: {text.count(old)}")
ui.write_text(text.replace(old, new, 1), encoding="utf-8")
if new not in ui.read_text(encoding="utf-8"):
    raise SystemExit("Windows v0.2.3 runtime version guard missing")
print("Applied ClipMesh v0.2.3 Windows runtime version patch")
