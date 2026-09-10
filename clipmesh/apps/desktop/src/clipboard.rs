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

struct ClipboardDedupe {
    suppressed: Option<[u8; 32]>,
    last_observed: Option<[u8; 32]>,
    remote_write_depth: usize,
}

pub struct ClipboardState {
    dedupe: Mutex<ClipboardDedupe>,
}

impl ClipboardState {
    pub fn new() -> Self {
        Self {
            dedupe: Mutex::new(ClipboardDedupe {
                suppressed: None,
                last_observed: None,
                remote_write_depth: 0,
            }),
        }
    }
    pub fn seed(&self, fingerprint: [u8; 32]) {
        self.dedupe.lock().last_observed=Some(fingerprint);
    }
    pub fn begin_remote_write(&self, fingerprint: [u8; 32]) {
        let mut state=self.dedupe.lock();
        state.suppressed=Some(fingerprint);
        state.remote_write_depth=state.remote_write_depth.saturating_add(1);
    }
    pub fn finish_remote_write(&self, actual_fingerprint: Option<[u8; 32]>) {
        let mut state=self.dedupe.lock();
        if let Some(fingerprint)=actual_fingerprint {
            // Seed the representation the OS actually stored. macOS can re-encode
            // image bytes, so the wire fingerprint alone is not enough to stop an
            // echo after the remote write completes.
            state.last_observed=Some(fingerprint);
            state.suppressed=None;
        }
        state.remote_write_depth=state.remote_write_depth.saturating_sub(1);
    }
    fn should_emit(&self, fingerprint: &[u8; 32]) -> bool {
        let mut state=self.dedupe.lock();
        if state.remote_write_depth>0 {
            // Only events observed while apply_remote() is actively writing are
            // suppressed. There is no sticky "ignore the next clipboard event"
            // bit, so an immediate genuine local copy can never be swallowed later.
            state.last_observed=Some(*fingerprint);
            if state.suppressed.as_ref()==Some(fingerprint) { state.suppressed=None; }
            return false;
        }
        if state.last_observed.as_ref()==Some(fingerprint) { return false; }
        state.last_observed=Some(*fingerprint);
        if state.suppressed.as_ref()==Some(fingerprint) {
            state.suppressed=None;
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
                match observation_fingerprint(&payload) {
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
        if let Ok(fp)=observation_fingerprint(&payload) { state.seed(fp); }
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
                std::thread::sleep(std::time::Duration::from_millis(350));
                match read_payload(&ctx,&poll_cfg) {
                    Ok(Some(payload)) => match observation_fingerprint(&payload) {
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
    let fp=observation_fingerprint(&payload)?;
    let mut observe_cfg=cfg.clone();
    // Duplicate suppression is based on canonical current content, independent
    // of source application metadata or image container re-encoding.
    observe_cfg.exclusions.clear();
    if let Ok(Some(current))=read_payload(&ctx,&observe_cfg) {
        if observation_fingerprint(&current).ok()==Some(fp) {
            state.seed(fp);
            debug!("ignored adjacent duplicate remote clipboard content");
            return Ok(());
        }
    }
    state.begin_remote_write(fp);

    // Keep suppression scoped to this exact remote write. ctx.set() is
    // synchronous, but native clipboard watchers may run on another thread while
    // it is executing, so should_emit() suppresses only while remote_write_depth
    // is non-zero. Once the write completes, read the actual OS representation
    // back and seed its fingerprint before clearing the gate. This handles macOS
    // image re-encoding without leaving a sticky flag that can swallow the next
    // genuine local copy.
    let set_result=ctx.set(contents).map_err(|e| anyhow::anyhow!(e.to_string()));
    let mut actual_fingerprint=None;
    if set_result.is_ok() {
        for _ in 0..4 {
            if let Ok(Some(observed))=read_payload(&ctx,&observe_cfg) {
                if let Ok(observed_fp)=observation_fingerprint(&observed) {
                    actual_fingerprint=Some(observed_fp);
                    break;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
    state.finish_remote_write(actual_fingerprint);
    if set_result.is_ok() && actual_fingerprint.is_none() {
        warn!("remote clipboard write succeeded but readback fingerprint was unavailable; exact wire suppression retained");
    }
    set_result?;
    Ok(())
}

fn observation_fingerprint(payload: &ClipPayload) -> Result<[u8; 32]> {
    let mut normalized=payload.clone();
    for representation in &mut normalized.representations {
        if representation.mime.to_ascii_lowercase().starts_with("image/") {
            let bytes=representation.bytes()?;
            let image=RustImageData::from_bytes(&bytes)
                .map_err(|e| anyhow::anyhow!(e.to_string()))?;
            let identity=image_perceptual_identity(&image)?;
            *representation=Representation::from_bytes("image/x-clipmesh-perceptual",&identity);
        }
    }
    normalized.stable_fingerprint()
}

fn image_perceptual_identity(image: &RustImageData) -> Result<Vec<u8>> {
    let rgba=image.to_rgba8().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    let (width,height)=image.get_size();
    if width==0 || height==0 { return Err(anyhow::anyhow!("empty image")); }
    let mut luminance=[0_u32;64];
    let (mut sum_r,mut sum_g,mut sum_b)=(0_u32,0_u32,0_u32);
    for gy in 0..8_u32 {
        for gx in 0..8_u32 {
            let x=((((2*gx+1) as u64)*(width as u64))/16).min((width-1) as u64) as u32;
            let y=((((2*gy+1) as u64)*(height as u64))/16).min((height-1) as u64) as u32;
            let pixel=rgba.get_pixel(x,y).0;
            let index=(gy*8+gx) as usize;
            sum_r+=pixel[0] as u32; sum_g+=pixel[1] as u32; sum_b+=pixel[2] as u32;
            luminance[index]=299*(pixel[0] as u32)+587*(pixel[1] as u32)+114*(pixel[2] as u32);
        }
    }
    let average=luminance.iter().sum::<u32>()/64;
    let mut hash=[0_u8;8];
    for (index,value) in luminance.iter().enumerate() {
        if *value>=average { hash[index/8]|=1_u8 << (7-(index%8)); }
    }
    let mut identity=Vec::with_capacity(19);
    identity.extend_from_slice(&width.to_be_bytes());
    identity.extend_from_slice(&height.to_be_bytes());
    identity.extend_from_slice(&hash);
    identity.push((sum_r/64/16) as u8);
    identity.push((sum_g/64/16) as u8);
    identity.push((sum_b/64/16) as u8);
    Ok(identity)
}

fn safe_filename(name: &str) -> String {
    let base=Path::new(name).file_name().and_then(|x|x.to_str()).unwrap_or("clipboard-file");
    base.chars().map(|c| if c=='/'||c=='\\'||c=='\0' {'_'} else {c}).collect()
}

#[cfg(test)]
mod image_echo_tests {
    use super::*;

    #[test]
    fn image_observation_fingerprint_ignores_png_container_reencoding() {
        let original=include_bytes!("../assets/clipmesh.png");
        let decoded=RustImageData::from_bytes(original).unwrap();
        let mut alternate=decoded.to_png().unwrap().get_bytes().to_vec();
        // PNG decoders ignore trailing non-image data. It models metadata/chunk
        // differences without changing a single displayed pixel.
        alternate.extend_from_slice(b"clipmesh-reencoded-container");

        let mut first=ClipPayload::new();
        first.representations.push(Representation::from_bytes("image/png",original));
        let mut second=ClipPayload::new();
        second.representations.push(Representation::from_bytes("image/png",&alternate));

        assert_ne!(first.stable_fingerprint().unwrap(),second.stable_fingerprint().unwrap());
        assert_eq!(observation_fingerprint(&first).unwrap(),observation_fingerprint(&second).unwrap());
    }

    #[test]
    fn adjacent_duplicates_are_suppressed_but_separated_recopies_are_emitted() {
        let state=ClipboardState::new();
        let image=[1_u8;32];
        let text=[2_u8;32];
        assert!(state.should_emit(&image));
        assert!(!state.should_emit(&image));
        assert!(state.should_emit(&text));
        assert!(state.should_emit(&image));
    }
}

