use anyhow::{Context, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use clipmesh_core::MasterKey;
use keyring::Entry;
use uuid::Uuid;

const SERVICE: &str = "dev.clipmesh.private";

fn entry(space_id: Uuid) -> Result<Entry> {
    Entry::new(SERVICE, &format!("space:{space_id}"))
        .context("create OS keyring entry")
}

pub fn save(space_id: Uuid, key: &MasterKey) -> Result<()> {
    entry(space_id)?.set_password(&URL_SAFE_NO_PAD.encode(key.0))
        .context("store space key in OS keyring")
}

pub fn load(space_id: Uuid) -> Result<MasterKey> {
    let value = entry(space_id)?.get_password().context("read space key from OS keyring")?;
    let bytes = URL_SAFE_NO_PAD.decode(value.trim()).context("decode stored space key")?;
    MasterKey::from_slice(&bytes)
}

pub fn delete(space_id: Uuid) -> Result<()> {
    let _ = entry(space_id)?.delete_credential();
    Ok(())
}
