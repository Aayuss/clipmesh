from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
source = root / "ci" / "build-windows-v2.ps1.fixed"
target = root / "clipmesh" / "scripts" / "build-windows.ps1"

if not source.is_file():
    raise SystemExit(f"Missing {source}")
if not target.parent.is_dir():
    raise SystemExit(f"Missing extracted Windows scripts directory: {target.parent}")

shutil.copyfile(source, target)
print(f"Applied native Windows tray packaging patch to {target}")
