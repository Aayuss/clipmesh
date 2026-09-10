use crate::crypto::{decrypt_aes_gcm, derive_data_key, encrypt_aes_gcm, random_nonce_12, MasterKey};
use anyhow::{anyhow, bail, Result};
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

pub const MAGIC: &[u8; 4] = b"CM01";
pub const VERSION: u8 = 1;
pub const FIXED_HEADER: usize = 4 + 1 + 1 + 2 + 16 + 16 + 8 + 12 + 4;
pub const MAX_FRAME_BYTES: usize = 72 * 1024 * 1024;
pub const MAX_CLOCK_SKEW_MS: i64 = 120_000;

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FrameKind {
    Clipboard = 1,
    Ack = 2,
    Ping = 3,
    Pong = 4,
}

impl TryFrom<u8> for FrameKind {
    type Error = anyhow::Error;
    fn try_from(value: u8) -> Result<Self> {
        match value {
            1 => Ok(Self::Clipboard),
            2 => Ok(Self::Ack),
            3 => Ok(Self::Ping),
            4 => Ok(Self::Pong),
            _ => bail!("unknown frame kind"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct ParsedFrame {
    pub kind: FrameKind,
    pub flags: u16,
    pub sender_id: Uuid,
    pub message_id: Uuid,
    pub timestamp_ms: i64,
    pub plaintext: Vec<u8>,
}

pub fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as i64
}

pub fn encrypt_frame(
    master: &MasterKey,
    space_id: Uuid,
    sender_id: Uuid,
    message_id: Uuid,
    kind: FrameKind,
    flags: u16,
    plaintext: &[u8],
) -> Result<Vec<u8>> {
    let timestamp_ms = now_ms();
    let nonce = random_nonce_12();
    let cipher_len = plaintext.len().checked_add(16).ok_or_else(|| anyhow!("frame too large"))?;
    if FIXED_HEADER + cipher_len > MAX_FRAME_BYTES {
        bail!("frame exceeds maximum size");
    }

    let mut header = Vec::with_capacity(FIXED_HEADER);
    header.extend_from_slice(MAGIC);
    header.push(VERSION);
    header.push(kind as u8);
    header.extend_from_slice(&flags.to_be_bytes());
    header.extend_from_slice(sender_id.as_bytes());
    header.extend_from_slice(message_id.as_bytes());
    header.extend_from_slice(&timestamp_ms.to_be_bytes());
    header.extend_from_slice(&nonce);
    header.extend_from_slice(&(cipher_len as u32).to_be_bytes());

    let key = derive_data_key(master, space_id, sender_id)?;
    let ciphertext = encrypt_aes_gcm(&key, &nonce, &header, plaintext)?;
    debug_assert_eq!(ciphertext.len(), cipher_len);
    header.extend_from_slice(&ciphertext);
    Ok(header)
}

pub fn decrypt_frame(master: &MasterKey, space_id: Uuid, bytes: &[u8], enforce_time: bool) -> Result<ParsedFrame> {
    if bytes.len() < FIXED_HEADER + 16 || bytes.len() > MAX_FRAME_BYTES {
        bail!("invalid frame length");
    }
    if &bytes[0..4] != MAGIC || bytes[4] != VERSION {
        bail!("invalid protocol magic/version");
    }
    let kind = FrameKind::try_from(bytes[5])?;
    let flags = u16::from_be_bytes([bytes[6], bytes[7]]);
    let sender_id = Uuid::from_slice(&bytes[8..24])?;
    let message_id = Uuid::from_slice(&bytes[24..40])?;
    let timestamp_ms = i64::from_be_bytes(bytes[40..48].try_into()?);
    let mut nonce = [0u8; 12];
    nonce.copy_from_slice(&bytes[48..60]);
    let cipher_len = u32::from_be_bytes(bytes[60..64].try_into()?) as usize;
    if cipher_len != bytes.len() - FIXED_HEADER {
        bail!("ciphertext length mismatch");
    }
    if enforce_time && (now_ms() - timestamp_ms).abs() > MAX_CLOCK_SKEW_MS {
        bail!("frame timestamp outside acceptance window");
    }
    let key = derive_data_key(master, space_id, sender_id)?;
    let plaintext = decrypt_aes_gcm(&key, &nonce, &bytes[..FIXED_HEADER], &bytes[FIXED_HEADER..])?;
    Ok(ParsedFrame { kind, flags, sender_id, message_id, timestamp_ms, plaintext })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn frame_roundtrip_and_tamper_rejection() {
        let master = MasterKey::generate();
        let space = Uuid::new_v4();
        let sender = Uuid::new_v4();
        let msg = Uuid::new_v4();
        let frame = encrypt_frame(&master, space, sender, msg, FrameKind::Clipboard, 0, b"secret").unwrap();
        let out = decrypt_frame(&master, space, &frame, true).unwrap();
        assert_eq!(out.plaintext, b"secret");
        let mut altered = frame.clone();
        let last = altered.len() - 1;
        altered[last] ^= 1;
        assert!(decrypt_frame(&master, space, &altered, true).is_err());
    }
}
