use aes_gcm::{
    aead::{Aead, Payload},
    Aes256Gcm, KeyInit, Nonce,
};
use anyhow::{anyhow, Context, Result};
use hkdf::Hkdf;
use rand::{rngs::OsRng, RngCore};
use sha2::Sha256;
use uuid::Uuid;
use zeroize::{Zeroize, ZeroizeOnDrop};

#[derive(Clone, Zeroize, ZeroizeOnDrop)]
pub struct MasterKey(pub [u8; 32]);

impl MasterKey {
    pub fn generate() -> Self {
        let mut bytes = [0u8; 32];
        OsRng.fill_bytes(&mut bytes);
        Self(bytes)
    }

    pub fn from_slice(input: &[u8]) -> Result<Self> {
        if input.len() != 32 {
            return Err(anyhow!("space key must be exactly 32 bytes"));
        }
        let mut out = [0u8; 32];
        out.copy_from_slice(input);
        Ok(Self(out))
    }
}

pub fn derive_data_key(master: &MasterKey, space_id: Uuid, sender_id: Uuid) -> Result<[u8; 32]> {
    let hk = Hkdf::<Sha256>::new(Some(space_id.as_bytes()), &master.0);
    let mut info = b"clipmesh/aead/v1".to_vec();
    info.extend_from_slice(sender_id.as_bytes());
    let mut key = [0u8; 32];
    hk.expand(&info, &mut key)
        .map_err(|_| anyhow!("HKDF expansion failed"))?;
    Ok(key)
}

pub fn derive_discovery_key(master: &MasterKey, space_id: Uuid) -> Result<[u8; 32]> {
    let hk = Hkdf::<Sha256>::new(Some(space_id.as_bytes()), &master.0);
    let mut key = [0u8; 32];
    hk.expand(b"clipmesh/discovery/v1", &mut key)
        .map_err(|_| anyhow!("HKDF expansion failed"))?;
    Ok(key)
}

pub fn random_nonce_12() -> [u8; 12] {
    let mut nonce = [0u8; 12];
    OsRng.fill_bytes(&mut nonce);
    nonce
}

pub fn encrypt_aes_gcm(key: &[u8; 32], nonce: &[u8; 12], aad: &[u8], plaintext: &[u8]) -> Result<Vec<u8>> {
    let cipher = Aes256Gcm::new_from_slice(key).context("invalid AES key")?;
    cipher
        .encrypt(Nonce::from_slice(nonce), Payload { msg: plaintext, aad })
        .map_err(|_| anyhow!("AES-GCM encryption failed"))
}

pub fn decrypt_aes_gcm(key: &[u8; 32], nonce: &[u8; 12], aad: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>> {
    let cipher = Aes256Gcm::new_from_slice(key).context("invalid AES key")?;
    cipher
        .decrypt(Nonce::from_slice(nonce), Payload { msg: ciphertext, aad })
        .map_err(|_| anyhow!("AES-GCM authentication failed"))
}
