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
}

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

    spawn_discovery(cfg.clone(),master.clone(),peers.clone(),pending.clone(),seen.clone(),latest.clone(),remote_clip_tx.clone()).await?;
    spawn_static_peer_loop(cfg.clone(),master.clone(),peers.clone(),pending.clone(),seen.clone(),latest.clone(),remote_clip_tx.clone());

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

async fn spawn_discovery(cfg:Arc<Config>,master:Arc<MasterKey>,peers:PeerMap,pending:Pending,seen:Seen,latest:Latest,remote:mpsc::UnboundedSender<(Uuid,ClipPayload)>) -> Result<()> {
    let socket=Arc::new(UdpSocket::bind((Ipv4Addr::UNSPECIFIED,DISCOVERY_PORT)).await?);
    socket.set_broadcast(true)?;
    {
        let socket=socket.clone(); let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone();
        tokio::spawn(async move {
            loop {
                match DiscoveryPacket::signed(&master,cfg.space_id,cfg.device_id,cfg.device_name.clone(),cfg.tcp_port) {
                    Ok(packet)=>if let Ok(data)=serde_json::to_vec(&packet) { let _=socket.send_to(&data,(Ipv4Addr::BROADCAST,DISCOVERY_PORT)).await; },
                    Err(e)=>warn!(error=%e,"discovery signing failed"),
                }
                let wait = if peers.is_empty() { 12 } else { 45 };
                time::sleep(Duration::from_secs(wait)).await;
            }
        });
    }
    {
        let socket=socket.clone(); let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone(); let pending=pending.clone(); let seen=seen.clone(); let latest=latest.clone();
        tokio::spawn(async move {
            let mut buf=[0u8;4096];
            loop {
                let Ok((n,addr))=socket.recv_from(&mut buf).await else { continue; };
                if !is_lan_ip(addr.ip()) { continue; }
                let Ok(packet)=serde_json::from_slice::<DiscoveryPacket>(&buf[..n]) else { continue; };
                if packet.device_id==cfg.device_id || cfg.blocked_devices.contains(&packet.device_id) || packet.verify(&master,cfg.space_id).is_err() { continue; }
                let _=Config::remember_peer(cfg.space_id,packet.device_id,&packet.name,&addr.ip().to_string(),packet.port);
                if peers.contains_key(&packet.device_id) { continue; }
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
            }
        });
    }
    Ok(())
}

fn spawn_static_peer_loop(cfg:Arc<Config>,master:Arc<MasterKey>,peers:PeerMap,pending:Pending,seen:Seen,latest:Latest,remote:mpsc::UnboundedSender<(Uuid,ClipPayload)>) {
    tokio::spawn(async move {
        loop {
            for target in &cfg.static_peers {
                if !is_lan_ip(target.ip()) { continue; }
                let target=*target; let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone(); let pending=pending.clone(); let seen=seen.clone(); let latest=latest.clone(); let remote=remote.clone();
                tokio::spawn(async move {
                    if let Ok(Ok(stream))=time::timeout(Duration::from_secs(2),TcpStream::connect(target)).await {
                        let _=handle_connection(stream,true,cfg,master,peers,pending,seen,latest,remote).await;
                    }
                });
            }
            time::sleep(Duration::from_secs(20)).await;
        }
    });
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
    let remote_hello = if outgoing {
        stream.write_all(&our_hello).await?;
        let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; Hello::verify(&master,cfg.space_id,&b)?
    } else {
        let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; let h=Hello::verify(&master,cfg.space_id,&b)?; stream.write_all(&our_hello).await?; h
    };
    if remote_hello.device_id==cfg.device_id { bail!("self connection"); }
    if cfg.blocked_devices.contains(&remote_hello.device_id) { bail!("removed peer"); }
    let peer_id=remote_hello.device_id;
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
    let ping_tx=tx.clone(); let cfg_ping=cfg.clone(); let master_ping=master.clone();
    let ping_task=tokio::spawn(async move {
        let mut interval=time::interval(Duration::from_secs(30));
        loop {
            interval.tick().await;
            let id=Uuid::new_v4();
            match encrypt_frame(&master_ping,cfg_ping.space_id,cfg_ping.device_id,id,FrameKind::Ping,0,&[]) { Ok(f)=>if ping_tx.send(f).is_err(){break;},Err(_)=>break }
        }
    });

    loop {
        let len=match read_half.read_u32().await { Ok(v)=>v as usize,Err(_)=>break };
        if len>MAX_FRAME_BYTES || len<80 { bail!("invalid frame size"); }
        let mut data=vec![0u8;len]; read_half.read_exact(&mut data).await?;
        let frame=decrypt_frame(&master,cfg.space_id,&data,true)?;
        if frame.sender_id!=peer_id { bail!("sender ID differs from authenticated peer"); }
        let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());
        match frame.kind {
            FrameKind::Clipboard => {
                let duplicate={
                    let mut s=seen.lock();
                    s.retain(|_,t|t.elapsed()<Duration::from_secs(300));
                    if s.contains_key(&frame.message_id) { true } else { s.insert(frame.message_id,Instant::now()); false }
                };
                let ack=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Ack,0,&[])?;
                let _=tx.send(ack);
                if !duplicate {
                    let payload=ClipPayload::from_json_bytes(&frame.plaintext,cfg.max_payload_bytes)?;
                    let _=remote.send((frame.message_id,payload));
                }
            }
            FrameKind::Ack => { pending.remove(&(peer_id,frame.message_id)); }
            FrameKind::Ping => {
                let pong=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Pong,0,&[])?; let _=tx.send(pong);
            }
            FrameKind::Pong => {}
        }
    }
    ping_task.abort();
    writer.abort();
    if peers.get(&peer_id).map(|e|e.connection_id)==Some(conn_id) { peers.remove(&peer_id); }
    Ok(())
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
}
