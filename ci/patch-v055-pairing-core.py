from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"


def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8")
    updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=flags)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared desktop clipboard engine fixes.
# A nearby-pair initiator must explicitly seed/unblock the responder after SAS
# verification. Previously only the receiver imported the initiator credential,
# leaving the initiator's old "Remove" block entry intact after a re-pair.
# ---------------------------------------------------------------------------
core = PROJECT / "apps/desktop/src/main.rs"
replace(
    core,
    "    ForgetPeer { device_id: uuid::Uuid },",
    "    ForgetPeer { device_id: uuid::Uuid },\n    SeedPeer { device_id: uuid::Uuid, #[arg(long)] name: String },",
    "desktop seed-peer CLI",
)
replace(
    core,
    "        Command::ForgetPeer{device_id} => forget_peer(device_id),",
    "        Command::ForgetPeer{device_id} => forget_peer(device_id),\n        Command::SeedPeer{device_id,name} => seed_peer(device_id,name),",
    "desktop seed-peer dispatch",
)
replace(
    core,
    "fn forget_peer(device_id:uuid::Uuid)->Result<()> {\n    let mut cfg=Config::load()?;\n    if device_id==cfg.device_id { bail!(\"cannot remove this device\"); }\n    if !cfg.blocked_devices.contains(&device_id) { cfg.blocked_devices.push(device_id); }\n    cfg.save()?; Config::forget_peer(cfg.space_id,device_id)?;\n    println!(\"Removed paired device {device_id}\"); Ok(())\n}\n\nfn set_name(name:String)->Result<()> {",
    """fn forget_peer(device_id:uuid::Uuid)->Result<()> {
    let mut cfg=Config::load()?;
    if device_id==cfg.device_id { bail!(\"cannot remove this device\"); }
    if !cfg.blocked_devices.contains(&device_id) { cfg.blocked_devices.push(device_id); }
    cfg.save()?; Config::forget_peer(cfg.space_id,device_id)?;
    println!(\"Removed paired device {device_id}\"); Ok(())
}

fn seed_peer(device_id:uuid::Uuid,name:String)->Result<()> {
    let mut cfg=Config::load()?;
    if device_id==cfg.device_id { bail!(\"cannot pair this device with itself\"); }
    cfg.blocked_devices.retain(|id| *id != device_id);
    cfg.save()?;
    Config::seed_peer(cfg.space_id,device_id,&sanitize_device_name(&name))?;
    println!(\"Seeded paired device {device_id}\"); Ok(())
}

fn set_name(name:String)->Result<()> {""",
    "desktop seed-peer implementation",
)
# Same-space pairing must not destroy the rest of an existing multi-device peer list.
replace(
    core,
    "    Config::clear_known_peers()?;\n    if let Some(source)=pairing.source_device_id.filter(|id|*id!=cfg.device_id) {",
    "    if old_space != Some(cfg.space_id) { Config::clear_known_peers()?; }\n    if let Some(source)=pairing.source_device_id.filter(|id|*id!=cfg.device_id) {",
    "desktop preserve same-space peer list",
)



print("Applied ClipMesh v0.2.17 bidirectional pairing core fixes")
