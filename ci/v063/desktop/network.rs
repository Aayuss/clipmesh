//! Push-only peer transport (v063).
//!
//! Idle costs nothing: a listening TCP socket and a UDP socket, no timers, no
//! pings, no periodic broadcasts. A copy dials each paired peer at its last known
//! LAN address (a unicast connect also wakes a sleeping phone), the connection
//! replays the latest clip, the peer ACKs, and the link closes after a short
//! linger. If an address went stale, one discovery broadcast re-learns it.
use crate::config::{Config, DISCOVERY_PORT};
use anyhow::{bail, Context, Result};
use clipmesh_core::{
    decrypt_frame, encrypt_frame, ClipPayload, DiscoveryPacket, FrameKind, Hello, MasterKey,
    MAX_FRAME_BYTES,
};
use dashmap::{mapref::entry::Entry, DashMap};
use std::{
    collections::HashMap,
    net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr},
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream, UdpSocket},
    sync::mpsc,
    time,
};
use tracing::{debug, info, warn};
use uuid::Uuid;

#[derive(Clone)]
struct PeerEntry {
    connection_id: Uuid,
    tx: mpsc::UnboundedSender<Vec<u8>>,
    created: Instant,
    kill: Arc<tokio::sync::Notify>,
}

/// Connections younger than this are treated as a simultaneous-connect duplicate.
const PEER_REPLACE_AFTER: Duration = Duration::from_secs(10);

type PeerMap = Arc<DashMap<Uuid, PeerEntry>>;
type Pending = Arc<DashMap<(Uuid, Uuid), ()>>;
type Seen = Arc<parking_lot::Mutex<HashMap<Uuid, Instant>>>;
type Latest = Arc<parking_lot::Mutex<Option<(Instant, Uuid, Vec<u8>)>>>;

pub async fn run(
    cfg: Config,
    master: MasterKey,
    mut local_clip_rx: mpsc::UnboundedReceiver<ClipPayload>,
    remote_clip_tx: mpsc::UnboundedSender<(Uuid, ClipPayload)>,
) -> Result<()> {
    let cfg=Arc::new(cfg);
    let master=Arc::new(master);
    let peers: PeerMap=Arc::new(DashMap::new());
    let pending: Pending=Arc::new(DashMap::new());
    let seen: Seen=Arc::new(parking_lot::Mutex::new(HashMap::new()));
    let latest: Latest=Arc::new(parking_lot::Mutex::new(None));

    let listener=TcpListener::bind((Ipv4Addr::UNSPECIFIED,cfg.tcp_port)).await
        .with_context(|| format!("bind TCP {}",cfg.tcp_port))?;
    info!(port=cfg.tcp_port,"peer listener ready");

    {
        let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone(); let pending=pending.clone(); let seen=seen.clone(); let latest=latest.clone(); let remote=remote_clip_tx.clone();
        tokio::spawn(async move {
            loop {
                match listener.accept().await {
                    Ok((stream,addr)) if is_lan_ip(addr.ip()) => {
                        let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone(); let pending=pending.clone(); let seen=seen.clone(); let latest=latest.clone(); let remote=remote.clone();
                        tokio::spawn(async move {
                            if let Err(e)=handle_connection(stream,false,cfg,master,peers,pending,seen,latest,remote).await { debug!(peer=%addr,error=%e,"incoming peer ended"); }
                        });
                    }
                    Ok((_stream,addr)) => warn!(peer=%addr,"rejected non-LAN incoming peer"),
                    Err(e) => { warn!(error=%e,"TCP accept failed"); time::sleep(Duration::from_secs(1)).await; }
                }
            }
        });
    }

    let net=Arc::new(Net{
        cfg:cfg.clone(),master:master.clone(),peers:peers.clone(),pending:pending.clone(),seen:seen.clone(),latest:latest.clone(),remote:remote_clip_tx.clone(),
        discovery:Arc::new(UdpSocket::bind((Ipv4Addr::UNSPECIFIED,DISCOVERY_PORT)).await?),
        dialing:Arc::new(DashMap::new()),replied:Arc::new(DashMap::new()),last_broadcast:Arc::new(parking_lot::Mutex::new(None)),
    });
    net.discovery.set_broadcast(true)?;
    spawn_discovery_listener(net.clone());
    // Announce once at start so peers learn our current address; never periodically.
    net.broadcast();

    while let Some(payload)=local_clip_rx.recv().await {
        let bytes=match payload.to_json_bytes(cfg.max_payload_bytes) { Ok(v)=>v, Err(e)=>{warn!(error=%e,"clipboard payload rejected");continue;} };
        let msg_id=Uuid::new_v4();
        let frame=match encrypt_frame(&master,cfg.space_id,cfg.device_id,msg_id,FrameKind::Clipboard,0,&bytes) { Ok(v)=>v,Err(e)=>{warn!(error=%e,"encrypt failed");continue;} };
        *latest.lock()=Some((Instant::now(),msg_id,frame.clone()));
        for peer in peers.iter() {
            let peer_id=*peer.key();
            if peer.tx.send(frame.clone()).is_ok() {
                pending.insert((peer_id,msg_id),());
                spawn_retry(peer_id,msg_id,frame.clone(),peer.tx.clone(),pending.clone());
            }
        }
        // Paired peers without a live link: dial them now; the new connection
        // replays this latest frame and the peer ACKs it.
        net.dial_known_peers();
    }
    Ok(())
}

fn spawn_retry(peer_id:Uuid,msg_id:Uuid,frame:Vec<u8>,tx:mpsc::UnboundedSender<Vec<u8>>,pending:Pending) {
    tokio::spawn(async move {
        let delays=[750u64,1500,3000];
        for ms in delays {
            time::sleep(Duration::from_millis(ms)).await;
            if !pending.contains_key(&(peer_id,msg_id)) { return; }
            if tx.send(frame.clone()).is_err() { break; }
        }
        pending.remove(&(peer_id,msg_id));
    });
}

/// Shared transport state for dialing and discovery.
struct Net {
    cfg:Arc<Config>,
    master:Arc<MasterKey>,
    peers:PeerMap,
    pending:Pending,
    seen:Seen,
    latest:Latest,
    remote:mpsc::UnboundedSender<(Uuid,ClipPayload)>,
    discovery:Arc<UdpSocket>,
    /// Targets with a connect in flight, so repeated copies don't stack dials.
    dialing:Arc<DashMap<SocketAddr,()>>,
    /// Last unicast discovery reply per peer (rate limit).
    replied:Arc<DashMap<Uuid,Instant>>,
    last_broadcast:Arc<parking_lot::Mutex<Option<Instant>>>,
}

/// Unused links close after this long. Reconnecting costs one connect + hello.
const LINK_LINGER:Duration=Duration::from_secs(45);

impl Net {
    fn latest_is_fresh(&self)->bool {
        self.latest.lock().as_ref().map(|(created,_,_)|created.elapsed()<Duration::from_secs(30)).unwrap_or(false)
    }

    /// One signed discovery broadcast, at most every 5s.
    fn broadcast(&self) {
        {
            let mut last=self.last_broadcast.lock();
            if last.map(|t|t.elapsed()<Duration::from_secs(5)).unwrap_or(false) { return; }
            *last=Some(Instant::now());
        }
        if let Ok(packet)=DiscoveryPacket::signed(&self.master,self.cfg.space_id,self.cfg.device_id,self.cfg.device_name.clone(),self.cfg.tcp_port) {
            if let Ok(data)=serde_json::to_vec(&packet) {
                let socket=self.discovery.clone();
                tokio::spawn(async move { let _=socket.send_to(&data,(Ipv4Addr::BROADCAST,DISCOVERY_PORT)).await; });
            }
        }
    }

    /// Dial every paired peer (and configured static peer) that has no live link.
    fn dial_known_peers(self:&Arc<Self>) {
        let mut targets:Vec<SocketAddr>=self.cfg.static_peers.iter().copied().filter(|t|is_lan_ip(t.ip())).collect();
        for known in Config::load_known_peers(self.cfg.space_id).unwrap_or_default() {
            if known.device_id==self.cfg.device_id || self.cfg.blocked_devices.contains(&known.device_id) || self.peers.contains_key(&known.device_id) { continue; }
            let Ok(ip)=known.address.parse::<IpAddr>() else { continue; };
            if !is_lan_ip(ip) { continue; }
            targets.push(SocketAddr::new(ip,if known.port==0 { self.cfg.tcp_port } else { known.port }));
        }
        for target in targets { self.dial(target); }
    }

    fn dial(self:&Arc<Self>,target:SocketAddr) {
        if self.dialing.insert(target,()).is_some() { return; }
        let net=self.clone();
        tokio::spawn(async move {
            let connected=time::timeout(Duration::from_secs(3),TcpStream::connect(target)).await;
            net.dialing.remove(&target);
            match connected {
                Ok(Ok(stream))=>{
                    if let Err(e)=handle_connection(stream,true,net.cfg.clone(),net.master.clone(),net.peers.clone(),net.pending.clone(),net.seen.clone(),net.latest.clone(),net.remote.clone()).await {
                        debug!(peer=%target,error=%e,"dialed peer ended");
                    }
                }
                // Stale address (DHCP / network change): ask peers to re-announce.
                _=>net.broadcast(),
            }
        });
    }
}

fn spawn_discovery_listener(net:Arc<Net>) {
    tokio::spawn(async move {
        let mut buf=[0u8;4096];
        loop {
            let Ok((n,addr))=net.discovery.recv_from(&mut buf).await else { continue; };
            if !is_lan_ip(addr.ip()) { continue; }
            let Ok(packet)=serde_json::from_slice::<DiscoveryPacket>(&buf[..n]) else { continue; };
            let cfg=&net.cfg;
            if packet.device_id==cfg.device_id || cfg.blocked_devices.contains(&packet.device_id) || packet.verify(&net.master,cfg.space_id).is_err() { continue; }
            let _=Config::remember_peer(cfg.space_id,packet.device_id,&packet.name,&addr.ip().to_string(),packet.port);
            // Answer by unicast so the announcer learns our address (rate limited).
            let reply_due=net.replied.get(&packet.device_id).map(|t|t.elapsed()>Duration::from_secs(30)).unwrap_or(true);
            if reply_due {
                net.replied.insert(packet.device_id,Instant::now());
                if let Ok(ours)=DiscoveryPacket::signed(&net.master,cfg.space_id,cfg.device_id,cfg.device_name.clone(),cfg.tcp_port) {
                    if let Ok(data)=serde_json::to_vec(&ours) { let _=net.discovery.send_to(&data,SocketAddr::new(addr.ip(),DISCOVERY_PORT)).await; }
                }
            }
            // A clip is waiting for this peer: deliver it at the address just learned.
            if net.latest_is_fresh() && !net.peers.contains_key(&packet.device_id) {
                net.dial(SocketAddr::new(addr.ip(),packet.port));
            }
        }
    });
}

/// On-demand reachability check for the UI (no keys, no persistent link):
/// a TCP connect to each paired peer's sync port; success refreshes last_seen.
pub async fn probe_peers(cfg:&Config)->Vec<(Uuid,bool)> {
    let mut checks=Vec::new();
    for known in Config::load_known_peers(cfg.space_id).unwrap_or_default() {
        if known.device_id==cfg.device_id || cfg.blocked_devices.contains(&known.device_id) { continue; }
        let Ok(ip)=known.address.parse::<IpAddr>() else { checks.push(tokio::spawn(async move { (known.device_id,false) })); continue; };
        let target=SocketAddr::new(ip,if known.port==0 { cfg.tcp_port } else { known.port });
        let space=cfg.space_id;
        checks.push(tokio::spawn(async move {
            let ok=is_lan_ip(ip) && matches!(time::timeout(Duration::from_millis(1500),TcpStream::connect(target)).await,Ok(Ok(_)));
            if ok { let _=Config::touch_peer(space,known.device_id,&ip.to_string()); }
            (known.device_id,ok)
        }));
    }
    let mut out=Vec::new();
    for c in checks { if let Ok(v)=c.await { out.push(v); } }
    out
}

async fn handle_connection(
    mut stream:TcpStream,
    outgoing:bool,
    cfg:Arc<Config>,
    master:Arc<MasterKey>,
    peers:PeerMap,
    pending:Pending,
    seen:Seen,
    latest:Latest,
    remote:mpsc::UnboundedSender<(Uuid,ClipPayload)>,
) -> Result<()> {
    stream.set_nodelay(true)?;
    let peer_addr=stream.peer_addr()?;
    if !is_lan_ip(peer_addr.ip()) { bail!("non-LAN peer"); }
    let our_hello=Hello::create(&master,cfg.space_id,cfg.device_id)?;
    let handshake=async {
        if outgoing {
            stream.write_all(&our_hello).await?;
            let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; Hello::verify(&master,cfg.space_id,&b)
        } else {
            let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; let h=Hello::verify(&master,cfg.space_id,&b)?; stream.write_all(&our_hello).await?; Ok(h)
        }
    };
    let remote_hello=match time::timeout(Duration::from_secs(10),handshake).await { Ok(r)=>r?, Err(_)=>bail!("peer handshake timed out") };
    if remote_hello.device_id==cfg.device_id { bail!("self connection"); }
    if cfg.blocked_devices.contains(&remote_hello.device_id) { bail!("removed peer"); }
    let peer_id=remote_hello.device_id;
    info!(peer=%peer_id,addr=%peer_addr,"peer authenticated");

    let (read_half,mut write_half)=stream.into_split();
    let (tx,mut rx)=mpsc::unbounded_channel::<Vec<u8>>();
    let conn_id=Uuid::new_v4();
    let kill=Arc::new(tokio::sync::Notify::new());
    match peers.entry(peer_id) {
        Entry::Occupied(mut entry) => {
            if entry.get().created.elapsed()<PEER_REPLACE_AFTER {
                debug!(peer=%peer_id,addr=%peer_addr,"closing duplicate authenticated connection");
                return Ok(());
            }
            info!(peer=%peer_id,addr=%peer_addr,"replacing stale peer connection");
            entry.get().kill.notify_one();
            entry.insert(PeerEntry{connection_id:conn_id,tx:tx.clone(),created:Instant::now(),kill:kill.clone()});
        }
        Entry::Vacant(entry) => {
            entry.insert(PeerEntry{connection_id:conn_id,tx:tx.clone(),created:Instant::now(),kill:kill.clone()});
        }
    }
    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());

    // Short RAM-only reconnect outbox: if a copy happened while Wi-Fi/socket recovery
    // was in progress, deliver the latest event once this authenticated peer returns.
    if let Some((created,msg_id,frame))=latest.lock().clone() {
        if created.elapsed()<Duration::from_secs(30) && tx.send(frame.clone()).is_ok() {
            pending.insert((peer_id,msg_id),());
            spawn_retry(peer_id,msg_id,frame,tx.clone(),pending.clone());
        }
    }

    let peers_for_writer=peers.clone();
    let writer=tokio::spawn(async move {
        while let Some(frame)=rx.recv().await {
            if frame.len()>MAX_FRAME_BYTES { break; }
            if write_half.write_u32(frame.len() as u32).await.is_err() || write_half.write_all(&frame).await.is_err() { break; }
        }
        if peers_for_writer.get(&peer_id).map(|e|e.connection_id)==Some(conn_id) { peers_for_writer.remove(&peer_id); }
    });

    let mut read_half=read_half;
    // No keepalive pings: the link exists only to carry clips and closes when idle.
    const PEER_IDLE_TIMEOUT:Duration=LINK_LINGER;
    let result:Result<()>=async { loop {
        let len=tokio::select! {
            _=kill.notified()=>{ debug!(peer=%peer_id,"connection replaced by a newer one"); break; }
            r=time::timeout(PEER_IDLE_TIMEOUT,read_half.read_u32())=>match r {
                Ok(Ok(v))=>v as usize,
                Ok(Err(_))=>break,
                Err(_)=>{ debug!(peer=%peer_id,"link idle; closing until the next copy"); break; }
            },
        };
        if len>MAX_FRAME_BYTES || len<80 { bail!("invalid frame size"); }
        let mut data=vec![0u8;len];
        match time::timeout(PEER_IDLE_TIMEOUT,read_half.read_exact(&mut data)).await {
            Ok(Ok(_))=>{}
            Ok(Err(e))=>return Err(e.into()),
            Err(_)=>bail!("peer stalled mid-frame"),
        }
        let frame=match decrypt_frame(&master,cfg.space_id,&data,true) {
            Ok(f)=>f,
            // One undecryptable/replayed frame must not take the whole link down.
            Err(e)=>{ warn!(peer=%peer_id,error=%e,"dropping undecryptable frame"); continue; }
        };
        if frame.sender_id!=peer_id { bail!("sender ID differs from authenticated peer"); }
        let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());
        match frame.kind {
            FrameKind::Clipboard => {
                let duplicate={
                    let mut s=seen.lock();
                    s.retain(|_,t|t.elapsed()<Duration::from_secs(300));
                    if s.contains_key(&frame.message_id) { true } else { s.insert(frame.message_id,Instant::now()); false }
                };
                if let Ok(ack)=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Ack,0,&[]) { let _=tx.send(ack); }
                if !duplicate {
                    match ClipPayload::from_json_bytes(&frame.plaintext,cfg.max_payload_bytes) {
                        Ok(payload)=>{ let _=remote.send((frame.message_id,payload)); }
                        Err(e)=>warn!(peer=%peer_id,error=%e,"ignoring unreadable clipboard payload"),
                    }
                }
            }
            FrameKind::Ack => { pending.remove(&(peer_id,frame.message_id)); }
            FrameKind::Ping => {
                if let Ok(pong)=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Pong,0,&[]) { let _=tx.send(pong); }
            }
            FrameKind::Pong => {}
        }
    } Ok(()) }.await;
    // Teardown runs on every exit path so a dead reader can never leave a
    // registered, write-only zombie that blocks the peer from reconnecting.
    writer.abort();
    if peers.get(&peer_id).map(|e|e.connection_id)==Some(conn_id) { peers.remove(&peer_id); }
    if let Err(e)=&result { warn!(peer=%peer_id,error=%e,"peer connection closed"); }
    result
}

pub fn is_lan_ip(ip:IpAddr)->bool {
    match ip {
        IpAddr::V4(v)=>v.is_private()||v.is_loopback()||v.is_link_local(),
        IpAddr::V6(v)=>v.is_loopback()||is_v6_unique_local(v)||v.is_unicast_link_local(),
    }
}
fn is_v6_unique_local(v:Ipv6Addr)->bool { (v.segments()[0]&0xfe00)==0xfc00 }


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

    async fn raw_client(addr:std::net::SocketAddr, master:&MasterKey, space:Uuid, id:Uuid) -> TcpStream {
        let mut s=TcpStream::connect(addr).await.unwrap();
        s.write_all(&Hello::create(master,space,id).unwrap()).await.unwrap();
        let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE];
        s.read_exact(&mut b).await.unwrap();
        s
    }

    async fn write_frame(s:&mut TcpStream, frame:&[u8]) {
        s.write_u32(frame.len() as u32).await.unwrap();
        s.write_all(frame).await.unwrap();
    }

    fn clip_frame(master:&MasterKey, space:Uuid, sender:Uuid, text:&[u8]) -> Vec<u8> {
        let mut p=ClipPayload::new();
        p.representations.push(Representation::from_bytes("text/plain; charset=utf-8",text));
        encrypt_frame(master,space,sender,Uuid::new_v4(),FrameKind::Clipboard,0,&p.to_json_bytes(clipmesh_core::payload::DEFAULT_MAX_PAYLOAD_BYTES).unwrap()).unwrap()
    }

    #[tokio::test]
    async fn bad_frames_do_not_kill_the_reader_and_teardown_always_unregisters() {
        let master=Arc::new(MasterKey::generate());
        let space=Uuid::new_v4();
        let mut b=Config::new("B".into());
        b.space_id=space;
        let b=Arc::new(b);
        let phone=Uuid::new_v4();
        let (peers,pending,seen,latest)=empty_maps();
        let (remote_tx,mut remote_rx)=mpsc::unbounded_channel();
        let listener=TcpListener::bind((Ipv4Addr::LOCALHOST,0)).await.unwrap();
        let addr=listener.local_addr().unwrap();
        let server={
            let b=b.clone(); let master=master.clone(); let peers=peers.clone();
            tokio::spawn(async move {
                let (stream,_)=listener.accept().await.unwrap();
                let _=handle_connection(stream,false,b,master,peers,pending,seen,latest,remote_tx).await;
            })
        };
        let mut client=raw_client(addr,&master,space,phone).await;

        // Garbage, a frame sealed with another key, and an exact replay must all be skipped.
        write_frame(&mut client,&vec![7u8;128]).await;
        let foreign=MasterKey::generate();
        write_frame(&mut client,&clip_frame(&foreign,space,phone,b"foreign")).await;
        let first=clip_frame(&master,space,phone,b"first");
        write_frame(&mut client,&first).await;
        write_frame(&mut client,&first).await;
        write_frame(&mut client,&clip_frame(&master,space,phone,b"second")).await;

        let mut got=Vec::new();
        while got.len()<2 {
            let (_,p)=time::timeout(Duration::from_secs(3),remote_rx.recv()).await.expect("reader stalled").unwrap();
            got.push(p.representations[0].bytes().unwrap());
        }
        assert_eq!(got,vec![b"first".to_vec(),b"second".to_vec()]);
        assert!(peers.contains_key(&phone));

        // A fatal framing error must tear everything down so the peer can reconnect.
        client.write_u32(u32::MAX).await.unwrap();
        time::timeout(Duration::from_secs(3),server).await.expect("connection not torn down").unwrap();
        assert!(!peers.contains_key(&phone), "dead connection left the peer registered");
    }

    #[tokio::test]
    async fn copy_with_no_open_link_dials_the_peer_and_delivers() {
        let master=Arc::new(MasterKey::generate());
        let space=Uuid::new_v4();
        let mut a=Config::new("A".into()); a.space_id=space;
        let mut b=Config::new("B".into()); b.space_id=space;
        let (a,b)=(Arc::new(a),Arc::new(b));
        // B only listens: no timers, no persistent link.
        let (b_peers,b_pending,b_seen,b_latest)=empty_maps();
        let (b_remote_tx,mut b_remote_rx)=mpsc::unbounded_channel();
        let listener=TcpListener::bind((Ipv4Addr::LOCALHOST,0)).await.unwrap();
        let b_addr=listener.local_addr().unwrap();
        {
            let b=b.clone(); let master=master.clone();
            tokio::spawn(async move {
                let (stream,_)=listener.accept().await.unwrap();
                let _=handle_connection(stream,false,b,master,b_peers,b_pending,b_seen,b_latest,b_remote_tx).await;
            });
        }
        // A copies: the frame becomes `latest`, then A dials B on demand.
        let (a_peers,a_pending,a_seen,a_latest)=empty_maps();
        let (a_remote_tx,_a_remote_rx)=mpsc::unbounded_channel();
        let net=Arc::new(Net{
            cfg:a.clone(),master:master.clone(),peers:a_peers.clone(),pending:a_pending.clone(),seen:a_seen,latest:a_latest.clone(),remote:a_remote_tx,
            discovery:Arc::new(UdpSocket::bind((Ipv4Addr::LOCALHOST,0)).await.unwrap()),
            dialing:Arc::new(DashMap::new()),replied:Arc::new(DashMap::new()),last_broadcast:Arc::new(parking_lot::Mutex::new(None)),
        });
        let msg=Uuid::new_v4();
        let mut payload=ClipPayload::new();
        payload.representations.push(Representation::from_bytes("text/plain; charset=utf-8",b"copied-while-idle"));
        let frame=encrypt_frame(&master,space,a.device_id,msg,FrameKind::Clipboard,0,&payload.to_json_bytes(clipmesh_core::payload::DEFAULT_MAX_PAYLOAD_BYTES).unwrap()).unwrap();
        *a_latest.lock()=Some((Instant::now(),msg,frame));
        net.dial(b_addr);
        let (_,p)=time::timeout(Duration::from_secs(3),b_remote_rx.recv()).await.expect("dial did not deliver the clip").unwrap();
        assert_eq!(p.representations[0].bytes().unwrap(),b"copied-while-idle");
        // B's ACK clears A's pending delivery.
        time::timeout(Duration::from_secs(3),async { while !a_pending.is_empty() { time::sleep(Duration::from_millis(10)).await; } }).await.expect("no ACK");
    }

    #[tokio::test]
    async fn reconnect_replaces_a_stale_registration() {
        let master=Arc::new(MasterKey::generate());
        let space=Uuid::new_v4();
        let mut b=Config::new("B".into());
        b.space_id=space;
        let b=Arc::new(b);
        let phone=Uuid::new_v4();
        let (peers,pending,seen,latest)=empty_maps();
        // A registration left behind by a link that silently died long ago.
        let (dead_tx,_dead_rx)=mpsc::unbounded_channel();
        peers.insert(phone,PeerEntry{connection_id:Uuid::new_v4(),tx:dead_tx,created:Instant::now()-Duration::from_secs(600),kill:Arc::new(tokio::sync::Notify::new())});
        let (remote_tx,mut remote_rx)=mpsc::unbounded_channel();
        let listener=TcpListener::bind((Ipv4Addr::LOCALHOST,0)).await.unwrap();
        let addr=listener.local_addr().unwrap();
        {
            let b=b.clone(); let master=master.clone(); let peers=peers.clone();
            tokio::spawn(async move {
                let (stream,_)=listener.accept().await.unwrap();
                let _=handle_connection(stream,false,b,master,peers,pending,seen,latest,remote_tx).await;
            });
        }
        let mut client=raw_client(addr,&master,space,phone).await;
        write_frame(&mut client,&clip_frame(&master,space,phone,b"after-reconnect")).await;
        let (_,p)=time::timeout(Duration::from_secs(3),remote_rx.recv()).await.expect("reconnect was rejected as a duplicate").unwrap();
        assert_eq!(p.representations[0].bytes().unwrap(),b"after-reconnect");
        assert!(peers.get(&phone).unwrap().created.elapsed()<Duration::from_secs(5));
    }
}
