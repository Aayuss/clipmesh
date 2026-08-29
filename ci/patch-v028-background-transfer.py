from pathlib import Path
import os
import platform
import re

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace(path: Path, old: str, new: str, label: str, count=1):
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def regex(path: Path, pattern: str, repl: str, label: str, flags=re.S):
    text = path.read_text(encoding="utf-8")
    out, found = re.subn(pattern, lambda _m: repl, text, count=1, flags=flags)
    if found != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {found}")
    path.write_text(out, encoding="utf-8")


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    engine = java / "fileshare/LocalTransferEngine.kt"
    incoming = java / "fileshare/IncomingRequestUi.kt"
    main = java / "MainActivity.kt"

    # Android 10+ stops app-process clipboard listeners while another app owns
    # input focus. Accessibility does not exempt ClipboardManager. Keep the
    # listener as a fast path, but use Shizuku as the privileged screen-on watcher.
    replace(runtime,
        "    private var clipboard: ClipboardBridge? = null\n",
        """    private var clipboard: ClipboardBridge? = null
    private var clipboardWatchdog: java.util.concurrent.ScheduledExecutorService? = null
""",
        "Android privileged clipboard watchdog field")
    replace(runtime,
        "        bridge.start(); net.start()\n",
        """        bridge.start(); net.start()
        startClipboardWatchdog(app, bridge, sh)
""",
        "Android privileged clipboard watchdog start")
    replace(runtime,
        "    @Synchronized fun stop() {\n",
        """    private fun startClipboardWatchdog(context: Context, bridge: ClipboardBridge, shizuku: ShizukuManager) {
        clipboardWatchdog?.shutdownNow()
        val power = context.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        val executor = java.util.concurrent.Executors.newSingleThreadScheduledExecutor { task ->
            Thread(task, "ClipMesh-ClipboardWatch").apply { isDaemon = true }
        }
        clipboardWatchdog = executor
        executor.scheduleWithFixedDelay({
            try {
                // Clipboard copies only happen while the user is actively using
                // the device. Avoid privileged reads while the screen sleeps.
                if (power.isInteractive && SettingsStore(context).backgroundSync && shizuku.hasPermission()) {
                    bridge.captureNowForForeground()
                }
            } catch (_: Throwable) {
                // Shizuku may restart independently. The next tick reconnects.
            }
        }, 0L, 650L, java.util.concurrent.TimeUnit.MILLISECONDS)
    }

    @Synchronized fun stop() {
        clipboardWatchdog?.shutdownNow()
        clipboardWatchdog = null
""",
        "Android privileged clipboard watchdog stop")

    # File discovery is presence-aware and only advertises once its HTTP
    # receiver is listening. This prevents a peer appearing and then timing out.
    replace(engine,
        "        val lastSeenMs: Long\n    )",
        """        val lastSeenMs: Long,
        val visible: Boolean = true
    )""",
        "Android transfer visibility field")
    replace(engine,
        "    private val started = AtomicBoolean(false)\n",
        """    private val started = AtomicBoolean(false)
    private val serverReady = AtomicBoolean(false)
    @Volatile private var uiVisible = false
""",
        "Android transfer readiness state")
    replace(engine,
        """        return nearby.values
            .filter { it.fingerprint != fingerprint(requireContext()) }
""",
        """        return nearby.values
            .filter { it.fingerprint != fingerprint(requireContext()) }
            .filter { it.visible || isFavorite(requireContext(), it.fingerprint) }
""",
        "Android favorite/background presence filter")
    replace(engine,
        "    fun fingerprint(context: Context): String {\n",
        """    fun setUiVisible(visible: Boolean) {
        if (uiVisible == visible) return
        uiVisible = visible
        discoverNow()
    }

    fun fingerprint(context: Context): String {
""",
        "Android UI presence setter")
    replace(engine,
        '        put("announce", announce)\n',
        '''        put("announce", announce)
        put("visible", uiVisible)
''',
        "Android advertised presence")
    replace(engine,
        """            lastSeenMs = System.currentTimeMillis()
        )
    }

    private fun remember(device: TransferDevice) {
""",
        """            lastSeenMs = System.currentTimeMillis(),
            visible = json.optBoolean("visible", true)
        )
    }

    private fun remember(device: TransferDevice) {
""",
        "Android parsed presence")
    replace(engine,
        """                val remote = deviceFromJson(json, packet.address.hostAddress.orEmpty()) ?: continue
                remember(remote)
                if (json.optBoolean("announce", false)) runCatching { sendAnnouncement(false) }
""",
        """                val remote = deviceFromJson(json, packet.address.hostAddress.orEmpty()) ?: continue
                remember(remote)
                if (json.optBoolean("announce", false)) {
                    // Multicast answers are lossy on real Wi-Fi/VPN setups. Reply
                    // directly over HTTP first, then retain multicast as fallback.
                    executor.execute {
                        runCatching {
                            postJson(remote, "/api/clipmesh/v1/register", myInfo(requireContext(), false))
                        }
                    }
                    runCatching { sendAnnouncement(false) }
                }
""",
        "Android HTTP registration discovery")
    replace(engine,
        """            server = listener
            while (started.get()) {
""",
        """            server = listener
            serverReady.set(true)
            runCatching { sendAnnouncement(true) }
            while (started.get()) {
""",
        "Android listener readiness")
    replace(engine,
        """        } finally {
            server = null
        }
""",
        """        } finally {
            serverReady.set(false)
            server = null
        }
""",
        "Android listener readiness cleanup")
    replace(engine,
        """    private fun sendAnnouncement(announce: Boolean) {
        val context = requireContext()
""",
        """    private fun sendAnnouncement(announce: Boolean) {
        if (!serverReady.get()) return
        val context = requireContext()
""",
        "Android do not advertise dead receiver")
    replace(incoming,
        "    fun attach(activity: Activity) { visible = WeakReference<Activity?>(activity) }\n",
        """    fun attach(activity: Activity) {
        visible = WeakReference<Activity?>(activity)
        LocalTransferEngine.setUiVisible(true)
    }
""",
        "Android visible activity presence")
    replace(incoming,
        "    fun detach(activity: Activity) { if (visible.get() === activity) visible.clear() }\n",
        """    fun detach(activity: Activity) {
        if (visible.get() === activity) {
            visible.clear()
            LocalTransferEngine.setUiVisible(false)
        }
    }
""",
        "Android hidden activity presence")

    # Test-only debug extra: CI seeds one trusted sender and exercises a real
    # metadata prepare + binary upload against the background receiver.
    regex(main,
        r"(override\s+fun\s+onCreate\s*\(savedInstanceState:\s*Bundle\?\)\s*\{\s*\n\s*super\.onCreate\(savedInstanceState\)\s*\n)",
        r'''\1        if (BuildConfig.DEBUG) {
            intent.getStringExtra("clipmesh_ci_favorite")?.takeIf { it.isNotBlank() }?.let {
                LocalTransferEngine.setFavorite(this, it, true)
            }
        }
''',
        "Android end-to-end favorite test hook")

elif system == "Darwin":
    app = root / "ci/ClipMeshApp.swift"
    transfer = root / "ci/ClipMeshTransfer.swift"

    replace(transfer,
        "    var aliasProvider: (() -> String)?\n",
        """    var aliasProvider: (() -> String)?
    private var uiVisible = false
    private var serverReady = false
    private var visibleDevices = Set<String>()
""",
        "macOS transfer presence state")
    replace(transfer,
        """        return devices.values
            .filter { $0.fingerprint != TransferPrefs.fingerprint }
""",
        """        return devices.values
            .filter { $0.fingerprint != TransferPrefs.fingerprint }
            .filter { visibleDevices.contains($0.fingerprint) || favorites.contains($0.fingerprint) }
""",
        "macOS favorite/background presence filter")
    replace(transfer,
        "    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }\n",
        """    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }

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
""",
        "macOS presence setter")
    replace(transfer,
        '            "announce": announce\n',
        '''            "announce": announce,
            "visible": isUIVisible
''',
        "macOS advertised presence")
    replace(transfer,
        "        stateLock.lock(); devices[fingerprint] = device; stateLock.unlock()\n",
        """        let remoteVisible = (json["visible"] as? Bool) ?? true
        stateLock.lock()
        devices[fingerprint] = device
        if remoteVisible { visibleDevices.insert(fingerprint) } else { visibleDevices.remove(fingerprint) }
        stateLock.unlock()
""",
        "macOS parsed presence")
    replace(transfer,
        """                self.register(json: json, address: address)
                if (json["announce"] as? Bool) == true { self.sendAnnouncement(announce: false) }
""",
        """                self.register(json: json, address: address)
                if (json["announce"] as? Bool) == true {
                    self.registerBack(json: json, address: address)
                    self.sendAnnouncement(announce: false)
                }
""",
        "macOS HTTP registration discovery")
    replace(transfer,
        "    // MARK: HTTP server\n",
        r'''    private func registerBack(json: [String: Any], address: String) {
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
''',
        "macOS HTTP registration helper")
    replace(transfer,
        """            self.listener = listener
            listener.newConnectionHandler = { [weak self] connection in self?.handle(connection) }
            listener.start(queue: queue)
""",
        """            self.listener = listener
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
            listener.start(queue: queue)
""",
        "macOS listener readiness")
    replace(transfer,
        "        listener?.cancel(); listener = nil\n",
        """        listener?.cancel(); listener = nil
        stateLock.lock(); serverReady = false; stateLock.unlock()
""",
        "macOS listener readiness cleanup")
    replace(transfer,
        """    private func sendAnnouncement(announce: Bool) {
        guard isRunning else { return }
""",
        """    private func sendAnnouncement(announce: Bool) {
        guard isRunning && isServerReady else { return }
""",
        "macOS do not advertise dead receiver")

    # The menu-bar process remains alive, but non-favorites only see this Mac
    # while its ClipMesh window is actually open.
    replace(app,
        """    private func showWindow() {
        NSApp.setActivationPolicy(.regular)
""",
        """    private func showWindow() {
        LocalTransferManager.shared.setUIVisible(true)
        NSApp.setActivationPolicy(.regular)
""",
        "macOS visible window presence")
    replace(app,
        """    private func hideWindow() {
        transferTimer?.invalidate(); transferTimer = nil
        window?.orderOut(nil)
""",
        """    private func hideWindow() {
        LocalTransferManager.shared.setUIVisible(false)
        transferTimer?.invalidate(); transferTimer = nil
        window?.orderOut(nil)
""",
        "macOS hidden window presence")

    # Avoid decoding arbitrary lazy/custom pasteboard objects. Some providers can
    # make NSImage(pasteboard:) terminate the process. Preview scalar content only.
    replace(app,
        "private final class CMModalTarget: NSObject {\n",
        r'''enum CMClipboardSnapshot {
    static func describe(_ pasteboard: NSPasteboard) -> String {
        var lines: [String] = []
        let types = pasteboard.types ?? []
        lines.append("Types: " + (types.isEmpty ? "none" : types.map(\.rawValue).joined(separator: ", ")))
        if let text = pasteboard.string(forType: .string), !text.isEmpty {
            lines.append("\nText:\n" + String(text.prefix(12_000)))
        } else if let html = pasteboard.string(forType: .html), !html.isEmpty {
            lines.append("\nHTML:\n" + String(html.prefix(12_000)))
        } else if types.contains(.png) || types.contains(.tiff) {
            lines.append("\nImage content is available.")
        } else if types.contains(.fileURL) {
            lines.append("\nFile content is available.")
        }
        return String(lines.joined(separator: "\n").prefix(20_000))
    }
}

private final class CMModalTarget: NSObject {
''',
        "macOS safe clipboard snapshot")
    regex(app,
        r'''    @objc private func viewClipboard\(\) \{.*?\n    \}\n\n    @objc private func quitApp''',
        r'''    @objc private func viewClipboard() {
        let snapshot = CMClipboardSnapshot.describe(NSPasteboard.general)
        CMDialog.run(title: "Current Clipboard", message: snapshot.isEmpty ? "Clipboard is empty." : snapshot)
    }

    @objc private func quitApp''',
        "macOS crash-safe clipboard viewer")
    replace(app,
        '''if CommandLine.arguments.contains("--reclaim-stale-daemon-test") {''',
        r'''if CommandLine.arguments.contains("--clipboard-preview-self-test") {
    let pasteboard = NSPasteboard(name: NSPasteboard.Name("dev.clipmesh.preview-self-test"))
    pasteboard.clearContents()
    pasteboard.setString("ClipMesh clipboard self-test", forType: .string)
    let snapshot = CMClipboardSnapshot.describe(pasteboard)
    guard snapshot.contains("ClipMesh clipboard self-test") else {
        fputs("ClipMesh clipboard preview self-test failed\n", stderr)
        exit(1)
    }
    print("ClipMesh clipboard preview self-test passed")
    exit(0)
}

if CommandLine.arguments.contains("--reclaim-stale-daemon-test") {''',
        "macOS executable clipboard preview test")

elif system == "Windows":
    transfer = root / "ci/ClipMeshTransfer.cs"
    ui = root / "ci/ClipMeshWindows.cs"

    replace(transfer,
        "    private TcpListener server;\n",
        """    private TcpListener server;
    private volatile bool serverReady;
    private volatile bool uiVisible = true;
    private readonly HashSet<string> visibleDevices = new HashSet<string>(StringComparer.Ordinal);
""",
        "Windows transfer presence state")
    replace(transfer,
        """            values.RemoveAll(delegate(TransferDeviceC d) { return d.Fingerprint == Fingerprint; });
""",
        """            values.RemoveAll(delegate(TransferDeviceC d) { return d.Fingerprint == Fingerprint; });
            values.RemoveAll(delegate(TransferDeviceC d) { return !IsFavorite(d.Fingerprint) && !visibleDevices.Contains(d.Fingerprint); });
""",
        "Windows favorite/background presence filter")
    replace(transfer,
        "    public bool IsFavorite(string fingerprint) { return LoadFavorites().Contains(fingerprint); }\n",
        """    public bool IsFavorite(string fingerprint) { return LoadFavorites().Contains(fingerprint); }

    public void SetUiVisible(bool visible)
    {
        bool changed = uiVisible != visible;
        uiVisible = visible;
        if (changed) DiscoverNow();
    }
""",
        "Windows UI presence setter")
    replace(transfer,
        '{"fingerprint", Fingerprint}, {"port", Port}, {"protocol", "http"}, {"download", false}, {"announce", announce}\n',
        '{"fingerprint", Fingerprint}, {"port", Port}, {"protocol", "http"}, {"download", false}, {"announce", announce}, {"visible", uiVisible}\n',
        "Windows advertised presence")
    replace(transfer,
        """        device.Address = address; device.LastSeen = DateTime.UtcNow;
        lock (gate) devices[fp] = device;
""",
        """        device.Address = address; device.LastSeen = DateTime.UtcNow;
        bool remoteVisible = !info.ContainsKey("visible") || Convert.ToBoolean(info["visible"]);
        lock (gate)
        {
            devices[fp] = device;
            if (remoteVisible) visibleDevices.Add(fp); else visibleDevices.Remove(fp);
        }
""",
        "Windows parsed presence")
    replace(transfer,
        """                Register(message, remote.Address.ToString());
                object announce;
                if (message.TryGetValue("announce", out announce) && Convert.ToBoolean(announce)) SendAnnouncement(false);
""",
        """                Register(message, remote.Address.ToString());
                object announce;
                if (message.TryGetValue("announce", out announce) && Convert.ToBoolean(announce))
                {
                    string address = remote.Address.ToString();
                    Task.Run(delegate { RegisterBack(message, address); });
                    SendAnnouncement(false);
                }
""",
        "Windows HTTP registration discovery")
    replace(transfer,
        "    private void ServerLoop()\n",
        r'''    private void RegisterBack(Dictionary<string, object> remote, string address)
    {
        try
        {
            object fpRaw; if (!remote.TryGetValue("fingerprint", out fpRaw)) return;
            if (Convert.ToString(fpRaw) == Fingerprint) return;
            int port = Port; object portRaw;
            if (remote.TryGetValue("port", out portRaw)) Int32.TryParse(Convert.ToString(portRaw), out port);
            if (port <= 0 || port > 65535) port = Port;
            string host = address.IndexOf(':') >= 0 ? "[" + address + "]" : address;
            byte[] body = Encoding.UTF8.GetBytes(json.Serialize(Info(false)));
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create("http://" + host + ":" + port + "/api/clipmesh/v1/register");
            request.Method = "POST"; request.ContentType = "application/json"; request.ContentLength = body.Length;
            request.Timeout = 2500; request.ReadWriteTimeout = 2500;
            using (Stream output = request.GetRequestStream()) output.Write(body, 0, body.Length);
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            using (Stream input = response.GetResponseStream())
            using (StreamReader reader = new StreamReader(input))
            {
                Dictionary<string, object> info = json.Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
                if (info != null) Register(info, address);
            }
        }
        catch { }
    }

    private void ServerLoop()
''',
        "Windows HTTP registration helper")
    replace(transfer,
        """            TcpListener listener = new TcpListener(IPAddress.Any, Port); listener.Start(); server = listener;
            while (Running)
""",
        """            TcpListener listener = new TcpListener(IPAddress.Any, Port); listener.Start(); server = listener; serverReady = true;
            try { SendAnnouncement(true); } catch { }
            while (Running)
""",
        "Windows listener readiness")
    replace(transfer,
        """        try { if (server != null) server.Stop(); } catch { }
        udp = null; server = null;
""",
        """        try { if (server != null) server.Stop(); } catch { }
        serverReady = false;
        udp = null; server = null;
""",
        "Windows listener readiness cleanup")
    replace(transfer,
        """    private void SendAnnouncement(bool announce)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(json.Serialize(Info(announce)));
""",
        """    private void SendAnnouncement(bool announce)
    {
        if (!serverReady) return;
        byte[] bytes = Encoding.UTF8.GetBytes(json.Serialize(Info(announce)));
""",
        "Windows do not advertise dead receiver")
    replace(ui,
        """        Hide();
        ShowInTaskbar = false;
""",
        """        LocalTransferManagerC.Shared.SetUiVisible(false);
        Hide();
        ShowInTaskbar = false;
""",
        "Windows hidden tray presence")
    replace(ui,
        """        if (!Visible) Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
""",
        """        if (!Visible) Show();
        LocalTransferManagerC.Shared.SetUiVisible(true);
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
""",
        "Windows restored tray presence")
else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh v0.2.7 background clipboard + reliable file-discovery hardening on {system}")
