use crate::{config::Config, exclusions};
use anyhow::{Context, Result};
use clipmesh_core::{ClipPayload, FilePayload, Representation};
use clipboard_rs::{
    common::RustImage, Clipboard, ClipboardContent, ClipboardContext, ClipboardHandler,
    ClipboardWatcher, ClipboardWatcherContext, ContentFormat, RustImageData,
};
use parking_lot::Mutex;
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio::sync::mpsc;
use tracing::{debug, warn};
use url::Url;
use uuid::Uuid;

pub struct ClipboardState {
    suppressed: Mutex<Option<[u8; 32]>>,
    last_observed: Mutex<Option<[u8; 32]>>,
}

impl ClipboardState {
    pub fn new() -> Self {
        Self { suppressed: Mutex::new(None), last_observed: Mutex::new(None) }
    }
    pub fn seed(&self, fingerprint: [u8; 32]) {
        *self.last_observed.lock()=Some(fingerprint);
    }
    pub fn suppress(&self, fingerprint: [u8; 32]) {
        *self.suppressed.lock()=Some(fingerprint);
        *self.last_observed.lock()=Some(fingerprint);
    }
    fn should_emit(&self, fingerprint: &[u8; 32]) -> bool {
        {
            let mut last=self.last_observed.lock();
            if last.as_ref()==Some(fingerprint) { return false; }
            *last=Some(*fingerprint);
        }
        let mut suppressed=self.suppressed.lock();
        if suppressed.as_ref()==Some(fingerprint) {
            *suppressed=None;
            return false;
        }
        true
    }
}

struct Handler {
    ctx: ClipboardContext,
    cfg: Config,
    state: Arc<ClipboardState>,
    tx: mpsc::UnboundedSender<ClipPayload>,
}

impl ClipboardHandler for Handler {
    fn on_clipboard_change(&mut self) {
        if !self.cfg.send_enabled { return; }
        match read_payload(&self.ctx, &self.cfg) {
            Ok(Some(payload)) => {
                match payload.stable_fingerprint() {
                    Ok(fp) if self.state.should_emit(&fp) => { let _=self.tx.send(payload); }
                    Ok(_) => debug!("ignored unchanged/suppressed clipboard"),
                    Err(e) => warn!(error=%e, "could not fingerprint clipboard"),
                }
            }
            Ok(None) => {}
            Err(e) => warn!(error=%e, "clipboard read failed"),
        }
    }
}

pub fn spawn_watcher(cfg: Config, state: Arc<ClipboardState>, tx: mpsc::UnboundedSender<ClipPayload>) -> Result<()> {
    let ctx=ClipboardContext::new().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    if let Ok(Some(payload))=read_payload(&ctx,&cfg) {
        if let Ok(fp)=payload.stable_fingerprint() { state.seed(fp); }
    }
    let handler=Handler{ctx,cfg:cfg.clone(),state:state.clone(),tx:tx.clone()};
    let mut watcher=ClipboardWatcherContext::new().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    watcher.add_handler(handler);
    std::thread::Builder::new().name("clipmesh-clipboard-watch".into()).spawn(move || {
        watcher.start_watch();
    })?;

    #[cfg(target_os="macos")]
    {
        let poll_cfg=cfg.clone();
        let poll_state=state.clone();
        let poll_tx=tx.clone();
        std::thread::Builder::new().name("clipmesh-macos-pasteboard-fallback".into()).spawn(move || {
            let Ok(ctx)=ClipboardContext::new() else { return; };
            loop {
                std::thread::sleep(std::time::Duration::from_millis(1500));
                match read_payload(&ctx,&poll_cfg) {
                    Ok(Some(payload)) => match payload.stable_fingerprint() {
                        Ok(fp) if poll_state.should_emit(&fp) => { let _=poll_tx.send(payload); }
                        Ok(_) => {}
                        Err(e) => debug!(error=%e,"macOS pasteboard fallback fingerprint failed"),
                    },
                    Ok(None) => {}
                    Err(e) => debug!(error=%e,"macOS pasteboard fallback read failed"),
                }
            }
        })?;
    }
    Ok(())
}

fn read_payload(ctx: &ClipboardContext, cfg: &Config) -> Result<Option<ClipPayload>> {
    let source=exclusions::active_app();
    // Never suppress ClipMesh itself. Remote echoes are already suppressed using
    // payload fingerprints, and source-app detection can observe ClipMesh after the
    // user switches back to the UI even though the copy happened in another app.
    let source_is_clipmesh = source.as_deref()
        .map(|value| value.to_ascii_lowercase().contains("clipmesh"))
        .unwrap_or(false);
    if !source_is_clipmesh && exclusions::is_excluded(source.as_deref(), &cfg.exclusions) {
        debug!(source=?source, "clipboard source excluded");
        return Ok(None);
    }

    let mut p=ClipPayload::new();
    p.source_app=source;

    // Pairing links contain the private space key. Copying one is an explicit
    // local pairing action and must never turn into a normal synced clipboard event.
    if ctx.has(ContentFormat::Text) {
        if let Ok(v)=ctx.get_text() {
            if v.trim_start().to_ascii_lowercase().starts_with("clipmesh://pair?") {
                debug!("ignored ClipMesh pairing link on clipboard");
                return Ok(None);
            }
        }
    }

    if ctx.has(ContentFormat::Text) {
        if let Ok(v)=ctx.get_text() { if !v.is_empty() { p.representations.push(Representation::from_bytes("text/plain; charset=utf-8",v.as_bytes())); } }
    }
    if ctx.has(ContentFormat::Html) {
        if let Ok(v)=ctx.get_html() { if !v.is_empty() { p.representations.push(Representation::from_bytes("text/html; charset=utf-8",v.as_bytes())); } }
    }
    if ctx.has(ContentFormat::Rtf) {
        if let Ok(v)=ctx.get_rich_text() { if !v.is_empty() { p.representations.push(Representation::from_bytes("text/rtf",v.as_bytes())); } }
    }
    if ctx.has(ContentFormat::Image) {
        if let Ok(img)=ctx.get_image() {
            if let Ok(png)=img.to_png() {
                p.representations.push(Representation::from_bytes("image/png", png.get_bytes()));
            }
        }
    }
    if ctx.has(ContentFormat::Files) {
        if let Ok(paths)=ctx.get_files() {
            let mut running=0usize;
            for raw in paths {
                let path=normalize_file_path(&raw);
                if let Ok(meta)=fs::metadata(&path) {
                    if !meta.is_file() { continue; }
                    let len=meta.len() as usize;
                    if running.saturating_add(len)>cfg.max_payload_bytes { warn!(file=%path.display(), "file skipped: payload limit"); break; }
                    let data=fs::read(&path).with_context(|| format!("read clipboard file {}",path.display()))?;
                    running+=data.len();
                    let name=path.file_name().and_then(|x|x.to_str()).unwrap_or("clipboard-file").to_string();
                    p.files.push(FilePayload::from_bytes(name,&data));
                }
            }
        }
    }

    if p.representations.is_empty() && p.files.is_empty() { return Ok(None); }
    p.to_json_bytes(cfg.max_payload_bytes)?;
    Ok(Some(p))
}

fn normalize_file_path(raw: &str) -> PathBuf {
    if raw.starts_with("file:") {
        if let Ok(url)=Url::parse(raw) { if let Ok(p)=url.to_file_path() { return p; } }
    }
    PathBuf::from(raw)
}

pub fn apply_remote(payload: &ClipPayload, cfg: &Config, state: &ClipboardState, message_id: Uuid) -> Result<()> {
    if !cfg.receive_enabled { return Ok(()); }
    let ctx=ClipboardContext::new().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    let mut contents: Vec<ClipboardContent>=Vec::new();

    for rep in &payload.representations {
        let bytes=rep.bytes()?;
        let mime=rep.mime.to_ascii_lowercase();
        if mime.starts_with("text/plain") {
            contents.push(ClipboardContent::Text(String::from_utf8(bytes)?));
        } else if mime.starts_with("text/html") {
            contents.push(ClipboardContent::Html(String::from_utf8(bytes)?));
        } else if mime.starts_with("text/rtf") {
            contents.push(ClipboardContent::Rtf(String::from_utf8(bytes)?));
        } else if mime == "image/png" {
            let img=RustImageData::from_bytes(&bytes).map_err(|e| anyhow::anyhow!(e.to_string()))?;
            contents.push(ClipboardContent::Image(img));
        }
    }

    if !payload.files.is_empty() {
        let base=Config::cache_dir()?.join("received").join(message_id.to_string());
        fs::create_dir_all(&base)?;
        let mut paths=Vec::new();
        for f in &payload.files {
            let safe=safe_filename(&f.name);
            let path=base.join(safe);
            fs::write(&path,f.bytes_verified()?)?;
            paths.push(path.to_string_lossy().into_owned());
        }
        if !paths.is_empty() { contents.push(ClipboardContent::Files(paths)); }
    }

    if contents.is_empty() { return Ok(()); }
    let fp=payload.stable_fingerprint()?;
    state.suppress(fp);
    ctx.set(contents).map_err(|e| anyhow::anyhow!(e.to_string()))?;
    Ok(())
}

fn safe_filename(name: &str) -> String {
    let base=Path::new(name).file_name().and_then(|x|x.to_str()).unwrap_or("clipboard-file");
    base.chars().map(|c| if c=='/'||c=='\\'||c=='\0' {'_'} else {c}).collect()
}
