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
    transfer = ROOT / "ci/ClipMeshTransfer.swift"

    # The v2 acceptance layer used DistributedNotificationCenter for commands.
    # A physical run showed the separate CLI could read app-written UserDefaults
    # while several distributed commands never reached the running AppDelegate.
    # Use the already-proven shared preferences domain as a tiny deterministic
    # debug-only IPC mailbox instead. This never ships in a release build because
    # the acceptance patch itself is applied only to isolated development builds.
    replace_once(
        app,
        "final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {\n",
        "final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {\n    private var acceptanceCommandTimer: Timer?\n",
        "macOS acceptance command timer property",
    )

    old_observer = '''        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("ClipMesh.Acceptance.Command"),
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let self, let command = note.userInfo?["command"] as? String else { return }
            switch command {
            case "show": self.showWindow()
            case "hide": self.hideWindow()
            case "clipboard":
                self.showWindow(); self.selectTab(0, animated: false)
                LocalTransferManager.shared.discoverNow(); self.refreshNearbyPairDevices()
            case "file":
                self.showWindow(); self.selectTab(1, animated: false)
                LocalTransferManager.shared.discoverNow(); self.refreshTransferDevices()
            case "snapshot":
                UserDefaults.standard.set(LocalTransferManager.shared.devAcceptanceSnapshotLines(), forKey: "ClipMesh.Acceptance.Nearby")
            case "clear-nearby":
                LocalTransferManager.shared.devAcceptanceClearNearby()
                UserDefaults.standard.set([], forKey: "ClipMesh.Acceptance.Nearby")
            default: break
            }
        }
'''
    new_observer = '''        let acceptanceTimer = Timer.scheduledTimer(withTimeInterval: 0.10, repeats: true) { [weak self] _ in
            self?.devAcceptancePollCommand()
        }
        RunLoop.main.add(acceptanceTimer, forMode: .common)
        acceptanceCommandTimer = acceptanceTimer
'''
    replace_once(app, old_observer, new_observer, "macOS acceptance command transport")

    command_method = '''    private func devAcceptancePollCommand() {
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
    replace_once(
        app,
        "    private func showWindow() {\n",
        command_method + "    private func showWindow() {\n",
        "macOS acceptance command polling method",
    )

    replace_once(
        app,
        '        UserDefaults.standard.set(true, forKey: "ClipMesh.Acceptance.WindowVisible")\n',
        '        UserDefaults.standard.set(true, forKey: "ClipMesh.Acceptance.WindowVisible")\n        UserDefaults.standard.synchronize()\n',
        "macOS acceptance visible state flush",
    )
    replace_once(
        app,
        '        UserDefaults.standard.set(false, forKey: "ClipMesh.Acceptance.WindowVisible")\n',
        '        UserDefaults.standard.set(false, forKey: "ClipMesh.Acceptance.WindowVisible")\n        UserDefaults.standard.synchronize()\n',
        "macOS acceptance hidden state flush",
    )

    text = app.read_text(encoding="utf-8")
    metric_old = 'UserDefaults.standard.set(devices.count, forKey: "{}")'
    metric_new = 'UserDefaults.standard.set(devices.count, forKey: "{}"); UserDefaults.standard.synchronize()'
    for key in ("ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount"):
        old = metric_old.format(key)
        if text.count(old) != 1:
            raise SystemExit(f"macOS acceptance metric flush: expected one {key}, found {text.count(old)}")
        text = text.replace(old, metric_new.format(key), 1)
    app.write_text(text, encoding="utf-8")

    replace_once(
        transfer,
        '            let policy = defaults.string(forKey: "ClipMesh.Acceptance.IncomingPolicy") ?? ""\n',
        '            defaults.synchronize()\n            let policy = defaults.string(forKey: "ClipMesh.Acceptance.IncomingPolicy") ?? ""\n',
        "macOS incoming policy read barrier",
    )

    replace_once(
        app,
        '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-set-favorite"), clipMeshAcceptanceArgs.count > index + 2 {
    let fingerprint = clipMeshAcceptanceArgs[index + 1]
    let favorite = clipMeshAcceptanceArgs[index + 2].lowercased() == "true"
    LocalTransferManager.shared.devAcceptanceSetFavorite(fingerprint, favorite)
    print("favorite=\\(fingerprint)"); print("value=\\(favorite)"); exit(0)
}
''',
        '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-set-favorite"), clipMeshAcceptanceArgs.count > index + 2 {
    let fingerprint = clipMeshAcceptanceArgs[index + 1]
    let favorite = clipMeshAcceptanceArgs[index + 2].lowercased() == "true"
    LocalTransferManager.shared.devAcceptanceSetFavorite(fingerprint, favorite)
    UserDefaults.standard.synchronize()
    print("favorite=\\(fingerprint)"); print("value=\\(favorite)"); exit(0)
}
''',
        "macOS favorite flush",
    )

    replace_once(
        app,
        '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-policy"), clipMeshAcceptanceArgs.count > index + 1 {
    let policy = clipMeshAcceptanceArgs[index + 1]
    UserDefaults.standard.set(policy, forKey: "ClipMesh.Acceptance.IncomingPolicy")
    print("policy=\\(policy)"); exit(0)
}
''',
        '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-policy"), clipMeshAcceptanceArgs.count > index + 1 {
    let policy = clipMeshAcceptanceArgs[index + 1]
    UserDefaults.standard.set(policy, forKey: "ClipMesh.Acceptance.IncomingPolicy")
    UserDefaults.standard.synchronize()
    print("policy=\\(policy)"); exit(0)
}
''',
        "macOS incoming policy flush",
    )

    old_command = '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-command"), clipMeshAcceptanceArgs.count > index + 1 {
    let command = clipMeshAcceptanceArgs[index + 1]
    DistributedNotificationCenter.default().post(
        name: Notification.Name("ClipMesh.Acceptance.Command"), object: nil, userInfo: ["command": command]
    )
    Thread.sleep(forTimeInterval: 0.18)
    print("command=\\(command)"); exit(0)
}
'''
    new_command = '''if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-command"), clipMeshAcceptanceArgs.count > index + 1 {
    let command = clipMeshAcceptanceArgs[index + 1]
    let defaults = UserDefaults.standard
    defaults.set(command, forKey: "ClipMesh.Acceptance.CommandKey")
    defaults.synchronize()
    Thread.sleep(forTimeInterval: 0.45)
    print("command=\\(command)"); exit(0)
}
'''
    replace_once(app, old_command, new_command, "macOS command mailbox CLI")

    replace_once(
        app,
        '''    for key in ["ClipMesh.Acceptance.PromptCount", "ClipMesh.Acceptance.LastPromptSender", "ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount", "ClipMesh.Acceptance.Nearby"] { defaults.removeObject(forKey: key) }
    print("reset=PASS"); exit(0)
''',
        '''    for key in ["ClipMesh.Acceptance.PromptCount", "ClipMesh.Acceptance.LastPromptSender", "ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount", "ClipMesh.Acceptance.Nearby", "ClipMesh.Acceptance.CommandKey"] { defaults.removeObject(forKey: key) }
    defaults.synchronize()
    print("reset=PASS"); exit(0)
''',
        "macOS reset metrics flush",
    )

    replace_once(
        app,
        '''if clipMeshAcceptanceArgs.contains("--dev-accept-state") {
    let defaults = UserDefaults.standard
''',
        '''if clipMeshAcceptanceArgs.contains("--dev-accept-state") {
    let defaults = UserDefaults.standard
    defaults.synchronize()
''',
        "macOS state read barrier",
    )

    final = app.read_text(encoding="utf-8")
    for needle in (
        "acceptanceCommandTimer",
        "devAcceptancePollCommand",
        "ClipMesh.Acceptance.CommandKey",
        'case "discover"',
        "defaults.synchronize()",
    ):
        if needle not in final:
            raise SystemExit(f"macOS acceptance v3 guard missing: {needle}")

elif SYSTEM == "Linux":
    # Android acceptance IPC already uses explicit broadcasts and run-as files.
    # Keep this layer present on both platforms so the physical setup and CI use
    # one deterministic patch stack.
    receiver = PROJECT / "android/app/src/debug/java/dev/clipmesh/AcceptanceReceiver.kt"
    if not receiver.is_file() or "ACTION_INFO" not in receiver.read_text(encoding="utf-8"):
        raise SystemExit("Android acceptance v2 receiver must be installed before v3")

else:
    raise SystemExit(f"acceptance v3 supports Darwin/Linux only, got {SYSTEM}")

print(f"Applied ClipMesh physical acceptance v3 on {SYSTEM}")
