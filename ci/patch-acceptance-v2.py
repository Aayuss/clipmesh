#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import re
import shutil
import xml.etree.ElementTree as ET
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


def regex_replace(path: Path, pattern: str, replacement: str, label: str, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8")
    out, count = re.subn(pattern, lambda m: m.expand(replacement), text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one regex match in {path}, found {count}")
    path.write_text(out, encoding="utf-8")


def insert_after_match(path: Path, pattern: str, addition: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text, re.S)
    if not match:
        raise SystemExit(f"{label}: anchor missing in {path}")
    path.write_text(text[: match.end()] + addition + text[match.end() :], encoding="utf-8")


if SYSTEM == "Linux":
    app = PROJECT / "android/app"
    java = app / "src/main/java/dev/clipmesh"
    debug_java = app / "src/debug/java/dev/clipmesh"
    debug_manifest = app / "src/debug/AndroidManifest.xml"
    engine = java / "fileshare/LocalTransferEngine.kt"
    incoming = java / "fileshare/IncomingRequestUi.kt"
    main = java / "MainActivity.kt"
    file_activity = java / "fileshare/FileShareActivity.kt"
    provider = debug_java / "DevTestFileProvider.kt"

    debug_java.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "dev/android/AcceptanceReceiverV2.kt", debug_java / "AcceptanceReceiver.kt")

    replace_once(
        engine,
        '''    fun resolveIncoming(requestId: String, accepted: Boolean) {
        val request = pending[requestId] ?: return
        request.accepted = accepted
        request.latch.countDown()
    }
''',
        '''    fun devAcceptancePendingRequestIds(): List<String> = pending.keys().toList().sorted()

    fun devAcceptanceClearNearby() {
        nearby.clear()
    }

    fun resolveIncoming(requestId: String, accepted: Boolean) {
        val request = pending[requestId] ?: return
        request.accepted = accepted
        request.latch.countDown()
    }
''',
        "Android acceptance engine hooks",
    )

    if "fun discoverNow()" not in engine.read_text(encoding="utf-8"):
        raise SystemExit("Android acceptance requires LocalTransferEngine.discoverNow()")

    replace_once(
        provider,
        '    override fun getType(uri: Uri): String = "application/octet-stream"\n',
        '''    override fun getType(uri: Uri): String =
        if (uri.lastPathSegment?.lowercase()?.endsWith(".png") == true) "image/png"
        else "application/octet-stream"
''',
        "Android debug provider MIME",
    )

    # Observe the exact lists that the real Clipboard and File Transfer pages render.
    insert_after_match(
        main,
        r'''private\s+fun\s+renderNearbyPairDevices\s*\(\)\s*\{.*?val\s+devices\s*=\s*LocalTransferEngine\.nearbyDevices\(\)[^;\n]*;''',
        'getSharedPreferences("clipmesh_acceptance", MODE_PRIVATE).edit().putInt("clipboard_nearby_count", devices.size).apply();',
        "Android Clipboard nearby renderer",
    )
    replace_once(
        file_activity,
        '        val devices = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())\n',
        '''        val devices = runCatching { LocalTransferEngine.nearbyDevices() }.getOrDefault(emptyList())
        getSharedPreferences("clipmesh_acceptance", MODE_PRIVATE).edit()
            .putInt("file_nearby_count", devices.size).apply()
''',
        "Android File nearby renderer",
    )

    # For foreground non-favorite transfers, keep the real dialog and real
    # button handler, but allow the physical suite to click it deterministically.
    incoming_text = incoming.read_text(encoding="utf-8")
    marker = "dialog.show()"
    if incoming_text.count(marker) != 1:
        raise SystemExit(f"Android incoming dialog: expected one dialog.show(), found {incoming_text.count(marker)}")
    injected = '''dialog.show()
            if (dev.clipmesh.BuildConfig.DEBUG) {
                val policy = activity.getSharedPreferences("clipmesh_acceptance", android.content.Context.MODE_PRIVATE)
                    .getString("incoming_policy", "").orEmpty()
                if (policy == "accept" || policy == "reject") {
                    body.postDelayed({
                        if (policy == "accept") accept.performClick() else reject.performClick()
                    }, 250L)
                }
            }'''
    incoming.write_text(incoming_text.replace(marker, injected, 1), encoding="utf-8")

    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    ANDROID = "{http://schemas.android.com/apk/res/android}"
    tree = ET.parse(debug_manifest)
    application = tree.getroot().find("application")
    if application is None:
        raise SystemExit("Android debug manifest application missing")
    for child in list(application):
        if child.tag == "receiver" and child.get(ANDROID + "name") == ".AcceptanceReceiver":
            application.remove(child)
    receiver = ET.SubElement(application, "receiver")
    receiver.set(ANDROID + "name", ".AcceptanceReceiver")
    receiver.set(ANDROID + "enabled", "true")
    receiver.set(ANDROID + "exported", "true")
    receiver.set(ANDROID + "permission", "android.permission.DUMP")
    tree.write(debug_manifest, encoding="utf-8", xml_declaration=True)

    required = {
        engine: ("devAcceptancePendingRequestIds", "devAcceptanceClearNearby"),
        incoming: ("incoming_policy", "accept.performClick()", "reject.performClick()"),
        main: ("clipboard_nearby_count",),
        file_activity: ("file_nearby_count",),
        debug_java / "AcceptanceReceiver.kt": (
            "ACTION_SET_FAVORITE", "ACTION_CHECK_FAVORITE", "ACTION_SET_POLICY",
            "ACTION_SET_BACKGROUND_RECEIVE", "ACTION_SEND_GENERATED", "ACTION_RESOLVE_PENDING"
        ),
        debug_manifest: (".AcceptanceReceiver", "android.permission.DUMP"),
    }
    for path, needles in required.items():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                raise SystemExit(f"Android acceptance guard missing in {path}: {needle}")

elif SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    app = ROOT / "ci/ClipMeshApp.swift"

    # v031 already provides a one-file debug hook. Replace it with the superset
    # needed by the physical acceptance suite.
    regex_replace(
        transfer,
        r'''    func devTestFingerprint\(\) -> String \{ TransferPrefs\.fingerprint \}\n\n    func devTestSend\(file: URL, address: String, fingerprint: String\) throws \{.*?\n    \}\n''',
        '''    func devTestFingerprint() -> String { TransferPrefs.fingerprint }

    func devAcceptanceSetFavorite(_ fingerprint: String, _ favorite: Bool) {
        setFavorite(fingerprint, favorite)
    }

    func devAcceptanceClearNearby() {
        stateLock.lock()
        devices.removeAll()
        stateLock.unlock()
    }

    func devAcceptanceSnapshotLines() -> [String] {
        nearbyDevices().map { device in
            let alias64 = Data(device.alias.utf8).base64EncodedString()
            return [device.fingerprint, isFavorite(device.fingerprint) ? "1" : "0", device.address, String(device.port), alias64]
                .joined(separator: "|")
        }
    }

    func devTestSend(file: URL, address: String, fingerprint: String) throws {
        try devAcceptanceSend(files: [file], address: address, fingerprint: fingerprint)
    }

    func devAcceptanceSend(files: [URL], address: String, fingerprint: String) throws {
        aliasProvider = { "ClipMesh Mac Acceptance" }
        let target = TransferDevice(
            alias: "ClipMesh Android Acceptance",
            fingerprint: fingerprint,
            address: address,
            port: Self.port,
            model: "Android",
            type: "mobile",
            lastSeen: Date()
        )
        try sendSync(files: files, to: target, progress: { _ in })
    }
''',
        "macOS acceptance transfer hooks",
    )

    # Exercise the real NSAlert and button actions, but automate the selected
    # button during acceptance runs. Run all AppKit work on the main queue.
    regex_replace(
        transfer,
        r'''enum TransferDialogs \{\n    static func ask\(sender: String, files: \[TransferMeta\]\) -> Bool \{.*?\n    \}\n\}''',
        '''enum TransferDialogs {
    static func ask(sender: String, files: [TransferMeta]) -> Bool {
        var accepted = false
        let work = {
            let defaults = UserDefaults.standard
            defaults.set(defaults.integer(forKey: "ClipMesh.Acceptance.PromptCount") + 1, forKey: "ClipMesh.Acceptance.PromptCount")
            defaults.set(sender, forKey: "ClipMesh.Acceptance.LastPromptSender")

            let alert = NSAlert()
            alert.alertStyle = .informational
            alert.messageText = "\\(sender) wants to send you \\(files.count == 1 ? files[0].name : "\\(files.count) files")"
            alert.informativeText = "Accept to save it in Downloads/ClipMesh. Star this device later if you want future transfers from it to save automatically."
            alert.addButton(withTitle: "Accept")
            alert.addButton(withTitle: "Reject")

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
        }
        if Thread.isMainThread { work() } else { DispatchQueue.main.sync(execute: work) }
        return accepted
    }
}''',
        "macOS real incoming prompt automation",
    )

    replace_once(
        app,
        '''        buildWindow()
        buildStatusItem()
''',
        '''        buildWindow()
        buildStatusItem()
        DistributedNotificationCenter.default().addObserver(
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
''',
        "macOS acceptance command observer",
    )

    replace_once(
        app,
        '''    private func showWindow() {
        LocalTransferManager.shared.setUIVisible(true)
''',
        '''    private func showWindow() {
        UserDefaults.standard.set(true, forKey: "ClipMesh.Acceptance.WindowVisible")
        LocalTransferManager.shared.setUIVisible(true)
''',
        "macOS visible state observation",
    )
    replace_once(
        app,
        '''    private func hideWindow() {
        LocalTransferManager.shared.setUIVisible(false)
''',
        '''    private func hideWindow() {
        UserDefaults.standard.set(false, forKey: "ClipMesh.Acceptance.WindowVisible")
        LocalTransferManager.shared.setUIVisible(false)
''',
        "macOS tray state observation",
    )

    # Insert metrics only after the complete `let devices = ...;` declaration,
    # never in the middle of a chained `.filter` expression.
    for function_name, key in (
        ("refreshNearbyPairDevices", "ClipMesh.Acceptance.ClipboardNearbyCount"),
        ("refreshTransferDevices", "ClipMesh.Acceptance.FileNearbyCount"),
    ):
        insert_after_match(
            app,
            rf'''private\s+func\s+{function_name}\s*\(\)\s*\{{.*?let\s+devices\s*=\s*LocalTransferManager\.shared\.nearbyDevices\(\)[^;\n]*;''',
            f' UserDefaults.standard.set(devices.count, forKey: "{key}");',
            f"macOS {function_name} metric",
        )

    cli = r'''let clipMeshAcceptanceArgs = CommandLine.arguments
if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-set-favorite"), clipMeshAcceptanceArgs.count > index + 2 {
    let fingerprint = clipMeshAcceptanceArgs[index + 1]
    let favorite = clipMeshAcceptanceArgs[index + 2].lowercased() == "true"
    LocalTransferManager.shared.devAcceptanceSetFavorite(fingerprint, favorite)
    print("favorite=\(fingerprint)"); print("value=\(favorite)"); exit(0)
}
if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-policy"), clipMeshAcceptanceArgs.count > index + 1 {
    let policy = clipMeshAcceptanceArgs[index + 1]
    UserDefaults.standard.set(policy, forKey: "ClipMesh.Acceptance.IncomingPolicy")
    print("policy=\(policy)"); exit(0)
}
if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-command"), clipMeshAcceptanceArgs.count > index + 1 {
    let command = clipMeshAcceptanceArgs[index + 1]
    DistributedNotificationCenter.default().post(
        name: Notification.Name("ClipMesh.Acceptance.Command"), object: nil, userInfo: ["command": command]
    )
    Thread.sleep(forTimeInterval: 0.18)
    print("command=\(command)"); exit(0)
}
if clipMeshAcceptanceArgs.contains("--dev-accept-reset-metrics") {
    let defaults = UserDefaults.standard
    for key in ["ClipMesh.Acceptance.PromptCount", "ClipMesh.Acceptance.LastPromptSender", "ClipMesh.Acceptance.ClipboardNearbyCount", "ClipMesh.Acceptance.FileNearbyCount", "ClipMesh.Acceptance.Nearby"] { defaults.removeObject(forKey: key) }
    print("reset=PASS"); exit(0)
}
if clipMeshAcceptanceArgs.contains("--dev-accept-state") {
    let defaults = UserDefaults.standard
    print("window_visible=\(defaults.bool(forKey: "ClipMesh.Acceptance.WindowVisible"))")
    print("clipboard_nearby_count=\(defaults.object(forKey: "ClipMesh.Acceptance.ClipboardNearbyCount") == nil ? -1 : defaults.integer(forKey: "ClipMesh.Acceptance.ClipboardNearbyCount"))")
    print("file_nearby_count=\(defaults.object(forKey: "ClipMesh.Acceptance.FileNearbyCount") == nil ? -1 : defaults.integer(forKey: "ClipMesh.Acceptance.FileNearbyCount"))")
    print("prompt_count=\(defaults.integer(forKey: "ClipMesh.Acceptance.PromptCount"))")
    print("last_prompt_sender=\(defaults.string(forKey: "ClipMesh.Acceptance.LastPromptSender") ?? "")")
    for line in defaults.stringArray(forKey: "ClipMesh.Acceptance.Nearby") ?? [] { print("nearby=\(line)") }
    exit(0)
}
if let index = clipMeshAcceptanceArgs.firstIndex(of: "--dev-accept-send-files"), clipMeshAcceptanceArgs.count > index + 3 {
    let address = clipMeshAcceptanceArgs[index + 1]
    let fingerprint = clipMeshAcceptanceArgs[index + 2]
    let paths = Array(clipMeshAcceptanceArgs[(index + 3)...])
    do {
        try LocalTransferManager.shared.devAcceptanceSend(files: paths.map { URL(fileURLWithPath: $0) }, address: address, fingerprint: fingerprint)
        print("send_files=PASS"); exit(0)
    } catch {
        fputs("send_files=FAIL\nerror=\(error.localizedDescription)\n", stderr); exit(1)
    }
}

'''
    replace_once(
        app,
        'if CommandLine.arguments.contains("--smoke-test") {\n',
        cli + 'if CommandLine.arguments.contains("--smoke-test") {\n',
        "macOS acceptance CLI",
    )

    required = {
        transfer: ("devAcceptanceSnapshotLines", "devAcceptanceSend(files:", "ClipMesh.Acceptance.IncomingPolicy", "DispatchQueue.main.sync"),
        app: ("--dev-accept-command", "--dev-accept-state", "--dev-accept-send-files", "ClipMesh.Acceptance.WindowVisible", "ClipMesh.Acceptance.FileNearbyCount"),
    }
    for path, needles in required.items():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                raise SystemExit(f"macOS acceptance guard missing in {path}: {needle}")

else:
    raise SystemExit(f"acceptance v2 supports Darwin/Linux only, got {SYSTEM}")

print(f"Applied ClipMesh comprehensive physical acceptance v2 on {SYSTEM}")
