from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
source = root / "ci" / "build-macos-v2.sh.fixed"
target = root / "clipmesh" / "scripts" / "build-macos.sh"

if not source.is_file():
    raise SystemExit(f"Missing {source}")
if not target.parent.is_dir():
    raise SystemExit(f"Missing extracted macOS scripts directory: {target.parent}")

shutil.copyfile(source, target)
target.chmod(0o755)
print(f"Applied repaired native macOS packaging patch to {target}")
