#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if SYSTEM == "Darwin":
    app = ROOT / "ci/ClipMeshApp.swift"
    config = PROJECT / "apps/desktop/src/config.rs"
    secrets = PROJECT / "apps/desktop/src/secrets.rs"

    # The public macOS app deliberately uses Keychain. Rebuilding an ad-hoc DEV
    # binary for every physical run gives macOS a different code identity and can
    # repeatedly ask the user to authorize access to that production Keychain
    # item. Acceptance builds must never touch production secrets. Use a dedicated
    # test-only Application Support tree and a mode-0600 local secret instead.
    replace_once(
        app,
        '''            .appendingPathComponent("dev.ClipMesh.ClipMesh", isDirectory: true)
''',
        '''            .appendingPathComponent("dev.ClipMesh.ClipMesh-Acceptance", isDirectory: true)
''',
        "macOS acceptance support isolation",
    )

    replace_once(
        config,
        '''    pub fn path() -> Result<PathBuf> {
        let dirs = ProjectDirs::from("dev", "ClipMesh", "ClipMesh")
            .ok_or_else(|| anyhow!("could not resolve application config directory"))?;
        Ok(dirs.config_dir().join("config.json"))
    }

    pub fn cache_dir() -> Result<PathBuf> {
        let dirs = ProjectDirs::from("dev", "ClipMesh", "ClipMesh")
            .ok_or_else(|| anyhow!("could not resolve application cache directory"))?;
        Ok(dirs.cache_dir().to_path_buf())
    }
''',
        '''    fn acceptance_root() -> Result<PathBuf> {
        let home = std::env::var_os("HOME").ok_or_else(|| anyhow!("HOME is unavailable"))?;
        Ok(PathBuf::from(home)
            .join("Library")
            .join("Application Support")
            .join("dev.ClipMesh.ClipMesh-Acceptance"))
    }

    pub fn path() -> Result<PathBuf> {
        Ok(Self::acceptance_root()?.join("config.json"))
    }

    pub fn cache_dir() -> Result<PathBuf> {
        Ok(Self::acceptance_root()?.join("cache"))
    }
''',
        "macOS acceptance Rust config isolation",
    )

    secrets.write_text(r'''use anyhow::{anyhow, Context, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use clipmesh_core::MasterKey;
use std::{
    fs,
    fs::{OpenOptions, Permissions},
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::PathBuf,
};
use uuid::Uuid;

// ACCEPTANCE-ONLY SECRET BACKEND.
// Public reconstruction never applies patch-acceptance-v4.py and continues to
// use keyring::Entry with the native macOS Keychain backend.
fn root() -> Result<PathBuf> {
    let home = std::env::var_os("HOME").ok_or_else(|| anyhow!("HOME is unavailable"))?;
    Ok(PathBuf::from(home)
        .join("Library")
        .join("Application Support")
        .join("dev.ClipMesh.ClipMesh-Acceptance")
        .join("secrets"))
}

fn path(space_id: Uuid) -> Result<PathBuf> {
    Ok(root()?.join(format!("space-{space_id}.key")))
}

fn ensure_root() -> Result<PathBuf> {
    let dir = root()?;
    fs::create_dir_all(&dir).context("create acceptance secret directory")?;
    fs::set_permissions(&dir, Permissions::from_mode(0o700))
        .context("secure acceptance secret directory")?;
    Ok(dir)
}

pub fn save(space_id: Uuid, key: &MasterKey) -> Result<()> {
    ensure_root()?;
    let destination = path(space_id)?;
    let temp = destination.with_extension("key.tmp");
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .mode(0o600)
        .open(&temp)
        .context("open acceptance secret")?;
    file.write_all(URL_SAFE_NO_PAD.encode(key.0).as_bytes())
        .context("write acceptance secret")?;
    file.sync_all().context("sync acceptance secret")?;
    fs::set_permissions(&temp, Permissions::from_mode(0o600))
        .context("secure acceptance secret")?;
    fs::rename(temp, destination).context("commit acceptance secret")?;
    Ok(())
}

pub fn load(space_id: Uuid) -> Result<MasterKey> {
    let value = fs::read_to_string(path(space_id)?).context("read acceptance space key")?;
    let bytes = URL_SAFE_NO_PAD.decode(value.trim()).context("decode acceptance space key")?;
    MasterKey::from_slice(&bytes)
}

pub fn delete(space_id: Uuid) -> Result<()> {
    let destination = path(space_id)?;
    if destination.exists() {
        fs::remove_file(destination).context("delete acceptance space key")?;
    }
    Ok(())
}
''', encoding="utf-8")

    # Deterministic file-based command mailbox. Cross-process UserDefaults and
    # DistributedNotificationCenter both proved timing-sensitive during real
    # hardware runs. The CLI now waits for an ACK written only after the running
    # AppDelegate has executed the requested UI action.
    old_method = '''    private func devAcceptancePollCommand() {
        let defaults = UserDefaults.standard
        defaults.synchronize()
        guard let command = defaults.string(forKey: "ClipMesh.Acceptance.CommandKey"), !command.isEmpty else { return }
        defaults.removeObject(forKey: "ClipMesh.Acceptance.CommandKey")
        defaults.synchronize()
        switch command {
        case "show": showWindow()
        case "hide": hideWindow()
        case "clipboard":
            showWindow(); selectTab(0, animated: false)
            LocalTransferManager.shared.discoverNow(); refreshNearbyPairDevices()
        case "file":
            showWindow(); selectTab(1, animated: false)
            LocalTransferManager.shared.discoverNow(); refreshTransferDevices()
        case "discover":
            LocalTransferManager.shared.discoverNow()
            defaults.set(LocalTransferManager.shared.devAcceptanceSnapshotLines(), forKey: "ClipMesh.Acceptance.Nearby")
        case "snapshot":
            defaults.set(LocalTransferManager.shared.devAcceptanceSnapshotLines(), forKey: "ClipMesh.Acceptance.Nearby")
        case "clear-nearby":
            LocalTransferManager.shared.devAcceptanceClearNearby()
            defaults.set([], forKey: "ClipMesh.Acceptance.Nearby")
        default: break
        }
        defaults.synchronize()
    }
'''
    new_method = '''    private func devAcceptancePollCommand() {
        let fm = FileManager.default
        let commandURL = Runtime.support.appendingPathComponent("acceptance-command.txt")
        let ackURL = Runtime.support.appendingPathComponent("acceptance-ack.txt")
        guard let raw = try? String(contentsOf: commandURL, encoding: .utf8) else { return }
        let parts = raw.split(separator: "\\n", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 2 else { try? fm.removeItem(at: commandURL); return }
        let token = parts[0]
        let command = parts[1]
        try? fm.removeItem(at: commandURL)
        let defaults = UserDefaults.standard
        switch command {
        case "show": showWindow()
        case "hide": hideWindow()
        case "clipboard":
            showWindow(); selectTab(0, animated: false)
            LocalTransferManager.shared.discoverNow(); refreshNearbyPairDevices()
        case "file":
            showWindow(); selectTab(1, animated: false)
            LocalTransferManager.shared.discoverNow(); refreshTransferDevices()
        case "discover":
            LocalTransferManager.shared.discoverNow()
            defaults.set(LocalTransferManager.shared.devAcceptanceSnapshotLines(), forKey: "ClipMesh.Acceptance.Nearby")
        case "snapshot":
            defaults.set(LocalTransferManager.shared.devAcceptanceSnapshotLines(), forKey: "ClipMesh.Acceptance.Nearby")
        case "clear-nearby":
            LocalTransferManager.shared.devAcceptanceClearNearby()
            defaults.set([], forKey: "ClipMesh.Acceptance.Nearby")
        default: break
        }
        defaults.synchronize()
        try? fm.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
        try? token.write(to: ackURL, atomically: true, encoding: .utf8)
    }
'''
    replace_once(app, old_method, new_method, "macOS acceptance command file mailbox")

    old_command = '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-command"), clipMeshAcceptanceArgs.count > index + 1 {
    let command = clipMeshAcceptanceArgs[index + 1]
    let defaults = UserDefaults.standard
    defaults.set(command, forKey: "ClipMesh.Acceptance.CommandKey")
    defaults.synchronize()
    Thread.sleep(forTimeInterval: 0.45)
    print("command=\\(command)"); exit(0)
}
'''
    new_command = '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-command"), clipMeshAcceptanceArgs.count > index + 1 {
    let command = clipMeshAcceptanceArgs[index + 1]
    let fm = FileManager.default
    try? fm.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
    let commandURL = Runtime.support.appendingPathComponent("acceptance-command.txt")
    let ackURL = Runtime.support.appendingPathComponent("acceptance-ack.txt")
    let token = UUID().uuidString
    try? fm.removeItem(at: ackURL)
    do {
        try "\\(token)\\n\\(command)".write(to: commandURL, atomically: true, encoding: .utf8)
    } catch {
        fputs("command=FAIL\\nerror=\\(error.localizedDescription)\\n", stderr); exit(2)
    }
    let deadline = Date().addingTimeInterval(4.0)
    var acknowledged = false
    while Date() < deadline {
        if (try? String(contentsOf: ackURL, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)) == token {
            acknowledged = true; break
        }
        Thread.sleep(forTimeInterval: 0.05)
    }
    guard acknowledged else { fputs("command=FAIL\\nerror=App did not acknowledge \\(command)\\n", stderr); exit(2) }
    print("command=\\(command)"); print("ack=PASS"); exit(0)
}
'''
    replace_once(app, old_command, new_command, "macOS acceptance command CLI ACK")

    # Incoming transfer policy is also file-backed. The real NSAlert is still
    # presented, but the acceptance build clicks the actual Accept/Reject button
    # itself. Production builds retain normal manual confirmation for nonfavorites.
    old_policy_cli = '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-policy"), clipMeshAcceptanceArgs.count > index + 1 {
    let policy = clipMeshAcceptanceArgs[index + 1]
    UserDefaults.standard.set(policy, forKey: "ClipMesh.Acceptance.IncomingPolicy")
    UserDefaults.standard.synchronize()
    print("policy=\\(policy)"); exit(0)
}
'''
    new_policy_cli = '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-policy"), clipMeshAcceptanceArgs.count > index + 1 {
    let policy = clipMeshAcceptanceArgs[index + 1]
    let fm = FileManager.default
    try? fm.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
    let policyURL = Runtime.support.appendingPathComponent("acceptance-incoming-policy.txt")
    if policy.isEmpty { try? fm.removeItem(at: policyURL) }
    else {
        do { try policy.write(to: policyURL, atomically: true, encoding: .utf8) }
        catch { fputs("policy=FAIL\\n", stderr); exit(2) }
    }
    UserDefaults.standard.set(policy, forKey: "ClipMesh.Acceptance.IncomingPolicy")
    UserDefaults.standard.synchronize()
    print("policy=\\(policy)"); exit(0)
}
'''
    replace_once(app, old_policy_cli, new_policy_cli, "macOS acceptance policy file CLI")

    replace_once(
        app,
        '''            defaults.synchronize()
            let policy = defaults.string(forKey: "ClipMesh.Acceptance.IncomingPolicy") ?? ""
            if policy == "accept" || policy == "reject" {
                let index = policy == "accept" ? 0 : 1
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                    guard alert.buttons.indices.contains(index) else { return }
                    alert.buttons[index].performClick(nil)
                }
            }
            NSApp.activate(ignoringOtherApps: true)
            accepted = alert.runModal() == .alertFirstButtonReturn
''',
        '''            defaults.synchronize()
            let policyURL = Runtime.support.appendingPathComponent("acceptance-incoming-policy.txt")
            let policy = (try? String(contentsOf: policyURL, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if policy == "accept" || policy == "reject" {
                let index = policy == "accept" ? 0 : 1
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) {
                    guard alert.buttons.indices.contains(index) else { return }
                    alert.buttons[index].performClick(nil)
                }
            }
            NSApp.activate(ignoringOtherApps: true)
            accepted = alert.runModal() == .alertFirstButtonReturn
            defaults.set(accepted ? "accept" : "reject", forKey: "ClipMesh.Acceptance.LastPromptDecision")
            defaults.synchronize()
''',
        "macOS acceptance real prompt automation",
    )

    replace_once(
        app,
        '''    print("last_prompt_sender=\\(defaults.string(forKey: "ClipMesh.Acceptance.LastPromptSender") ?? "")")
''',
        '''    print("last_prompt_sender=\\(defaults.string(forKey: "ClipMesh.Acceptance.LastPromptSender") ?? "")")
    print("last_prompt_decision=\\(defaults.string(forKey: "ClipMesh.Acceptance.LastPromptDecision") ?? "")")
''',
        "macOS acceptance prompt-decision state",
    )

    replace_once(
        app,
        '''    for key in ["ClipMesh.Acceptance.PromptCount", "ClipMesh.Acceptance.LastPromptSender", "ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount", "ClipMesh.Acceptance.Nearby", "ClipMesh.Acceptance.CommandKey"] { defaults.removeObject(forKey: key) }
''',
        '''    for key in ["ClipMesh.Acceptance.PromptCount", "ClipMesh.Acceptance.LastPromptSender", "ClipMesh.Acceptance.LastPromptDecision", "ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount", "ClipMesh.Acceptance.Nearby", "ClipMesh.Acceptance.CommandKey"] { defaults.removeObject(forKey: key) }
''',
        "macOS acceptance reset decision metric",
    )

    final_app = app.read_text(encoding="utf-8")
    final_config = config.read_text(encoding="utf-8")
    final_secrets = secrets.read_text(encoding="utf-8")
    for needle in (
        "dev.ClipMesh.ClipMesh-Acceptance",
        "acceptance-command.txt",
        "acceptance-ack.txt",
        "acceptance-incoming-policy.txt",
        "last_prompt_decision=",
        "App did not acknowledge",
    ):
        if needle not in final_app:
            raise SystemExit(f"macOS acceptance v4 app guard missing: {needle}")
    if "ClipMeshAcceptance" not in final_config and "ClipMesh.ClipMesh-Acceptance" not in final_config:
        raise SystemExit("macOS acceptance config isolation guard missing")
    for needle in ("ACCEPTANCE-ONLY SECRET BACKEND", "0o600", "0o700", "read acceptance space key"):
        if needle not in final_secrets:
            raise SystemExit(f"macOS acceptance secret guard missing: {needle}")
    if "keyring::Entry" in final_secrets or "set_password" in final_secrets:
        raise SystemExit("macOS acceptance build still touches production Keychain")

elif SYSTEM == "Linux":
    receiver = PROJECT / "android/app/src/debug/java/dev/clipmesh/AcceptanceReceiver.kt"
    if not receiver.is_file() or "ACTION_INFO" not in receiver.read_text(encoding="utf-8"):
        raise SystemExit("Android acceptance receiver missing before v4")
else:
    raise SystemExit(f"acceptance v4 supports Darwin/Linux only, got {SYSTEM}")

print(f"Applied ClipMesh physical acceptance v4 on {SYSTEM}")
