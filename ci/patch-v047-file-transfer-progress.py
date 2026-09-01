#!/usr/bin/env python3
from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es), found {found} in {path}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh/fileshare"
    engine = java / "LocalTransferEngine.kt"
    activity = java / "FileShareActivity.kt"
    notifications = java / "TransferNotifications.kt"

    replace(engine,
'''        val files: Map<String, FileMeta>,
        val tokens: Map<String, String>,
        val received: MutableSet<String> = ConcurrentHashMap.newKeySet()
''',
'''        val files: Map<String, FileMeta>,
        val tokens: Map<String, String>,
        val automaticallyAccepted: Boolean,
        val received: MutableSet<String> = ConcurrentHashMap.newKeySet()
''', "Android automatic-save session provenance")

    replace(engine,
'''        progress: (completed: Int, total: Int, status: String) -> Unit
''',
'''        progress: (completed: Int, total: Int, sentBytes: Long, totalBytes: Long, status: String) -> Unit
''', "Android byte-progress callback")
    replace(engine,
'''        progress(0, metas.size, "Waiting for ${target.alias}…")
''',
'''        val totalBytes = metas.sumOf { it.size }
        progress(0, metas.size, 0L, totalBytes, "Waiting for ${target.alias}…")
''', "Android initial transfer progress")
    replace(engine,
'''        metas.forEachIndexed { index, meta ->
            val token = tokens.optString(meta.id, "")
            if (token.isBlank()) return@forEachIndexed
            progress(index, metas.size, "Sending ${meta.name}")
            uploadUri(context, target, sessionId, meta, token)
            progress(index + 1, metas.size, "Sent ${index + 1} of ${metas.size}")
        }
''',
'''        var completedBytes = 0L
        metas.forEachIndexed { index, meta ->
            val token = tokens.optString(meta.id, "")
            if (token.isBlank()) return@forEachIndexed
            progress(index, metas.size, completedBytes, totalBytes, "Sending ${meta.name}")
            uploadUri(context, target, sessionId, meta, token) { fileBytes ->
                progress(index, metas.size, completedBytes + fileBytes, totalBytes, "Sending ${meta.name}")
            }
            completedBytes += meta.size
            progress(index + 1, metas.size, completedBytes, totalBytes, "Sent ${index + 1} of ${metas.size}")
        }
''', "Android aggregate byte progress")

    replace(engine,
'''        val accepted = if (isFavorite(requireContext(), sender.fingerprint) && SettingsStore(requireContext()).autoAcceptFavoriteFiles) {
            true
        } else {
''',
'''        val automaticallyAccepted = isFavorite(requireContext(), sender.fingerprint) && SettingsStore(requireContext()).autoAcceptFavoriteFiles
        val accepted = if (automaticallyAccepted) {
            true
        } else {
''', "Android favorite auto-accept marker")
    replace(engine,
'''            files = files,
            tokens = tokens
''',
'''            files = files,
            tokens = tokens,
            automaticallyAccepted = automaticallyAccepted
''', "Android store favorite auto-accept marker")
    replace(engine,
'''                TransferNotifications.showCompleted(requireContext(), session.senderAlias, session.files.size)
''',
'''                if (session.automaticallyAccepted) {
                    TransferNotifications.showAutomaticallySaved(requireContext(), session.senderAlias, session.files.values.map { it.fileName })
                } else {
                    TransferNotifications.showCompleted(requireContext(), session.senderAlias, session.files.size)
                }
''', "Android favorite auto-save notification")
    replace(engine,
'''    private fun uploadUri(context: Context, target: TransferDevice, sessionId: String, meta: SendMeta, token: String) {
''',
'''    private fun uploadUri(context: Context, target: TransferDevice, sessionId: String, meta: SendMeta, token: String, onProgress: (Long) -> Unit) {
''', "Android upload progress parameter")
    replace(engine,
'''        context.contentResolver.openInputStream(meta.uri)?.use { input ->
            connection.outputStream.use { output -> input.copyTo(output, 128 * 1024) }
        } ?: throw IllegalStateException("Could not open ${meta.name}")
''',
'''        context.contentResolver.openInputStream(meta.uri)?.use { input ->
            connection.outputStream.use { output ->
                val buffer = ByteArray(128 * 1024)
                var sent = 0L
                while (true) {
                    val count = input.read(buffer)
                    if (count <= 0) break
                    output.write(buffer, 0, count)
                    sent += count
                    onProgress(sent)
                }
                output.flush()
            }
        } ?: throw IllegalStateException("Could not open ${meta.name}")
''', "Android streamed upload byte progress")

    replace(activity,
'''    private lateinit var status: TextView
    private var sending = false
''',
'''    private lateinit var status: TextView
    private lateinit var transferProgress: ProgressBar
    private var sending = false
''', "Android compact progress field")
    replace(activity,
'''        root.addView(status, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        shell.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
''',
'''        root.addView(status, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT))
        transferProgress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 1000
            progress = 0
            visibility = View.GONE
            progressTintList = android.content.res.ColorStateList.valueOf(accent)
        }
        root.addView(transferProgress, fullWidth(dp(5)).apply { topMargin = dp(3); bottomMargin = dp(4) })
        shell.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
''', "Android compact in-app progress bar")
    replace(activity,
'''        sending = true
        status.text = "Connecting to ${device.alias}…"
        io.execute {
            runCatching {
                LocalTransferEngine.sendUris(this, selected.toList(), device) { completed, total, message ->
                    main.post { status.text = message }
                }
            }.onSuccess {
                main.post {
                    sending = false
                    status.text = "Sent to ${device.alias}"
                    ClipMeshDialog.confirm(this, "Sent", "${if (selected.size == 1) displayName(selected.first()) else "${selected.size} files"} was sent to ${device.alias}.") { done -> if (done) finish() }
                }
            }.onFailure { error ->
                main.post {
                    sending = false
                    status.text = error.message ?: "Transfer failed"
                    ClipMeshDialog.info(this, "Couldn’t send", error.message ?: "The transfer failed.")
                }
            }
        }
''',
'''        sending = true
        transferProgress.progress = 0
        transferProgress.visibility = View.VISIBLE
        status.text = "Connecting to ${device.alias}…"
        val outgoingId = java.util.UUID.randomUUID().toString()
        var lastNotifiedPercent = -1
        io.execute {
            runCatching {
                LocalTransferEngine.sendUris(this, selected.toList(), device) { _, _, sentBytes, totalBytes, message ->
                    val fraction = if (totalBytes <= 0L) 0 else ((sentBytes * 1000L) / totalBytes).toInt().coerceIn(0, 1000)
                    main.post {
                        status.text = message
                        transferProgress.progress = fraction
                        val percent = fraction / 10
                        if (percent != lastNotifiedPercent) {
                            lastNotifiedPercent = percent
                            TransferNotifications.showSending(this, outgoingId, device.alias, message, percent)
                        }
                    }
                }
            }.onSuccess {
                main.post {
                    val sentDescription = if (selected.size == 1) displayName(selected.first()) else "${selected.size} files"
                    selected.clear()
                    refreshFiles()
                    sending = false
                    transferProgress.progress = 1000
                    transferProgress.visibility = View.GONE
                    TransferNotifications.cancelSending(this, outgoingId)
                    status.text = "Sent to ${device.alias}"
                    ClipMeshDialog.confirm(this, "Sent", "$sentDescription was sent to ${device.alias}.") { _ ->
                        // Continue intentionally remains on File Transfer.
                        LocalTransferEngine.discoverNow()
                        renderDevices()
                    }
                }
            }.onFailure { error ->
                main.post {
                    sending = false
                    transferProgress.visibility = View.GONE
                    TransferNotifications.cancelSending(this, outgoingId)
                    status.text = error.message ?: "Transfer failed"
                    ClipMeshDialog.info(this, "Couldn’t send", error.message ?: "The transfer failed.")
                }
            }
        }
''', "Android success clearing, Continue routing, and progress")

    dev_receiver = project / "android/app/src/debug/java/dev/clipmesh/DevTestReceiver.kt"
    replace(dev_receiver,
'''                LocalTransferEngine.sendUris(app, listOf(uri), target) { _, _, _ -> }
''',
'''                LocalTransferEngine.sendUris(app, listOf(uri), target) { _, _, _, _, _ -> }
''', "Android development transfer callback compatibility")

    replace(notifications,
'''    private const val COMPLETE_CHANNEL = "clipmesh_file_complete_v020"
''',
'''    private const val COMPLETE_CHANNEL = "clipmesh_file_complete_v020"
    private const val SEND_CHANNEL = "clipmesh_file_send_v047"
''', "Android outgoing progress channel constant")
    replace(notifications,
'''        manager.createNotificationChannel(NotificationChannel(
            COMPLETE_CHANNEL,
''',
'''        manager.createNotificationChannel(NotificationChannel(
            SEND_CHANNEL,
            "File sending progress",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Shows progress while ClipMesh sends files"
            enableVibration(false)
            setSound(null, null)
        })
        manager.createNotificationChannel(NotificationChannel(
            COMPLETE_CHANNEL,
''', "Android create progress channel")
    replace(notifications,
'''    fun showCompleted(context: Context, sender: String, count: Int) {
''',
'''    fun showSending(context: Context, transferId: String, receiver: String, file: String, percent: Int) {
        ensureChannels(context)
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val open = PendingIntent.getActivity(
            context,
            outgoingId(transferId),
            Intent(context, FileShareActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        manager.notify(
            outgoingId(transferId),
            android.app.Notification.Builder(context, SEND_CHANNEL)
                .setSmallIcon(R.drawable.ic_clipmesh_notification)
                .setContentTitle("Sending to $receiver • $percent%")
                .setContentText(file)
                .setProgress(100, percent.coerceIn(0, 100), false)
                .setContentIntent(open)
                .setOnlyAlertOnce(true)
                .setOngoing(true)
                .build()
        )
    }

    fun cancelSending(context: Context, transferId: String) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancel(outgoingId(transferId))
    }

    fun showAutomaticallySaved(context: Context, sender: String, files: List<String>) {
        ensureChannels(context)
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val summary = if (files.size == 1) files.first() else "${files.size} files"
        val open = PendingIntent.getActivity(
            context,
            9903,
            Intent(context, FileShareActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag()
        )
        manager.notify(
            7333,
            android.app.Notification.Builder(context, COMPLETE_CHANNEL)
                .setSmallIcon(R.drawable.ic_clipmesh_notification)
                .setContentTitle("Saved automatically from $sender")
                .setContentText("$summary saved to Downloads/ClipMesh")
                .setStyle(android.app.Notification.BigTextStyle().bigText("Saved $summary automatically from favorited sender $sender to Downloads/ClipMesh."))
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
        )
    }

    fun showCompleted(context: Context, sender: String, count: Int) {
''', "Android sending and automatic-save notifications")
    replace(notifications,
'''    private fun incomingId(id: String): Int = 0x52000000 xor id.hashCode()
''',
'''    private fun incomingId(id: String): Int = 0x52000000 xor id.hashCode()
    private fun outgoingId(id: String): Int = 0x53000000 xor id.hashCode()
''', "Android outgoing notification id")

elif system == "Darwin":
    transfer = root / "ci/ClipMeshTransfer.swift"
    replace(transfer,
'''    func send(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, completion: @escaping (Result<Void, Error>) -> Void) {
        sendQueue.async {
            do {
                try self.sendSync(files: files, to: device, progress: progress)
''',
'''    func send(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, progressValue: @escaping (Double) -> Void = { _ in }, completion: @escaping (Result<Void, Error>) -> Void) {
        sendQueue.async {
            do {
                try self.sendSync(files: files, to: device, progress: progress, progressValue: progressValue)
''', "macOS public byte-progress callback")
    replace(transfer,
'''    private func sendSync(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void) throws {
''',
'''    private func sendSync(files: [URL], to device: TransferDevice, progress: @escaping (String) -> Void, progressValue: @escaping (Double) -> Void = { _ in }) throws {
''', "macOS synchronous byte-progress callback")
    replace(transfer,
'''        let body: [String: Any] = ["info": info(announce: false), "files": fileObject]
        DispatchQueue.main.async { progress("Waiting for \\(device.alias)…") }
''',
'''        let totalBytes = ids.reduce(Int64(0)) { $0 + $1.2 }
        var completedBytes: Int64 = 0
        let body: [String: Any] = ["info": info(announce: false), "files": fileObject]
        DispatchQueue.main.async { progress("Waiting for \\(device.alias)…"); progressValue(0) }
''', "macOS aggregate progress setup")
    replace(transfer,
'''            DispatchQueue.main.async { progress("Sending \\(item.1.lastPathComponent) • \\(index + 1)/\\(ids.count)") }
            try uploadFile(device: device, sessionID: sessionID, fileID: item.0, token: token, file: item.1, size: item.2)
''',
'''            DispatchQueue.main.async { progress("Sending \\(item.1.lastPathComponent) • \\(index + 1)/\\(ids.count)") }
            try uploadFile(device: device, sessionID: sessionID, fileID: item.0, token: token, file: item.1, size: item.2) { sent in
                let fraction = totalBytes > 0 ? Double(completedBytes + sent) / Double(totalBytes) : 1
                DispatchQueue.main.async { progressValue(min(1, max(0, fraction))) }
            }
            completedBytes += item.2
''', "macOS upload aggregation")
    replace(transfer,
'''    private func uploadFile(device: TransferDevice, sessionID: String, fileID: String, token: String, file: URL, size: Int64) throws {
''',
'''    private func uploadFile(device: TransferDevice, sessionID: String, fileID: String, token: String, file: URL, size: Int64, onProgress: @escaping (Int64) -> Void) throws {
''', "macOS upload progress parameter")
    replace(transfer,
'''        URLSession.shared.uploadTask(with: request, fromFile: file) { _, response, error in
            if let error { output = .failure(error) } else { output = .success((response as? HTTPURLResponse)?.statusCode ?? 0) }
            sem.signal()
        }.resume()
        guard sem.wait(timeout: .now() + 190) == .success, let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \\(file.lastPathComponent)."]) }
''',
'''        let task = URLSession.shared.uploadTask(with: request, fromFile: file) { _, response, error in
            if let error { output = .failure(error) } else { output = .success((response as? HTTPURLResponse)?.statusCode ?? 0) }
            sem.signal()
        }
        task.resume()
        let deadline = Date().addingTimeInterval(190)
        while sem.wait(timeout: .now() + 0.1) == .timedOut {
            onProgress(max(0, task.countOfBytesSent))
            if Date() >= deadline { task.cancel(); throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \\(file.lastPathComponent)."]) }
        }
        onProgress(size)
        guard let output else { throw NSError(domain: "ClipMesh", code: -1001, userInfo: [NSLocalizedDescriptionKey: "Timed out while sending \\(file.lastPathComponent)."]) }
''', "macOS task byte polling")
    replace(transfer,
'''    private var fileLabel: NSTextField?
    private var files: [URL] = []
''',
'''    private var fileLabel: NSTextField?
    private var transferProgress: NSProgressIndicator?
    private var files: [URL] = []
''', "macOS compact progress field")
    replace(transfer,
'''        status = label("Looking on this Wi‑Fi…", 12, .regular); status?.textColor = .secondaryLabelColor; root.addArrangedSubview(status!)
        self.window = window
''',
'''        status = label("Looking on this Wi‑Fi…", 12, .regular); status?.textColor = .secondaryLabelColor; root.addArrangedSubview(status!)
        let bar = NSProgressIndicator(); bar.style = .bar; bar.isIndeterminate = false; bar.minValue = 0; bar.maxValue = 1; bar.doubleValue = 0; bar.isHidden = true
        transferProgress = bar; root.addArrangedSubview(bar); bar.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        self.window = window
''', "macOS compact in-app progress bar")
    replace(transfer,
'''        status?.stringValue = "Connecting to \\(device.alias)…"
        LocalTransferManager.shared.send(files: files, to: device, progress: { [weak self] text in self?.status?.stringValue = text }) { [weak self] result in
            switch result {
            case .success:
                self?.status?.stringValue = "Sent to \\(device.alias)"
            case .failure(let error):
                self?.status?.stringValue = error.localizedDescription
                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)
            }
        }
''',
'''        status?.stringValue = "Connecting to \\(device.alias)…"
        transferProgress?.doubleValue = 0; transferProgress?.isHidden = false
        LocalTransferManager.shared.send(files: files, to: device, progress: { [weak self] text in self?.status?.stringValue = text }, progressValue: { [weak self] value in self?.transferProgress?.doubleValue = value }) { [weak self] result in
            switch result {
            case .success:
                self?.files.removeAll(); self?.refreshFiles()
                self?.transferProgress?.doubleValue = 1; self?.transferProgress?.isHidden = true
                self?.status?.stringValue = "Sent to \\(device.alias)"
            case .failure(let error):
                self?.transferProgress?.isHidden = true
                self?.status?.stringValue = error.localizedDescription
                CMDialog.run(title: "Couldn’t send", message: error.localizedDescription)
            }
        }
''', "macOS progress UI and clear-on-success")

elif system == "Windows":
    transfer = root / "ci/ClipMeshTransfer.cs"
    ui = root / "ci/ClipMeshWindows.cs"
    replace(transfer,
'''    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress)
    {
''',
'''    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress)
    {
        SendFiles(paths, target, progress, null);
    }

    public void SendFiles(IList<string> paths, TransferDeviceC target, Action<string> progress, Action<int> progressValue)
    {
''', "Windows byte-progress overload")
    replace(transfer,
'''        if (files.Count == 0) throw new InvalidOperationException("No readable files were selected.");
        if (progress != null) progress("Waiting for " + target.Alias + "…");
''',
'''        if (files.Count == 0) throw new InvalidOperationException("No readable files were selected.");
        long totalBytes = 0; foreach (string path in byId.Values) totalBytes += new FileInfo(path).Length; long completedBytes = 0;
        if (progress != null) progress("Waiting for " + target.Alias + "…"); if (progressValue != null) progressValue(0);
''', "Windows aggregate progress setup")
    replace(transfer,
'''            if (progress != null) progress("Sending " + Path.GetFileName(item.Value) + " • " + index + "/" + byId.Count);
            Upload(target, sid, item.Key, Convert.ToString(tokenRaw), item.Value);
''',
'''            if (progress != null) progress("Sending " + Path.GetFileName(item.Value) + " • " + index + "/" + byId.Count);
            long before = completedBytes;
            Upload(target, sid, item.Key, Convert.ToString(tokenRaw), item.Value, delegate(long sent) { if (progressValue != null) progressValue(totalBytes <= 0 ? 1000 : (int)Math.Min(1000L, ((before + sent) * 1000L) / totalBytes)); });
            completedBytes += new FileInfo(item.Value).Length;
''', "Windows aggregate upload progress")
    replace(transfer,
'''    private void Upload(TransferDeviceC target, string sid, string fid, string token, string path)
''',
'''    private void Upload(TransferDeviceC target, string sid, string fid, string token, string path, Action<long> onProgress)
''', "Windows upload progress parameter")
    replace(transfer,
'''        using (Stream output = request.GetRequestStream()) using (FileStream input = File.OpenRead(path)) input.CopyTo(output, 131072);
''',
'''        using (Stream output = request.GetRequestStream()) using (FileStream input = File.OpenRead(path)) { byte[] buffer = new byte[131072]; long sent = 0; int read; while ((read = input.Read(buffer, 0, buffer.Length)) > 0) { output.Write(buffer, 0, read); sent += read; if (onProgress != null) onProgress(sent); } output.Flush(); }
''', "Windows streamed upload byte progress")

    replace(transfer,
'''    private readonly Label status;
    private readonly System.Windows.Forms.Timer timer;
''',
'''    private readonly Label status;
    private readonly ProgressBar transferProgress;
    private readonly System.Windows.Forms.Timer timer;
''', "Windows chooser progress field")
    replace(transfer,
'''        status = L("Looking on this Wi-Fi…", 9, FontStyle.Regular, Muted); status.Width = 550; status.Height = 30; status.TextAlign = ContentAlignment.MiddleCenter; root.Controls.Add(status);
''',
'''        status = L("Looking on this Wi-Fi…", 9, FontStyle.Regular, Muted); status.Width = 550; status.Height = 30; status.TextAlign = ContentAlignment.MiddleCenter; root.Controls.Add(status);
        transferProgress = new ProgressBar(); transferProgress.Width = 550; transferProgress.Height = 8; transferProgress.Minimum = 0; transferProgress.Maximum = 1000; transferProgress.Visible = false; root.Controls.Add(transferProgress);
''', "Windows chooser compact progress bar")
    replace(transfer,
'''    private void Send(TransferDeviceC device) { if (files.Count==0) { Choose(); return; } Enabled=false; status.Text="Connecting to "+device.Alias+"…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(files,device,delegate(string s){ if(!IsDisposed) BeginInvoke((Action)(delegate{status.Text=s;}));}); if(!IsDisposed) BeginInvoke((Action)(delegate{Enabled=true; status.Text="Sent to "+device.Alias;})); } catch(Exception ex){ if(!IsDisposed) BeginInvoke((Action)(delegate{Enabled=true; status.Text=ex.Message; ClipMeshDialogC.Show(this,"Couldn’t send",ex.Message,false);})); } }); }
''',
'''    private void Send(TransferDeviceC device) { if (files.Count==0) { Choose(); return; } Enabled=false; transferProgress.Value=0; transferProgress.Visible=true; status.Text="Connecting to "+device.Alias+"…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(new List<string>(files),device,delegate(string s){ if(!IsDisposed) BeginInvoke((Action)(delegate{status.Text=s;}));},delegate(int value){if(!IsDisposed)BeginInvoke((Action)(delegate{transferProgress.Value=Math.Max(0,Math.Min(1000,value));}));}); if(!IsDisposed) BeginInvoke((Action)(delegate{files.Clear();RefreshFiles();Enabled=true;transferProgress.Visible=false;status.Text="Sent to "+device.Alias;})); } catch(Exception ex){ if(!IsDisposed) BeginInvoke((Action)(delegate{Enabled=true;transferProgress.Visible=false;status.Text=ex.Message;ClipMeshDialogC.Show(this,"Couldn’t send",ex.Message,false);})); } }); }
''', "Windows chooser progress and clear-on-success")

    replace(ui,
'''    private readonly Label transferStatus;
    private readonly Panel clipboardPreview;
''',
'''    private readonly Label transferStatus;
    private readonly ProgressBar transferProgress;
    private readonly Panel clipboardPreview;
''', "Windows main progress field")
    replace(ui,
'''        Panel nearbyCard = MakeCard(340); nearbyCard.Width = 650; Label nearby = MakeLabel("NEARBY DEVICES", 8, FontStyle.Bold, Muted); nearby.SetBounds(18, 15, 320, 20); Button rescan = MakeButton("Rescan", false); rescan.SetBounds(536, 10, 95, 38); rescan.Click += delegate { LocalTransferManagerC.Shared.DiscoverNow(); RefreshTransferDevices(); }; nearbyCard.Controls.Add(nearby); nearbyCard.Controls.Add(rescan); Label nhint = MakeLabel("Send directly. Star trusted devices so future incoming files can save automatically.", 9, FontStyle.Regular, Muted); nhint.SetBounds(18, 48, 610, 30); nearbyCard.Controls.Add(nhint); transferDevicePanel = new FlowLayoutPanel(); transferDevicePanel.FlowDirection = FlowDirection.TopDown; transferDevicePanel.WrapContents = false; transferDevicePanel.AutoScroll = true; transferDevicePanel.SetBounds(18, 82, 613, 238); transferDevicePanel.BackColor = Card; nearbyCard.Controls.Add(transferDevicePanel); tf.Controls.Add(nearbyCard); transferStatus = MakeLabel("Looking on this Wi-Fi…", 9, FontStyle.Regular, Muted); transferStatus.Width = 650; transferStatus.Height = 28; transferStatus.TextAlign = ContentAlignment.MiddleCenter; tf.Controls.Add(transferStatus);
''',
'''        Panel nearbyCard = MakeCard(340); nearbyCard.Width = 650; Label nearby = MakeLabel("NEARBY DEVICES", 8, FontStyle.Bold, Muted); nearby.SetBounds(18, 15, 320, 20); Button rescan = MakeButton("Rescan", false); rescan.SetBounds(536, 10, 95, 38); rescan.Click += delegate { LocalTransferManagerC.Shared.DiscoverNow(); RefreshTransferDevices(); }; nearbyCard.Controls.Add(nearby); nearbyCard.Controls.Add(rescan); Label nhint = MakeLabel("Send directly. Star trusted devices so future incoming files can save automatically.", 9, FontStyle.Regular, Muted); nhint.SetBounds(18, 48, 610, 30); nearbyCard.Controls.Add(nhint); transferDevicePanel = new FlowLayoutPanel(); transferDevicePanel.FlowDirection = FlowDirection.TopDown; transferDevicePanel.WrapContents = false; transferDevicePanel.AutoScroll = true; transferDevicePanel.SetBounds(18, 82, 613, 238); transferDevicePanel.BackColor = Card; nearbyCard.Controls.Add(transferDevicePanel); tf.Controls.Add(nearbyCard); transferStatus = MakeLabel("Looking on this Wi-Fi…", 9, FontStyle.Regular, Muted); transferStatus.Width = 650; transferStatus.Height = 28; transferStatus.TextAlign = ContentAlignment.MiddleCenter; tf.Controls.Add(transferStatus); transferProgress = new ProgressBar(); transferProgress.Width = 650; transferProgress.Height = 8; transferProgress.Minimum = 0; transferProgress.Maximum = 1000; transferProgress.Visible = false; tf.Controls.Add(transferProgress);
''', "Windows main compact progress bar")
    replace(ui,
'''    private void SendTransfer(TransferDeviceC device) { if (transferFiles.Count == 0) { ChooseTransferFiles(); return; } transferStatus.Text = "Connecting to " + device.Alias + "…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(transferFiles, device, delegate(string text) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = text; })); }); if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = "Sent to " + device.Alias; })); } catch (Exception ex) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = ex.Message; ClipMeshDialogC.Show(this, "Couldn’t send", ex.Message, false); })); } }); }
''',
'''    private void SendTransfer(TransferDeviceC device) { if (transferFiles.Count == 0) { ChooseTransferFiles(); return; } transferProgress.Value = 0; transferProgress.Visible = true; transferStatus.Text = "Connecting to " + device.Alias + "…"; Task.Run(delegate { try { LocalTransferManagerC.Shared.SendFiles(new List<string>(transferFiles), device, delegate(string text) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferStatus.Text = text; })); }, delegate(int value) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferProgress.Value = Math.Max(0, Math.Min(1000, value)); })); }); if (!IsDisposed) BeginInvoke((Action)(delegate { transferFiles.Clear(); UpdateTransferFiles(); transferProgress.Visible = false; transferStatus.Text = "Sent to " + device.Alias; })); } catch (Exception ex) { if (!IsDisposed) BeginInvoke((Action)(delegate { transferProgress.Visible = false; transferStatus.Text = ex.Message; ClipMeshDialogC.Show(this, "Couldn’t send", ex.Message, false); })); } }); }
''', "Windows main progress and clear-on-success")

else:
    raise SystemExit(f"unsupported platform: {system}")

print(f"Applied ClipMesh v047 file-transfer progress and success UX on {system}")
