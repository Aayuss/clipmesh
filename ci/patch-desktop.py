from pathlib import Path

root = Path(__file__).resolve().parents[1]
cargo = root / "clipmesh" / "apps" / "desktop" / "Cargo.toml"
text = cargo.read_text(encoding="utf-8")
old = 'keyring = "3"'
new = 'keyring = { version = "3", default-features = false, features = ["apple-native", "windows-native"] }'
if old not in text and new not in text:
    raise SystemExit("Could not find the ClipMesh keyring dependency to patch")
if old in text:
    text = text.replace(old, new, 1)
cargo.write_text(text, encoding="utf-8")
print("Enabled native macOS Keychain and Windows Credential Manager backends")
