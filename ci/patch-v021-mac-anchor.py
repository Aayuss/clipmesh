from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "clipmesh/scripts/build-macos.sh"
text = path.read_text(encoding="utf-8")
old = 'codesign --force --deep --sign - "$APP"\ncodesign --verify --deep --strict --verbose=2 "$APP"'
new = 'if command -v codesign >/dev/null 2>&1; then\n  codesign --force --deep --sign - "$APP" || true\nfi\ncodesign --verify --deep --strict --verbose=2 "$APP"'
if old not in text:
    raise SystemExit("macOS v0.2.1 signing anchor missing before normalization")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Normalized macOS signing anchor for v0.2.1 extension packaging")
