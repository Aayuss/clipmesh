#!/usr/bin/env python3
"""Prevent remote image clipboard writes from being re-emitted by desktop watchers."""

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

new = r'''pub struct ClipboardState {
    suppressed: Mutex<Option<[u8; 32]>>,
    last_observed: Mutex<Option<[u8; 32]>>,
    suppress_next_observed: Mutex<bool>,
}

impl ClipboardState {
    pub fn new() -> Self {
        Self {
            suppressed: Mutex::new(None),
            last_observed: Mutex::new(None),
            suppress_next_observed: Mutex::new(false),
        }
    }
    pub fn seed(&self, fingerprint: [u8; 32]) {
        *self.last_observed.lock()=Some(fingerprint);
    }
    pub fn suppress(&self, fingerprint: [u8; 32]) {
        // A remote clipboard write is one event even when the platform re-encodes
        // its bytes. In particular, macOS may expose an image with PNG bytes that
        // differ from the bytes received over ClipMesh. The first observation
        // caused by this remote write must therefore be suppressed by event, not
        // only by an exact content fingerprint.
        *self.suppressed.lock()=Some(fingerprint);
        *self.suppress_next_observed.lock()=true;
    }
    fn should_emit(&self, fingerprint: &[u8; 32]) -> bool {
        let suppress_next = {
            let mut pending=self.suppress_next_observed.lock();
            let value=*pending;
            if value { *pending=false; }
            value
        };
        if suppress_next {
            // Seed the ACTUAL representation that the local clipboard exposes
            // after the remote write. Subsequent native-watcher/poller reads of
            // the same image now dedupe even if the platform re-encoded it.
            *self.last_observed.lock()=Some(*fingerprint);
            *self.suppressed.lock()=None;
            return false;
        }
        {
            let mut last=self.last_observed.lock();
            if last.as_ref()==Some(fingerprint) { return false; }
            *last=Some(*fingerprint);
        }
        // Keep exact-fingerprint suppression as a fallback for platforms where
        // the observer sees the received representation byte-for-byte.
        let mut suppressed=self.suppressed.lock();
        if suppressed.as_ref()==Some(fingerprint) {
            *suppressed=None;
            return false;
        }
        true
    }
}
'''

if text.count(old) != 1:
    raise SystemExit(
        f"desktop ClipboardState remote-event suppression anchor: expected one match, found {text.count(old)}"
    )

text = text.replace(old, new, 1)
clipboard.write_text(text, encoding="utf-8")

final = clipboard.read_text(encoding="utf-8")
for needle in (
    "suppress_next_observed: Mutex<bool>",
    "*self.suppress_next_observed.lock()=true",
    "let suppress_next = {",
    "*self.last_observed.lock()=Some(*fingerprint)",
    "*self.suppressed.lock()=None",
    "macOS may expose an image with PNG bytes",
):
    if needle not in final:
        raise SystemExit(f"desktop image echo suppression guard missing: {needle}")

# The old behavior seeded last_observed from the wire representation before the
# OS wrote/re-encoded the clipboard. That exact pattern is the image-loop bug.
if "*self.suppressed.lock()=Some(fingerprint);\n        *self.last_observed.lock()=Some(fingerprint);" in final:
    raise SystemExit("desktop remote write still seeds last_observed from wire bytes")

print(f"Applied desktop once-per-remote-event image echo suppression on {SYSTEM}")
