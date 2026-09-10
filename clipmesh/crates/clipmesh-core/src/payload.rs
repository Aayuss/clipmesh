use anyhow::{anyhow, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const DEFAULT_MAX_PAYLOAD_BYTES: usize = 64 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Representation {
    pub mime: String,
    pub data_b64: String,
}

impl Representation {
    pub fn from_bytes(mime: impl Into<String>, data: &[u8]) -> Self {
        Self { mime: mime.into(), data_b64: STANDARD.encode(data) }
    }

    pub fn bytes(&self) -> Result<Vec<u8>> {
        STANDARD.decode(&self.data_b64).map_err(Into::into)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FilePayload {
    pub name: String,
    pub sha256: String,
    pub data_b64: String,
}

impl FilePayload {
    pub fn from_bytes(name: impl Into<String>, data: &[u8]) -> Self {
        let mut hasher = Sha256::new();
        hasher.update(data);
        Self {
            name: name.into(),
            sha256: hex_lower(&hasher.finalize()),
            data_b64: STANDARD.encode(data),
        }
    }

    pub fn bytes_verified(&self) -> Result<Vec<u8>> {
        let bytes = STANDARD.decode(&self.data_b64)?;
        let mut hasher = Sha256::new();
        hasher.update(&bytes);
        let actual = hex_lower(&hasher.finalize());
        if actual != self.sha256.to_ascii_lowercase() {
            return Err(anyhow!("file SHA-256 mismatch"));
        }
        Ok(bytes)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ClipPayload {
    pub schema: u8,
    pub source_app: Option<String>,
    pub representations: Vec<Representation>,
    pub files: Vec<FilePayload>,
}

impl ClipPayload {
    pub fn new() -> Self {
        Self { schema: 1, source_app: None, representations: Vec::new(), files: Vec::new() }
    }

    pub fn to_json_bytes(&self, max_bytes: usize) -> Result<Vec<u8>> {
        let data = serde_json::to_vec(self)?;
        if data.len() > max_bytes {
            return Err(anyhow!("clipboard payload exceeds configured limit"));
        }
        Ok(data)
    }

    pub fn from_json_bytes(data: &[u8], max_bytes: usize) -> Result<Self> {
        if data.len() > max_bytes {
            return Err(anyhow!("clipboard payload exceeds configured limit"));
        }
        let payload: Self = serde_json::from_slice(data)?;
        if payload.schema != 1 {
            return Err(anyhow!("unsupported clipboard payload schema"));
        }
        Ok(payload)
    }

    pub fn stable_fingerprint(&self) -> Result<[u8; 32]> {
        // The foreground/source app differs after applying a remote clipboard.
        // Excluding it makes echo suppression depend only on clipboard content.
        let mut normalized = self.clone();
        normalized.source_app = None;
        let data = serde_json::to_vec(&normalized)?;
        let digest = Sha256::digest(data);
        let mut out = [0u8; 32];
        out.copy_from_slice(&digest);
        Ok(out)
    }
}

impl Default for ClipPayload {
    fn default() -> Self { Self::new() }
}

fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}
