from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"


def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8")
    updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=flags)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")


if True:
    app = ROOT / "ci/ClipMeshApp.swift"
    pairing = ROOT / "ci/ClipMeshNearbyPairing.swift"
    # Pair protocol returns the responder clipboard identity so the initiator can
    # seed/unblock it after the encrypted credential exchange succeeds.
    replace(
        pairing,
        "    var fingerprintProvider: (() -> String)?\n",
        "    var fingerprintProvider: (() -> String)?\n    var deviceIDProvider: (() -> String)?\n    var peerConsumer: ((String, String) -> Bool)?\n",
        "mac pairing identity callbacks",
    )
    replace(
        pairing,
        '                guard response.0 == 200, let root = response.1, let id = root["sessionId"] as? String, let responderFP = root["responderFingerprint"] as? String, let responderText = root["responderPublicKey"] as? String, let responderData = NearbyPairingCrypto.decode64(responderText) else { throw self.error(response.0, "Pairing request was rejected") }',
        '                guard response.0 == 200, let root = response.1, let id = root["sessionId"] as? String, let responderFP = root["responderFingerprint"] as? String, let responderText = root["responderPublicKey"] as? String, let responderData = NearbyPairingCrypto.decode64(responderText), let responderID = root["responderDeviceId"] as? String else { throw self.error(response.0, "Pairing request was rejected") }\n                let responderName = (root["responderName"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false ? (root["responderName"] as! String) : device.alias',
        "mac parse responder clipboard identity",
    )
    replace(pairing, "                for _ in 0..<160 {", "                for _ in 0..<80 {", "mac lower pairing request count")
    replace(pairing, "                    Thread.sleep(forTimeInterval: 0.75)", "                    Thread.sleep(forTimeInterval: 1.5)", "mac pairing backoff")
    replace(
        pairing,
        '                guard done.0 == 200 else { throw self.error(done.0, "The receiving device could not apply the pairing") }\n                DispatchQueue.main.async { completion(.success(())) }',
        '                guard done.0 == 200 else { throw self.error(done.0, "The receiving device could not apply the pairing") }\n                guard self.peerConsumer?(responderID, responderName) == true else { throw self.error(422, "The paired device identity could not be saved") }\n                DispatchQueue.main.async { completion(.success(())) }',
        "mac seed responder after pairing",
    )
    replace(
        pairing,
        '            respond(connection, 200, ["sessionId":id, "responderFingerprint":responderFP, "responderPublicKey":responderText]) { [weak self] in',
        '            respond(connection, 200, ["sessionId":id, "responderFingerprint":responderFP, "responderPublicKey":responderText, "responderDeviceId":deviceIDProvider?() ?? "", "responderName":aliasProvider?() ?? "Mac"]) { [weak self] in',
        "mac advertise clipboard identity during pair",
    )
    replace(
        app,
        "    static func setName(_ name: String) throws {",
        """    static func seedPeer(_ id: String, name: String) throws {
        _ = try checked([\"seed-peer\", id, \"--name\", name], message: \"Could not save the paired device.\")
    }

    static func setName(_ name: String) throws {""",
        "mac seed-peer runtime bridge",
    )
    replace(app,"    private var nearbyPairStack: NSStackView!","    private var nearbyPairStack: NSStackView!\n    private var nearbyCodeAlert: NSAlert?","mac pairing code dialog property")
    replace(
        app,
        "        nearbyPair.fingerprintProvider = { LocalTransferManager.shared.fingerprint }",
        """        nearbyPair.fingerprintProvider = { LocalTransferManager.shared.fingerprint }
        nearbyPair.deviceIDProvider = { [weak self] in self?.latestState?.deviceID ?? ((try? Runtime.uiState().deviceID) ?? \"\") }
        nearbyPair.peerConsumer = { [weak self] id, name in
            guard let self else { return false }
            var ok = false
            let work = {
                self.stopDaemon()
                do { try Runtime.seedPeer(id, name: name); try self.startDaemon(); self.refreshHome(); ok = true }
                catch { try? self.startDaemon(); self.showError(error.localizedDescription) }
            }
            if Thread.isMainThread { work() } else { DispatchQueue.main.sync(execute: work) }
            return ok
        }""",
        "mac pairing identity setup",
    )
    regex(
        app,
        r"    private func startNearbyPair\(_ device: TransferDevice\) \{.*?\n    private func approveNearbyPair",
        r'''    private func startNearbyPair(_ device: TransferDevice) {
        do {
            let credential = try Runtime.pairingLink()
            statusLabel.stringValue = "Waiting for \(device.alias)…"
            NearbyPairingManager.shared.pair(credential: credential, with: device, code: { [weak self] value in
                self?.showNearbyPairCode(value, device: device.alias)
            }, completion: { [weak self] result in
                guard let self else { return }
                self.dismissNearbyPairCode()
                switch result {
                case .success:
                    self.statusLabel.stringValue = "Paired with \(device.alias)"
                    LocalTransferManager.shared.discoverNow()
                    self.refreshHome()
                    self.refreshNearbyPairDevices()
                case .failure(let error):
                    self.showError(error.localizedDescription)
                    self.refreshHome()
                }
            })
        } catch { showError(error.localizedDescription) }
    }

    private func showNearbyPairCode(_ value: String, device: String) {
        dismissNearbyPairCode()
        let code = NSTextField(labelWithString: value)
        code.font = .monospacedDigitSystemFont(ofSize: 46, weight: .bold)
        code.alignment = .center
        code.maximumNumberOfLines = 1
        code.translatesAutoresizingMaskIntoConstraints = false
        code.widthAnchor.constraint(greaterThanOrEqualToConstant: 300).isActive = true
        code.heightAnchor.constraint(greaterThanOrEqualToConstant: 60).isActive = true
        let alert = NSAlert()
        alert.messageText = "Verification code"
        alert.informativeText = "Type this code on \(device). This window closes automatically when pairing completes."
        alert.accessoryView = code
        alert.addButton(withTitle: "Pairing…")
        alert.buttons.first?.isEnabled = false
        nearbyCodeAlert = alert
        NSApp.activate(ignoringOtherApps: true)
        if let window { alert.beginSheetModal(for: window) { _ in } }
    }

    private func dismissNearbyPairCode() {
        guard let alert = nearbyCodeAlert else { return }
        nearbyCodeAlert = nil
        if let parent = alert.window.sheetParent { parent.endSheet(alert.window) }
        else { alert.window.orderOut(nil) }
    }

    private func approveNearbyPair''',
        "mac auto-dismiss pairing code dialog",
    )
    regex(
        app,
        r"    private func promptNearbyCode\(_ sender:String,submit:@escaping\(String\?\)->Void\)\{.*?\}\n    private func acceptNearbyCredential",
        r'''    private func promptNearbyCode(_ sender: String, submit: @escaping (String?) -> Void) {
        DispatchQueue.main.async {
            let input = NSTextField(string: "")
            input.placeholderString = "000000"
            input.alignment = .center
            input.font = .monospacedDigitSystemFont(ofSize: 34, weight: .bold)
            input.frame = NSRect(x: 0, y: 0, width: 280, height: 52)
            submit(CMDialog.run(title: "Verify \(sender)", message: "Type the six-digit code shown on \(sender).", accessory: input, buttons: ["Cancel", "Pair"]) == 1 ? input.stringValue : nil)
        }
    }
    private func acceptNearbyCredential''',
        "mac large pairing code input",
    )
