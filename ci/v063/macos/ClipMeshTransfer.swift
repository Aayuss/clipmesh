import Cocoa
import UserNotifications
import Foundation
import Network
import Darwin

struct TransferDevice: Hashable {
    let alias: String
    let fingerprint: String
    let address: String
    let port: UInt16
    let model: String
    let type: String
    let lastSeen: Date
}

struct TransferMeta {
    let id: String
    let name: String
    let size: Int64
    let mime: String
    let sha256: String?
}

private final class UploadSession {
    let id: String
    let sender: String
    let fingerprint: String
    let files: [String: TransferMeta]
    let tokens: [String: String]
    var received = Set<String>()
    var receivedBytes: Int64 = 0
    var lastProgressPercent = -1
    var lastNotifiedPercent = -10
    var totalBytes: Int64 { files.values.reduce(0) { $0 + $1.size } }

    init(id: String, sender: String, fingerprint: String, files: [String: TransferMeta], tokens: [String: String]) {
        self.id = id; self.sender = sender; self.fingerprint = fingerprint; self.files = files; self.tokens = tokens
    }
}

private enum TransferPrefs {
    static let fingerprintKey = "ClipMesh.FileTransfer.Fingerprint"
    static let favoritesKey = "ClipMesh.FileTransfer.Favorites"
    static let outputFolderKey = "ClipMesh.FileTransfer.OutputFolder"

    static var fingerprint: String {
        let defaults = UserDefaults.standard
        if let value = defaults.string(forKey: fingerprintKey), !value.isEmpty { return value }
        let value = UUID().uuidString.lowercased()
        defaults.set(value, forKey: fingerprintKey)
        return value
    }

    static var favorites: Set<String> {
        get { Set(UserDefaults.standard.stringArray(forKey: favoritesKey) ?? []) }
        set { UserDefaults.standard.set(Array(newValue).sorted(), forKey: favoritesKey) }
    }

    static var outputFolder: URL {
        get {
            if let path = UserDefaults.standard.string(forKey: outputFolderKey), !path.isEmpty {
                return URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL
            }
            return FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0].appendingPathComponent("ClipMesh", isDirectory: true)
        }
        set { UserDefaults.standard.set(newValue.standardizedFileURL.path, forKey: outputFolderKey) }
    }
}

private final class CMUploadProgressDelegate: NSObject, URLSessionTaskDelegate {
    let onProgress: (Int64) -> Void
    let onComplete: (Result<Int, Error>) -> Void
    init(onProgress: @escaping (Int64) -> Void, onComplete: @escaping (Result<Int, Error>) -> Void) {
        self.onProgress = onProgress
        self.onComplete = onComplete
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        onProgress(totalBytesSent)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { onComplete(.failure(error)) }
        else { onComplete(.success((task.response as? HTTPURLResponse)?.statusCode ?? 0)) }
    }
}

private enum CMTransferPresentation {
    private static var lastDockPercent = -1
    static func updateDock(_ fraction: Double) {
        DispatchQueue.main.async {
            let percent = Int((min(1, max(0, fraction)) * 100).rounded())
            guard percent != lastDockPercent else { return }
            lastDockPercent = percent
            NSApp.dockTile.badgeLabel = percent >= 100 ? nil : "\(percent)%"
            NSApp.dockTile.display()
        }
    }
    static func clearDock() {
        DispatchQueue.main.async {
            lastDockPercent = -1
            NSApp.dockTile.badgeLabel = nil
            NSApp.dockTile.display()
        }
    }
    static func notify(identifier: String = "clipmesh-transfer-\(UUID().uuidString)", title: String, body: String) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            let post: () -> Void = {
                let content = UNMutableNotificationContent()
                content.title = title
                content.body = body
                center.removeDeliveredNotifications(withIdentifiers: [identifier])
                center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil))
            }
            switch settings.authorizationStatus {
            case .authorized, .provisional: post()
            case .notDetermined:
                center.requestAuthorization(options: [.alert, .sound]) { granted, _ in if granted { post() } }
            default: break
            }
        }
    }
}

final class LocalTransferManager {
    static let shared = LocalTransferManager()
    static let port: UInt16 = 53421
    static let group = "224.0.0.167"

    var incomingPrompt: ((String, [TransferMeta]) -> Bool)?
    var incomingProgress: ((String, String, Double, Bool) -> Void)?
    /// Fired on the main thread (coalesced ~100ms) when a nearby device appears,
    /// changes, or expires. Replaces any UI-side polling of nearbyDevices().
    var devicesChanged: (() -> Void)?
    private static let deviceTTL: TimeInterval = 180
    private var devicesChangedScheduled = false
    private var expiryWorkItem: DispatchWorkItem?
    var aliasProvider: (() -> String)?
    private var uiVisible = false
    private var serverReady = false
    private var visibleDevices = Set<String>()

    private let httpQueue = DispatchQueue(label: "dev.clipmesh.fileshare.http", qos: .utility)
    private let discoveryQueue = DispatchQueue(label: "dev.clipmesh.fileshare.discovery", qos: .utility)
    private let announceQueue = DispatchQueue(label: "dev.clipmesh.fileshare.announce", qos: .utility)
    private let sendQueue = DispatchQueue(label: "dev.clipmesh.fileshare.send", qos: .utility)
    private let stateLock = NSLock()
    private var listener: NWListener?
    private var udpFD: Int32 = -1
    private var running = false
    private var devices: [String: TransferDevice] = [:]
    private var sessions: [String: UploadSession] = [:]

    private init() {}

    func start(aliasProvider: @escaping () -> String) {
        stateLock.lock()
        if running { self.aliasProvider = aliasProvider; stateLock.unlock(); return }
        running = true
        self.aliasProvider = aliasProvider
        stateLock.unlock()
        startHTTP()
        startDiscovery()
    }

    func stop() {
        stateLock.lock(); running = false; stateLock.unlock()
        listener?.cancel(); listener = nil
        stateLock.lock(); serverReady = false; stateLock.unlock()
        if udpFD >= 0 { Darwin.close(udpFD); udpFD = -1 }
    }

    func nearbyDevices() -> [TransferDevice] {
        stateLock.lock(); defer { stateLock.unlock() }
        let cutoff = Date().addingTimeInterval(-180)
        devices = devices.filter { $0.value.lastSeen >= cutoff }
        let favorites = TransferPrefs.favorites
        return devices.values
            .filter { $0.fingerprint != TransferPrefs.fingerprint }
            .sorted {
                let af = favorites.contains($0.fingerprint), bf = favorites.contains($1.fingerprint)
                if af != bf { return af && !bf }
                return $0.alias.localizedCaseInsensitiveCompare($1.alias) == .orderedAscending
            }
    }

    var fingerprint: String { TransferPrefs.fingerprint }

    var outputFolderURL: URL { TransferPrefs.outputFolder }

    func setOutputFolder(_ url: URL) throws {
        let selected = url.standardizedFileURL
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: selected.path, isDirectory: &isDirectory) {
            guard isDirectory.boolValue else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Choose a folder, not a file."]) }
        } else {
            try FileManager.default.createDirectory(at: selected, withIntermediateDirectories: true)
        }
        guard FileManager.default.isWritableFile(atPath: selected.path) else { throw NSError(domain: "ClipMesh", code: 71, userInfo: [NSLocalizedDescriptionKey: "ClipMesh cannot write to that folder."]) }
        TransferPrefs.outputFolder = selected
    }

    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }

    func setUIVisible(_ visible: Bool) {
        stateLock.lock()
        let changed = uiVisible != visible
        uiVisible = visible
        stateLock.unlock()
        if changed { discoverNow() }
    }

    private var isServerReady: Bool {
        stateLock.lock(); defer { stateLock.unlock() }
        return serverReady
    }

    private var isUIVisible: Bool {
        stateLock.lock(); defer { stateLock.unlock() }
        return uiVisible
    }

    func discoverNow() {
        announceQueue.async { [weak self] in
            guard let self else { return }
            self.sendAnnouncement(announce: true)
            self.announceQueue.asyncAfter(deadline: .now() + 0.18) { [weak self] in self?.sendAnnouncement(announce: true) }
            self.announceQueue.asyncAfter(deadline: .now() + 0.36) { [weak self] in self?.sendAnnouncement(announce: true) }
        }
    }

    func setFavorite(_ fingerprint: String, _ favorite: Bool) {
        var values = TransferPrefs.favorites
        if favorite { values.insert(fingerprint) } else { values.remove(fingerprint) }
        TransferPrefs.favorites = values
    }

    func devTestFingerprint() -> String { TransferPrefs.fingerprint }

    func devTestSend(file: URL, address: String, fingerprint: String) throws {
        aliasProvider = { "ClipMesh Mac E2E" }
        let target = TransferDevice(alias: "ClipMesh Android E2E", fingerprint: fingerprint, address: address, port: Self.port, model: "Android", type: "mobile", lastSeen: Date())
        try sendSync(files: [file], to: target, progress: { _ in })
    }

    func send(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, progressValue: @escaping (Double) -> Void = { _ in }, completion: @escaping (Result<Void, Error>) -> Void) {
        sendQueue.async {
            do {
                try self.sendSync(files: files, to: device, progress: progress, progressValue: progressValue)
                DispatchQueue.main.async { completion(.success(())) }
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
            }
        }
    }

    // MARK: Discovery

    private func startDiscovery() {
        discoveryQueue.async {
            let fd = Darwin.socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
            guard fd >= 0 else { return }
            self.udpFD = fd
            var yes: Int32 = 1
            setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
            var bindAddr = sockaddr_in()
            bindAddr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            bindAddr.sin_family = sa_family_t(AF_INET)
            bindAddr.sin_port = in_port_t(Self.port.bigEndian)
            bindAddr.sin_addr = in_addr(s_addr: INADDR_ANY)
            let bound = withUnsafePointer(to: &bindAddr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
            }
            guard bound == 0 else { Darwin.close(fd); self.udpFD = -1; return }
            var request = ip_mreq(
                imr_multiaddr: in_addr(s_addr: inet_addr(Self.group)),
                imr_interface: in_addr(s_addr: INADDR_ANY)
            )
            guard setsockopt(fd, IPPROTO_IP, IP_ADD_MEMBERSHIP, &request, socklen_t(MemoryLayout<ip_mreq>.size)) == 0 else {
                Darwin.close(fd); self.udpFD = -1; return
            }
            var buffer = [UInt8](repeating: 0, count: 65535)
            while self.isRunning {
                var remote = sockaddr_in()
                var remoteLen = socklen_t(MemoryLayout<sockaddr_in>.size)
                let count = withUnsafeMutablePointer(to: &remote) { ptr -> Int in
                    ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                        recvfrom(fd, &buffer, buffer.count, 0, sa, &remoteLen)
                    }
                }
                if count <= 0 { if self.isRunning { usleep(100_000) }; continue }
                let data = Data(buffer.prefix(count))
                guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                var addressBuffer = [CChar](repeating: 0, count: Int(INET6_ADDRSTRLEN))
                var addr = remote.sin_addr
                inet_ntop(AF_INET, &addr, &addressBuffer, socklen_t(INET_ADDRSTRLEN))
                let address = String(cString: addressBuffer)
                self.register(json: json, address: address)
                if (json["announce"] as? Bool) == true {
                    self.registerBack(json: json, address: address)
                    self.sendAnnouncement(announce: false)
                }
            }
        }
    }

    private func sendAnnouncement(announce: Bool) {
        guard isRunning && isServerReady else { return }
        let payload = info(announce: announce)
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        let fd = Darwin.socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard fd >= 0 else { return }
        defer { Darwin.close(fd) }
        var ttl: UInt8 = 1
        setsockopt(fd, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, socklen_t(MemoryLayout<UInt8>.size))
        var broadcastEnabled: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &broadcastEnabled, socklen_t(MemoryLayout<Int32>.size))

        func sendPacket(_ address: in_addr_t) {
            var destination = sockaddr_in()
            destination.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            destination.sin_family = sa_family_t(AF_INET)
            destination.sin_port = in_port_t(Self.port.bigEndian)
            destination.sin_addr = in_addr(s_addr: address)
            data.withUnsafeBytes { bytes in
                withUnsafePointer(to: &destination) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                        _ = sendto(fd, bytes.baseAddress, data.count, 0, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
        }

        // Multicast remains the primary protocol. Limited IPv4 broadcast is a
        // fallback for real Wi-Fi stacks that pass TCP but suppress multicast.
        sendPacket(inet_addr(Self.group))
        sendPacket(inet_addr("255.255.255.255"))
    }

    private func info(announce: Bool) -> [String: Any] {
        [
            "alias": safeAlias,
            "version": "2.0",
            "deviceModel": Host.current().localizedName ?? "Mac",
            "deviceType": "desktop",
            "fingerprint": TransferPrefs.fingerprint,
            "port": Int(Self.port),
            "protocol": "http",
            "download": false,
            "announce": announce,
            "visible": isUIVisible
        ]
    }

    private func register(json: [String: Any], address: String) {
        guard let fingerprint = json["fingerprint"] as? String, !fingerprint.isEmpty, fingerprint != TransferPrefs.fingerprint else { return }
        let alias = (json["alias"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).prefix(80) ?? "Nearby device"
        let model = (json["deviceModel"] as? String) ?? ""
        let type = (json["deviceType"] as? String) ?? "desktop"
        let port = UInt16((json["port"] as? Int) ?? Int(Self.port))
        let device = TransferDevice(alias: String(alias), fingerprint: fingerprint, address: address, port: port, model: model, type: type, lastSeen: Date())
        let remoteVisible = (json["visible"] as? Bool) ?? true
        stateLock.lock()
        let previous = devices[fingerprint]
        devices[fingerprint] = device
        if remoteVisible { visibleDevices.insert(fingerprint) } else { visibleDevices.remove(fingerprint) }
        stateLock.unlock()
        let changed = previous.map { $0.alias != device.alias || $0.address != device.address || $0.port != device.port || $0.model != device.model || $0.type != device.type } ?? true
        devicesDidChange(notify: changed)
    }

    /// Re-arms the single one-shot expiry and, when `notify`, schedules one coalesced callback.
    private func devicesDidChange(notify: Bool) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.rearmDeviceExpiry()
            guard notify, !self.devicesChangedScheduled else { return }
            self.devicesChangedScheduled = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                guard let self else { return }
                self.devicesChangedScheduled = false
                self.devicesChanged?()
            }
        }
    }

    /// One one-shot work item at the earliest device expiry (no periodic sweep).
    private func rearmDeviceExpiry() {
        expiryWorkItem?.cancel()
        expiryWorkItem = nil
        stateLock.lock()
        let earliest = devices.values.map(\.lastSeen).min()
        stateLock.unlock()
        guard let earliest else { return }
        let delay = max(0.5, earliest.addingTimeInterval(Self.deviceTTL).timeIntervalSinceNow + 0.05)
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            let cutoff = Date().addingTimeInterval(-Self.deviceTTL)
            self.stateLock.lock()
            let before = self.devices.count
            self.devices = self.devices.filter { $0.value.lastSeen >= cutoff }
            let removed = self.devices.count != before
            self.stateLock.unlock()
            self.devicesDidChange(notify: removed)
        }
        expiryWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private func registerBack(json: [String: Any], address: String) {
        guard
            let fingerprint = json["fingerprint"] as? String,
            !fingerprint.isEmpty,
            fingerprint != TransferPrefs.fingerprint
        else { return }
        let rawPort = (json["port"] as? NSNumber)?.intValue ?? Int(Self.port)
        guard let port = UInt16(exactly: rawPort), port > 0 else { return }
        let device = TransferDevice(
            alias: (json["alias"] as? String) ?? "Nearby device",
            fingerprint: fingerprint,
            address: address,
            port: port,
            model: (json["deviceModel"] as? String) ?? "",
            type: (json["deviceType"] as? String) ?? "desktop",
            lastSeen: Date()
        )
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            _ = try? self.requestJSON(device: device, path: "/api/clipmesh/v1/register", object: self.info(announce: false))
        }
    }

    // MARK: HTTP server

    private func startHTTP() {
        do {
            let parameters = NWParameters.tcp
            guard let ip = parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options else {
                throw NSError(domain: "ClipMesh", code: -1, userInfo: [NSLocalizedDescriptionKey: "Network.framework has no IP options"])
            }
            ip.version = .v4
            let listener = try NWListener(using: parameters, on: NWEndpoint.Port(rawValue: Self.port)!)
            self.listener = listener
            listener.newConnectionHandler = { [weak self] connection in self?.handle(connection) }
            listener.stateUpdateHandler = { [weak self] state in
                guard let self else { return }
                var becameReady = false
                self.stateLock.lock()
                switch state {
                case .ready:
                    self.serverReady = true
                    becameReady = true
                case .failed(_), .cancelled:
                    self.serverReady = false
                default:
                    break
                }
                self.stateLock.unlock()
                if becameReady { self.sendAnnouncement(announce: true) }
            }
            listener.start(queue: httpQueue)
        } catch {
            NSLog("ClipMesh file transfer listener failed: %@", error.localizedDescription)
        }
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: httpQueue)
        receiveHeader(connection, buffer: Data())
    }

    private func receiveHeader(_ connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, complete, error in
            guard let self else { return }
            if error != nil { connection.cancel(); return }
            var accumulated = buffer
            if let data { accumulated.append(data) }
            if let range = accumulated.range(of: Data("\r\n\r\n".utf8)) {
                let header = accumulated.subdata(in: 0..<range.lowerBound)
                let extra = accumulated.subdata(in: range.upperBound..<accumulated.count)
                self.route(connection, header: header, extra: extra)
            } else if accumulated.count > 128 * 1024 || complete {
                self.respond(connection, code: 400, body: "Invalid request")
            } else {
                self.receiveHeader(connection, buffer: accumulated)
            }
        }
    }

    private func route(_ connection: NWConnection, header: Data, extra: Data) {
        guard let text = String(data: header, encoding: .isoLatin1) else { return respond(connection, code: 400, body: "Bad request") }
        let lines = text.components(separatedBy: "\r\n")
        guard let first = lines.first else { return respond(connection, code: 400, body: "Bad request") }
        let parts = first.split(separator: " ").map(String.init)
        guard parts.count >= 2 else { return respond(connection, code: 400, body: "Bad request") }
        let method = parts[0].uppercased(), target = parts[1]
        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { continue }
            headers[String(line[..<colon]).lowercased()] = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
        }
        let length = Int(headers["content-length"] ?? "0") ?? 0
        if headers["expect"]?.lowercased().contains("100-continue") == true {
            connection.send(content: Data("HTTP/1.1 100 Continue\r\n\r\n".utf8), completion: .contentProcessed { error in if error != nil { connection.cancel() } })
        }
        guard let components = URLComponents(string: "http://clipmesh\(target)") else { return respond(connection, code: 400, body: "Bad target") }
        switch (method, components.path) {
        case ("GET", "/api/clipmesh/v1/info"):
            respondJSON(connection, object: info(announce: false))
        case ("POST", "/api/clipmesh/v1/register"):
            receiveSmallBody(connection, expected: length, initial: extra) { body in
                if let body, let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any] {
                    let endpoint = connection.currentPath?.remoteEndpoint
                    let address = Self.endpointAddress(endpoint) ?? ""
                    self.register(json: json, address: address)
                }
                self.respondJSON(connection, object: self.info(announce: false))
            }
        case ("POST", "/api/clipmesh/v1/prepare-upload"):
            receiveSmallBody(connection, expected: length, initial: extra) { body in
                guard let body else { return self.respond(connection, code: 400, body: "Invalid body") }
                self.prepareUpload(connection, body: body)
            }
        case ("POST", "/api/clipmesh/v1/upload"):
            upload(connection, components: components, expected: length, initial: extra)
        case ("POST", "/api/clipmesh/v1/cancel"):
            let query = Dictionary(uniqueKeysWithValues: (components.queryItems ?? []).map { ($0.name, $0.value ?? "") })
            if let session = query["sessionId"] { stateLock.lock(); sessions.removeValue(forKey: session); stateLock.unlock() }
            respond(connection, code: 200, body: "")
        default:
            respond(connection, code: 404, body: "Not found")
        }
    }

    private func receiveSmallBody(_ connection: NWConnection, expected: Int, initial: Data, completion: @escaping (Data?) -> Void) {
        guard expected >= 0 && expected <= 2 * 1024 * 1024 else { completion(nil); return }
        if initial.count >= expected { completion(initial.prefix(expected)); return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: min(64 * 1024, expected - initial.count)) { [weak self] data, _, complete, error in
            guard self != nil, error == nil else { completion(nil); return }
            var combined = initial
            if let data { combined.append(data) }
            if combined.count >= expected { completion(combined.prefix(expected)) }
            else if complete { completion(nil) }
            else { self?.receiveSmallBody(connection, expected: expected, initial: combined, completion: completion) }
        }
    }

    private func prepareUpload(_ connection: NWConnection, body: Data) {
        guard let root = try? JSONSerialization.jsonObject(with: body) as? [String: Any],
              let senderInfo = root["info"] as? [String: Any],
              let fileRoot = root["files"] as? [String: Any] else {
            return respond(connection, code: 400, body: "Invalid body")
        }
        let sender = (senderInfo["alias"] as? String) ?? "Nearby device"
        let fingerprint = (senderInfo["fingerprint"] as? String) ?? "unknown"
        var files: [String: TransferMeta] = [:]
        for (key, raw) in fileRoot {
            guard let item = raw as? [String: Any] else { continue }
            let id = (item["id"] as? String) ?? key
            let name = Self.safeFileName((item["fileName"] as? String) ?? "file")
            let size: Int64
            if let n = item["size"] as? NSNumber { size = n.int64Value } else { continue }
            if size < 0 { continue }
            files[id] = TransferMeta(id: id, name: name, size: size, mime: (item["fileType"] as? String) ?? "application/octet-stream", sha256: item["sha256"] as? String)
        }
        guard !files.isEmpty else { return respond(connection, code: 400, body: "No files") }
        let accepted: Bool
        if TransferPrefs.favorites.contains(fingerprint) {
            accepted = true
        } else {
            let sem = DispatchSemaphore(value: 0)
            var answer = false
            DispatchQueue.main.async {
                answer = self.incomingPrompt?(sender, Array(files.values)) ?? false
                sem.signal()
            }
            accepted = sem.wait(timeout: .now() + 60) == .success && answer
        }
        guard accepted else { return respond(connection, code: 403, body: "Rejected") }
        let sessionID = UUID().uuidString.lowercased()
        var tokens: [String: String] = [:]
        files.keys.forEach { tokens[$0] = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased() }
        let session = UploadSession(id: sessionID, sender: sender, fingerprint: fingerprint, files: files, tokens: tokens)
        stateLock.lock(); sessions[sessionID] = session; stateLock.unlock()
        respondJSON(connection, object: ["sessionId": sessionID, "files": tokens])
    }

    private func upload(_ connection: NWConnection, components: URLComponents, expected: Int, initial: Data) {
        let query = Dictionary(uniqueKeysWithValues: (components.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        guard let sid = query["sessionId"], let fid = query["fileId"], let token = query["token"] else { return respond(connection, code: 400, body: "Missing parameters") }
        stateLock.lock(); let session = sessions[sid]; stateLock.unlock()
        guard let session, let meta = session.files[fid], session.tokens[fid] == token else { return respond(connection, code: 403, body: "Invalid token") }
        guard expected == meta.size else { return respond(connection, code: 400, body: "Unexpected size") }
        do {
            let url = try destinationURL(for: meta)
            FileManager.default.createFile(atPath: url.path, contents: nil)
            let handle = try FileHandle(forWritingTo: url)
            let first = initial.prefix(min(initial.count, expected))
            if !first.isEmpty { try handle.write(contentsOf: first) }
            var fileReceived = first.count
            session.receivedBytes += Int64(first.count)
            publishIncomingProgress(session: session, file: meta.name, complete: false)
            receiveUpload(connection, handle: handle, destination: url, remaining: expected - first.count, onProgress: { count in
                fileReceived += count
                session.receivedBytes += Int64(count)
                self.publishIncomingProgress(session: session, file: meta.name, complete: false)
            }) { success in
                try? handle.close()
                guard success else {
                    session.receivedBytes -= Int64(fileReceived)
                    try? FileManager.default.removeItem(at: url)
                    self.publishIncomingFailure(session: session, file: meta.name)
                    return self.respond(connection, code: 500, body: "Transfer failed")
                }
                self.stateLock.lock()
                session.received.insert(fid)
                let done = session.received.count >= session.files.count
                if done { self.sessions.removeValue(forKey: sid) }
                self.stateLock.unlock()
                if done {
                    self.publishIncomingProgress(session: session, file: meta.name, complete: true)
                    self.refreshDownloadsFolderRecency()
                }
                self.respond(connection, code: 200, body: "")
            }
        } catch {
            respond(connection, code: 500, body: "Could not create destination")
        }
    }

    private func receiveUpload(_ connection: NWConnection, handle: FileHandle, destination: URL, remaining: Int, onProgress: @escaping (Int) -> Void, completion: @escaping (Bool) -> Void) {
        if remaining <= 0 { completion(true); return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: min(128 * 1024, remaining)) { [weak self] data, _, complete, error in
            guard self != nil, error == nil, let data, !data.isEmpty else { completion(false); return }
            do { try handle.write(contentsOf: data) } catch { completion(false); return }
            onProgress(data.count)
            let left = remaining - data.count
            if left <= 0 { completion(true) }
            else if complete { completion(false) }
            else { self?.receiveUpload(connection, handle: handle, destination: destination, remaining: left, onProgress: onProgress, completion: completion) }
        }
    }

    private func publishIncomingProgress(session: UploadSession, file: String, complete: Bool) {
        let fraction = session.totalBytes <= 0 ? 1 : min(1, max(0, Double(session.receivedBytes) / Double(session.totalBytes)))
        let percent = Int((fraction * 100).rounded())
        if !complete && percent == session.lastProgressPercent { return }
        session.lastProgressPercent = percent
        DispatchQueue.main.async { [weak self] in
            self?.incomingProgress?(session.sender, file, fraction, complete)
            if complete {
                CMTransferPresentation.clearDock()
                CMTransferPresentation.notify(identifier: "clipmesh-receive-\(session.id)", title: "Files received", body: "Saved from \(session.sender) to Downloads/ClipMesh")
            } else {
                CMTransferPresentation.updateDock(fraction)
                if percent == 0 || percent == 100 || percent - session.lastNotifiedPercent >= 10 {
                    session.lastNotifiedPercent = percent
                    CMTransferPresentation.notify(identifier: "clipmesh-receive-\(session.id)", title: "Receiving from \(session.sender) • \(percent)%", body: file)
                }
            }
        }
    }

    private func publishIncomingFailure(session: UploadSession, file: String) {
        DispatchQueue.main.async { [weak self] in
            self?.incomingProgress?(session.sender, file, -1, false)
            CMTransferPresentation.clearDock()
            CMTransferPresentation.notify(identifier: "clipmesh-receive-\(session.id)", title: "Transfer failed", body: "Could not receive \(file) from \(session.sender)")
        }
    }

    private struct FinderAddedTimeBuffer {
        var added: timespec
    }

    private func setFinderDateAdded(_ date: Date, for path: String) -> Bool {
        var attributes = attrlist()
        attributes.bitmapcount = UInt16(ATTR_BIT_MAP_COUNT)
        attributes.reserved = 0
        attributes.commonattr = attrgroup_t(ATTR_CMN_ADDEDTIME)
        attributes.volattr = 0
        attributes.dirattr = 0
        attributes.fileattr = 0
        attributes.forkattr = 0

        let seconds = date.timeIntervalSince1970
        var buffer = FinderAddedTimeBuffer(
            added: timespec(
                tv_sec: Int(seconds),
                tv_nsec: Int((seconds - floor(seconds)) * 1_000_000_000)
            )
        )
        let size = MemoryLayout<FinderAddedTimeBuffer>.size
        let result = path.withCString { cPath in
            setattrlist(cPath, &attributes, &buffer, size, 0)
        }
        if result != 0 {
            NSLog("ClipMesh could not set Finder Date Added on receive folder (errno=%d)", errno)
            return false
        }
        return true
    }

    private func refreshDownloadsFolderRecency() {
        let manager = FileManager.default
        let folder = TransferPrefs.outputFolder.standardizedFileURL
        guard manager.fileExists(atPath: folder.path) else { return }

        let now = Date()
        try? manager.setAttributes([.modificationDate: now], ofItemAtPath: folder.path)

        // Finder's Downloads grouping uses Date Added (ATTR_CMN_ADDEDTIME), not
        // ordinary modification time. Update that filesystem metadata directly.
        // This changes only metadata on the ClipMesh directory itself: no rename,
        // no copy, no recreation, and no traversal or rewriting of child files.
        guard setFinderDateAdded(now, for: folder.path) else { return }

        // Ask Spotlight to notice the metadata change promptly. Finder can still
        // cache a view briefly, but no expensive re-index of the Downloads tree is
        // requested here.
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/mdimport")
        task.arguments = ["-f", folder.path]
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        try? task.run()
    }

    private func destinationURL(for meta: TransferMeta) throws -> URL {
        var folder = TransferPrefs.outputFolder
        let mime = meta.mime.lowercased()
        if mime.hasPrefix("image/") { folder.appendPathComponent("images", isDirectory: true) }
        else if mime.hasPrefix("video/") { folder.appendPathComponent("video", isDirectory: true) }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let rawName = (meta.name as NSString).lastPathComponent.trimmingCharacters(in: .whitespacesAndNewlines)
        let safe = rawName.isEmpty ? "file" : String(rawName.prefix(180)).replacingOccurrences(of: ":", with: "_")
        var candidate = folder.appendingPathComponent(safe)
        let ext = candidate.pathExtension
        let stem = candidate.deletingPathExtension().lastPathComponent
        var index = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            let name = ext.isEmpty ? "\(stem) (\(index))" : "\(stem) (\(index)).\(ext)"
            candidate = folder.appendingPathComponent(name)
            index += 1
        }
        return candidate
    }

    // MARK: HTTP client

    private func sendSync(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, progressValue: @escaping (Double) -> Void = { _ in }) throws {
        guard !files.isEmpty else { throw NSError(domain: "ClipMesh", code: 1, userInfo: [NSLocalizedDescriptionKey: "Choose at least one file."]) }
        var fileObject: [String: Any] = [:]
        var ids: [(String, URL, Int64)] = []
        for file in files {
            let values = try file.resourceValues(forKeys: [.fileSizeKey, .contentTypeKey])
            let size = Int64(values.fileSize ?? 0)
            let id = UUID().uuidString.lowercased()
            let mime: String
            if #available(macOS 11.0, *), let type = values.contentType { mime = type.preferredMIMEType ?? "application/octet-stream" }
            else { mime = "application/octet-stream" }
            fileObject[id] = ["id": id, "fileName": file.lastPathComponent, "size": size, "fileType": mime]
            ids.append((id, file, size))
        }
        let totalBytes = ids.reduce(Int64(0)) { $0 + $1.2 }
        var completedBytes: Int64 = 0
        let body: [String: Any] = ["info": info(announce: false), "files": fileObject]
        DispatchQueue.main.async { progress("Waiting for \(device.alias)…"); progressValue(0) }
        let result = try requestJSON(device: device, path: "/api/clipmesh/v1/prepare-upload", object: body)
        if result.status == 403 { throw NSError(domain: "ClipMesh", code: 403, userInfo: [NSLocalizedDescriptionKey: "\(device.alias) declined the transfer."]) }
        guard result.status == 200,
              let response = try JSONSerialization.jsonObject(with: result.data) as? [String: Any],
              let sessionID = response["sessionId"] as? String,
              let tokens = response["files"] as? [String: String] else {
            throw NSError(domain: "ClipMesh", code: result.status, userInfo: [NSLocalizedDescriptionKey: "Transfer request failed (\(result.status))."])
        }
        for (index, item) in ids.enumerated() {
            guard let token = tokens[item.0] else { continue }
            DispatchQueue.main.async { progress("Sending \(item.1.lastPathComponent) • \(index + 1)/\(ids.count)") }
            try uploadFile(device: device, sessionID: sessionID, fileID: item.0, token: token, file: item.1, size: item.2) { sent in
                let fraction = totalBytes > 0 ? Double(completedBytes + sent) / Double(totalBytes) : 1
                DispatchQueue.main.async { progressValue(min(1, max(0, fraction))); CMTransferPresentation.updateDock(fraction) }
            }
            completedBytes += item.2
        }
    }

    private func requestJSON(device: TransferDevice, path: String, object: [String: Any]) throws -> (status: Int, data: Data) {
        let body = try JSONSerialization.data(withJSONObject: object)
        var request = URLRequest(url: URL(string: "http://\(device.address):\(device.port)\(path)")!)
        request.httpMethod = "POST"; request.timeoutInterval = 75
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body; request.setValue(String(body.count), forHTTPHeaderField: "Content-Length")
        let sem = DispatchSemaphore(value: 0)
        var output: Result<(Int, Data), Error>!
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error { output = .failure(error) }
            else { output = .success(((response as? HTTPURLResponse)?.statusCode ?? 0, data ?? Data())) }
            sem.signal()
        }.resume()
        guard sem.wait(timeout: .now() + 80) == .success, let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out waiting for \(device.alias). Check the firewall and Wi-Fi connection."]) }
        return try output.get()
    }

    private func uploadFile(device: TransferDevice, sessionID: String, fileID: String, token: String, file: URL, size: Int64, onProgress: @escaping (Int64) -> Void) throws {
        var components = URLComponents(string: "http://\(device.address):\(device.port)/api/clipmesh/v1/upload")!
        components.queryItems = [URLQueryItem(name: "sessionId", value: sessionID), URLQueryItem(name: "fileId", value: fileID), URLQueryItem(name: "token", value: token)]
        var request = URLRequest(url: components.url!); request.httpMethod = "POST"; request.timeoutInterval = 180
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.setValue(String(size), forHTTPHeaderField: "Content-Length")
        let sem = DispatchSemaphore(value: 0)
        var output: Result<Int, Error>!
        let delegate = CMUploadProgressDelegate(onProgress: onProgress) { result in
            output = result
            sem.signal()
        }
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        let task = session.uploadTask(with: request, fromFile: file)
        task.resume()
        guard sem.wait(timeout: .now() + 190) == .success else {
            task.cancel()
            session.invalidateAndCancel()
            throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."])
        }
        session.finishTasksAndInvalidate()
        onProgress(size)
        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \(file.lastPathComponent)."]) }
        let status = try output.get()
        if !(200...299).contains(status) { throw NSError(domain: "ClipMesh", code: status, userInfo: [NSLocalizedDescriptionKey: "The receiver rejected \(file.lastPathComponent) (\(status))."]) }
    }

    private func respondJSON(_ connection: NWConnection, object: [String: Any]) {
        let data = (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8)
        respond(connection, code: 200, data: data, contentType: "application/json")
    }

    private func respond(_ connection: NWConnection, code: Int, body: String) {
        respond(connection, code: code, data: Data(body.utf8), contentType: "text/plain; charset=utf-8")
    }

    private func respond(_ connection: NWConnection, code: Int, data: Data, contentType: String) {
        let reason: String = [200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 422: "Unprocessable Entity", 500: "Internal Server Error"][code] ?? "Error"
        let header = "HTTP/1.1 \(code) \(reason)\r\nContent-Type: \(contentType)\r\nContent-Length: \(data.count)\r\nConnection: close\r\n\r\n"
        var packet = Data(header.utf8); packet.append(data)
        connection.send(content: packet, completion: .contentProcessed { _ in connection.cancel() })
    }

    private var safeAlias: String {
        let value = aliasProvider?().trimmingCharacters(in: .whitespacesAndNewlines) ?? "Mac"
        return value.isEmpty ? "Mac" : String(value.prefix(80))
    }

    private var isRunning: Bool { stateLock.lock(); defer { stateLock.unlock() }; return running }

    private static func endpointAddress(_ endpoint: NWEndpoint?) -> String? {
        guard case let .hostPort(host, _) = endpoint else { return nil }
        switch host {
        case .ipv4(let address): return address.debugDescription
        case .ipv6(let address): return address.debugDescription
        case .name(let name, _): return name
        @unknown default: return nil
        }
    }

    private static func safeFileName(_ value: String) -> String {
        let last = (value as NSString).lastPathComponent
        let allowed = last.unicodeScalars.filter { $0.value >= 32 && $0 != ":" }
        let cleaned = String(String.UnicodeScalarView(allowed)).trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? "file" : String(cleaned.prefix(180))
    }
}

private final class CMActionTarget: NSObject {
    let handler: () -> Void

    init(handler: @escaping () -> Void) {
        self.handler = handler
        super.init()
    }

    @objc func invoke(_ sender: Any?) {
        handler()
    }
}

private final class CMActionButton: NSButton {
    private var retainedActionTarget: CMActionTarget?

    convenience init(title: String, handler: @escaping () -> Void) {
        self.init(frame: .zero)
        self.title = title
        let actionTarget = CMActionTarget(handler: handler)
        retainedActionTarget = actionTarget
        target = actionTarget
        action = #selector(CMActionTarget.invoke(_:))
    }
}

/// Small bridge so the main window can use the private dock/notification presentation.
enum CMTransferFeedback {
    static func clearDock() { CMTransferPresentation.clearDock() }
    static func notify(title: String, body: String) { CMTransferPresentation.notify(title: title, body: body) }
}

enum TransferSelfTest {
    static func run() throws {
        var fired = false
        let button = CMActionButton(title: "Test") { fired = true }
        guard let action = button.action,
              action == #selector(CMActionTarget.invoke(_:)),
              let target = button.target as? CMActionTarget else {
            throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button target/action was not retained"])
        }
        target.invoke(button)
        guard fired else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button handler did not fire"]) }
        let fp = "clipmesh-selftest-" + UUID().uuidString
        LocalTransferManager.shared.setFavorite(fp, true)
        guard LocalTransferManager.shared.isFavorite(fp) else { throw NSError(domain: "ClipMesh", code: 71, userInfo: [NSLocalizedDescriptionKey: "Favorite persistence failed"]) }
        LocalTransferManager.shared.setFavorite(fp, false)
    }
}

enum TransferDialogs {
    static func ask(sender: String, files: [TransferMeta]) -> Bool {
        return CMDialog.run(title: "Incoming file transfer", message: "\(sender) wants to send you \(files.count == 1 ? files[0].name : "\(files.count) files"). Accept to save in Downloads/ClipMesh.", buttons: ["Reject", "Accept"]) == 1
    }
}

// v049 compatibility marker: countOfBytesSent polling was removed; progress uses URLSession didSendBodyData.
