from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Peer liveness: signed UDP discovery means "trusted device exists on LAN";
# it does NOT mean the encrypted TCP clipboard channel is connected. Preserve
# discovery metadata without refreshing last_seen. Only authenticated traffic
# is allowed to mark a peer online.
# ---------------------------------------------------------------------------
rust_config = project / "apps/desktop/src/config.rs"
replace_once(
    rust_config,
    '''    pub fn remember_peer(
        space_id: Uuid,
        device_id: Uuid,
        name: &str,
        address: &str,
        port: u16,
    ) -> Result<()> {
        let mut peers = Self::load_known_peers(space_id)?;
        let now = now_ms();
        let safe_name = peer_name(name, device_id);
        if let Some(peer) = peers.iter_mut().find(|p| p.device_id == device_id) {
            peer.name = safe_name;
            peer.address = address.trim().chars().take(128).collect();
            peer.port = port;
            peer.last_seen_ms = now;
        } else {
            peers.push(KnownPeer {
                device_id,
                name: safe_name,
                address: address.trim().chars().take(128).collect(),
                port,
                last_seen_ms: now,
            });
        }
        Self::save_known_peers(space_id, peers)
    }
''',
    '''    pub fn remember_peer(
        space_id: Uuid,
        device_id: Uuid,
        name: &str,
        address: &str,
        port: u16,
    ) -> Result<()> {
        let mut peers = Self::load_known_peers(space_id)?;
        let safe_name = peer_name(name, device_id);
        if let Some(peer) = peers.iter_mut().find(|p| p.device_id == device_id) {
            peer.name = safe_name;
            peer.address = address.trim().chars().take(128).collect();
            peer.port = port;
            // Discovery alone must never mark a peer online.
        } else {
            peers.push(KnownPeer {
                device_id,
                name: safe_name,
                address: address.trim().chars().take(128).collect(),
                port,
                last_seen_ms: 0,
            });
        }
        Self::save_known_peers(space_id, peers)
    }
''',
    "desktop discovery must not mark peer online",
)

android_settings = project / "android/app/src/main/java/dev/clipmesh/SettingsStore.kt"
replace_once(
    android_settings,
    '''    @Synchronized
    fun rememberPeer(deviceId: UUID, name: String?, address: String, port: Int) {
        val peers = parseKnownPeers().toMutableList()
        val safeName = peerName(name, deviceId)
        val safeAddress = address.trim().take(128)
        val now = System.currentTimeMillis()
        val index = peers.indexOfFirst { it.deviceId == deviceId }
        val peer = KnownPeer(deviceId, safeName, safeAddress, port.coerceIn(0, 65535), now)
        if (index >= 0) peers[index] = peer else peers += peer
        saveKnownPeers(peers)
    }
''',
    '''    @Synchronized
    fun rememberPeer(deviceId: UUID, name: String?, address: String, port: Int) {
        val peers = parseKnownPeers().toMutableList()
        val safeName = peerName(name, deviceId)
        val safeAddress = address.trim().take(128)
        val index = peers.indexOfFirst { it.deviceId == deviceId }
        if (index >= 0) {
            val old = peers[index]
            peers[index] = old.copy(
                name = safeName,
                address = safeAddress,
                port = port.coerceIn(0, 65535)
            )
        } else {
            peers += KnownPeer(deviceId, safeName, safeAddress, port.coerceIn(0, 65535), 0L)
        }
        saveKnownPeers(peers)
    }
''',
    "Android discovery must not mark peer online",
)


# ---------------------------------------------------------------------------
# Transport connection policy.
# v0.1.4 picked exactly one initiator from the random device UUIDs. That prevents
# duplicate races, but it also makes connectivity depend on that chosen direction.
# If (for example) macOS blocks the chosen incoming direction, no clipboard TCP
# channel is ever created even though UDP discovery works.
#
# v0.1.5 keeps the preferred direction for a race-free fast path, but the other
# device retries in the reverse direction after 2.5 s if no authenticated peer
# exists. The first authenticated connection wins. This retains deterministic
# normal operation while surviving asymmetric host firewalls / OEM networking.
# ---------------------------------------------------------------------------
android_network = project / "android/app/src/main/java/dev/clipmesh/network/NetworkEngine.kt"
replace_once(
    android_network,
    '''                    if (peers.containsKey(d.deviceId)) continue
                    if (shouldInitiate(settings.deviceId, d.deviceId)) {
                        scope.launch { connect(packet.address, d.port) }
                    }
''',
    '''                    if (peers.containsKey(d.deviceId)) continue
                    val preferred = shouldInitiate(settings.deviceId, d.deviceId)
                    scope.launch {
                        if (!preferred) {
                            delay(2_500L)
                            if (peers.containsKey(d.deviceId)) return@launch
                        }
                        connect(packet.address, d.port)
                    }
''',
    "Android preferred connection with reverse fallback",
)
replace_once(
    android_network,
    '''            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())
            val preferredOutgoing = shouldInitiate(settings.deviceId, peerId)
            if (outgoing != preferredOutgoing) {
                socket.close()
                return@withContext
            }

            val connection = PeerConnection(UUID.randomUUID(), peerId, socket.inetAddress, socket, output)
            val prior = peers.put(peerId, connection)
            prior?.close()
            onStatus("Connected peers: ${peers.size}")
''',
    '''            val connection = PeerConnection(UUID.randomUUID(), peerId, socket.inetAddress, socket, output)
            val accepted = synchronized(peers) {
                if (peers.containsKey(peerId)) {
                    false
                } else {
                    peers[peerId] = connection
                    true
                }
            }
            if (!accepted) {
                connection.close()
                return@withContext
            }
            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())
            onStatus("Connected peers: ${peers.size}")
''',
    "Android first authenticated connection wins",
)
replace_once(
    android_network,
    '''                    val frame = Crypto.decryptFrame(masterKey, requireNotNull(settings.spaceId), bytes)
                    if (frame.sender != peerId) throw SecurityException("authenticated peer/sender mismatch")
                    when (frame.kind) {
''',
    '''                    val frame = Crypto.decryptFrame(masterKey, requireNotNull(settings.spaceId), bytes)
                    if (frame.sender != peerId) throw SecurityException("authenticated peer/sender mismatch")
                    settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())
                    when (frame.kind) {
''',
    "Android authenticated traffic refreshes liveness",
)

rust_network = project / "apps/desktop/src/network.rs"
replace_once(
    rust_network,
    "use dashmap::DashMap;",
    "use dashmap::{mapref::entry::Entry, DashMap};",
    "desktop DashMap entry import",
)
replace_once(
    rust_network,
    '''                if peers.contains_key(&packet.device_id) { continue; }
                if cfg.device_id.as_bytes() >= packet.device_id.as_bytes() { continue; }
                let target=SocketAddr::new(addr.ip(),packet.port);
                let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone(); let pending=pending.clone(); let seen=seen.clone(); let latest=latest.clone(); let remote=remote.clone();
                tokio::spawn(async move {
                    if let Ok(Ok(stream))=time::timeout(Duration::from_secs(2),TcpStream::connect(target)).await {
                        if let Err(e)=handle_connection(stream,true,cfg,master,peers,pending,seen,latest,remote).await { debug!(peer=%target,error=%e,"outgoing peer ended"); }
                    }
                });
''',
    '''                if peers.contains_key(&packet.device_id) { continue; }
                let peer_id=packet.device_id;
                let preferred=cfg.device_id.as_bytes() < peer_id.as_bytes();
                let target=SocketAddr::new(addr.ip(),packet.port);
                let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone(); let pending=pending.clone(); let seen=seen.clone(); let latest=latest.clone(); let remote=remote.clone();
                tokio::spawn(async move {
                    if !preferred {
                        time::sleep(Duration::from_millis(2_500)).await;
                        if peers.contains_key(&peer_id) { return; }
                    }
                    if let Ok(Ok(stream))=time::timeout(Duration::from_secs(2),TcpStream::connect(target)).await {
                        if let Err(e)=handle_connection(stream,true,cfg,master,peers,pending,seen,latest,remote).await { debug!(peer=%target,error=%e,"outgoing peer ended"); }
                    }
                });
''',
    "desktop preferred connection with reverse fallback",
)
replace_once(
    rust_network,
    '''    let peer_id=remote_hello.device_id;
    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());
    let preferred_outgoing = cfg.device_id.as_bytes() < peer_id.as_bytes();
    if outgoing != preferred_outgoing {
        debug!(peer=%peer_id,addr=%peer_addr,"closing non-preferred duplicate connection");
        return Ok(());
    }
    info!(peer=%peer_id,addr=%peer_addr,"peer authenticated");

    let (read_half,mut write_half)=stream.into_split();
    let (tx,mut rx)=mpsc::unbounded_channel::<Vec<u8>>();
    let conn_id=Uuid::new_v4();
    peers.insert(peer_id,PeerEntry{connection_id:conn_id,tx:tx.clone()});
''',
    '''    let peer_id=remote_hello.device_id;
    info!(peer=%peer_id,addr=%peer_addr,"peer authenticated");

    let (read_half,mut write_half)=stream.into_split();
    let (tx,mut rx)=mpsc::unbounded_channel::<Vec<u8>>();
    let conn_id=Uuid::new_v4();
    match peers.entry(peer_id) {
        Entry::Occupied(_) => {
            debug!(peer=%peer_id,addr=%peer_addr,"closing duplicate authenticated connection");
            return Ok(());
        }
        Entry::Vacant(entry) => {
            entry.insert(PeerEntry{connection_id:conn_id,tx:tx.clone()});
        }
    }
    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());
''',
    "desktop first authenticated connection wins",
)
replace_once(
    rust_network,
    '''        let frame=decrypt_frame(&master,cfg.space_id,&data,true)?;
        if frame.sender_id!=peer_id { bail!("sender ID differs from authenticated peer"); }
        match frame.kind {
''',
    '''        let frame=decrypt_frame(&master,cfg.space_id,&data,true)?;
        if frame.sender_id!=peer_id { bail!("sender ID differs from authenticated peer"); }
        let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());
        match frame.kind {
''',
    "desktop authenticated traffic refreshes liveness",
)


# ---------------------------------------------------------------------------
# Clipboard format interoperability.
# Android v0.1.4 emitted text/plain;charset=utf-8 while desktop only accepted
# text/plain; charset=utf-8. Normalize Android output and make desktop MIME
# matching tolerant of parameters/casing.
# ---------------------------------------------------------------------------
android_bridge = project / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
bridge_text = android_bridge.read_text(encoding="utf-8")
count = bridge_text.count('Representation("text/plain;charset=utf-8"')
if count != 2:
    raise SystemExit(f"Android text MIME normalization: expected 2 matches, found {count}")
android_bridge.write_text(
    bridge_text.replace('Representation("text/plain;charset=utf-8"', 'Representation("text/plain; charset=utf-8"'),
    encoding="utf-8",
)

rust_clipboard = project / "apps/desktop/src/clipboard.rs"
replace_once(
    rust_clipboard,
    '''        match rep.mime.as_str() {
            "text/plain; charset=utf-8" | "text/plain" => contents.push(ClipboardContent::Text(String::from_utf8(bytes)?)),
            "text/html; charset=utf-8" | "text/html" => contents.push(ClipboardContent::Html(String::from_utf8(bytes)?)),
            "text/rtf" => contents.push(ClipboardContent::Rtf(String::from_utf8(bytes)?)),
            "image/png" => {
                let img=RustImageData::from_bytes(&bytes).map_err(|e| anyhow::anyhow!(e.to_string()))?;
                contents.push(ClipboardContent::Image(img));
            }
            _ => {}
        }
''',
    '''        let mime=rep.mime.to_ascii_lowercase();
        if mime.starts_with("text/plain") {
            contents.push(ClipboardContent::Text(String::from_utf8(bytes)?));
        } else if mime.starts_with("text/html") {
            contents.push(ClipboardContent::Html(String::from_utf8(bytes)?));
        } else if mime.starts_with("text/rtf") {
            contents.push(ClipboardContent::Rtf(String::from_utf8(bytes)?));
        } else if mime == "image/png" {
            let img=RustImageData::from_bytes(&bytes).map_err(|e| anyhow::anyhow!(e.to_string()))?;
            contents.push(ClipboardContent::Image(img));
        }
''',
    "desktop tolerant MIME receive",
)


# ---------------------------------------------------------------------------
# macOS clipboard reliability.
# Keep clipboard-rs' native watcher, but add a macOS-only 350 ms change fallback.
# The fallback is content-fingerprint deduplicated, sleeps while idle, performs no
# network work until content actually changes, and prevents watcher/poller doubles.
# ---------------------------------------------------------------------------
replace_once(
    rust_clipboard,
    '''pub struct ClipboardState {
    suppressed: Mutex<Option<[u8; 32]>>,
}

impl ClipboardState {
    pub fn new() -> Self { Self { suppressed: Mutex::new(None) } }
    pub fn suppress(&self, fingerprint: [u8; 32]) { *self.suppressed.lock()=Some(fingerprint); }
    fn consume_if_suppressed(&self, fingerprint: &[u8; 32]) -> bool {
        let mut guard=self.suppressed.lock();
        if guard.as_ref()==Some(fingerprint) { *guard=None; true } else { false }
    }
}
''',
    '''pub struct ClipboardState {
    suppressed: Mutex<Option<[u8; 32]>>,
    last_observed: Mutex<Option<[u8; 32]>>,
}

impl ClipboardState {
    pub fn new() -> Self {
        Self { suppressed: Mutex::new(None), last_observed: Mutex::new(None) }
    }
    pub fn seed(&self, fingerprint: [u8; 32]) {
        *self.last_observed.lock()=Some(fingerprint);
    }
    pub fn suppress(&self, fingerprint: [u8; 32]) {
        *self.suppressed.lock()=Some(fingerprint);
        *self.last_observed.lock()=Some(fingerprint);
    }
    fn should_emit(&self, fingerprint: &[u8; 32]) -> bool {
        {
            let mut last=self.last_observed.lock();
            if last.as_ref()==Some(fingerprint) { return false; }
            *last=Some(*fingerprint);
        }
        let mut suppressed=self.suppressed.lock();
        if suppressed.as_ref()==Some(fingerprint) {
            *suppressed=None;
            return false;
        }
        true
    }
}
''',
    "desktop clipboard dedupe state",
)
replace_once(
    rust_clipboard,
    '''                match payload.stable_fingerprint() {
                    Ok(fp) if self.state.consume_if_suppressed(&fp) => {
                        debug!("suppressed remote clipboard echo");
                    }
                    Ok(_) => { let _=self.tx.send(payload); }
                    Err(e) => warn!(error=%e, "could not fingerprint clipboard"),
                }
''',
    '''                match payload.stable_fingerprint() {
                    Ok(fp) if self.state.should_emit(&fp) => { let _=self.tx.send(payload); }
                    Ok(_) => debug!("ignored unchanged/suppressed clipboard"),
                    Err(e) => warn!(error=%e, "could not fingerprint clipboard"),
                }
''',
    "desktop watcher dedupe",
)
replace_once(
    rust_clipboard,
    '''pub fn spawn_watcher(cfg: Config, state: Arc<ClipboardState>, tx: mpsc::UnboundedSender<ClipPayload>) -> Result<()> {
    let ctx=ClipboardContext::new().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    let handler=Handler{ctx,cfg,state,tx};
    let mut watcher=ClipboardWatcherContext::new().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    watcher.add_handler(handler);
    std::thread::Builder::new().name("clipmesh-clipboard-watch".into()).spawn(move || {
        watcher.start_watch();
    })?;
    Ok(())
}
''',
    '''pub fn spawn_watcher(cfg: Config, state: Arc<ClipboardState>, tx: mpsc::UnboundedSender<ClipPayload>) -> Result<()> {
    let ctx=ClipboardContext::new().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    if let Ok(Some(payload))=read_payload(&ctx,&cfg) {
        if let Ok(fp)=payload.stable_fingerprint() { state.seed(fp); }
    }
    let handler=Handler{ctx,cfg:cfg.clone(),state:state.clone(),tx:tx.clone()};
    let mut watcher=ClipboardWatcherContext::new().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    watcher.add_handler(handler);
    std::thread::Builder::new().name("clipmesh-clipboard-watch".into()).spawn(move || {
        watcher.start_watch();
    })?;

    #[cfg(target_os="macos")]
    {
        let poll_cfg=cfg.clone();
        let poll_state=state.clone();
        let poll_tx=tx.clone();
        std::thread::Builder::new().name("clipmesh-macos-pasteboard-fallback".into()).spawn(move || {
            let Ok(ctx)=ClipboardContext::new() else { return; };
            loop {
                std::thread::sleep(std::time::Duration::from_millis(350));
                match read_payload(&ctx,&poll_cfg) {
                    Ok(Some(payload)) => match payload.stable_fingerprint() {
                        Ok(fp) if poll_state.should_emit(&fp) => { let _=poll_tx.send(payload); }
                        Ok(_) => {}
                        Err(e) => debug!(error=%e,"macOS pasteboard fallback fingerprint failed"),
                    },
                    Ok(None) => {}
                    Err(e) => debug!(error=%e,"macOS pasteboard fallback read failed"),
                }
            }
        })?;
    }
    Ok(())
}
''',
    "macOS clipboard change fallback",
)


# ---------------------------------------------------------------------------
# Android foreground + Accessibility fallback.
# - Returning to ClipMesh after copying causes one immediate foreground capture,
#   so foreground testing does not depend on Shizuku.
# - If the optional Accessibility service is enabled, its clipboard-change listener
#   triggers capture event-by-event. This adds no polling/battery loop and provides a
#   Shizuku-free background TEXT fallback on devices where Android grants clipboard
#   access to the accessibility service UID.
# ---------------------------------------------------------------------------
replace_once(
    android_bridge,
    "    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)\n    fun captureNowForBackgroundMonitor() = captureAsync(fromWatchdog = true)",
    "    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)\n    fun captureNowForBackgroundMonitor() = captureAsync(fromWatchdog = true)\n    fun captureNowForForeground() = captureAsync(fromWatchdog = true)\n    fun captureNowForAccessibility() = captureAsync(fromWatchdog = true)",
    "Android explicit clipboard capture entry points",
)
replace_once(
    android_bridge,
    '''    fun start() {
        if (started) return
        started = true
        main.post { clipboard.addPrimaryClipChangedListener(listener) }
    }
''',
    '''    fun start() {
        if (started) return
        started = true
        ForegroundTracker.clipboardChanged = { captureNowForAccessibility() }
        main.post { clipboard.addPrimaryClipChangedListener(listener) }
    }
''',
    "Android Accessibility clipboard event hook",
)
replace_once(
    android_bridge,
    '''    fun stop() {
        if (!started) return
        started = false
        main.post { clipboard.removePrimaryClipChangedListener(listener) }
        captureExecutor.shutdownNow()
    }
''',
    '''    fun stop() {
        if (!started) return
        started = false
        ForegroundTracker.clipboardChanged = null
        main.post { clipboard.removePrimaryClipChangedListener(listener) }
        captureExecutor.shutdownNow()
    }
''',
    "Android Accessibility clipboard event cleanup",
)

foreground_tracker = project / "android/app/src/main/java/dev/clipmesh/exclusion/ForegroundTracker.kt"
replace_once(
    foreground_tracker,
    '''object ForegroundTracker {
    @Volatile var currentPackage: String? = null
}
''',
    '''object ForegroundTracker {
    @Volatile var currentPackage: String? = null
    @Volatile var clipboardChanged: (() -> Unit)? = null
}
''',
    "Accessibility clipboard event bus",
)

access_service = project / "android/app/src/main/java/dev/clipmesh/exclusion/ExclusionAccessibilityService.kt"
replace_once(
    access_service,
    '''package dev.clipmesh.exclusion

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent

/**
 * Privacy-minimized helper used only for source-app exclusions.
 * The service configuration explicitly disables window-content retrieval.
 */
class ExclusionAccessibilityService : AccessibilityService() {
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val pkg = event?.packageName?.toString()
        if (!pkg.isNullOrBlank()) ForegroundTracker.currentPackage = pkg
    }
    override fun onInterrupt() = Unit
}
''',
    '''package dev.clipmesh.exclusion

import android.accessibilityservice.AccessibilityService
import android.content.ClipboardManager
import android.view.accessibility.AccessibilityEvent

/**
 * Privacy-minimized helper for source-app exclusions and an event-driven clipboard
 * fallback. It never retrieves window content. Clipboard change callbacks are used
 * only as a wake signal; ClipMesh still applies its exclusion and send settings.
 */
class ExclusionAccessibilityService : AccessibilityService() {
    private var clipboard: ClipboardManager? = null
    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        ForegroundTracker.clipboardChanged?.invoke()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        clipboard = getSystemService(ClipboardManager::class.java)
        clipboard?.addPrimaryClipChangedListener(clipboardListener)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val pkg = event?.packageName?.toString()
        if (!pkg.isNullOrBlank()) ForegroundTracker.currentPackage = pkg
    }

    override fun onDestroy() {
        clipboard?.removePrimaryClipChangedListener(clipboardListener)
        clipboard = null
        super.onDestroy()
    }

    override fun onInterrupt() = Unit
}
''',
    "Accessibility event-driven clipboard fallback",
)

sync_service = project / "android/app/src/main/java/dev/clipmesh/SyncService.kt"
replace_once(
    sync_service,
    '''        const val ACTION_STOP = "dev.clipmesh.STOP"
        private const val CHANNEL_ID = "clipmesh_sync"
''',
    '''        const val ACTION_STOP = "dev.clipmesh.STOP"
        const val ACTION_CAPTURE_CURRENT = "dev.clipmesh.CAPTURE_CURRENT"
        private const val CHANNEL_ID = "clipmesh_sync"
''',
    "Android foreground capture service action",
)
replace_once(
    sync_service,
    '''        if (intent?.action == ACTION_STOP) {
            settings.backgroundSync = false
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
''',
    '''        if (intent?.action == ACTION_STOP) {
            settings.backgroundSync = false
            stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.action == ACTION_CAPTURE_CURRENT) {
            clipboard?.captureNowForForeground()
            return START_STICKY
        }
        return START_STICKY
''',
    "Android foreground capture dispatch",
)

main_activity = project / "android/app/src/main/java/dev/clipmesh/MainActivity.kt"
replace_once(
    main_activity,
    '''    override fun onResume() {
        super.onResume()
        if (::status.isInitialized) refreshHome()
    }
''',
    '''    override fun onResume() {
        super.onResume()
        if (::status.isInitialized) refreshHome()
        if (settings.backgroundSync && settings.spaceId != null && secrets.loadSpaceKey() != null) {
            window.decorView.postDelayed({
                runCatching {
                    startService(Intent(this, SyncService::class.java).setAction(SyncService.ACTION_CAPTURE_CURRENT))
                }
            }, 250L)
        }
    }
''',
    "Android foreground resume clipboard capture",
)


# ---------------------------------------------------------------------------
# Add a real bidirectional TCP transport test inside the desktop network module.
# This exercises the same authenticated hello, AES-GCM frame, length prefix, ACK,
# and remote payload path used by the app rather than only testing crypto helpers.
# ---------------------------------------------------------------------------
network_text = rust_network.read_text(encoding="utf-8")
if "bidirectional_authenticated_transport_roundtrip" in network_text:
    raise SystemExit("desktop transport integration test already present")
network_text += r'''

#[cfg(test)]
mod transport_tests {
    use super::*;
    use clipmesh_core::Representation;
    use tokio::sync::mpsc;

    fn empty_maps() -> (PeerMap, Pending, Seen, Latest) {
        (
            Arc::new(DashMap::new()),
            Arc::new(DashMap::new()),
            Arc::new(parking_lot::Mutex::new(HashMap::new())),
            Arc::new(parking_lot::Mutex::new(None)),
        )
    }

    #[tokio::test]
    async fn bidirectional_authenticated_transport_roundtrip() {
        let master=Arc::new(MasterKey::generate());
        let space=Uuid::new_v4();
        let mut a=Config::new("A".into());
        let mut b=Config::new("B".into());
        a.space_id=space;
        b.space_id=space;
        a.device_id=Uuid::parse_str("11111111-1111-4111-8111-111111111111").unwrap();
        b.device_id=Uuid::parse_str("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee").unwrap();
        let a=Arc::new(a);
        let b=Arc::new(b);
        let (a_peers,a_pending,a_seen,a_latest)=empty_maps();
        let (b_peers,b_pending,b_seen,b_latest)=empty_maps();
        let (a_remote_tx,mut a_remote_rx)=mpsc::unbounded_channel();
        let (b_remote_tx,mut b_remote_rx)=mpsc::unbounded_channel();

        let listener=TcpListener::bind((Ipv4Addr::LOCALHOST,0)).await.unwrap();
        let addr=listener.local_addr().unwrap();
        let b_task={
            let b=b.clone(); let master=master.clone(); let peers=b_peers.clone();
            tokio::spawn(async move {
                let (stream,_)=listener.accept().await.unwrap();
                handle_connection(stream,false,b,master,peers,b_pending,b_seen,b_latest,b_remote_tx).await.unwrap();
            })
        };
        let a_task={
            let a=a.clone(); let master=master.clone(); let peers=a_peers.clone();
            tokio::spawn(async move {
                let stream=TcpStream::connect(addr).await.unwrap();
                handle_connection(stream,true,a,master,peers,a_pending,a_seen,a_latest,a_remote_tx).await.unwrap();
            })
        };

        time::timeout(Duration::from_secs(2),async {
            loop {
                if a_peers.contains_key(&b.device_id) && b_peers.contains_key(&a.device_id) { break; }
                time::sleep(Duration::from_millis(10)).await;
            }
        }).await.unwrap();

        let mut p=ClipPayload::new();
        p.representations.push(Representation::from_bytes("text/plain; charset=utf-8",b"from-a"));
        let msg=Uuid::new_v4();
        let frame=encrypt_frame(&master,space,a.device_id,msg,FrameKind::Clipboard,0,&p.to_json_bytes(a.max_payload_bytes).unwrap()).unwrap();
        a_peers.get(&b.device_id).unwrap().tx.send(frame).unwrap();
        let (_,got)=time::timeout(Duration::from_secs(2),b_remote_rx.recv()).await.unwrap().unwrap();
        assert_eq!(got.representations[0].bytes().unwrap(),b"from-a");

        let mut p=ClipPayload::new();
        p.representations.push(Representation::from_bytes("text/plain;charset=utf-8",b"from-b"));
        let msg=Uuid::new_v4();
        let frame=encrypt_frame(&master,space,b.device_id,msg,FrameKind::Clipboard,0,&p.to_json_bytes(b.max_payload_bytes).unwrap()).unwrap();
        b_peers.get(&a.device_id).unwrap().tx.send(frame).unwrap();
        let (_,got)=time::timeout(Duration::from_secs(2),a_remote_rx.recv()).await.unwrap().unwrap();
        assert_eq!(got.representations[0].bytes().unwrap(),b"from-b");

        a_task.abort();
        b_task.abort();
    }
}
'''
rust_network.write_text(network_text,encoding="utf-8")

print("Applied ClipMesh v0.1.5 foreground sync, transport fallback, macOS watcher, MIME, and Accessibility fixes")
