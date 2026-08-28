import Cocoa
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

    init(id: String, sender: String, fingerprint: String, files: [String: TransferMeta], tokens: [String: String]) {
        self.id = id; self.sender = sender; self.fingerprint = fingerprint; self.files = files; self.tokens = tokens
    }
}

private enum TransferPrefs {
    static let fingerprintKey = "ClipMesh.FileTransfer.Fingerprint"
    static let favoritesKey = "ClipMesh.FileTransfer.Favorites"

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
}

final class LocalTransferManager {
    static let shared = LocalTransferManager()
    static let port: UInt16 = 53317
    static let group = "224.0.0.167"

    var incomingPrompt: ((String, [TransferMeta]) -> Bool)?
    var aliasProvider: (() -> String)?

    private let queue = DispatchQueue(label: "dev.clipmesh.fileshare", qos: .utility)
    private let stateLock = NSLock()
    private var listener: NWListener?
    private var udpFD: Int32 = -1
    private var timer: DispatchSourceTimer?
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
        startAnnouncer()
    }

    func stop() {
        stateLock.lock(); running = false; stateLock.unlock()
        listener?.cancel(); listener = nil
        timer?.cancel(); timer = nil
        if udpFD >= 0 { Darwin.close(udpFD); udpFD = -1 }
    }

    func nearbyDevices() -> [TransferDevice] {
        stateLock.lock(); defer { stateLock.unlock() }
        let cutoff = Date().addingTimeInterval(-22)
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

    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }

    func setFavorite(_ fingerprint: String, _ favorite: Bool) {
        var values = TransferPrefs.favorites
        if favorite { values.insert(fingerprint) } else { values.remove(fingerprint) }
        TransferPrefs.favorites = values
    }

    func send(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, completion: @escaping (Result<Void, Error>) -> Void) {
        queue.async {
            do {
                try self.sendSync(files: files, to: device, progress: progress)
                DispatchQueue.main.async { completion(.success(())) }
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
            }
        }
    }

    // MARK: Discovery

    private func startDiscovery() {
        queue.async {
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
                if (json["announce"] as? Bool) == true { self.sendAnnouncement(announce: false) }
            }
        }
    }

    private func startAnnouncer() {
        let source = DispatchSource.makeTimerSource(queue: queue)
        source.schedule(deadline: .now() + 0.2, repeating: 5.0)
        source.setEventHandler { [weak self] in self?.sendAnnouncement(announce: true) }
        timer = source
        source.resume()
    }

    private func sendAnnouncement(announce: Bool) {
        guard isRunning else { return }
        let payload = info(announce: announce)
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        let fd = Darwin.socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard fd >= 0 else { return }
        defer { Darwin.close(fd) }
        var ttl: UInt8 = 1
        setsockopt(fd, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, socklen_t(MemoryLayout<UInt8>.size))
        var destination = sockaddr_in()
        destination.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        destination.sin_family = sa_family_t(AF_INET)
        destination.sin_port = in_port_t(Self.port.bigEndian)
        destination.sin_addr = in_addr(s_addr: inet_addr(Self.group))
        data.withUnsafeBytes { bytes in
            withUnsafePointer(to: &destination) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                    _ = sendto(fd, bytes.baseAddress, data.count, 0, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
        }
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
            "announce": announce
        ]
    }

    private func register(json: [String: Any], address: String) {
        guard let fingerprint = json["fingerprint"] as? String, !fingerprint.isEmpty, fingerprint != TransferPrefs.fingerprint else { return }
        let alias = (json["alias"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).prefix(80) ?? "Nearby device"
        let model = (json["deviceModel"] as? String) ?? ""
        let type = (json["deviceType"] as? String) ?? "desktop"
        let port = UInt16((json["port"] as? Int) ?? Int(Self.port))
        let device = TransferDevice(alias: String(alias), fingerprint: fingerprint, address: address, port: port, model: model, type: type, lastSeen: Date())
        stateLock.lock(); devices[fingerprint] = device; stateLock.unlock()
    }

    // MARK: HTTP server

    private func startHTTP() {
        do {
            let listener = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: Self.port)!)
            self.listener = listener
            listener.newConnectionHandler = { [weak self] connection in self?.handle(connection) }
            listener.start(queue: queue)
        } catch {
            NSLog("ClipMesh file transfer listener failed: %@", error.localizedDescription)
        }
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
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
        guard let components = URLComponents(string: "http://clipmesh\(target)") else { return respond(connection, code: 400, body: "Bad target") }
        switch (method, components.path) {
        case ("GET", "/api/localsend/v2/info"):
            respondJSON(connection, object: info(announce: false))
        case ("POST", "/api/localsend/v2/register"):
            receiveSmallBody(connection, expected: length, initial: extra) { body in
                if let body, let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any] {
                    let endpoint = connection.currentPath?.remoteEndpoint
                    let address = Self.endpointAddress(endpoint) ?? ""
                    self.register(json: json, address: address)
                }
                self.respondJSON(connection, object: self.info(announce: false))
            }
        case ("POST", "/api/localsend/v2/prepare-upload"):
            receiveSmallBody(connection, expected: length, initial: extra) { body in
                guard let body else { return self.respond(connection, code: 400, body: "Invalid body") }
                self.prepareUpload(connection, body: body)
            }
        case ("POST", "/api/localsend/v2/upload"):
            upload(connection, components: components, expected: length, initial: extra)
        case ("POST", "/api/localsend/v2/cancel"):
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
            receiveUpload(connection, handle: handle, destination: url, remaining: expected - first.count) { success in
                try? handle.close()
                guard success else { try? FileManager.default.removeItem(at: url); return self.respond(connection, code: 500, body: "Transfer failed") }
                self.stateLock.lock()
                session.received.insert(fid)
                let done = session.received.count >= session.files.count
                if done { self.sessions.removeValue(forKey: sid) }
                self.stateLock.unlock()
                self.respond(connection, code: 200, body: "")
            }
        } catch {
            respond(connection, code: 500, body: "Could not create destination")
        }
    }

    private func receiveUpload(_ connection: NWConnection, handle: FileHandle, destination: URL, remaining: Int, completion: @escaping (Bool) -> Void) {
        if remaining <= 0 { completion(true); return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: min(128 * 1024, remaining)) { [weak self] data, _, complete, error in
            guard self != nil, error == nil, let data, !data.isEmpty else { completion(false); return }
            do { try handle.write(contentsOf: data) } catch { completion(false); return }
            let left = remaining - data.count
            if left <= 0 { completion(true) }
            else if complete { completion(false) }
            else { self?.receiveUpload(connection, handle: handle, destination: destination, remaining: left, completion: completion) }
        }
    }

    private func destinationURL(for meta: TransferMeta) throws -> URL {
        var folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0].appendingPathComponent("ClipMesh", isDirectory: true)
        if meta.mime.lowercased().hasPrefix("image/") { folder.appendPathComponent("Images", isDirectory: true) }
        else if meta.mime.lowercased().hasPrefix("video/") { folder.appendPathComponent("Videos", isDirectory: true) }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let ext = (meta.name as NSString).pathExtension
        let stem = (meta.name as NSString).deletingPathExtension
        var candidate = folder.appendingPathComponent(meta.name)
        var i = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            let name = ext.isEmpty ? "\(stem) (\(i))" : "\(stem) (\(i)).\(ext)"
            candidate = folder.appendingPathComponent(name); i += 1
        }
        return candidate
    }

    // MARK: HTTP client

    private func sendSync(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void) throws {
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
        let body: [String: Any] = ["info": info(announce: false), "files": fileObject]
        DispatchQueue.main.async { progress("Waiting for \(device.alias)…") }
        let result = try requestJSON(device: device, path: "/api/localsend/v2/prepare-upload", object: body)
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
            try uploadFile(device: device, sessionID: sessionID, fileID: item.0, token: token, file: item.1, size: item.2)
        }
    }

    private func requestJSON(device: TransferDevice, path: String, object: [String: Any]) throws -> (status: Int, data: Data) {
        let body = try JSONSerialization.data(withJSONObject: object)
        var request = URLRequest(url: URL(string: "http://\(device.address):\(device.port)\(path)")!)
        request.httpMethod = "POST"; request.timeoutInterval = 75
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let sem = DispatchSemaphore(value: 0)
        var output: Result<(Int, Data), Error>!
        URLSession.shared.uploadTask(with: request, from: body) { data, response, error in
            if let error { output = .failure(error) }
            else { output = .success(((response as? HTTPURLResponse)?.statusCode ?? 0, data ?? Data())) }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 80)
        return try output.get()
    }

    private func uploadFile(device: TransferDevice, sessionID: String, fileID: String, token: String, file: URL, size: Int64) throws {
        var components = URLComponents(string: "http://\(device.address):\(device.port)/api/localsend/v2/upload")!
        components.queryItems = [URLQueryItem(name: "sessionId", value: sessionID), URLQueryItem(name: "fileId", value: fileID), URLQueryItem(name: "token", value: token)]
        var request = URLRequest(url: components.url!); request.httpMethod = "POST"; request.timeoutInterval = 180
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.setValue(String(size), forHTTPHeaderField: "Content-Length")
        let sem = DispatchSemaphore(value: 0)
        var output: Result<Int, Error>!
        URLSession.shared.uploadTask(with: request, fromFile: file) { _, response, error in
            if let error { output = .failure(error) } else { output = .success((response as? HTTPURLResponse)?.statusCode ?? 0) }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 190)
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

private final class CMActionButton: NSButton {
    var handler: (() -> Void)?
    override init(frame frameRect: NSRect) { super.init(frame: frameRect); target = self; action = #selector(fire) }
    required init?(coder: NSCoder) { super.init(coder: coder); target = self; action = #selector(fire) }
    @objc private func fire() { handler?() }
}

final class TransferChooserController: NSObject, NSWindowDelegate {
    static let shared = TransferChooserController()
    private var window: NSWindow?
    private var deviceStack: NSStackView?
    private var status: NSTextField?
    private var fileLabel: NSTextField?
    private var files: [URL] = []
    private var timer: Timer?

    func show(files: [URL]) {
        DispatchQueue.main.async {
            self.files = files
            if self.window == nil { self.build() }
            self.refreshFiles()
            self.refreshDevices()
            self.window?.center(); self.window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            self.timer?.invalidate()
            self.timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.refreshDevices() }
        }
    }

    func windowWillClose(_ notification: Notification) { timer?.invalidate(); timer = nil }

    private func build() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 620, height: 640), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Send with ClipMesh"; window.minSize = NSSize(width: 520, height: 520); window.delegate = self
        let effect = NSVisualEffectView(); effect.material = .hudWindow; effect.blendingMode = .behindWindow; effect.state = .active; effect.translatesAutoresizingMaskIntoConstraints = false
        window.contentView = effect
        let root = NSStackView(); root.orientation = .vertical; root.alignment = .leading; root.spacing = 12; root.translatesAutoresizingMaskIntoConstraints = false
        effect.addSubview(root)
        NSLayoutConstraint.activate([root.leadingAnchor.constraint(equalTo: effect.leadingAnchor, constant: 28), root.trailingAnchor.constraint(equalTo: effect.trailingAnchor, constant: -28), root.topAnchor.constraint(equalTo: effect.topAnchor, constant: 26), root.bottomAnchor.constraint(lessThanOrEqualTo: effect.bottomAnchor, constant: -24)])
        let eyebrow = label("CLIPMESH DROP", 11, .semibold); eyebrow.textColor = NSColor(calibratedWhite: 0.78, alpha: 1); root.addArrangedSubview(eyebrow)
        let title = label("Send without\nbreaking your flow.", 34, .medium); root.addArrangedSubview(title)
        let subtitle = label("Nearby, direct, private. No cloud in the middle.", 13, .regular); subtitle.textColor = .secondaryLabelColor; root.addArrangedSubview(subtitle)
        let fileRow = NSStackView(); fileRow.orientation = .horizontal; fileRow.alignment = .centerY; fileRow.spacing = 10
        fileLabel = label("No files selected", 16, .semibold); fileRow.addArrangedSubview(fileLabel!); fileRow.addArrangedSubview(spacer())
        let choose = actionButton("Choose files", primary: true) { [weak self] in self?.chooseFiles() }; fileRow.addArrangedSubview(choose); root.addArrangedSubview(fileRow); fileRow.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        let separator = NSBox(); separator.boxType = .separator; root.addArrangedSubview(separator); separator.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        let nearby = label("Nearby devices", 20, .semibold); root.addArrangedSubview(nearby)
        let hint = label("Click Send. Star a device to trust future incoming files from it.", 12, .regular); hint.textColor = .secondaryLabelColor; root.addArrangedSubview(hint)
        let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 8; deviceStack = stack; root.addArrangedSubview(stack); stack.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        status = label("Looking on this Wi‑Fi…", 12, .regular); status?.textColor = .secondaryLabelColor; root.addArrangedSubview(status!)
        self.window = window
    }

    private func refreshFiles() {
        fileLabel?.stringValue = files.isEmpty ? "No files selected" : files.count == 1 ? files[0].lastPathComponent : "\(files.count) files selected"
    }

    private func chooseFiles() {
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = true
        panel.beginSheetModal(for: window!) { response in
            if response == .OK { self.files = panel.urls; self.refreshFiles() }
        }
    }

    private func refreshDevices() {
        guard let stack = deviceStack else { return }
        stack.arrangedSubviews.forEach { stack.removeArrangedSubview($0); $0.removeFromSuperview() }
        let devices = LocalTransferManager.shared.nearbyDevices()
        if devices.isEmpty {
            let empty = label("No ClipMesh devices found yet.", 13, .regular); empty.textColor = .secondaryLabelColor; stack.addArrangedSubview(empty); status?.stringValue = "Looking on this Wi‑Fi…"; return
        }
        status?.stringValue = "\(devices.count) device\(devices.count == 1 ? "" : "s") visible"
        for device in devices {
            let row = NSStackView(); row.orientation = .horizontal; row.alignment = .centerY; row.spacing = 10
            let info = NSStackView(); info.orientation = .vertical; info.alignment = .leading; info.spacing = 2
            info.addArrangedSubview(label(device.alias, 15, .semibold)); let sub = label(device.model.isEmpty ? device.type.capitalized : device.model, 11, .regular); sub.textColor = .secondaryLabelColor; info.addArrangedSubview(sub)
            row.addArrangedSubview(info); row.addArrangedSubview(spacer())
            let favorite = LocalTransferManager.shared.isFavorite(device.fingerprint)
            row.addArrangedSubview(actionButton(favorite ? "★" : "☆", primary: false) { LocalTransferManager.shared.setFavorite(device.fingerprint, !favorite); self.refreshDevices() })
            row.addArrangedSubview(actionButton("Send", primary: true) { [weak self] in self?.send(to: device) })
            stack.addArrangedSubview(row); row.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
    }

    private func send(to device: TransferDevice) {
        if files.isEmpty { chooseFiles(); return }
        status?.stringValue = "Connecting to \(device.alias)…"
        LocalTransferManager.shared.send(files: files, to: device, progress: { [weak self] text in self?.status?.stringValue = text }) { [weak self] result in
            switch result {
            case .success:
                self?.status?.stringValue = "Sent to \(device.alias)"
            case .failure(let error):
                self?.status?.stringValue = error.localizedDescription
                let alert = NSAlert(); alert.messageText = "Couldn’t send"; alert.informativeText = error.localizedDescription; alert.addButton(withTitle: "OK"); alert.runModal()
            }
        }
    }

    private func label(_ text: String, _ size: CGFloat, _ weight: NSFont.Weight) -> NSTextField { let field = NSTextField(labelWithString: text); field.font = .systemFont(ofSize: size, weight: weight); field.textColor = .labelColor; return field }
    private func spacer() -> NSView { let view = NSView(); view.setContentHuggingPriority(.defaultLow, for: .horizontal); return view }
    private func actionButton(_ text: String, primary: Bool, handler: @escaping () -> Void) -> NSButton {
        let button = CMActionButton(title: text, target: nil, action: nil); button.handler = handler; button.bezelStyle = .rounded; button.controlSize = .large; button.font = .systemFont(ofSize: 12, weight: .semibold); button.contentTintColor = primary ? .labelColor : .secondaryLabelColor; return button
    }
}

enum TransferDialogs {
    static func ask(sender: String, files: [TransferMeta]) -> Bool {
        let alert = NSAlert(); alert.alertStyle = .informational; alert.messageText = "\(sender) wants to send you \(files.count == 1 ? files[0].name : "\(files.count) files")"
        alert.informativeText = "Accept to save it in Downloads/ClipMesh. Star this device later if you want future transfers from it to save automatically."
        alert.addButton(withTitle: "Accept"); alert.addButton(withTitle: "Reject")
        NSApp.activate(ignoringOtherApps: true)
        return alert.runModal() == .alertFirstButtonReturn
    }
}
