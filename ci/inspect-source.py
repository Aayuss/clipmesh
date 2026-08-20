from pathlib import Path

root = Path(__file__).resolve().parents[1] / "clipmesh"
print("=== CLIPMESH SOURCE TREE ===")
for p in sorted(root.rglob("*")):
    if p.is_file() and p.suffix in {".rs", ".kt", ".kts", ".xml", ".toml"}:
        print(p.relative_to(root))

keywords = (
    "pairing-uri", "pairing", "join", "device_name", "device name", "peer", "clipboard",
    "config", "space_id", "SyncService", "MainActivity", "status"
)
print("=== RELEVANT SOURCE FILES ===")
for p in sorted(root.rglob("*")):
    if not p.is_file() or p.suffix not in {".rs", ".kt", ".kts", ".xml", ".toml"}:
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        continue
    lower = text.lower()
    if any(k.lower() in lower for k in keywords):
        print(f"\n===== {p.relative_to(root)} =====")
        print(text[:30000])
