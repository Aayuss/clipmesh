# v063 desktop daemon (shared by macOS + Windows): a failed peer connection must
# never become a zombie. Previously any per-frame error (`?`/`bail!`) returned
# from handle_connection before cleanup, leaving the writer + ping task alive and
# the peer registered, so the reader was dead (phone -> desktop sync stopped,
# "Last seen" froze) while every reconnect from the phone was rejected as a
# duplicate. Now: bad single frames are dropped, silent links time out, and
# teardown always runs.
network = PROJECT / "apps/desktop/src/network.rs"
replace_once(
    network,
    '''    loop {
        let len=match read_half.read_u32().await { Ok(v)=>v as usize,Err(_)=>break };
        if len>MAX_FRAME_BYTES || len<80 { bail!("invalid frame size"); }
        let mut data=vec![0u8;len]; read_half.read_exact(&mut data).await?;
        let frame=decrypt_frame(&master,cfg.space_id,&data,true)?;
        if frame.sender_id!=peer_id { bail!("sender ID differs from authenticated peer"); }
        let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());''',
    '''    // Both sides ping at least every 30s, so a silent link for this long is dead.
    const PEER_IDLE_TIMEOUT:Duration=Duration::from_secs(100);
    let result:Result<()>=async { loop {
        let len=match time::timeout(PEER_IDLE_TIMEOUT,read_half.read_u32()).await {
            Ok(Ok(v))=>v as usize,
            Ok(Err(_))=>break,
            Err(_)=>{ info!(peer=%peer_id,"peer connection idle; reconnecting"); break; }
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
        let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());''',
    "v063 resilient peer read loop",
)
replace_once(
    network,
    '''                let ack=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Ack,0,&[])?;
                let _=tx.send(ack);
                if !duplicate {
                    let payload=ClipPayload::from_json_bytes(&frame.plaintext,cfg.max_payload_bytes)?;
                    let _=remote.send((frame.message_id,payload));
                }''',
    '''                if let Ok(ack)=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Ack,0,&[]) { let _=tx.send(ack); }
                if !duplicate {
                    match ClipPayload::from_json_bytes(&frame.plaintext,cfg.max_payload_bytes) {
                        Ok(payload)=>{ let _=remote.send((frame.message_id,payload)); }
                        Err(e)=>warn!(peer=%peer_id,error=%e,"ignoring unreadable clipboard payload"),
                    }
                }''',
    "v063 non-fatal clipboard payload errors",
)
replace_once(
    network,
    '''            FrameKind::Ping => {
                let pong=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Pong,0,&[])?; let _=tx.send(pong);
            }
            FrameKind::Pong => {}
        }
    }
    ping_task.abort();
    writer.abort();
    if peers.get(&peer_id).map(|e|e.connection_id)==Some(conn_id) { peers.remove(&peer_id); }
    Ok(())
}''',
    '''            FrameKind::Ping => {
                if let Ok(pong)=encrypt_frame(&master,cfg.space_id,cfg.device_id,frame.message_id,FrameKind::Pong,0,&[]) { let _=tx.send(pong); }
            }
            FrameKind::Pong => {}
        }
    } Ok(()) }.await;
    // Teardown runs on every exit path so a dead reader can never leave a
    // registered, write-only zombie that blocks the peer from reconnecting.
    ping_task.abort();
    writer.abort();
    if peers.get(&peer_id).map(|e|e.connection_id)==Some(conn_id) { peers.remove(&peer_id); }
    if let Err(e)=&result { warn!(peer=%peer_id,error=%e,"peer connection closed"); }
    result
}''',
    "v063 unconditional peer teardown",
)

# Unit tests exercise handle_connection, which persists peers. Never let a test
# run touch the user's real config directory.
config_rs = PROJECT / "apps/desktop/src/config.rs"
replace_once(
    config_rs,
    '''    fn peers_path() -> Result<PathBuf> {
        let config = Self::path()?;''',
    '''    fn peers_path() -> Result<PathBuf> {
        #[cfg(test)]
        {
            return Ok(std::env::temp_dir().join(format!("clipmesh-unit-tests-{}", std::process::id())).join("peers.json"));
        }
        #[allow(unreachable_code)]
        let config = Self::path()?;''',
    "v063 test-isolated peers path",
)

# Regression tests for the zombie-connection bug.
replace_once(
    network,
    '''        a_task.abort();
        b_task.abort();
    }
}''',
    '''        a_task.abort();
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
}''',
    "v063 zombie-connection regression tests",
)

# "First connection wins" made any stale entry permanent. A peer only reconnects
# when it believes its old link is dead, so a newer authenticated connection now
# replaces one older than a few seconds (simultaneous connects still de-dupe).
replace_once(
    network,
    '''struct PeerEntry {
    connection_id: Uuid,
    tx: mpsc::UnboundedSender<Vec<u8>>,
}''',
    '''struct PeerEntry {
    connection_id: Uuid,
    tx: mpsc::UnboundedSender<Vec<u8>>,
    created: Instant,
    kill: Arc<tokio::sync::Notify>,
}

/// Connections younger than this are treated as a simultaneous-connect duplicate.
const PEER_REPLACE_AFTER: Duration = Duration::from_secs(10);''',
    "v063 peer entry replacement state",
)
replace_once(
    network,
    '''    match peers.entry(peer_id) {
        Entry::Occupied(_) => {
            debug!(peer=%peer_id,addr=%peer_addr,"closing duplicate authenticated connection");
            return Ok(());
        }
        Entry::Vacant(entry) => {
            entry.insert(PeerEntry{connection_id:conn_id,tx:tx.clone()});
        }
    }''',
    '''    let kill=Arc::new(tokio::sync::Notify::new());
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
    }''',
    "v063 newer connection replaces stale",
)
replace_once(
    network,
    '''        let len=match time::timeout(PEER_IDLE_TIMEOUT,read_half.read_u32()).await {
            Ok(Ok(v))=>v as usize,
            Ok(Err(_))=>break,
            Err(_)=>{ info!(peer=%peer_id,"peer connection idle; reconnecting"); break; }
        };''',
    '''        let len=tokio::select! {
            _=kill.notified()=>{ debug!(peer=%peer_id,"connection replaced by a newer one"); break; }
            r=time::timeout(PEER_IDLE_TIMEOUT,read_half.read_u32())=>match r {
                Ok(Ok(v))=>v as usize,
                Ok(Err(_))=>break,
                Err(_)=>{ info!(peer=%peer_id,"peer connection idle; reconnecting"); break; }
            },
        };''',
    "v063 replaced connections stop reading",
)
# Regression test: a reconnect from the same peer replaces a stale registration.
replace_once(
    network,
    '''        assert!(!peers.contains_key(&phone), "dead connection left the peer registered");
    }
}''',
    '''        assert!(!peers.contains_key(&phone), "dead connection left the peer registered");
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
}''',
    "v063 stale-registration regression test",
)

# Always-connected paired devices: a sleeping phone barely broadcasts discovery,
# so waiting for its announcement left it "offline" until unlock. Dial every
# paired-but-disconnected peer at its last known LAN address (a unicast SYN wakes
# the phone), immediately after a link drops and then with 5s..60s backoff.
replace_once(
    network,
    "    spawn_static_peer_loop(cfg.clone(),master.clone(),peers.clone(),pending.clone(),seen.clone(),latest.clone(),remote_clip_tx.clone());\n",
    "    spawn_static_peer_loop(cfg.clone(),master.clone(),peers.clone(),pending.clone(),seen.clone(),latest.clone(),remote_clip_tx.clone());\n"
    "    spawn_known_peer_redial(cfg.clone(),master.clone(),peers.clone(),pending.clone(),seen.clone(),latest.clone(),remote_clip_tx.clone());\n",
    "v063 start known-peer redial",
)
replace_once(
    network,
    "fn spawn_static_peer_loop(",
    '''/// Woken whenever an authenticated peer link ends, so redial starts at once.
static PEER_LOST: tokio::sync::Notify = tokio::sync::Notify::const_new();

fn spawn_known_peer_redial(cfg:Arc<Config>,master:Arc<MasterKey>,peers:PeerMap,pending:Pending,seen:Seen,latest:Latest,remote:mpsc::UnboundedSender<(Uuid,ClipPayload)>) {
    let dialing:Arc<DashMap<Uuid,()>>=Arc::new(DashMap::new());
    tokio::spawn(async move {
        let mut backoff=Duration::from_secs(5);
        loop {
            let mut missing=false;
            for known in Config::load_known_peers(cfg.space_id).unwrap_or_default() {
                if known.device_id==cfg.device_id || cfg.blocked_devices.contains(&known.device_id) || peers.contains_key(&known.device_id) { continue; }
                let Ok(ip)=known.address.parse::<IpAddr>() else { continue; };
                if !is_lan_ip(ip) { continue; }
                missing=true;
                if dialing.insert(known.device_id,()).is_some() { continue; }
                let target=SocketAddr::new(ip,if known.port==0 { cfg.tcp_port } else { known.port });
                let cfg=cfg.clone(); let master=master.clone(); let peers=peers.clone(); let pending=pending.clone(); let seen=seen.clone(); let latest=latest.clone(); let remote=remote.clone(); let dialing=dialing.clone();
                let id=known.device_id;
                tokio::spawn(async move {
                    if let Ok(Ok(stream))=time::timeout(Duration::from_secs(3),TcpStream::connect(target)).await {
                        dialing.remove(&id);
                        if let Err(e)=handle_connection(stream,true,cfg,master,peers,pending,seen,latest,remote).await { debug!(peer=%target,error=%e,"redialed peer ended"); }
                    } else {
                        dialing.remove(&id);
                    }
                });
            }
            let wait=if missing { let w=backoff; backoff=(backoff*2).min(Duration::from_secs(60)); w } else { backoff=Duration::from_secs(5); Duration::from_secs(60) };
            tokio::select! {
                _=time::sleep(wait)=>{}
                _=PEER_LOST.notified()=>{ backoff=Duration::from_secs(5); time::sleep(Duration::from_secs(1)).await; }
            }
        }
    });
}

fn spawn_static_peer_loop(''',
    "v063 known-peer redial loop",
)
replace_once(
    network,
    '''    if peers.get(&peer_id).map(|e|e.connection_id)==Some(conn_id) { peers.remove(&peer_id); }
    if let Err(e)=&result { warn!(peer=%peer_id,error=%e,"peer connection closed"); }''',
    '''    if peers.get(&peer_id).map(|e|e.connection_id)==Some(conn_id) { peers.remove(&peer_id); PEER_LOST.notify_one(); }
    if let Err(e)=&result { warn!(peer=%peer_id,error=%e,"peer connection closed"); }''',
    "v063 redial immediately after a link ends",
)
# The hello exchange had no timeout: a dial to the wrong host could hang forever.
replace_once(
    network,
    '''    let remote_hello = if outgoing {
        stream.write_all(&our_hello).await?;
        let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; Hello::verify(&master,cfg.space_id,&b)?
    } else {
        let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; let h=Hello::verify(&master,cfg.space_id,&b)?; stream.write_all(&our_hello).await?; h
    };''',
    '''    let handshake=async {
        if outgoing {
            stream.write_all(&our_hello).await?;
            let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; Hello::verify(&master,cfg.space_id,&b)
        } else {
            let mut b=vec![0u8;clipmesh_core::discovery::HELLO_SIZE]; stream.read_exact(&mut b).await?; let h=Hello::verify(&master,cfg.space_id,&b)?; stream.write_all(&our_hello).await?; Ok(h)
        }
    };
    let remote_hello=match time::timeout(Duration::from_secs(10),handshake).await { Ok(r)=>r?, Err(_)=>bail!("peer handshake timed out") };''',
    "v063 handshake timeout",
)
