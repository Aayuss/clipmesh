using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class CMTaskbarProgress
{
    [ComImport, Guid("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ITaskbarList3
    {
        void HrInit(); void AddTab(IntPtr hwnd); void DeleteTab(IntPtr hwnd); void ActivateTab(IntPtr hwnd); void SetActiveAlt(IntPtr hwnd);
        void MarkFullscreenWindow(IntPtr hwnd, [MarshalAs(UnmanagedType.Bool)] bool fullscreen);
        void SetProgressValue(IntPtr hwnd, ulong completed, ulong total);
        void SetProgressState(IntPtr hwnd, uint flags);
    }
    [ComImport, Guid("56FDF344-FD6D-11D0-958A-006097C9A090"), ClassInterface(ClassInterfaceType.None)]
    private class TaskbarList { }
    private const uint TBPF_NOPROGRESS = 0x0;
    private const uint TBPF_NORMAL = 0x2;
    private static readonly ITaskbarList3 Api = Create();
    private static ITaskbarList3 Create() { try { ITaskbarList3 value = (ITaskbarList3)new TaskbarList(); value.HrInit(); return value; } catch { return null; } }
    public static void Set(IntPtr hwnd, int value) { if (Api == null || hwnd == IntPtr.Zero) return; try { Api.SetProgressState(hwnd, TBPF_NORMAL); Api.SetProgressValue(hwnd, (ulong)Math.Max(0, Math.Min(1000, value)), 1000); } catch { } }
    public static void Clear(IntPtr hwnd) { if (Api == null || hwnd == IntPtr.Zero) return; try { Api.SetProgressState(hwnd, TBPF_NOPROGRESS); } catch { } }
}

internal sealed class TransferDeviceC
{
    public string Alias = "Nearby device";
    public string Fingerprint = "";
    public string Address = "";
    public int Port = 53421;
    public string Model = "";
    public string Type = "desktop";
    public DateTime LastSeen = DateTime.UtcNow;
}

internal sealed class TransferFileMetaC
{
    public string Id = "";
    public string Name = "file";
    public long Size;
    public string Mime = "application/octet-stream";
    public string Sha256;
}

internal sealed class TransferSessionC
{
    public string Id;
    public string Sender;
    public string Fingerprint;
    public Dictionary<string, TransferFileMetaC> Files;
    public Dictionary<string, string> Tokens;
    public readonly HashSet<string> Received = new HashSet<string>();
    public long ReceivedBytes;
    public int LastProgress = -1;
}

internal sealed class LocalTransferManagerC : IDisposable
{
    public static readonly LocalTransferManagerC Shared = new LocalTransferManagerC();
    public const int Port = 53421;
    public const string Group = "224.0.0.167";

    public Func<string, List<TransferFileMetaC>, bool> IncomingPrompt;
    public Action<string, string, int, bool> IncomingProgress;
    // Raised (on a thread-pool thread, coalesced ~100ms) when a nearby device is added, changes or expires.
    // Event-driven replacement for UI polling; subscribers marshal to their UI thread.
    public event Action DevicesChanged;
    private const int DeviceTtlSeconds = 180;
    private System.Threading.Timer changeTimer;
    private System.Threading.Timer expiryTimer;
    private readonly object gate = new object();
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly Dictionary<string, TransferDeviceC> devices = new Dictionary<string, TransferDeviceC>();
    private readonly Dictionary<string, TransferSessionC> sessions = new Dictionary<string, TransferSessionC>();
    private CancellationTokenSource cancel;
    private UdpClient udp;
    private TcpListener server;
    private volatile bool serverReady;
    private volatile bool uiVisible = true;
    private readonly HashSet<string> visibleDevices = new HashSet<string>(StringComparer.Ordinal);
    private string alias = Environment.MachineName;

    private string StoreDir
    {
        get
        {
            string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ClipMesh", "FileTransfer");
            Directory.CreateDirectory(dir); return dir;
        }
    }

    public string OutputFolder
    {
        get
        {
            string file = Path.Combine(StoreDir, "output-folder.txt");
            if (File.Exists(file)) { string found = File.ReadAllText(file).Trim(); if (found.Length > 0) return found; }
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "ClipMesh");
        }
        set
        {
            string selected = Path.GetFullPath(value); Directory.CreateDirectory(selected); File.WriteAllText(Path.Combine(StoreDir, "output-folder.txt"), selected);
        }
    }

    public string Fingerprint
    {
        get
        {
            string file = Path.Combine(StoreDir, "fingerprint.txt");
            if (File.Exists(file)) { string found = File.ReadAllText(file).Trim(); if (found.Length > 0) return found; }
            string value = Guid.NewGuid().ToString("D").ToLowerInvariant(); File.WriteAllText(file, value); return value;
        }
    }

    public void Start(string deviceAlias)
    {
        lock (gate)
        {
            alias = String.IsNullOrWhiteSpace(deviceAlias) ? Environment.MachineName : deviceAlias.Trim();
            if (cancel != null) return;
            cancel = new CancellationTokenSource();
        }
        Task.Run((Action)DiscoveryLoop);
        Task.Run((Action)ServerLoop);
    }

    public void Stop()
    {
        CancellationTokenSource local;
        lock (gate) { local = cancel; cancel = null; }
        if (local != null) local.Cancel();
        try { if (udp != null) udp.Close(); } catch { }
        try { if (server != null) server.Stop(); } catch { }
        serverReady = false;
        udp = null; server = null;
    }

    public List<TransferDeviceC> Nearby()
    {
        lock (gate)
        {
            DateTime cutoff = DateTime.UtcNow.AddSeconds(-DeviceTtlSeconds);
            List<string> stale = new List<string>();
            foreach (KeyValuePair<string, TransferDeviceC> pair in devices) if (pair.Value.LastSeen < cutoff) stale.Add(pair.Key);
            foreach (string key in stale) devices.Remove(key);
            List<TransferDeviceC> values = new List<TransferDeviceC>(devices.Values);
            values.RemoveAll(delegate(TransferDeviceC d) { return d.Fingerprint == Fingerprint; });
            values.Sort(delegate(TransferDeviceC a, TransferDeviceC b)
            {
                bool af = IsFavorite(a.Fingerprint), bf = IsFavorite(b.Fingerprint);
                if (af != bf) return af ? -1 : 1;
                return StringComparer.CurrentCultureIgnoreCase.Compare(a.Alias, b.Alias);
            });
            return values;
        }
    }

    public bool IsFavorite(string fingerprint) { return LoadFavorites().Contains(fingerprint); }

    public void SetUiVisible(bool visible)
    {
        bool changed = uiVisible != visible;
        uiVisible = visible;
        if (changed) DiscoverNow();
    }

    public void DiscoverNow()
    {
        Task.Run(delegate { for (int i = 0; i < 3 && Running; i++) { try { SendAnnouncement(true); } catch { } if (i < 2) Thread.Sleep(180); } });
    }

    public void SetFavorite(string fingerprint, bool favorite)
    {
        HashSet<string> set = LoadFavorites();
        if (favorite) set.Add(fingerprint); else set.Remove(fingerprint);
        File.WriteAllLines(Path.Combine(StoreDir, "favorites.txt"), new List<string>(set).ToArray());
    }

    private HashSet<string> LoadFavorites()
    {
        string file = Path.Combine(StoreDir, "favorites.txt");
        return new HashSet<string>(File.Exists(file) ? File.ReadAllLines(file) : new string[0], StringComparer.Ordinal);
    }

    private bool Running { get { lock (gate) return cancel != null && !cancel.IsCancellationRequested; } }

    private Dictionary<string, object> Info(bool announce)
    {
        return new Dictionary<string, object>
        {
            {"alias", alias}, {"version", "2.0"}, {"deviceModel", Environment.MachineName}, {"deviceType", "desktop"},
            {"fingerprint", Fingerprint}, {"port", Port}, {"protocol", "http"}, {"download", false}, {"announce", announce}, {"visible", uiVisible}
        };
    }

    private void DiscoveryLoop()
    {
        try
        {
            UdpClient client = new UdpClient();
            client.ExclusiveAddressUse = false;
            client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
            client.Client.Bind(new IPEndPoint(IPAddress.Any, Port));
            client.JoinMulticastGroup(IPAddress.Parse(Group));
            udp = client;
            while (Running)
            {
                IPEndPoint remote = new IPEndPoint(IPAddress.Any, 0);
                byte[] bytes;
                try { bytes = client.Receive(ref remote); } catch { if (!Running) break; else continue; }
                Dictionary<string, object> message;
                try { message = json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(bytes)); } catch { continue; }
                Register(message, remote.Address.ToString());
                object announce;
                if (message.TryGetValue("announce", out announce) && Convert.ToBoolean(announce))
                {
                    string address = remote.Address.ToString();
                    Task.Run(delegate { RegisterBack(message, address); });
                    SendAnnouncement(false);
                }
            }
        }
        catch { }
    }

    private void SendAnnouncement(bool announce)
    {
        if (!serverReady) return;
        byte[] bytes = Encoding.UTF8.GetBytes(json.Serialize(Info(announce)));
        using (UdpClient sender = new UdpClient())
        {
            sender.Ttl = 1;
            sender.Send(bytes, bytes.Length, new IPEndPoint(IPAddress.Parse(Group), Port));
        }
    }

    private void Register(Dictionary<string, object> info, string address)
    {
        object fpRaw; if (!info.TryGetValue("fingerprint", out fpRaw)) return;
        string fp = Convert.ToString(fpRaw); if (String.IsNullOrWhiteSpace(fp) || fp == Fingerprint) return;
        TransferDeviceC device = new TransferDeviceC();
        device.Fingerprint = fp;
        object value;
        if (info.TryGetValue("alias", out value)) device.Alias = Convert.ToString(value);
        if (info.TryGetValue("deviceModel", out value)) device.Model = Convert.ToString(value);
        if (info.TryGetValue("deviceType", out value)) device.Type = Convert.ToString(value);
        if (info.TryGetValue("port", out value)) { int p; if (Int32.TryParse(Convert.ToString(value), out p) && p > 0 && p < 65536) device.Port = p; }
        device.Address = address; device.LastSeen = DateTime.UtcNow;
        bool remoteVisible = !info.ContainsKey("visible") || Convert.ToBoolean(info["visible"]);
        bool changed, added;
        lock (gate)
        {
            TransferDeviceC previous;
            added = !devices.TryGetValue(fp, out previous);
            changed = added || previous.Alias != device.Alias || previous.Model != device.Model || previous.Type != device.Type
                || previous.Address != device.Address || previous.Port != device.Port || visibleDevices.Contains(fp) != remoteVisible;
            devices[fp] = device;
            if (remoteVisible) visibleDevices.Add(fp); else visibleDevices.Remove(fp);
        }
        if (added) ArmExpiry();
        if (changed) NotifyDevicesChanged();
    }

    // Coalesces bursts of discovery traffic into a single DevicesChanged notification.
    private void NotifyDevicesChanged()
    {
        lock (gate)
        {
            if (changeTimer == null) changeTimer = new System.Threading.Timer(delegate { Action handler = DevicesChanged; if (handler != null) { try { handler(); } catch { } } }, null, 100, Timeout.Infinite);
            else changeTimer.Change(100, Timeout.Infinite);
        }
    }

    // One one-shot timer at the earliest device expiry (no periodic sweep).
    private void ArmExpiry()
    {
        lock (gate)
        {
            DateTime earliest = DateTime.MaxValue;
            foreach (TransferDeviceC d in devices.Values) if (d.LastSeen < earliest) earliest = d.LastSeen;
            long due = earliest == DateTime.MaxValue ? Timeout.Infinite : Math.Max(250L, (long)(earliest.AddSeconds(DeviceTtlSeconds) - DateTime.UtcNow).TotalMilliseconds + 250L);
            if (expiryTimer == null) { if (due == Timeout.Infinite) return; expiryTimer = new System.Threading.Timer(delegate { ExpireDevices(); }, null, due, Timeout.Infinite); }
            else expiryTimer.Change(due, Timeout.Infinite);
        }
    }

    private void ExpireDevices()
    {
        bool removed = false;
        lock (gate)
        {
            DateTime cutoff = DateTime.UtcNow.AddSeconds(-DeviceTtlSeconds);
            List<string> stale = new List<string>();
            foreach (KeyValuePair<string, TransferDeviceC> pair in devices) if (pair.Value.LastSeen < cutoff) stale.Add(pair.Key);
            foreach (string key in stale) { devices.Remove(key); visibleDevices.Remove(key); removed = true; }
        }
        ArmExpiry();
        if (removed) NotifyDevicesChanged();
    }

    // Used only by the --ui-snapshot preview mode (no network involved).
    internal void SeedSnapshotDevices(IEnumerable<TransferDeviceC> seeded)
    {
        lock (gate) foreach (TransferDeviceC d in seeded) { d.LastSeen = DateTime.UtcNow; devices[d.Fingerprint] = d; }
    }

    private void RegisterBack(Dictionary<string, object> remote, string address)
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
    {
        try
        {
            TcpListener listener = new TcpListener(IPAddress.Any, Port); listener.Start(); server = listener; serverReady = true;
            try { SendAnnouncement(true); } catch { }
            while (Running)
            {
                TcpClient client;
                try { client = listener.AcceptTcpClient(); } catch { break; }
                ThreadPool.QueueUserWorkItem(delegate { try { HandleClient(client); } catch { } finally { client.Close(); } });
            }
        }
        catch { }
    }

    private void HandleClient(TcpClient client)
    {
        client.ReceiveTimeout = 75000; client.SendTimeout = 75000;
        NetworkStream stream = client.GetStream();
        string request = ReadLine(stream); if (request == null) return;
        string[] parts = request.Split(' '); if (parts.Length < 2) { Respond(stream, 400, "Invalid request", "text/plain"); return; }
        string method = parts[0].ToUpperInvariant(); string rawTarget = parts[1];
        Dictionary<string, string> headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        while (true)
        {
            string line = ReadLine(stream); if (line == null || line.Length == 0) break;
            int colon = line.IndexOf(':'); if (colon > 0) headers[line.Substring(0, colon).Trim()] = line.Substring(colon + 1).Trim();
        }
        long length = 0; string len; if (headers.TryGetValue("Content-Length", out len)) Int64.TryParse(len, out length);
        string expect; if (headers.TryGetValue("Expect", out expect) && expect.IndexOf("100-continue", StringComparison.OrdinalIgnoreCase) >= 0) { byte[] interim=Encoding.ASCII.GetBytes("HTTP/1.1 100 Continue\r\n\r\n"); stream.Write(interim,0,interim.Length); stream.Flush(); }
        Uri target; if (!Uri.TryCreate("http://clipmesh" + rawTarget, UriKind.Absolute, out target)) { Respond(stream, 400, "Invalid target", "text/plain"); return; }
        string remote = ((IPEndPoint)client.Client.RemoteEndPoint).Address.ToString();
        if (method == "GET" && target.AbsolutePath == "/api/clipmesh/v1/info")
        {
            Respond(stream, 200, json.Serialize(Info(false)), "application/json"); return;
        }
        if (method == "POST" && target.AbsolutePath == "/api/clipmesh/v1/register")
        {
            byte[] body = ReadExact(stream, length, 2 * 1024 * 1024); if (body == null) { Respond(stream, 400, "Invalid body", "text/plain"); return; }
            try { Register(json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(body)), remote); } catch { }
            Respond(stream, 200, json.Serialize(Info(false)), "application/json"); return;
        }
        if (method == "POST" && target.AbsolutePath == "/api/clipmesh/v1/prepare-upload")
        {
            byte[] body = ReadExact(stream, length, 2 * 1024 * 1024); if (body == null) { Respond(stream, 400, "Invalid body", "text/plain"); return; }
            Prepare(stream, body, remote); return;
        }
        if (method == "POST" && target.AbsolutePath == "/api/clipmesh/v1/upload") { ReceiveFile(stream, target, length); return; }
        if (method == "POST" && target.AbsolutePath == "/api/clipmesh/v1/cancel")
        {
            Dictionary<string,string> q = Query(target); string sid; if (q.TryGetValue("sessionId", out sid)) lock (gate) sessions.Remove(sid);
            Respond(stream, 200, "", "text/plain"); return;
        }
        Respond(stream, 404, "Not found", "text/plain");
    }

    private void Prepare(NetworkStream stream, byte[] body, string remote)
    {
        Dictionary<string, object> root;
        try { root = json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(body)); } catch { Respond(stream, 400, "Invalid body", "text/plain"); return; }
        Dictionary<string, object> sender = root.ContainsKey("info") ? root["info"] as Dictionary<string, object> : null;
        Dictionary<string, object> rawFiles = root.ContainsKey("files") ? root["files"] as Dictionary<string, object> : null;
        if (sender == null || rawFiles == null) { Respond(stream, 400, "Invalid body", "text/plain"); return; }
        Register(sender, remote);
        string senderAlias = sender.ContainsKey("alias") ? Convert.ToString(sender["alias"]) : "Nearby device";
        string fingerprint = sender.ContainsKey("fingerprint") ? Convert.ToString(sender["fingerprint"]) : "unknown";
        Dictionary<string, TransferFileMetaC> files = new Dictionary<string, TransferFileMetaC>();
        foreach (KeyValuePair<string, object> pair in rawFiles)
        {
            Dictionary<string, object> item = pair.Value as Dictionary<string, object>; if (item == null) continue;
            TransferFileMetaC meta = new TransferFileMetaC(); meta.Id = item.ContainsKey("id") ? Convert.ToString(item["id"]) : pair.Key;
            meta.Name = SafeName(item.ContainsKey("fileName") ? Convert.ToString(item["fileName"]) : "file");
            long size; if (!Int64.TryParse(item.ContainsKey("size") ? Convert.ToString(item["size"]) : "", out size) || size < 0) continue; meta.Size = size;
            if (item.ContainsKey("fileType")) meta.Mime = Convert.ToString(item["fileType"]); if (item.ContainsKey("sha256")) meta.Sha256 = Convert.ToString(item["sha256"]);
            files[meta.Id] = meta;
        }
        if (files.Count == 0) { Respond(stream, 400, "No files", "text/plain"); return; }
        bool accepted = IsFavorite(fingerprint);
        if (!accepted && IncomingPrompt != null)
        {
            try { accepted = IncomingPrompt(senderAlias, new List<TransferFileMetaC>(files.Values)); } catch { accepted = false; }
        }
        if (!accepted) { Respond(stream, 403, "Rejected", "text/plain"); return; }
        string sid = Guid.NewGuid().ToString("D").ToLowerInvariant(); Dictionary<string, string> tokens = new Dictionary<string, string>();
        foreach (string id in files.Keys) tokens[id] = Guid.NewGuid().ToString("N").ToLowerInvariant();
        TransferSessionC session = new TransferSessionC { Id = sid, Sender = senderAlias, Fingerprint = fingerprint, Files = files, Tokens = tokens };
        lock (gate) sessions[sid] = session;
        Respond(stream, 200, json.Serialize(new Dictionary<string, object> { { "sessionId", sid }, { "files", tokens } }), "application/json");
    }

    private void ReceiveFile(NetworkStream stream, Uri target, long length)
    {
        Dictionary<string, string> q = Query(target); string sid, fid, token;
        if (!q.TryGetValue("sessionId", out sid) || !q.TryGetValue("fileId", out fid) || !q.TryGetValue("token", out token)) { Respond(stream, 400, "Missing parameters", "text/plain"); return; }
        TransferSessionC session; lock (gate) sessions.TryGetValue(sid, out session);
        TransferFileMetaC meta; if (session == null || !session.Files.TryGetValue(fid, out meta) || !session.Tokens.ContainsKey(fid) || session.Tokens[fid] != token) { Respond(stream, 403, "Invalid token", "text/plain"); return; }
        if (length != meta.Size) { Respond(stream, 400, "Unexpected size", "text/plain"); return; }
        string path = Destination(meta); bool success = false; long fileReceived = 0;
        try
        {
            using (FileStream output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                byte[] buffer = new byte[131072]; long left = length;
                while (left > 0) { int read = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, left)); if (read <= 0) throw new IOException("Upload ended early"); output.Write(buffer, 0, read); left -= read; fileReceived += read; Interlocked.Add(ref session.ReceivedBytes, read); PublishIncoming(session, meta.Name, false); }
            }
            success = true;
        }
        catch { Interlocked.Add(ref session.ReceivedBytes, -fileReceived); Action<string, string, int, bool> failed = IncomingProgress; if (failed != null) failed(session.Sender, meta.Name, -1, false); try { File.Delete(path); } catch { } }
        if (!success) { Respond(stream, 500, "Transfer failed", "text/plain"); return; }
        bool complete; lock (gate)
        {
            session.Received.Add(fid); complete = session.Received.Count >= session.Files.Count; if (complete) sessions.Remove(sid);
        }
        if (complete) PublishIncoming(session, meta.Name, true);
        Respond(stream, 200, "", "text/plain");
    }

    private void PublishIncoming(TransferSessionC session, string file, bool complete)
    {
        long total = 0; foreach (TransferFileMetaC item in session.Files.Values) total += item.Size;
        long received = Interlocked.Read(ref session.ReceivedBytes);
        int value = total <= 0 ? 1000 : (int)Math.Min(1000L, (received * 1000L) / total);
        lock (session) { if (!complete && value == session.LastProgress) return; session.LastProgress = value; }
        Action<string, string, int, bool> callback = IncomingProgress;
        if (callback != null) callback(session.Sender, file, value, complete);
    }

    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress)
    {
        SendFiles(paths, target, progress, null);
    }

    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress, Action<int> progressValue)
    {
        if (paths == null || paths.Count == 0) throw new InvalidOperationException("Choose at least one file.");
        Dictionary<string, object> files = new Dictionary<string, object>(); Dictionary<string, string> byId = new Dictionary<string, string>();
        foreach (string path in paths)
        {
            FileInfo info = new FileInfo(path); if (!info.Exists) continue; string id = Guid.NewGuid().ToString("D").ToLowerInvariant(); byId[id] = path;
            files[id] = new Dictionary<string, object> { {"id", id}, {"fileName", info.Name}, {"size", info.Length}, {"fileType", Mime(info.Extension)} };
        }
        if (files.Count == 0) throw new InvalidOperationException("No readable files were selected.");
        long totalBytes = 0; foreach (string path in byId.Values) totalBytes += new FileInfo(path).Length; long completedBytes = 0;
        if (progress != null) progress("Waiting for " + target.Alias + "…"); if (progressValue != null) progressValue(0);
        Dictionary<string, object> payload = new Dictionary<string, object> { {"info", Info(false)}, {"files", files} };
        HttpResultC prepare = PostJson(target, "/api/clipmesh/v1/prepare-upload", json.Serialize(payload));
        if (prepare.Status == 403) throw new InvalidOperationException(target.Alias + " declined the transfer.");
        if (prepare.Status != 200) throw new InvalidOperationException("Transfer request failed (" + prepare.Status + ").");
        Dictionary<string, object> response = json.Deserialize<Dictionary<string, object>>(prepare.Body); string sid = Convert.ToString(response["sessionId"]);
        Dictionary<string, object> rawTokens = response["files"] as Dictionary<string, object>; int index = 0;
        foreach (KeyValuePair<string,string> item in byId)
        {
            index++; object tokenRaw; if (rawTokens == null || !rawTokens.TryGetValue(item.Key, out tokenRaw)) continue;
            if (progress != null) progress("Sending " + Path.GetFileName(item.Value) + " • " + index + "/" + byId.Count);
            long before = completedBytes;
            Upload(target, sid, item.Key, Convert.ToString(tokenRaw), item.Value, delegate(long sent) { if (progressValue != null) progressValue(totalBytes <= 0 ? 1000 : (int)Math.Min(1000L, ((before + sent) * 1000L) / totalBytes)); });
            completedBytes += new FileInfo(item.Value).Length;
        }
    }

    private sealed class HttpResultC { public int Status; public string Body; }

    private HttpResultC PostJson(TransferDeviceC target, string path, string body)
    {
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create("http://" + Host(target.Address) + ":" + target.Port + path); request.Method = "POST"; request.ContentType = "application/json"; request.Timeout = 75000; request.ReadWriteTimeout = 75000;
        byte[] bytes = Encoding.UTF8.GetBytes(body); request.ContentLength = bytes.Length; using (Stream output = request.GetRequestStream()) output.Write(bytes, 0, bytes.Length);
        try { using (HttpWebResponse response = (HttpWebResponse)request.GetResponse()) return new HttpResultC { Status = (int)response.StatusCode, Body = ReadAll(response.GetResponseStream()) }; }
        catch (WebException error) { HttpWebResponse response = error.Response as HttpWebResponse; return new HttpResultC { Status = response == null ? 0 : (int)response.StatusCode, Body = response == null ? error.Message : ReadAll(response.GetResponseStream()) }; }
    }

    private void Upload(TransferDeviceC target, string sid, string fid, string token, string path, Action<long> onProgress)
    {
        string url = "http://" + Host(target.Address) + ":" + target.Port + "/api/clipmesh/v1/upload?sessionId=" + Uri.EscapeDataString(sid) + "&fileId=" + Uri.EscapeDataString(fid) + "&token=" + Uri.EscapeDataString(token);
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url); request.Method = "POST"; request.ContentType = "application/octet-stream"; FileInfo info = new FileInfo(path); request.ContentLength = info.Length; request.Timeout = 180000; request.ReadWriteTimeout = 180000;
        using (Stream output = request.GetRequestStream()) using (FileStream input = File.OpenRead(path)) { byte[] buffer = new byte[131072]; long sent = 0; int read; while ((read = input.Read(buffer, 0, buffer.Length)) > 0) { output.Write(buffer, 0, read); sent += read; if (onProgress != null) onProgress(sent); } output.Flush(); }
        try { using (HttpWebResponse response = (HttpWebResponse)request.GetResponse()) { if ((int)response.StatusCode < 200 || (int)response.StatusCode >= 300) throw new InvalidOperationException("Receiver rejected " + info.Name); } }
        catch (WebException error) { HttpWebResponse response = error.Response as HttpWebResponse; throw new InvalidOperationException("Receiver rejected " + info.Name + " (" + (response == null ? 0 : (int)response.StatusCode) + ")."); }
    }

    private static string ReadAll(Stream stream) { if (stream == null) return ""; using (StreamReader reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd(); }
    private static string Host(string value) { return value.IndexOf(':') >= 0 && !value.StartsWith("[") ? "[" + value + "]" : value; }
    private static string Mime(string ext) { string e = (ext ?? "").ToLowerInvariant(); if (e == ".png") return "image/png"; if (e == ".jpg" || e == ".jpeg") return "image/jpeg"; if (e == ".gif") return "image/gif"; if (e == ".webp") return "image/webp"; if (e == ".mp4") return "video/mp4"; if (e == ".mov") return "video/quicktime"; if (e == ".pdf") return "application/pdf"; if (e == ".txt") return "text/plain"; return "application/octet-stream"; }

    private string Destination(TransferFileMetaC meta)
    {
        string folder = OutputFolder;
        if (meta.Mime.StartsWith("image/", StringComparison.OrdinalIgnoreCase)) folder = Path.Combine(folder, "images");
        else if (meta.Mime.StartsWith("video/", StringComparison.OrdinalIgnoreCase)) folder = Path.Combine(folder, "video");
        Directory.CreateDirectory(folder); string name = SafeName(meta.Name); string path = Path.Combine(folder, name); int i = 2; string stem = Path.GetFileNameWithoutExtension(name), ext = Path.GetExtension(name);
        while (File.Exists(path)) { path = Path.Combine(folder, stem + " (" + i + ")" + ext); i++; } return path;
    }

    private static string SafeName(string value) { string name = Path.GetFileName(value ?? "file"); foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c.ToString(), ""); name = name.Trim(); return name.Length == 0 ? "file" : (name.Length > 180 ? name.Substring(0,180) : name); }
    private static string ReadLine(Stream input) { MemoryStream bytes = new MemoryStream(); while (bytes.Length < 16384) { int b = input.ReadByte(); if (b < 0) return bytes.Length == 0 ? null : Encoding.GetEncoding(28591).GetString(bytes.ToArray()); if (b == 10) break; if (b != 13) bytes.WriteByte((byte)b); } return Encoding.GetEncoding(28591).GetString(bytes.ToArray()); }
    private static byte[] ReadExact(Stream input, long length, int max) { if (length < 0 || length > max) return null; byte[] data = new byte[(int)length]; int offset = 0; while (offset < data.Length) { int read = input.Read(data, offset, data.Length - offset); if (read <= 0) return null; offset += read; } return data; }
    private static Dictionary<string,string> Query(Uri uri) { Dictionary<string,string> result = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase); string query = uri.Query.TrimStart('?'); foreach (string part in query.Split('&')) { if (part.Length == 0) continue; int eq = part.IndexOf('='); string k = eq < 0 ? part : part.Substring(0,eq), v = eq < 0 ? "" : part.Substring(eq+1); result[Uri.UnescapeDataString(k)] = Uri.UnescapeDataString(v.Replace("+"," ")); } return result; }
    private static void Respond(Stream output, int code, string body, string type) { byte[] bytes = Encoding.UTF8.GetBytes(body ?? ""); string reason = code == 200 ? "OK" : code == 400 ? "Bad Request" : code == 403 ? "Forbidden" : code == 404 ? "Not Found" : code == 422 ? "Unprocessable Entity" : "Internal Server Error"; byte[] header = Encoding.ASCII.GetBytes("HTTP/1.1 " + code + " " + reason + "\r\nContent-Type: " + type + "\r\nContent-Length: " + bytes.Length + "\r\nConnection: close\r\n\r\n"); output.Write(header,0,header.Length); output.Write(bytes,0,bytes.Length); output.Flush(); }

    public void Dispose() { Stop(); }
}

internal static class ClipMeshShellIntegration
{
    private const string VerbText = "Send with ClipMesh";

    private static string Command(string exe) { return "\"" + exe + "\" --share \"%1\""; }

    private static string SendToShortcut
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.SendTo), "ClipMesh.lnk"); }
    }

    public static void Register()
    {
        string exe = Application.ExecutablePath;
        try
        {
            RegisterKey(@"Software\Classes\*\shell\ClipMeshShare", exe);
            RegisterKey(@"Software\Classes\Directory\shell\ClipMeshShare", exe);
        }
        catch { }
        try { EnsureSendToShortcut(exe); } catch { }
    }

    public static bool IsRegistered()
    {
        string exe = Application.ExecutablePath;
        foreach (string path in new string[] { @"Software\Classes\*\shell\ClipMeshShare\command", @"Software\Classes\Directory\shell\ClipMeshShare\command" })
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(path))
            {
                if (key == null) return false;
                if (!String.Equals(Convert.ToString(key.GetValue("")), Command(exe), StringComparison.OrdinalIgnoreCase)) return false;
            }
        }
        return File.Exists(SendToShortcut);
    }

    private static void RegisterKey(string path, string exe)
    {
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(path))
        {
            key.SetValue("", VerbText); key.SetValue("Icon", exe); key.SetValue("MultiSelectModel", "Player");
            using (RegistryKey command = key.CreateSubKey("command")) command.SetValue("", Command(exe));
        }
    }

    // "Send to > ClipMesh" passes every selected item to a single process.
    private static void EnsureSendToShortcut(string exe)
    {
        string link = SendToShortcut;
        string folder = Path.GetDirectoryName(link);
        if (String.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return;
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType == null) return;
        object shell = null, shortcut = null;
        try
        {
            shell = Activator.CreateInstance(shellType);
            shortcut = shellType.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod, null, shell, new object[] { link });
            Type t = shortcut.GetType();
            if (File.Exists(link))
            {
                string target = Convert.ToString(t.InvokeMember("TargetPath", System.Reflection.BindingFlags.GetProperty, null, shortcut, null));
                string arguments = Convert.ToString(t.InvokeMember("Arguments", System.Reflection.BindingFlags.GetProperty, null, shortcut, null));
                if (String.Equals(target, exe, StringComparison.OrdinalIgnoreCase) && arguments.Trim() == "--share") return;
            }
            t.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { exe });
            t.InvokeMember("Arguments", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { "--share" });
            t.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { Path.GetDirectoryName(exe) });
            t.InvokeMember("IconLocation", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { exe + ",0" });
            t.InvokeMember("Description", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { VerbText });
            t.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, shortcut, null);
        }
        finally
        {
            if (shortcut != null && Marshal.IsComObject(shortcut)) Marshal.FinalReleaseComObject(shortcut);
            if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
        }
    }
}
