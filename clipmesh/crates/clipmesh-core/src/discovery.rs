use crate::crypto::{derive_discovery_key, MasterKey};
use crate::protocol::now_ms;
use anyhow::{bail, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use hmac::{Hmac, Mac};
use rand::{rngs::OsRng, RngCore};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use subtle::ConstantTimeEq;
use uuid::Uuid;

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiscoveryPacket {
    pub v: u8,
    pub space_id: Uuid,
    pub device_id: Uuid,
    pub name: String,
    pub port: u16,
    pub timestamp_ms: i64,
    pub mac: String,
}

impl DiscoveryPacket {
    pub fn signed(master: &MasterKey, space_id: Uuid, device_id: Uuid, name: String, port: u16) -> Result<Self> {
        let timestamp_ms = now_ms();
        let mut p = Self { v: 1, space_id, device_id, name, port, timestamp_ms, mac: String::new() };
        p.mac = URL_SAFE_NO_PAD.encode(p.compute_mac(master)?);
        Ok(p)
    }

    pub fn verify(&self, master: &MasterKey, expected_space: Uuid) -> Result<()> {
        if self.v != 1 || self.space_id != expected_space { bail!("wrong discovery version/space"); }
        if (now_ms() - self.timestamp_ms).abs() > 120_000 { bail!("stale discovery packet"); }
        let claimed = URL_SAFE_NO_PAD.decode(&self.mac)?;
        let actual = self.compute_mac(master)?;
        if claimed.len() != 32 || claimed.ct_eq(&actual).unwrap_u8() != 1 { bail!("invalid discovery MAC"); }
        Ok(())
    }

    fn canonical(&self) -> Vec<u8> {
        format!("{}\0{}\0{}\0{}\0{}\0{}", self.v, self.space_id, self.device_id, self.name, self.port, self.timestamp_ms).into_bytes()
    }

    fn compute_mac(&self, master: &MasterKey) -> Result<[u8; 32]> {
        let key = derive_discovery_key(master, self.space_id)?;
        let mut mac = HmacSha256::new_from_slice(&key).expect("HMAC accepts any key size");
        mac.update(&self.canonical());
        let bytes = mac.finalize().into_bytes();
        let mut out = [0u8; 32];
        out.copy_from_slice(&bytes);
        Ok(out)
    }
}

pub const HELLO_MAGIC: &[u8;4] = b"CMH1";
pub const HELLO_SIZE: usize = 4 + 16 + 16 + 8 + 16 + 32;

#[derive(Debug, Clone)]
pub struct Hello {
    pub space_id: Uuid,
    pub device_id: Uuid,
    pub timestamp_ms: i64,
    pub nonce: [u8;16],
}

impl Hello {
    pub fn create(master: &MasterKey, space_id: Uuid, device_id: Uuid) -> Result<Vec<u8>> {
        let mut nonce=[0u8;16]; OsRng.fill_bytes(&mut nonce);
        let timestamp_ms=now_ms();
        let mut body=Vec::with_capacity(HELLO_SIZE);
        body.extend_from_slice(HELLO_MAGIC);
        body.extend_from_slice(space_id.as_bytes());
        body.extend_from_slice(device_id.as_bytes());
        body.extend_from_slice(&timestamp_ms.to_be_bytes());
        body.extend_from_slice(&nonce);
        let key=derive_discovery_key(master, space_id)?;
        let mut mac=HmacSha256::new_from_slice(&key).expect("HMAC key");
        mac.update(&body);
        body.extend_from_slice(&mac.finalize().into_bytes());
        Ok(body)
    }

    pub fn verify(master: &MasterKey, expected_space: Uuid, bytes: &[u8]) -> Result<Self> {
        if bytes.len()!=HELLO_SIZE || &bytes[0..4]!=HELLO_MAGIC { bail!("invalid hello"); }
        let space_id=Uuid::from_slice(&bytes[4..20])?;
        if space_id!=expected_space { bail!("wrong space"); }
        let device_id=Uuid::from_slice(&bytes[20..36])?;
        let timestamp_ms=i64::from_be_bytes(bytes[36..44].try_into()?);
        if (now_ms()-timestamp_ms).abs()>120_000 { bail!("stale hello"); }
        let mut nonce=[0u8;16]; nonce.copy_from_slice(&bytes[44..60]);
        let key=derive_discovery_key(master, space_id)?;
        let mut mac=HmacSha256::new_from_slice(&key).expect("HMAC key");
        mac.update(&bytes[..60]);
        mac.verify_slice(&bytes[60..92]).map_err(|_| anyhow::anyhow!("invalid hello MAC"))?;
        Ok(Self{space_id,device_id,timestamp_ms,nonce})
    }
}
