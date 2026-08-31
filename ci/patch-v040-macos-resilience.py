#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
from pathlib import Path

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if system == "Darwin":
    app = root / "ci/ClipMeshApp.swift"

    replace_once(
        app,
        '''    private var quitting = false
    private var latestState: UIState?
''',
        '''    private var quitting = false
    private var latestState: UIState?
    private var daemonRestartAttempts = 0
    private var daemonRestartWorkItem: DispatchWorkItem?
''',
        "macOS daemon restart state",
    )

    replace_once(
        app,
        '''    private static func processIsClipMeshDaemon(_ pid: Int32) -> Bool {
        guard let result = try? external("/usr/sbin/lsof", ["-nP", "-a", "-p", String(pid), "-d", "txt", "-FcFn"]), result.status == 0 else { return false }
        let lines = result.output.split(whereSeparator: { $0.isNewline }).map(String.init)
        let commandMatches = lines.contains("cclipmesh-bin")
        let executableMatches = lines.contains { line in
            guard line.first == "n" else { return false }
            return URL(fileURLWithPath: String(line.dropFirst())).lastPathComponent == "clipmesh-bin"
        }
        return commandMatches && executableMatches
    }
''',
        r'''    private static func processIsClipMeshDaemon(_ pid: Int32) -> Bool {
        guard let result = try? external("/usr/sbin/lsof", ["-nP", "-a", "-p", String(pid), "-d", "txt", "-FcFn"]), result.status == 0 else { return false }
        let lines = result.output.split(whereSeparator: { $0.isNewline }).map(String.init)
        let commandMatches = lines.contains("cclipmesh-bin")
        let executableMatches = lines.contains { line in
            guard line.first == "n" else { return false }
            return URL(fileURLWithPath: String(line.dropFirst())).lastPathComponent == "clipmesh-bin"
        }
        return commandMatches && executableMatches
    }

    static func clipboardDaemonIsListening(_ pid: Int32) -> Bool {
        guard pid > 0, processIsClipMeshDaemon(pid) else { return false }
        guard let result = try? external(
            "/usr/sbin/lsof",
            ["-nP", "-a", "-p", String(pid), "-iTCP:\(clipboardPort())", "-sTCP:LISTEN", "-t"]
        ), result.status == 0 else { return false }
        return result.output.split(whereSeparator: { $0.isWhitespace }).contains { Int32($0) == pid }
    }
''',
        "macOS clipboard daemon readiness probe",
    )

    # Every scheduled recovery closure checks `quitting` before doing any work.
    # Both existing shutdown paths set that flag before stopping the daemon, so
    # a pending recovery cannot resurrect the daemon during application exit.
    old_handler = r'''        process.terminationHandler = { [weak self, weak process] ended in
            DispatchQueue.main.async {
                guard let self, let process, !self.quitting, self.daemon === process else { return }
                self.daemon = nil
                self.statusLabel.stringValue = "Background sync stopped (exit \(ended.terminationStatus))"
                self.statusLabel.textColor = .systemRed
                self.showWindow()
            }
        }
'''
    new_handler = r'''        process.terminationHandler = { [weak self, weak process] ended in
            DispatchQueue.main.async {
                guard let self, let process, !self.quitting, self.daemon === process else { return }
                self.daemon = nil
                self.statusLabel.stringValue = "Background sync interrupted - recovering…"
                self.statusLabel.textColor = .systemOrange
                self.scheduleDaemonRestart(after: ended.terminationStatus)
            }
        }
'''
    replace_once(app, old_handler, new_handler, "macOS unexpected daemon recovery handler")

    replace_once(
        app,
        '''    private func startDaemon() throws {
''',
        r'''    private func scheduleDaemonRestart(after terminationStatus: Int32) {
        guard !quitting else { return }
        daemonRestartWorkItem?.cancel()
        daemonRestartAttempts += 1
        let attempt = daemonRestartAttempts
        guard attempt <= 4 else {
            statusLabel.stringValue = "Background sync could not recover (exit \(terminationStatus))"
            statusLabel.textColor = .systemRed
            showWindow()
            return
        }
        let delays: [TimeInterval] = [0.35, 0.8, 1.6, 3.0]
        let work = DispatchWorkItem { [weak self] in
            guard let self, !self.quitting else { return }
            do {
                try self.startDaemon()
            } catch {
                self.statusLabel.stringValue = "Background sync recovery \(attempt)/4 failed"
                self.statusLabel.textColor = .systemOrange
                self.scheduleDaemonRestart(after: terminationStatus)
            }
        }
        daemonRestartWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delays[min(attempt - 1, delays.count - 1)], execute: work)
    }

    private func startDaemon() throws {
''',
        "macOS bounded daemon restart scheduler",
    )

    replace_once(
        app,
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
''',
        '''        try process.run()
        daemon = process
        var ready = false
        for _ in 0..<35 {
            if !process.isRunning { break }
            if Runtime.clipboardDaemonIsListening(process.processIdentifier) {
                ready = true
                break
            }
            usleep(100_000)
        }
        guard ready, process.isRunning else {
            if process.isRunning { process.terminate() }
            process.waitUntilExit()
            if daemon === process { daemon = nil }
            throw NSError(domain: "ClipMesh", code: Int(process.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: "ClipMesh background sync started but never became ready."
            ])
        }
        statusLabel.stringValue = "Background sync is running"
''',
        "macOS clipboard daemon readiness gate",
    )

    replace_once(
        app,
        '''        statusLabel.stringValue = "Background sync is running"
        statusLabel.textColor = .secondaryLabelColor
''',
        '''        statusLabel.stringValue = "Background sync is running"
        statusLabel.textColor = .secondaryLabelColor
        daemonRestartWorkItem?.cancel()
        daemonRestartWorkItem = nil
        let stableProcess = process
        DispatchQueue.main.asyncAfter(deadline: .now() + 8.0) { [weak self, weak stableProcess] in
            guard let self, let stableProcess, self.daemon === stableProcess, stableProcess.isRunning else { return }
            self.daemonRestartAttempts = 0
        }
''',
        "macOS daemon stability reset",
    )

    final = app.read_text(encoding="utf-8")
    for needle in (
        "clipboardDaemonIsListening",
        "scheduleDaemonRestart",
        "Background sync interrupted - recovering",
        "daemonRestartAttempts",
        "started but never became ready",
    ):
        if needle not in final:
            raise SystemExit(f"macOS resilience guard missing: {needle}")

elif system in ("Linux", "Windows"):
    # v040 is a macOS clipboard-daemon lifecycle repair. Other platforms retain
    # their existing runtime ownership implementations unchanged.
    pass
else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh v040 macOS clipboard-daemon resilience on {system}")
