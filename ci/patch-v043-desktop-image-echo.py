#!/usr/bin/env python3
"""Prevent remote desktop clipboard writes from being re-emitted without suppressing later local copies."""

from pathlib import Path
import os
import platform

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

clipboard = PROJECT / "apps/desktop/src/clipboard.rs"
text = clipboard.read_text(encoding="utf-8")

old = r'''pub struct ClipboardState {
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
'''

new = r'''struct ClipboardDedupe {
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
'''

if text.count(old) != 1:
    raise SystemExit(
        f"desktop ClipboardState scoped remote-write anchor: expected one match, found {text.count(old)}"
    )
text = text.replace(old, new, 1)

old_apply = r'''    if contents.is_empty() { return Ok(()); }
    let fp=payload.stable_fingerprint()?;
    state.suppress(fp);
    ctx.set(contents).map_err(|e| anyhow::anyhow!(e.to_string()))?;
    Ok(())
'''

new_apply = r'''    if contents.is_empty() { return Ok(()); }
    let fp=payload.stable_fingerprint()?;
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
        let mut observe_cg=cfg.clone();
        // Remote-write observation must not depend on whichever foreground app is
        // excluded by the user; this is internal dedupe bookkeeping only.
        observe_cfg.exclusions.clear();
        for _ in 0..4 {
            if let Ok(Some(observed))=read_payload(&ctx,&observe_cfg) {
                if let Ok(observed_fp)=observed.stable_fingerprint() {
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
'''

if text.count(old_apply) != 1:
    raise SystemExit(
        f"desktop apply_remote scoped suppression anchor: expected one match, found {text.count(old_apply)}"
    )
text = text.replace(old_apply, new_apply, 1)
clipboard.write_text(text, encoding="utf-8")

final = clipboard.read_text(encoding="utf-8")
for needle in (
    "remote_write_depth: usize",
    "state.remote_write_depth=state.remote_write_depth.saturating_add(1)",
    "state.remote_write_depth=state.remote_write_depth.saturating_sub(1)",
    "state.begin_remote_write(fp)",
    "observe_cfg.exclusions.clear()",
    "actual_fingerprint=Some(observed_fp)",
    "state.finish_remote_write(actual_fingerprint)",
    'There is no sticky "ignore the next clipboard event"',
):
    if needle not in final:
        raise SystemExit(f"desktop scoped image-echo suppression guard missing: {needle}")

for forbidden in (
    "suppress_next_observed",
    "state.suppress(fp)",
):
    if forbidden in final:
        raise SystemExit(f"desktop stale remote-event suppression remains: {forbidden}")

print(f"Applied scoped desktop remote-write echo suppression on {SYSTEM}")
