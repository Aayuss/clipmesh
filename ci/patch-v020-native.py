from pathlib import Path
import platform
import runpy

root = Path(__file__).resolve().parent
system = platform.system()

if system == "Darwin":
    target = root / "patch-v020-macos.py"
elif system == "Windows":
    target = root / "patch-v020-windows.py"
else:
    raise SystemExit(f"v0.2.0 native desktop patch is not supported on {system}")

runpy.run_path(str(target), run_name="__main__")
if system == "Darwin" and (root / "patch-v021-mac-anchor.py").is_file():
    runpy.run_path(str(root / "patch-v021-mac-anchor.py"), run_name="__main__")
