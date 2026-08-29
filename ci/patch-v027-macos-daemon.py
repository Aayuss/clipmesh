from pathlib import Path
import os
import platform
import runpy


root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace(path: Path, old: str, new: str, label: str, count=None):
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found == 0 or (count is not None and found != count):
        raise SystemExit(f"{label}: expected {count or 'at least one'} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new), encoding="utf-8")


if system == "Darwin":
    app = root / "ci/ClipMeshApp.swift"
    build = project / "scripts/build-macos.sh"
    replace(build, "0.2.6", "0.2.7", "macOS version")
    replace(app, "import Foundation\n", "import Foundation\nimport Darwin\n", "Darwin process APIs", 1)
    replace(app,
        '''    static var config: URL { support.appendingPathComponent("config.json") }
    static var log: URL { support.appendingPathComponent("clipmesh.log") }
''',
        r'''    static var config: URL { support.appendingPathComponent("config.json") }
    static var log: URL { support.appendingPathComponent("clipmesh.log") }
    static var instanceLock: URL { support.appendingPathComponent("mac-ui.lock") }

    static func acquireInstanceLock() throws -> Int32? {
        try fileManager.createDirectory(at: support, withIntermediateDirectories: true)
        let descriptor = Darwin.open(instanceLock.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else {
            throw NSError(domain: "ClipMesh", code: Int(errno), userInfo: [
                NSLocalizedDescriptionKey: "ClipMesh could not create its single-instance lock."
            ])
        }
        guard Darwin.lockf(descriptor, F_TLOCK, 0) == 0 else {
            Darwin.close(descriptor)
            return nil
        }
        return descriptor
    }

    static func releaseInstanceLock(_ descriptor: Int32) {
        guard descriptor >= 0 else { return }
        _ = Darwin.lockf(descriptor, F_ULOCK, 0)
        Darwin.close(descriptor)
    }

    private static func external(_ executable: String, _ arguments: [String]) throws -> CLIResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        process.waitUntilExit()
        return CLIResult(
            status: process.terminationStatus,
            output: String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "",
            error: String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        )
    }

    private static func clipboardPort() -> Int {
        guard
            let data = try? Data(contentsOf: config),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let number = object["tcp_port"] as? NSNumber
        else { return 41474 }
        return number.intValue
    }

    private static func processIsClipMeshDaemon(_ pid: Int32) -> Bool {
        guard let result = try? external("/usr/sbin/lsof", ["-nP", "-a", "-p", String(pid), "-d", "txt", "-FcFn"]), result.status == 0 else { return false }
        let lines = result.output.split(whereSeparator: { $0.isNewline }).map(String.init)
        let commandMatches = lines.contains("cclipmesh-bin")
        let executableMatches = lines.contains { line in
            guard line.first == "n" else { return false }
            return URL(fileURLWithPath: String(line.dropFirst())).lastPathComponent == "clipmesh-bin"
        }
        return commandMatches && executableMatches
    }

    static func reclaimStaleDaemonListener() throws {
        let port = clipboardPort()
        let result = try external("/usr/sbin/lsof", ["-nP", "-t", "-iTCP:\(port)", "-sTCP:LISTEN"])
        guard result.status == 0 else { return } // lsof uses 1 when no process matches.
        let pids = result.output.split(whereSeparator: { $0.isWhitespace }).compactMap { Int32($0) }
        for pid in Set(pids) where pid != getpid() {
            guard processIsClipMeshDaemon(pid) else {
                throw NSError(domain: "ClipMesh", code: 48, userInfo: [
                    NSLocalizedDescriptionKey: "Clipboard port \(port) is already used by another application. ClipMesh left that process untouched."
                ])
            }
            guard Darwin.kill(pid, SIGTERM) == 0 || errno == ESRCH else {
                throw NSError(domain: "ClipMesh", code: Int(errno), userInfo: [
                    NSLocalizedDescriptionKey: "ClipMesh found its previous background process but could not stop it."
                ])
            }
            for _ in 0..<20 {
                if Darwin.kill(pid, 0) != 0 && errno == ESRCH { break }
                usleep(100_000)
            }
            if Darwin.kill(pid, 0) == 0 {
                // The identity was verified immediately before SIGTERM. A hard stop
                // is safe here and prevents a crashed old build blocking every launch.
                _ = Darwin.kill(pid, SIGKILL)
                for _ in 0..<10 {
                    if Darwin.kill(pid, 0) != 0 && errno == ESRCH { break }
                    usleep(100_000)
                }
            }
            guard Darwin.kill(pid, 0) != 0 && errno == ESRCH else {
                throw NSError(domain: "ClipMesh", code: 48, userInfo: [
                    NSLocalizedDescriptionKey: "The previous ClipMesh background process did not stop."
                ])
            }
        }
    }
''', "macOS daemon ownership runtime", 1)
    replace(app,
        '''    private var receiveSwitch: NSSwitch!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMainMenu()
''',
        '''    private var receiveSwitch: NSSwitch!
    private var instanceLockFD: Int32 = -1

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        do {
            guard let descriptor = try Runtime.acquireInstanceLock() else {
                if let identifier = Bundle.main.bundleIdentifier {
                    NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
                        .first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier })?
                        .activate(options: [.activateAllWindows])
                }
                NSApp.terminate(nil)
                return
            }
            instanceLockFD = descriptor
        } catch {
            buildWindow()
            showError(error.localizedDescription)
            return
        }
        buildMainMenu()
''', "macOS UI singleton", 1)
    replace(app,
        '''}


private final class CMClosureButton: NSButton {''',
        r'''}

if CommandLine.arguments.contains("--reclaim-stale-daemon-test") {
    do {
        try Runtime.reclaimStaleDaemonListener()
        print("ClipMesh stale-daemon ownership test passed")
        exit(0)
    } catch {
        fputs("ClipMesh stale-daemon ownership test failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}


private final class CMClosureButton: NSButton {''',
        "macOS daemon ownership executable self-test", 1)
    replace(app,
        '''        stopDaemon()
        logHandle?.closeFile()
    }
''',
        '''        stopDaemon()
        logHandle?.closeFile()
        Runtime.releaseInstanceLock(instanceLockFD)
        instanceLockFD = -1
    }
''', "macOS UI lock cleanup", 1)
    replace(app,
        '''    private func startDaemon() throws {
        try FileManager.default.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
''',
        '''    private func startDaemon() throws {
        try FileManager.default.createDirectory(at: Runtime.support, withIntermediateDirectories: true)
        // A force-quit or UI crash can orphan clipmesh-bin. Reclaim only an
        // executable positively identified as ClipMesh; never kill by port alone.
        try Runtime.reclaimStaleDaemonListener()
''', "macOS stale daemon takeover", 1)
    replace(app,
        '''        try process.run()
        daemon = process
        statusLabel.stringValue = "Background sync is running"
''',
        '''        try process.run()
        daemon = process
        usleep(150_000)
        guard process.isRunning else {
            process.waitUntilExit()
            daemon = nil
            throw NSError(domain: "ClipMesh", code: Int(process.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: "ClipMesh background sync could not start. Open Settings → Diagnostics for the log."
            ])
        }
        statusLabel.stringValue = "Background sync is running"
''', "macOS daemon launch verification", 1)

elif system == "Windows":
    ui = root / "ci/ClipMeshWindows.cs"
    replace(ui, 'private const string Version = "0.2.6";', 'private const string Version = "0.2.7";', "Windows version", 1)

elif system == "Linux":
    gradle = project / "android/app/build.gradle.kts"
    replace(gradle, "versionCode = 16", "versionCode = 17", "Android version code", 1)
    replace(gradle, 'versionName = "0.2.6"', 'versionName = "0.2.7"', "Android version", 1)

else:
    raise SystemExit(f"unsupported platform {system}")

# Keep the workflow entry point stable while layering the cross-platform
# background clipboard and file-transfer repair after all earlier patches.
runpy.run_path(str(root / "ci/patch-v028-background-transfer.py"), run_name="__main__")

# The initial v0.2.8 patch used a regex replacement whose first capture was
# intentionally preserved in the patch text. Normalize that one generated
# Android source fragment here before source validation/compilation.
if system == "Linux":
    main = project / "android/app/src/main/java/dev/clipmesh/MainActivity.kt"
    text = main.read_text(encoding="utf-8")
    bad = r'''\1        if (BuildConfig.DEBUG) {
            intent.getStringExtra("clipmesh_ci_favorite")?.takeIf { it.isNotBlank() }?.let {
                LocalTransferEngine.setFavorite(this, it, true)
            }
        }
'''
    if bad in text:
        good = '''        super.onCreate(savedInstanceState)
        if (BuildConfig.DEBUG) {
            intent.getStringExtra("clipmesh_ci_favorite")?.takeIf { it.isNotBlank() }?.let {
                LocalTransferEngine.setFavorite(this, it, true)
            }
        }
'''
        main.write_text(text.replace(bad, good, 1), encoding="utf-8")

print(f"Applied ClipMesh v0.2.7 daemon ownership + background/transfer repair on {system}")
