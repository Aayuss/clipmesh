using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

internal sealed class TransferDeviceC
{
    public string Alias = "Nearby device";
    public string Fingerprint = "";
    public string Address = "";
    public int Port = 53317;
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
}

internal sealed class LocalTransferManagerC : IDisposable
{
    public static readonly LocalTransferManagerC Shared = new LocalTransferManagerC();
    public const int Port = 53317;
    public const string Group = "224.0.0.167";

    public Func<string, List<TransferFileMetaC>, bool> IncomingPrompt;
    private readonly object gate = new object();
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly Dictionary<string, TransferDeviceC> devices = new Dictionary<string, TransferDeviceC>();
    private readonly Dictionary<string, TransferSessionC> sessions = new Dictionary<string, TransferSessionC>();
    private CancellationTokenSource cancel;
    private UdpClient udp;
    private TcpListener server;
    private string alias = Environment.MachineName;

    private string StoreDir
    {
        get
        {
            string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ClipMesh", "FileTransfer");
            Directory.CreateDirectory(dir); return dir;
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
        Task.Run((Action)AnnounceLoop);
    }

    public void Stop()
    {
        CancellationTokenSource local;
        lock (gate) { local = cancel; cancel = null; }
        if (local != null) local.Cancel();
        try { if (udp != null) udp.Close(); } catch { }
        try { if (server != null) server.Stop(); } catch { }
        udp = null; server = null;
    }

    public List<TransferDeviceC> Nearby()
    {
        lock (gate)
        {
            DateTime cutoff = DateTime.UtcNow.AddSeconds(-22);
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
            {"fingerprint", Fingerprint}, {"port", Port}, {"protocol", "http"}, {"download", false}, {"announce", announce}
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
                if (message.TryGetValue("announce", out announce) && Convert.ToBoolean(announce)) SendAnnouncement(false);
            }
        }
        catch { }
    }

    private void AnnounceLoop()
    {
        while (Running)
        {
            try { SendAnnouncement(true); } catch { }
            for (int i = 0; i < 50 && Running; i++) Thread.Sleep(100);
        }
    }

    private void SendAnnouncement(bool announce)
    {
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
        lock (gate) devices[fp] = device;
    }

    private void ServerLoop()
    {
        try
        {
            TcpListener listener = new TcpListener(IPAddress.Any, Port); listener.Start(); server = listener;
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
        Uri target; if (!Uri.TryCreate("http://clipmesh" + rawTarget, UriKind.Absolute, out target)) { Respond(stream, 400, "Invalid target", "text/plain"); return; }
        string remote = ((IPEndPoint)client.Client.RemoteEndPoint).Address.ToString();
        if (method == "GET" && target.AbsolutePath == "/api/localsend/v2/info")
        {
            Respond(stream, 200, json.Serialize(Info(false)), "application/json"); return;
        }
        if (method == "POST" && target.AbsolutePath == "/api/localsend/v2/register")
        {
            byte[] body = ReadExact(stream, length, 2 * 1024 * 1024); if (body == null) { Respond(stream, 400, "Invalid body", "text/plain"); return; }
            try { Register(json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(body)), remote); } catch { }
            Respond(stream, 200, json.Serialize(Info(false)), "application/json"); return;
        }
        if (method == "POST" && target.AbsolutePath == "/api/localsend/v2/prepare-upload")
        {
            byte[] body = ReadExact(stream, length, 2 * 1024 * 1024); if (body == null) { Respond(stream, 400, "Invalid body", "text/plain"); return; }
            Prepare(stream, body, remote); return;
        }
        if (method == "POST" && target.AbsolutePath == "/api/localsend/v2/upload") { ReceiveFile(stream, target, length); return; }
        if (method == "POST" && target.AbsolutePath == "/api/localsend/v2/cancel")
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
        string path = Destination(meta); bool success = false;
        try
        {
            using (FileStream output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                byte[] buffer = new byte[131072]; long left = length;
                while (left > 0) { int read = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, left)); if (read <= 0) throw new IOException("Upload ended early"); output.Write(buffer, 0, read); left -= read; }
            }
            success = true;
        }
        catch { try { File.Delete(path); } catch { } }
        if (!success) { Respond(stream, 500, "Transfer failed", "text/plain"); return; }
        lock (gate)
        {
            session.Received.Add(fid); if (session.Received.Count >= session.Files.Count) sessions.Remove(sid);
        }
        Respond(stream, 200, "", "text/plain");
    }

    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress)
    {
        if (paths == null || paths.Count == 0) throw new InvalidOperationException("Choose at least one file.");
        Dictionary<string, object> files = new Dictionary<string, object>(); Dictionary<string, string> byId = new Dictionary<string, string>();
        foreach (string path in paths)
        {
            FileInfo info = new FileInfo(path); if (!info.Exists) continue; string id = Guid.NewGuid().ToString("D").ToLowerInvariant(); byId[id] = path;
            files[id] = new Dictionary<string, object> { {"id", id}, {"fileName", info.Name}, {"size", info.Length}, {"fileType", Mime(info.Extension)} };
        }
        if (files.Count == 0) throw new InvalidOperationException("No readable files were selected.");
        if (progress != null) progress("Waiting for " + target.Alias + "…");
        Dictionary<string, object> payload = new Dictionary<string, object> { {"info", Info(false)}, {"files", files} };
        HttpResultC prepare = PostJson(target, "/api/localsend/v2/prepare-upload", json.Serialize(payload));
        if (prepare.Status == 403) throw new InvalidOperationException(target.Alias + " declined the transfer.");
        if (prepare.Status != 200) throw new InvalidOperationException("Transfer request failed (" + prepare.Status + ").");
        Dictionary<string, object> response = json.Deserialize<Dictionary<string, object>>(prepare.Body); string sid = Convert.ToString(response["sessionId"]);
        Dictionary<string, object> rawTokens = response["files"] as Dictionary<string, object>; int index = 0;
        foreach (KeyValuePair<string,string> item in byId)
        {
            index++; object tokenRaw; if (rawTokens == null || !rawTokens.TryGetValue(item.Key, out tokenRaw)) continue;
            if (progress != null) progress("Sending " + Path.GetFileName(item.Value) + " • " + index + "/" + byId.Count);
            Upload(target, sid, item.Key, Convert.ToString(tokenRaw), item.Value);
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

    private void Upload(TransferDeviceC target, string sid, string fid, string token, string path)
    {
        string url = "http://" + Host(target.Address) + ":" + target.Port + "/api/localsend/v2/upload?sessionId=" + Uri.EscapeDataString(sid) + "&fileId=" + Uri.EscapeDataString(fid) + "&token=" + Uri.EscapeDataString(token);
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url); request.Method = "POST"; request.ContentType = "application/octet-stream"; FileInfo info = new FileInfo(path); request.ContentLength = info.Length; request.Timeout = 180000; request.ReadWriteTimeout = 180000;
        using (Stream output = request.GetRequestStream()) using (FileStream input = File.OpenRead(path)) input.CopyTo(output, 131072);
        try { using (HttpWebResponse response = (HttpWebResponse)request.GetResponse()) { if ((int)response.StatusCode < 200 || (int)response.StatusCode >= 300) throw new InvalidOperationException("Receiver rejected " + info.Name); } }
        catch (WebException error) { HttpWebResponse response = error.Response as HttpWebResponse; throw new InvalidOperationException("Receiver rejected " + info.Name + " (" + (response == null ? 0 : (int)response.StatusCode) + ")."); }
    }

    private static string ReadAll(Stream stream) { if (stream == null) return ""; using (StreamReader reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd(); }
    private static string Host(string value) { return value.IndexOf(':') >= 0 && !value.StartsWith("[") ? "[" + value + "]" : value; }
    private static string Mime(string ext) { string e = (ext ?? "").ToLowerInvariant(); if (e == ".png") return "image/png"; if (e == ".jpg" || e == ".jpeg") return "image/jpeg"; if (e == ".gif") return "image/gif"; if (e == ".webp") return "image/webp"; if (e == ".mp4") return "video/mp4"; if (e == ".mov") return "video/quicktime"; if (e == ".pdf") return "application/pdf"; if (e == ".txt") return "text/plain"; return "application/octet-stream"; }

    private string Destination(TransferFileMetaC meta)
    {
        string downloads = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "ClipMesh");
        if (meta.Mime.StartsWith("image/", StringComparison.OrdinalIgnoreCase)) downloads = Path.Combine(downloads, "Images"); else if (meta.Mime.StartsWith("video/", StringComparison.OrdinalIgnoreCase)) downloads = Path.Combine(downloads, "Videos");
        Directory.CreateDirectory(downloads); string name = SafeName(meta.Name); string path = Path.Combine(downloads, name); int i = 2; string stem = Path.GetFileNameWithoutExtension(name), ext = Path.GetExtension(name);
        while (File.Exists(path)) { path = Path.Combine(downloads, stem + " (" + i + ")" + ext); i++; } return path;
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
    public static void Register()
    {
        try
        {
            string exe = Application.ExecutablePath;
            RegisterKey(@"Software\Classes\*\shell\ClipMeshShare", exe);
            RegisterKey(@"Software\Classes\Directory\shell\ClipMeshShare", exe);
        }
        catch { }
    }

    private static void RegisterKey(string path, string exe)
    {
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(path))
        {
            key.SetValue("", "Share with ClipMesh"); key.SetValue("Icon", exe); key.SetValue("MultiSelectModel", "Player");
            using (RegistryKey command = key.CreateSubKey("command")) command.SetValue("", "\"" + exe + "\" --share \"%1\"");
        }
    }
}

internal sealed class TransferChooserFormC : Form
{
    private readonly Color Page = Color.FromArgb(35, 34, 29);
    private readonly Color Card = Color.FromArgb(69, 66, 56);
    private readonly Color Ink = Color.FromArgb(249, 247, 239);
    private readonly Color Muted = Color.FromArgb(194, 189, 171);
    private readonly Color Accent = Color.FromArgb(242, 238, 218);
    private readonly List<string> files = new List<string>();
    private readonly FlowLayoutPanel devicePanel;
    private readonly Label fileLabel;
    private readonly Label status;
    private readonly System.Windows.Forms.Timer timer;

    public TransferChooserFormC(IEnumerable<string> initial)
    {
        if (initial != null) foreach (string path in initial) if (File.Exists(path)) files.Add(path);
        Text = "Send with ClipMesh"; Width = 640; Height = 680; MinimumSize = new Size(560, 560); StartPosition = FormStartPosition.CenterScreen; BackColor = Page; ForeColor = Ink; AutoScaleMode = AutoScaleMode.Dpi;
        FlowLayoutPanel root = new FlowLayoutPanel(); root.Dock = DockStyle.Fill; root.AutoScroll = true; root.FlowDirection = FlowDirection.TopDown; root.WrapContents = false; root.Padding = new Padding(28,24,28,30); root.BackColor = Page; Controls.Add(root);
        Label eyebrow = L("CLIPMESH DROP", 9, FontStyle.Bold, Muted); eyebrow.Width = 550; eyebrow.Height = 22; root.Controls.Add(eyebrow);
        Label title = L("Send without\r\nbreaking your flow.", 25, FontStyle.Regular, Ink); title.Width = 550; title.Height = 74; root.Controls.Add(title);
        Label sub = L("Nearby, private, direct. No cloud in the middle.", 10, FontStyle.Regular, Muted); sub.Width = 550; sub.Height = 28; root.Controls.Add(sub);
        Panel filesCard = PanelCard(550, 84); fileLabel = L("No files selected", 12, FontStyle.Bold, Ink); fileLabel.SetBounds(18,16,350,48); Button choose = B("Choose files", false); choose.SetBounds(408,20,124,42); choose.Click += delegate { Choose(); }; filesCard.Controls.Add(fileLabel); filesCard.Controls.Add(choose); root.Controls.Add(filesCard);
        Panel nearbyCard = PanelCard(550, 330); Label nearby = L("Nearby devices", 15, FontStyle.Bold, Ink); nearby.SetBounds(18,16,350,28); nearbyCard.Controls.Add(nearby); Label hint = L("Send directly. Star devices you trust for automatic incoming saves.", 9, FontStyle.Regular, Muted); hint.SetBounds(18,46,510,28); nearbyCard.Controls.Add(hint); devicePanel = new FlowLayoutPanel(); devicePanel.FlowDirection = FlowDirection.TopDown; devicePanel.WrapContents = false; devicePanel.AutoScroll = true; devicePanel.SetBounds(18,78,514,235); devicePanel.BackColor = Card; nearbyCard.Controls.Add(devicePanel); root.Controls.Add(nearbyCard);
        status = L("Looking on this Wi-Fi…", 9, FontStyle.Regular, Muted); status.Width = 550; status.Height = 30; status.TextAlign = ContentAlignment.MiddleCenter; root.Controls.Add(status);
        RefreshFiles(); RefreshDevices(); timer = new System.Windows.Forms.Timer(); timer.Interval = 1000; timer.Tick += delegate { RefreshDevices(); }; timer.Start();
        FormClosed += delegate { timer.Stop(); timer.Dispose(); };
    }

    private void Choose() { using (OpenFileDialog dialog = new OpenFileDialog()) { dialog.Multiselect = true; dialog.Title = "Send with ClipMesh"; if (dialog.ShowDialog(this) == DialogResult.OK) { files.Clear(); files.AddRange(dialog.FileNames); RefreshFiles(); } } }
    private void RefreshFiles() { fileLabel.Text = files.Count == 0 ? "No files selected" : files.Count == 1 ? Path.GetFileName(files[0]) : files.Count + " files selected"; }
    private void RefreshDevices() { if (IsDisposed) return; devicePanel.SuspendLayout(); devicePanel.Controls.Clear(); List<TransferDeviceC> devices = LocalTransferManagerC.Shared.Nearby(); if (devices.Count == 0) { Label empty = L("No ClipMesh devices found yet.", 10, FontStyle.Regular, Muted); empty.Width=490; empty.Height=42; devicePanel.Controls.Add(empty); status.Text="Looking on this Wi-Fi…"; } else { status.Text = devices.Count + " device" + (devices.Count == 1 ? "" : "s") + " visible"; foreach (TransferDeviceC device in devices) { Panel row = new Panel(); row.Width=490; row.Height=62; row.BackColor=Card; Label name=L(device.Alias,11,FontStyle.Bold,Ink); name.SetBounds(4,7,275,23); Label model=L(String.IsNullOrWhiteSpace(device.Model)?device.Type:device.Model,8,FontStyle.Regular,Muted); model.SetBounds(4,32,275,20); bool fav=LocalTransferManagerC.Shared.IsFavorite(device.Fingerprint); Button star=B(fav?"★":"☆",false); star.SetBounds(312,10,48,40); star.Click += delegate { LocalTransferManagerC.Shared.SetFavorite(device.Fingerprint,!fav); RefreshDevices(); }; Button send=B("Send",true); send.SetBounds(370,10,108,40); send.Click += delegate { Send(device); }; row.Controls.Add(name); row.Controls.Add(model); row.Controls.Add(star); row.Controls.Add(send); devicePanel.Controls.Add(row); } } devicePanel.ResumeLayout(); }
    private void Send(TransferDeviceC device) { if (files.Count==0) { Choose(); return; } Enabled=false; status.Text="Connecting to "+device.Alias+"…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(files,device,delegate(string s){ if(!IsDisposed) BeginInvoke((Action)(delegate{status.Text=s;}));}); if(!IsDisposed) BeginInvoke((Action)(delegate{Enabled=true; status.Text="Sent to "+device.Alias;})); } catch(Exception ex){ if(!IsDisposed) BeginInvoke((Action)(delegate{Enabled=true; status.Text=ex.Message; MessageBox.Show(this,ex.Message,"Couldn’t send",MessageBoxButtons.OK,MessageBoxIcon.Error);})); } }); }
    private Panel PanelCard(int width,int height){Panel p=new Panel();p.Width=width;p.Height=height;p.BackColor=Card;p.Margin=new Padding(0,0,0,12);return p;}
    private Label L(string text,float size,FontStyle style,Color color){Label l=new Label();l.Text=text;l.Font=new Font(SystemFonts.MessageBoxFont.FontFamily,size,style);l.ForeColor=color;l.AutoEllipsis=true;return l;}
    private Button B(string text,bool primary){Button b=new Button();b.Text=text;b.FlatStyle=FlatStyle.Flat;b.FlatAppearance.BorderSize=0;b.BackColor=primary?Color.FromArgb(91,86,70):Accent;b.ForeColor=primary?Ink:Color.FromArgb(44,42,34);b.Font=new Font(SystemFonts.MessageBoxFont.FontFamily,9,FontStyle.Bold);b.Cursor=Cursors.Hand;return b;}
}
