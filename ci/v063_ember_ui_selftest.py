#!/usr/bin/env python3
"""Static guards for the v063 Ember UI layer (run after reconstruct, before release patches)."""

from __future__ import annotations

import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"v063 missing source: {path}")
    return path.read_text(encoding="utf-8")


def require(text: str, *needles: str) -> None:
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"v063 guard missing: {needle}")


def forbid(text: str, *needles: str) -> None:
    for needle in needles:
        if needle in text:
            raise SystemExit(f"v063 forbidden text present: {needle}")


if SYSTEM in ("Darwin", "Windows"):
    # Peer connections must never become write-only zombies (desktop daemon).
    net = read(PROJECT / "apps/desktop/src/network.rs")
    require(net, "PEER_IDLE_TIMEOUT", "dropping undecryptable frame", "} Ok(()) }.await;", "bad_frames_do_not_kill_the_reader_and_teardown_always_unregisters", "replacing stale peer connection", "reconnect_replaces_a_stale_registration")
    forbid(net, "let frame=decrypt_frame(&master,cfg.space_id,&data,true)?;")
    require(read(PROJECT / "apps/desktop/src/config.rs"), "clipmesh-unit-tests-")

if SYSTEM == "Linux":
    app = PROJECT / "android/app"
    java = app / "src/main/java/dev/clipmesh"
    gradle = read(app / "build.gradle.kts")
    require(gradle, 'id("org.jetbrains.kotlin.plugin.compose")', "compose = true", "androidx.compose:compose-bom", "androidx.activity:activity-compose")
    require(read(PROJECT / "android/build.gradle.kts"), 'id("org.jetbrains.kotlin.plugin.compose") version')
    for font in ("sora_regular.ttf", "sora_medium.ttf", "sora_semibold.ttf", "sora_bold.ttf"):
        if not (app / "src/main/res/font" / font).is_file():
            raise SystemExit(f"v063 missing bundled font {font}")
    theme = read(java / "ui/Theme.kt")
    require(theme, "Color(0xFF131314)", "Color(0xFF222222)", "Color(0xFFE55F11)", "R.font.sora_semibold")
    components = read(java / "ui/Components.kt")
    require(components, "fun EmberBottomNav(", "bottom_nav_indicator_x", "fun <T> AnimatedItems(", "fun EmberToggle(")
    main = read(java / "MainActivity.kt")
    require(main, "open class MainActivity : ComponentActivity()", "ClipMeshRoot(", "onWindowFocusChanged", "ClipPreview.Image(")
    share = read(java / "fileshare/FileShareActivity.kt")
    # Sent files must leave the selection automatically once the transfer succeeds.
    require(share, "class FileShareActivity : MainActivity()", "selected.removeAll(outgoing)", "ui.files.removeAll { it.uri in outgoing }", "SendState.Sent")
    # Zero UI polling: refreshes are driven by engine/runtime/preference events.
    forbid(main, "postDelayed(this", "1_500L")
    require(main, "LocalTransferEngine.setDevicesListener(engineListener)", "registerOnSharedPreferenceChangeListener(peersListener)")
    require(read(java / "fileshare/LocalTransferEngine.kt"), "fun setDevicesListener(", "fun nextDeviceExpiryInMs()")
    # Screenshot edges are deferred, never dropped (Samsung sync-before-preview-closes fix).
    bridge = read(java / "clipboard/ClipboardBridge.kt")
    require(bridge, "scheduleScreenshotFollowUp(SCREENSHOT_MIN_PROBE_SPACING_MS - elapsed)", "SCREENSHOT_FOLLOW_UP_DELAYS_MS")
    forbid(bridge, "if (now - previous < 2_000L")
    require(read(java / "network/NetworkEngine.kt"), "socket.soTimeout = PEER_IDLE_TIMEOUT_MS", "PEER_REPLACE_AFTER_MS", "replaced?.close()")
    manifest = read(app / "src/main/AndroidManifest.xml")
    require(manifest, 'android:name=".fileshare.FileShareActivity"', "android.intent.action.SEND_MULTIPLE", "android:configChanges=")
elif SYSTEM == "Darwin":
    app = read(ROOT / "ci/ClipMeshApp.swift")
    build = read(PROJECT / "scripts/build-macos.sh")
    require(app, "clearTransferSelection(animated: true)", "progressValue:")
    # Never show raw pasteboard type identifiers to people.
    forbid(app, 'lines.append("Types: "')
    require(build, "ATSApplicationFontsPath", "_NSExtensionMain", "com.apple.share-services")
    entitlements = read(ROOT / "ci/v063/macos/ClipMeshShare.entitlements")
    require(entitlements, "com.apple.security.app-sandbox")
    forbid(build, "-bundle -o", 'codesign --force --deep --sign - "$APP"')
elif SYSTEM == "Windows":
    app = read(ROOT / "ci/ClipMeshWindows.cs")
    transfer = read(ROOT / "ci/ClipMeshTransfer.cs")
    require(app, "transferFiles.Clear(); UpdateTransferFiles()", "AddClipboardFormatListener")
    forbid(app, 'lines.Add("Formats: "')
    forbid(app + transfer, "class TransferChooserFormC")
else:
    raise SystemExit(f"Unsupported CLIPMESH_PLATFORM: {SYSTEM}")

print(f"v063 Ember UI self-test passed on {SYSTEM}")
