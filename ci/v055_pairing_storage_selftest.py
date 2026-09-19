#!/usr/bin/env python3
"""Static acceptance guards for v055 pairing and receive-folder fixes."""

from __future__ import annotations
import os, platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())

def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"v055 missing source: {path}")
    return path.read_text(encoding="utf-8")

def require(text: str, *needles: str) -> None:
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"v055 guard missing: {needle}")

core = read(PROJECT / "apps/desktop/src/main.rs")
require(core,
    "SeedPeer { device_id: uuid::Uuid",
    "Command::SeedPeer{device_id,name}",
    "cfg.blocked_devices.retain(|id| *id != device_id)",
    "if old_space != Some(cfg.space_id) { Config::clear_known_peers()?; }",
)

if SYSTEM == "Darwin":
    app = read(ROOT / "ci/ClipMeshApp.swift")
    pairing = read(ROOT / "ci/ClipMeshNearbyPairing.swift")
    transfer = read(ROOT / "ci/ClipMeshTransfer.swift")
    require(pairing,
        "responderDeviceId",
        "peerConsumer?(responderID, responderName)",
        "deviceIDProvider",
        "for _ in 0..<80",
        "Thread.sleep(forTimeInterval: 1.5)",
    )
    require(app,
        "Runtime.seedPeer",
        "showNearbyPairCode",
        "dismissNearbyPairCode",
        "monospacedDigitSystemFont(ofSize: 46",
        "Choose ClipMesh receive folder",
    )
    require(transfer,
        'outputFolderKey = "ClipMesh.FileTransfer.OutputFolder"',
        'appendPathComponent("images"',
        'appendPathComponent("video"',
        "let folder = TransferPrefs.outputFolder",
        ".modificationDate: now",
    )
    recency = transfer[transfer.index("private func refreshDownloadsFolderRecency"):transfer.index("private func destinationURL")]
    if "copyItem(" in recency or "removeItem(" in recency or "contentsOfDirectory" in recency:
        raise SystemExit("macOS recency refresh must not copy/remove/enumerate receive-folder contents")

elif SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    main = read(java / "MainActivity.kt")
    pairing = read(java / "fileshare/NearbyPairingManager.kt")
    pair_ui = read(java / "fileshare/NearbyPairingUi.kt")
    dialog_ui = read(java / "ClipMeshDialog.kt")
    transfer = read(java / "fileshare/LocalTransferEngine.kt")
    share = read(java / "fileshare/FileShareActivity.kt")
    require(pairing,
        "responderDeviceId",
        "settings.seedPeer(responderId,responderName)",
        "if(previousSpace!=parsed.spaceId)settings.clearKnownPeers()",
        "NearbyPairingUi.notifyPaired()",
        "for(i in 0 until 80)",
    )
    require(pair_ui,
        "emphasized = true",
        "pairedCallback",
        "fun notifyPaired()",
    )
    require(dialog_ui,
        "emphasized: Boolean = false",
        "textSize = if (emphasized) 34f else 15f",
    )
    require(main,
        "showNearbyCode",
        "textSize=46f",
        "NearbyPairingUi.attach(this) { refreshHome(); renderNearbyPairDevices() }",
    )
    require(transfer,
        '"output_tree_uri"',
        "DocumentsContract.createDocument",
        '"images"',
        '"video"',
        "outputTreeUri(context)",
    )
    require(share,
        "Intent.ACTION_OPEN_DOCUMENT_TREE",
        "PICK_OUTPUT_FOLDER",
        "Choose folder",
    )

elif SYSTEM == "Windows":
    app = read(ROOT / "ci/ClipMeshWindows.cs")
    pairing = read(ROOT / "ci/ClipMeshNearbyPairing.cs")
    transfer = read(ROOT / "ci/ClipMeshTransfer.cs")
    require(pairing,
        "responderDeviceId",
        "PeerConsumer(responderId,responderName)",
        "DeviceIdProvider",
        "for(int i=0;i<80;i++)",
        "Thread.Sleep(1500)",
    )
    require(app,
        "ClipMeshRuntime.SeedPeer",
        "ShowPairingCode",
        "ClosePairingCode",
        "FolderBrowserDialog",
        "Choose ClipMesh receive folder",
    )
    require(transfer,
        "public string OutputFolder",
        'Path.Combine(folder, "images")',
        'Path.Combine(folder, "video")',
        '"output-folder.txt"',
    )
else:
    raise SystemExit(f"Unsupported CLIPMESH_PLATFORM: {SYSTEM}")

print(f"v055 pairing/storage self-test passed on {SYSTEM}")
