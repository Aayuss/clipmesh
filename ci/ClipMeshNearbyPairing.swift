import Cocoa
import CryptoKit
import Foundation
import Network

private struct CMPairKeys {
    let encryption: Data
    let authentication: Data
}

enum NearbyPairingCrypto {
    static let protocolName = "ClipMesh-Pair-v1"

    static func base64url(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    static func decode64(_ value: String) -> Data? {
        var text = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        text += String(repeating: "=", count: (4 - text.count % 4) % 4)
        return Data(base64Encoded: text)
    }

    static func transcript(session: String, requestNonce: String, initiatorFingerprint: String, responderFingerprint: String, initiatorPublic: String, responderPublic: String) -> Data {
        Data("\(protocolName)\n\(session)\n\(requestNonce)\n\(initiatorFingerprint)\n\(responderFingerprint)\n\(initiatorPublic)\n\(responderPublic)".utf8)
    }

    private static func hmac(_ key: Data, _ data: Data) -> Data {
        Data(HMAC<SHA256>.authenticationCode(for: data, using: SymmetricKey(data: key)))
    }

    private static func expand(prk: Data, info: Data, count: Int) -> Data {
        var output = Data(), previous = Data(), counter: UInt8 = 1
        while output.count < count {
            previous = hmac(prk, previous + info + Data([counter]))
            output.append(previous); counter &+= 1
        }
        return output.prefix(count)
    }

    private static func keys(sharedSecret: Data, transcript: Data) -> CMPairKeys {
        let salt = Data(SHA256.hash(data: transcript))
        let prk = hmac(salt, sharedSecret)
        let material = expand(prk: prk, info: Data("clipmesh-nearby-pair-v1".utf8), count: 64)
        return CMPairKeys(encryption: material.prefix(32), authentication: material.dropFirst(32).prefix(32))
    }

    static func verificationCode(sharedSecret: Data, transcript: Data) -> String {
        let key = keys(sharedSecret: sharedSecret, transcript: transcript).authentication
        let digest = hmac(key, Data("sas\n".utf8) + transcript)
        let value = digest.prefix(4).reduce(UInt32(0)) { ($0 << 8) | UInt32($1) } % 1_000_000
        return String(format: "%06u", value)
    }

    static func seal(_ plaintext: Data, sharedSecret: Data, transcript: Data, nonce: Data) -> (Data, Data) {
        let key = keys(sharedSecret: sharedSecret, transcript: transcript)
        var stream = Data(), counter: UInt32 = 0
        while stream.count < plaintext.count {
            let bytes = Data([UInt8(counter >> 24), UInt8(counter >> 16), UInt8(counter >> 8), UInt8(counter)])
            stream.append(hmac(key.encryption, Data("stream\n".utf8) + nonce + bytes)); counter &+= 1
        }
        let cipher = Data(zip(plaintext, stream).map { $0 ^ $1 })
        let tag = hmac(key.authentication, Data("payload\n".utf8) + transcript + nonce + cipher)
        return (cipher, tag)
    }

    static func open(_ ciphertext: Data, tag: Data, sharedSecret: Data, transcript: Data, nonce: Data) -> Data? {
        let key = keys(sharedSecret: sharedSecret, transcript: transcript)
        let expected = hmac(key.authentication, Data("payload\n".utf8) + transcript + nonce + ciphertext)
        guard constantTimeEqual(tag, expected) else { return nil }
        var stream = Data(), counter: UInt32 = 0
        while stream.count < ciphertext.count {
            let bytes = Data([UInt8(counter >> 24), UInt8(counter >> 16), UInt8(counter >> 8), UInt8(counter)])
            stream.append(hmac(key.encryption, Data("stream\n".utf8) + nonce + bytes)); counter &+= 1
        }
        return Data(zip(ciphertext, stream).map { $0 ^ $1 })
    }

    static func constantTimeEqual(_ lhs: Data, _ rhs: Data) -> Bool {
        guard lhs.count == rhs.count else { return false }
        return zip(lhs, rhs).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
    }

    static func selfTest() throws {
        let a = P256.KeyAgreement.PrivateKey(), b = P256.KeyAgreement.PrivateKey()
        let ab = try a.sharedSecretFromKeyAgreement(with: b.publicKey).withUnsafeBytes { Data(SHA256.hash(data: Data($0))) }
        let ba = try b.sharedSecretFromKeyAgreement(with: a.publicKey).withUnsafeBytes { Data(SHA256.hash(data: Data($0))) }
        guard constantTimeEqual(ab, ba) else { throw NSError(domain: "ClipMeshPairing", code: 1) }
        let transcript = Data("self-test".utf8), nonce = Data((0..<16).map(UInt8.init)), message = Data("clipmesh://pair?self-test".utf8)
        let sealed = seal(message, sharedSecret: ab, transcript: transcript, nonce: nonce)
        guard open(sealed.0, tag: sealed.1, sharedSecret: ba, transcript: transcript, nonce: nonce) == message else { throw NSError(domain: "ClipMeshPairing", code: 2) }
    }
}

private final class CMPairReceiveSession {
    let id: String, sender: String, code: String
    let secret: Data, transcript: Data
    let expires = Date().addingTimeInterval(120)
    var verified = false, rejected = false
    init(id: String, sender: String, code: String, secret: Data, transcript: Data) { self.id = id; self.sender = sender; self.code = code; self.secret = secret; self.transcript = transcript }
}

final class NearbyPairingManager {
    static let shared = NearbyPairingManager()
    static let port: UInt16 = 53422

    var approvalPrompt: ((String) -> Bool)?
    var codePrompt: ((String, @escaping (String?) -> Void) -> Void)?
    var credentialConsumer: ((String, String) -> Bool)?
    var aliasProvider: (() -> String)?
    var fingerprintProvider: (() -> String)?

    private let queue = DispatchQueue(label: "dev.clipmesh.nearby-pairing", qos: .utility)
    private let lock = NSLock()
    private var listener: NWListener?
    private var sessions: [String: CMPairReceiveSession] = [:]

    func start() {
        guard listener == nil else { return }
        do {
            let value = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: Self.port)!)
            listener = value
            value.newConnectionHandler = { [weak self] in self?.handle($0) }
            value.start(queue: queue)
        } catch { NSLog("ClipMesh nearby pairing listener failed: %@", error.localizedDescription) }
    }

    func stop() { listener?.cancel(); listener = nil; lock.lock(); sessions.removeAll(); lock.unlock() }

    func pair(credential: String, with device: TransferDevice, code: @escaping (String) -> Void, completion: @escaping (Result<Void, Error>) -> Void) {
        queue.async {
            do {
                let privateKey = P256.KeyAgreement.PrivateKey()
                let initiatorPublic = NearbyPairingCrypto.base64url(privateKey.publicKey.x963Representation)
                let requestNonce = NearbyPairingCrypto.base64url(Self.random(16))
                let initiatorFingerprint = self.fingerprintProvider?() ?? "unavailable"
                let start: [String: Any] = ["alias": self.aliasProvider?() ?? "Mac", "fingerprint": initiatorFingerprint, "publicKey": initiatorPublic, "requestNonce": requestNonce]
                let response = try self.post(device: device, path: "/api/clipmesh/v1/pair/start", object: start)
                guard response.0 == 200, let root = response.1, let id = root["sessionId"] as? String, let responderFP = root["responderFingerprint"] as? String, let responderText = root["responderPublicKey"] as? String, let responderData = NearbyPairingCrypto.decode64(responderText) else { throw self.error(response.0, "Pairing request was rejected") }
                let peer = try P256.KeyAgreement.PublicKey(x963Representation: responderData)
                let secret = try privateKey.sharedSecretFromKeyAgreement(with: peer).withUnsafeBytes { Data(SHA256.hash(data: Data($0))) }
                let transcript = NearbyPairingCrypto.transcript(session: id, requestNonce: requestNonce, initiatorFingerprint: initiatorFingerprint, responderFingerprint: responderFP, initiatorPublic: initiatorPublic, responderPublic: responderText)
                let sas = NearbyPairingCrypto.verificationCode(sharedSecret: secret, transcript: transcript)
                DispatchQueue.main.async { code(sas) }
                var verified = false
                for _ in 0..<160 {
                    let state = try self.post(device: device, path: "/api/clipmesh/v1/pair/status", object: ["sessionId": id])
                    if state.0 == 200, let json = state.1, (json["verified"] as? Bool) == true { verified = true; break }
                    if state.0 == 403 || (state.1?["rejected"] as? Bool) == true { break }
                    Thread.sleep(forTimeInterval: 0.75)
                }
                guard verified else { throw self.error(408, "The verification code was not confirmed") }
                let nonce = Self.random(16)
                let sealed = NearbyPairingCrypto.seal(Data(credential.utf8), sharedSecret: secret, transcript: transcript, nonce: nonce)
                let complete: [String: Any] = ["sessionId": id, "nonce": NearbyPairingCrypto.base64url(nonce), "ciphertext": NearbyPairingCrypto.base64url(sealed.0), "tag": NearbyPairingCrypto.base64url(sealed.1)]
                let done = try self.post(device: device, path: "/api/clipmesh/v1/pair/complete", object: complete)
                guard done.0 == 200 else { throw self.error(done.0, "The receiving device could not apply the pairing") }
                DispatchQueue.main.async { completion(.success(())) }
            } catch { DispatchQueue.main.async { completion(.failure(error)) } }
        }
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
        receive(connection, buffer: Data())
    }

    private func receive(_ connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 96 * 1024) { [weak self] data, _, complete, error in
            guard let self, error == nil else { connection.cancel(); return }
            var all = buffer; if let data { all.append(data) }
            guard let split = all.range(of: Data("\r\n\r\n".utf8)) else { if complete || all.count > 128 * 1024 { self.respond(connection, 400, ["error":"invalid request"]) } else { self.receive(connection, buffer: all) }; return }
            let header = String(data: all[..<split.lowerBound], encoding: .isoLatin1) ?? ""
            let lines = header.components(separatedBy: "\r\n"), first = lines.first?.split(separator: " ").map(String.init) ?? []
            var length = 0
            for line in lines.dropFirst() { if line.lowercased().hasPrefix("content-length:"), let n = Int(line.split(separator: ":", maxSplits: 1)[1].trimmingCharacters(in: .whitespaces)) { length = n } }
            let initial = Data(all[split.upperBound...])
            guard first.count >= 2, first[0] == "POST", length <= 65_536 else { self.respond(connection, 400, ["error":"invalid request"]); return }
            self.receiveBody(connection, expected: length, data: initial) { body in self.route(connection, path: first[1], body: body) }
        }
    }

    private func receiveBody(_ connection: NWConnection, expected: Int, data: Data, completion: @escaping (Data) -> Void) {
        if data.count >= expected { completion(data.prefix(expected)); return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: expected - data.count) { [weak self] next, _, complete, _ in var all = data; if let next { all.append(next) }; if complete && all.count < expected { self?.respond(connection, 400, ["error":"short body"]) } else { self?.receiveBody(connection, expected: expected, data: all, completion: completion) } }
    }

    private func route(_ connection: NWConnection, path: String, body: Data) {
        cleanup()
        guard let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else { respond(connection, 400, ["error":"invalid json"]); return }
        if path == "/api/clipmesh/v1/pair/start" { begin(connection, json); return }
        guard let id = json["sessionId"] as? String else { respond(connection, 400, ["error":"missing session"]); return }
        lock.lock(); let session = sessions[id]; lock.unlock()
        guard let session, session.expires > Date() else { respond(connection, 404, ["error":"expired"]); return }
        if path == "/api/clipmesh/v1/pair/status" { respond(connection, session.rejected ? 403 : 200, ["verified":session.verified, "rejected":session.rejected]); return }
        if path == "/api/clipmesh/v1/pair/complete" { complete(connection, json, session); return }
        respond(connection, 404, ["error":"not found"])
    }

    private func begin(_ connection: NWConnection, _ json: [String: Any]) {
        guard let sender = json["alias"] as? String, let initiatorFP = json["fingerprint"] as? String, let initiatorText = json["publicKey"] as? String, let requestNonce = json["requestNonce"] as? String, sender.count <= 80, initiatorFP.count <= 200, requestNonce.count <= 100, let initiatorData = NearbyPairingCrypto.decode64(initiatorText), initiatorData.count == 65 else { respond(connection, 400, ["error":"invalid pairing request"]); return }
        guard approvalPrompt?(sender) == true else { respond(connection, 403, ["error":"rejected"]); return }
        do {
            let privateKey = P256.KeyAgreement.PrivateKey(), responderText = NearbyPairingCrypto.base64url(privateKey.publicKey.x963Representation), id = UUID().uuidString.lowercased(), responderFP = fingerprintProvider?() ?? "unavailable"
            let peer = try P256.KeyAgreement.PublicKey(x963Representation: initiatorData)
            let secret = try privateKey.sharedSecretFromKeyAgreement(with: peer).withUnsafeBytes { Data(SHA256.hash(data: Data($0))) }
            let transcript = NearbyPairingCrypto.transcript(session: id, requestNonce: requestNonce, initiatorFingerprint: initiatorFP, responderFingerprint: responderFP, initiatorPublic: initiatorText, responderPublic: responderText)
            let session = CMPairReceiveSession(id: id, sender: sender, code: NearbyPairingCrypto.verificationCode(sharedSecret: secret, transcript: transcript), secret: secret, transcript: transcript)
            lock.lock(); sessions[id] = session; lock.unlock()
            respond(connection, 200, ["sessionId":id, "responderFingerprint":responderFP, "responderPublicKey":responderText]) { [weak self] in
                self?.codePrompt?(sender) { entered in self?.verify(id: id, entered: entered) }
            }
        } catch { respond(connection, 400, ["error":"invalid public key"]) }
    }

    private func verify(id: String, entered: String?) {
        lock.lock(); defer { lock.unlock() }
        guard let session = sessions[id], session.expires > Date() else { return }
        let value = entered?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        session.verified = NearbyPairingCrypto.constantTimeEqual(Data(value.utf8), Data(session.code.utf8)); session.rejected = !session.verified
    }

    private func complete(_ connection: NWConnection, _ json: [String: Any], _ session: CMPairReceiveSession) {
        guard session.verified, let n = json["nonce"] as? String, let c = json["ciphertext"] as? String, let t = json["tag"] as? String, let nonce = NearbyPairingCrypto.decode64(n), nonce.count == 16, let cipher = NearbyPairingCrypto.decode64(c), cipher.count <= 16_384, let tag = NearbyPairingCrypto.decode64(t), let plain = NearbyPairingCrypto.open(cipher, tag: tag, sharedSecret: session.secret, transcript: session.transcript, nonce: nonce), let credential = String(data: plain, encoding: .utf8), credential.hasPrefix("clipmesh://pair?") else { respond(connection, 403, ["error":"authentication failed"]); return }
        guard credentialConsumer?(credential, session.sender) == true else { respond(connection, 422, ["error":"credential rejected"]); return }
        lock.lock(); sessions.removeValue(forKey: session.id); lock.unlock(); respond(connection, 200, ["paired":true])
    }

    private func post(device: TransferDevice, path: String, object: [String: Any]) throws -> (Int, [String: Any]?) {
        let body = try JSONSerialization.data(withJSONObject: object)
        guard let url = URL(string: "http://\(device.address):\(Self.port)\(path)") else { throw error(400, "Invalid device address") }
        var request = URLRequest(url: url); request.httpMethod = "POST"; request.httpBody = body; request.timeoutInterval = 65; request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let sem = DispatchSemaphore(value: 0); var result: (Int, Data?, Error?) = (0, nil, nil)
        URLSession.shared.dataTask(with: request) { data, response, problem in result = ((response as? HTTPURLResponse)?.statusCode ?? 0, data, problem); sem.signal() }.resume()
        guard sem.wait(timeout: .now() + 70) == .success else { throw error(408, "Pairing request timed out") }
        if let problem = result.2 { throw problem }
        let json = result.1.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        return (result.0, json)
    }

    private func respond(_ connection: NWConnection, _ code: Int, _ object: [String: Any], completion: (() -> Void)? = nil) {
        let data = (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8)
        let reason = code == 200 ? "OK" : code == 400 ? "Bad Request" : code == 403 ? "Forbidden" : code == 404 ? "Not Found" : code == 422 ? "Unprocessable Entity" : "Error"
        var packet = Data("HTTP/1.1 \(code) \(reason)\r\nContent-Type: application/json\r\nContent-Length: \(data.count)\r\nConnection: close\r\n\r\n".utf8); packet.append(data)
        connection.send(content: packet, completion: .contentProcessed { _ in connection.cancel(); completion?() })
    }

    private func cleanup() { let now = Date(); lock.lock(); sessions = sessions.filter { $0.value.expires > now }; lock.unlock() }
    private func error(_ code: Int, _ message: String) -> Error { NSError(domain: "ClipMeshNearbyPairing", code: code, userInfo: [NSLocalizedDescriptionKey: message]) }
    private static func random(_ count: Int) -> Data { var rng = SystemRandomNumberGenerator(); return Data((0..<count).map { _ in UInt8.random(in: 0...255, using: &rng) }) }
}
