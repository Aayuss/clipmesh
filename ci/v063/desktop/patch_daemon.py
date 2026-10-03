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
