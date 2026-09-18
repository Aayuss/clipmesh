from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8"); found = text.count(old)
    if found != count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")

def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8"); updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=flags)
    if found != count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")

ui = ROOT / "ci/ClipMeshWindows.cs"
pairing = ROOT / "ci/ClipMeshNearbyPairing.cs"

replace(pairing,
    "public Func<string> FingerprintProvider;",
    "public Func<string> FingerprintProvider; public Func<string> DeviceIdProvider; public Func<string,string,bool> PeerConsumer;",
    "windows pairing identity callbacks")

regex(pairing,
    r"    public void Pair\(string credential, TransferDeviceC device, Action<string> showCode\)\n    \{.*?\n    \}\n\n    private void ServerLoop",
    r'''    public void Pair(string credential, TransferDeviceC device, Action<string> showCode)
    {
        using(ECDiffieHellmanCng key=NearbyPairingCryptoC.NewKey())
        {
            string initiatorPublic=NearbyPairingCryptoC.B64(NearbyPairingCryptoC.Public(key)),requestNonce=NearbyPairingCryptoC.B64(NearbyPairingCryptoC.Random(16));
            string initiatorFp=FingerprintProvider==null?"unavailable":FingerprintProvider();
            Dictionary<string,object> start=new Dictionary<string,object>{{"alias",AliasProvider==null?Environment.MachineName:AliasProvider()},{"fingerprint",initiatorFp},{"publicKey",initiatorPublic},{"requestNonce",requestNonce}};
            PairHttpResultC response=Post(device,"/api/clipmesh/v1/pair/start",start);
            if(response.Status!=200||response.Json==null)throw new InvalidOperationException("Pairing request was rejected.");
            string id=Convert.ToString(response.Json["sessionId"]),responderFp=Convert.ToString(response.Json["responderFingerprint"]),responderPublic=Convert.ToString(response.Json["responderPublicKey"]);
            string responderId=response.Json.ContainsKey("responderDeviceId")?Convert.ToString(response.Json["responderDeviceId"]):"";
            string responderName=response.Json.ContainsKey("responderName")?Convert.ToString(response.Json["responderName"]):device.Alias;
            if(String.IsNullOrWhiteSpace(responderId))throw new InvalidOperationException("Pairing response did not include a device identity.");
            byte[] secret=NearbyPairingCryptoC.Agree(key,NearbyPairingCryptoC.Un64(responderPublic));byte[] transcript=NearbyPairingCryptoC.Transcript(id,requestNonce,initiatorFp,responderFp,initiatorPublic,responderPublic);
            if(showCode!=null)showCode(NearbyPairingCryptoC.Code(secret,transcript));bool verified=false;
            for(int i=0;i<80;i++){PairHttpResultC state=Post(device,"/api/clipmesh/v1/pair/status",new Dictionary<string,object>{{"sessionId",id}});if(state.Status==200&&state.Json!=null&&Convert.ToBoolean(state.Json["verified"])){verified=true;break;}if(state.Status==403)break;Thread.Sleep(1500);}
            if(!verified)throw new InvalidOperationException("The verification code was not confirmed.");byte[] nonce=NearbyPairingCryptoC.Random(16),plain=Encoding.UTF8.GetBytes(credential);byte[][] sealedValue=NearbyPairingCryptoC.Seal(plain,secret,transcript,nonce);
            PairHttpResultC done=Post(device,"/api/clipmesh/v1/pair/complete",new Dictionary<string,object>{{"sessionId",id},{"nonce",NearbyPairingCryptoC.B64(nonce)},{"ciphertext",NearbyPairingCryptoC.B64(sealedValue[0])},{"tag",NearbyPairingCryptoC.B64(sealedValue[1])}});
            if(done.Status!=200)throw new InvalidOperationException("The receiving device could not apply the pairing.");
            if(PeerConsumer==null||!PeerConsumer(responderId,responderName))throw new InvalidOperationException("The paired device identity could not be saved.");
        }
    }

    private void ServerLoop''',
    "windows bidirectional Pair method")

replace(pairing,
    'Respond(stream,200,new Dictionary<string,object>{{"sessionId",id},{"responderFingerprint",responderFp},{"responderPublicKey",responderPublic}});',
    'Respond(stream,200,new Dictionary<string,object>{{"sessionId",id},{"responderFingerprint",responderFp},{"responderPublicKey",responderPublic},{"responderDeviceId",DeviceIdProvider==null?"":DeviceIdProvider()},{"responderName",AliasProvider==null?"Windows PC":AliasProvider()}});',
    "windows advertise clipboard identity")

replace(ui,
    "    public static void ForgetPeer(string id)",
    """    public static void SeedPeer(string id, string name)
    {
        Checked("Could not save the paired device.", "seed-peer", id, "--name", name);
    }

    public static void ForgetPeer(string id)""",
    "windows seed runtime")

replace(ui,
    "                NearbyPairingManagerC.Shared.FingerprintProvider=delegate{return LocalTransferManagerC.Shared.Fingerprint;};",
    """                NearbyPairingManagerC.Shared.FingerprintProvider=delegate{return LocalTransferManagerC.Shared.Fingerprint;};
                NearbyPairingManagerC.Shared.DeviceIdProvider=delegate{return latestState==null?ClipMeshRuntime.GetUiState().DeviceId:latestState.DeviceId;};
                NearbyPairingManagerC.Shared.PeerConsumer=delegate(string id,string name){bool ok=false;MethodInvoker save=delegate{StopDaemon();try{ClipMeshRuntime.SeedPeer(id,name);StartDaemon();RefreshHome();ok=true;}catch(Exception ex){try{StartDaemon();}catch{}ShowError(ex.Message);}};if(InvokeRequired)Invoke(save);else save();return ok;};""",
    "windows pairing identity setup")

replace(ui,
    "    private readonly FlowLayoutPanel nearbyPairPanel;",
    "    private readonly FlowLayoutPanel nearbyPairPanel;\n    private Form pairingCodeWindow;",
    "windows pairing dialog property")

regex(ui,
    r"    private void StartNearbyPair\(TransferDeviceC device\)\{.*?\}\n    private bool ApproveNearbyPair",
    r'''    private void StartNearbyPair(TransferDeviceC device)
    {
        string credential; try { credential=ClipMeshRuntime.PairingLink(); } catch(Exception ex) { ShowError(ex.Message); return; }
        status.Text="Waiting for "+device.Alias+"…";
        Task.Run(delegate {
            try {
                NearbyPairingManagerC.Shared.Pair(credential,device,delegate(string value){if(!IsDisposed)BeginInvoke((Action)(delegate{ShowPairingCode(device.Alias,value);}));});
                if(!IsDisposed)BeginInvoke((Action)(delegate{ClosePairingCode();status.Text="Paired with "+device.Alias;LocalTransferManagerC.Shared.DiscoverNow();RefreshHome();RefreshNearbyPairDevices();}));
            } catch(Exception ex) {
                if(!IsDisposed)BeginInvoke((Action)(delegate{ClosePairingCode();ShowError(ex.Message);RefreshHome();}));
            }
        });
    }

    private void ShowPairingCode(string device,string value)
    {
        ClosePairingCode();
        Form dialog=new Form();dialog.Text="ClipMesh";dialog.Width=470;dialog.Height=260;dialog.FormBorderStyle=FormBorderStyle.FixedDialog;dialog.StartPosition=FormStartPosition.CenterParent;dialog.MaximizeBox=false;dialog.MinimizeBox=false;dialog.BackColor=Color.FromArgb(11,12,15);dialog.ForeColor=Color.FromArgb(244,241,234);dialog.ControlBox=false;
        Label title=MakeLabel("Verification code",15,FontStyle.Bold,dialog.ForeColor);title.SetBounds(24,20,410,32);
        Label detail=MakeLabel("Type this code on "+device+". This window closes automatically.",9,FontStyle.Regular,Color.FromArgb(166,163,156));detail.SetBounds(24,56,410,42);
        Label code=MakeLabel(value,32,FontStyle.Bold,dialog.ForeColor);code.Font=new Font(FontFamily.GenericMonospace,32,FontStyle.Bold);code.TextAlign=ContentAlignment.MiddleCenter;code.SetBounds(24,108,410,76);
        dialog.Controls.Add(title);dialog.Controls.Add(detail);dialog.Controls.Add(code);pairingCodeWindow=dialog;dialog.Show(this);
    }

    private void ClosePairingCode(){Form dialog=pairingCodeWindow;pairingCodeWindow=null;if(dialog!=null&&!dialog.IsDisposed)dialog.Close();}

    private bool ApproveNearbyPair''',
    "windows auto-dismiss pairing code dialog")

print("Applied ClipMesh v055 Windows bidirectional pairing UX")
