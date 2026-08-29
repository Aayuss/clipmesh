using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class NearbyPairingCryptoC
{
    public const string ProtocolName = "ClipMesh-Pair-v1";

    public static string B64(byte[] value) { return Convert.ToBase64String(value).TrimEnd('=').Replace('+','-').Replace('/','_'); }
    public static byte[] Un64(string value) { string text = (value ?? "").Replace('-','+').Replace('_','/'); text += new string('=', (4 - text.Length % 4) % 4); return Convert.FromBase64String(text); }

    public static byte[] Transcript(string session, string nonce, string initiatorFp, string responderFp, string initiatorPublic, string responderPublic)
    { return Encoding.UTF8.GetBytes(ProtocolName + "\n" + session + "\n" + nonce + "\n" + initiatorFp + "\n" + responderFp + "\n" + initiatorPublic + "\n" + responderPublic); }

    private static byte[] Hmac(byte[] key, byte[] data) { using (HMACSHA256 h = new HMACSHA256(key)) return h.ComputeHash(data); }
    private static byte[] Join(params byte[][] values) { int size=0; foreach(byte[] v in values) size+=v.Length; byte[] result=new byte[size]; int at=0; foreach(byte[] v in values){Buffer.BlockCopy(v,0,result,at,v.Length);at+=v.Length;} return result; }
    private static byte[] Expand(byte[] prk, byte[] info, int count) { List<byte> output=new List<byte>(); byte[] previous=new byte[0]; byte counter=1; while(output.Count<count){previous=Hmac(prk,Join(previous,info,new byte[]{counter++}));output.AddRange(previous);} return output.GetRange(0,count).ToArray(); }
    private static byte[][] Keys(byte[] agreementSecret, byte[] transcript) { byte[] salt; using(SHA256 h=SHA256.Create())salt=h.ComputeHash(transcript); byte[] prk=Hmac(salt,agreementSecret); byte[] material=Expand(prk,Encoding.UTF8.GetBytes("clipmesh-nearby-pair-v1"),64); byte[] enc=new byte[32],mac=new byte[32];Buffer.BlockCopy(material,0,enc,0,32);Buffer.BlockCopy(material,32,mac,0,32);return new byte[][]{enc,mac}; }

    public static string Code(byte[] agreementSecret, byte[] transcript) { byte[] mac=Keys(agreementSecret,transcript)[1];byte[] d=Hmac(mac,Join(Encoding.UTF8.GetBytes("sas\n"),transcript));uint n=((uint)d[0]<<24)|((uint)d[1]<<16)|((uint)d[2]<<8)|d[3];return (n%1000000).ToString("D6"); }
    private static byte[] Stream(byte[] key, byte[] nonce, int count) { List<byte> output=new List<byte>();uint c=0;while(output.Count<count){byte[] b=new byte[]{(byte)(c>>24),(byte)(c>>16),(byte)(c>>8),(byte)c};output.AddRange(Hmac(key,Join(Encoding.UTF8.GetBytes("stream\n"),nonce,b)));c++;}return output.GetRange(0,count).ToArray(); }
    public static byte[][] Seal(byte[] plain, byte[] agreementSecret, byte[] transcript, byte[] nonce) { byte[][] keys=Keys(agreementSecret,transcript);byte[] stream=Stream(keys[0],nonce,plain.Length),cipher=new byte[plain.Length];for(int i=0;i<plain.Length;i++)cipher[i]=(byte)(plain[i]^stream[i]);byte[] tag=Hmac(keys[1],Join(Encoding.UTF8.GetBytes("payload\n"),transcript,nonce,cipher));return new byte[][]{cipher,tag}; }
    public static byte[] Open(byte[] cipher, byte[] tag, byte[] agreementSecret, byte[] transcript, byte[] nonce) { byte[][] keys=Keys(agreementSecret,transcript);byte[] expected=Hmac(keys[1],Join(Encoding.UTF8.GetBytes("payload\n"),transcript,nonce,cipher));if(!Equal(tag,expected))return null;byte[] stream=Stream(keys[0],nonce,cipher.Length),plain=new byte[cipher.Length];for(int i=0;i<cipher.Length;i++)plain[i]=(byte)(cipher[i]^stream[i]);return plain; }
    public static bool Equal(byte[] a, byte[] b){if(a==null||b==null||a.Length!=b.Length)return false;int diff=0;for(int i=0;i<a.Length;i++)diff|=a[i]^b[i];return diff==0;}

    public static ECDiffieHellmanCng NewKey(){ECDiffieHellmanCng key=new ECDiffieHellmanCng(256);key.KeyDerivationFunction=ECDiffieHellmanKeyDerivationFunction.Hash;key.HashAlgorithm=CngAlgorithm.Sha256;return key;}
    public static byte[] Public(ECDiffieHellmanCng key){byte[] blob=key.Key.Export(CngKeyBlobFormat.EccPublicBlob);if(blob.Length!=72)throw new CryptographicException("Unexpected P-256 key");byte[] result=new byte[65];result[0]=4;Buffer.BlockCopy(blob,8,result,1,64);return result;}
    public static byte[] Agree(ECDiffieHellmanCng key, byte[] peer){if(peer==null||peer.Length!=65||peer[0]!=4)throw new CryptographicException("Invalid P-256 public key");byte[] blob=new byte[72];Buffer.BlockCopy(BitConverter.GetBytes(0x314B4345),0,blob,0,4);Buffer.BlockCopy(BitConverter.GetBytes(32),0,blob,4,4);Buffer.BlockCopy(peer,1,blob,8,64);using(ECDiffieHellmanCngPublicKey p=ECDiffieHellmanCngPublicKey.FromByteArray(blob,CngKeyBlobFormat.EccPublicBlob))return key.DeriveKeyMaterial(p);}
    public static byte[] Random(int count){byte[] b=new byte[count];using(RandomNumberGenerator r=RandomNumberGenerator.Create())r.GetBytes(b);return b;}
    public static void SelfTest(){using(ECDiffieHellmanCng a=NewKey())using(ECDiffieHellmanCng b=NewKey()){byte[] ab=Agree(a,Public(b)),ba=Agree(b,Public(a));if(!Equal(ab,ba))throw new CryptographicException("ECDH self-test failed");byte[] tr=Encoding.UTF8.GetBytes("self-test"),n=new byte[16],m=Encoding.UTF8.GetBytes("clipmesh://pair?self-test");byte[][] s=Seal(m,ab,tr,n);if(!Equal(Open(s[0],s[1],ba,tr,n),m))throw new CryptographicException("pairing cipher self-test failed");}}
}

internal sealed class PairReceiveSessionC
{
    public string Id, Sender, Code; public byte[] Secret, Transcript; public DateTime Expires=DateTime.UtcNow.AddMinutes(2); public bool Verified, Rejected;
}

internal sealed class PairHttpResultC { public int Status; public Dictionary<string,object> Json; }

internal sealed class NearbyPairingManagerC : IDisposable
{
    public static readonly NearbyPairingManagerC Shared=new NearbyPairingManagerC(); public const int Port=53422;
    public Func<string,bool> ApprovalPrompt; public Action<string,Action<string>> CodePrompt; public Func<string,string,bool> CredentialConsumer; public Func<string> AliasProvider; public Func<string> FingerprintProvider;
    private readonly object gate=new object(); private readonly JavaScriptSerializer json=new JavaScriptSerializer(); private readonly Dictionary<string,PairReceiveSessionC> sessions=new Dictionary<string,PairReceiveSessionC>(); private TcpListener listener; private bool running;

    public void Start(){lock(gate){if(running)return;running=true;}TaskRun(ServerLoop);NearbyPairingCryptoC.SelfTest();}
    public void Stop(){lock(gate){running=false;sessions.Clear();}try{if(listener!=null)listener.Stop();}catch{}listener=null;}
    private bool Running{get{lock(gate)return running;}}
    private static void TaskRun(Action value){System.Threading.Tasks.Task.Run(value);}

    public void Pair(string credential, TransferDeviceC device, Action<string> showCode)
    {
        using(ECDiffieHellmanCng key=NearbyPairingCryptoC.NewKey())
        {
            string initiatorPublic=NearbyPairingCryptoC.B64(NearbyPairingCryptoC.Public(key)),requestNonce=NearbyPairingCryptoC.B64(NearbyPairingCryptoC.Random(16));
            string initiatorFp=FingerprintProvider==null?"unavailable":FingerprintProvider();
            Dictionary<string,object> start=new Dictionary<string,object>{{"alias",AliasProvider==null?Environment.MachineName:AliasProvider()},{"fingerprint",initiatorFp},{"publicKey",initiatorPublic},{"requestNonce",requestNonce}};
            PairHttpResultC response=Post(device,"/api/clipmesh/v1/pair/start",start);
            if(response.Status!=200||response.Json==null)throw new InvalidOperationException("Pairing request was rejected.");
            string id=Convert.ToString(response.Json["sessionId"]),responderFp=Convert.ToString(response.Json["responderFingerprint"]),responderPublic=Convert.ToString(response.Json["responderPublicKey"]);
            byte[] secret=NearbyPairingCryptoC.Agree(key,NearbyPairingCryptoC.Un64(responderPublic));byte[] transcript=NearbyPairingCryptoC.Transcript(id,requestNonce,initiatorFp,responderFp,initiatorPublic,responderPublic);
            if(showCode!=null)showCode(NearbyPairingCryptoC.Code(secret,transcript));bool verified=false;
            for(int i=0;i<160;i++){PairHttpResultC state=Post(device,"/api/clipmesh/v1/pair/status",new Dictionary<string,object>{{"sessionId",id}});if(state.Status==200&&state.Json!=null&&Convert.ToBoolean(state.Json["verified"])){verified=true;break;}if(state.Status==403)break;Thread.Sleep(750);}
            if(!verified)throw new InvalidOperationException("The verification code was not confirmed.");byte[] nonce=NearbyPairingCryptoC.Random(16),plain=Encoding.UTF8.GetBytes(credential);byte[][] sealedValue=NearbyPairingCryptoC.Seal(plain,secret,transcript,nonce);
            PairHttpResultC done=Post(device,"/api/clipmesh/v1/pair/complete",new Dictionary<string,object>{{"sessionId",id},{"nonce",NearbyPairingCryptoC.B64(nonce)},{"ciphertext",NearbyPairingCryptoC.B64(sealedValue[0])},{"tag",NearbyPairingCryptoC.B64(sealedValue[1])}});if(done.Status!=200)throw new InvalidOperationException("The receiving device could not apply the pairing.");
        }
    }

    private void ServerLoop(){try{TcpListener l=new TcpListener(IPAddress.Any,Port);l.Start();listener=l;while(Running){TcpClient c;try{c=l.AcceptTcpClient();}catch{break;}ThreadPool.QueueUserWorkItem(delegate{try{Handle(c);}catch{}finally{c.Close();}});}}catch{}finally{listener=null;}}
    private void Handle(TcpClient client){client.ReceiveTimeout=70000;client.SendTimeout=70000;NetworkStream stream=client.GetStream();string line=ReadLine(stream);if(line==null)return;string[] first=line.Split(' ');Dictionary<string,string> headers=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);while(true){line=ReadLine(stream);if(String.IsNullOrEmpty(line))break;int colon=line.IndexOf(':');if(colon>0)headers[line.Substring(0,colon).Trim()]=line.Substring(colon+1).Trim();}long length=0;string len;if(headers.TryGetValue("Content-Length",out len))Int64.TryParse(len,out length);if(first.Length<2||first[0]!="POST"||length<0||length>65536){Respond(stream,400,new Dictionary<string,object>{{"error","invalid request"}});return;}byte[] body=ReadExact(stream,(int)length);Dictionary<string,object> root;try{root=json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(body));}catch{Respond(stream,400,new Dictionary<string,object>{{"error","invalid json"}});return;}Cleanup();Route(stream,first[1],root);}
    private void Route(Stream stream,string path,Dictionary<string,object> root){if(path=="/api/clipmesh/v1/pair/start"){Begin(stream,root);return;}object raw;if(!root.TryGetValue("sessionId",out raw)){Respond(stream,400,new Dictionary<string,object>{{"error","missing session"}});return;}string id=Convert.ToString(raw);PairReceiveSessionC session;lock(gate)sessions.TryGetValue(id,out session);if(session==null||session.Expires<DateTime.UtcNow){Respond(stream,404,new Dictionary<string,object>{{"error","expired"}});return;}if(path=="/api/clipmesh/v1/pair/status"){Respond(stream,session.Rejected?403:200,new Dictionary<string,object>{{"verified",session.Verified},{"rejected",session.Rejected}});return;}if(path=="/api/clipmesh/v1/pair/complete"){Complete(stream,root,session);return;}Respond(stream,404,new Dictionary<string,object>{{"error","not found"}});}
    private void Begin(Stream stream,Dictionary<string,object> root){try{string sender=Convert.ToString(root["alias"]),initiatorFp=Convert.ToString(root["fingerprint"]),initiatorPublic=Convert.ToString(root["publicKey"]),requestNonce=Convert.ToString(root["requestNonce"]);if(sender.Length>80||initiatorFp.Length>200||requestNonce.Length>100)throw new Exception();if(ApprovalPrompt==null||!ApprovalPrompt(sender)){Respond(stream,403,new Dictionary<string,object>{{"error","rejected"}});return;}using(ECDiffieHellmanCng key=NearbyPairingCryptoC.NewKey()){string responderPublic=NearbyPairingCryptoC.B64(NearbyPairingCryptoC.Public(key)),id=Guid.NewGuid().ToString("D").ToLowerInvariant(),responderFp=FingerprintProvider==null?"unavailable":FingerprintProvider();byte[] secret=NearbyPairingCryptoC.Agree(key,NearbyPairingCryptoC.Un64(initiatorPublic)),transcript=NearbyPairingCryptoC.Transcript(id,requestNonce,initiatorFp,responderFp,initiatorPublic,responderPublic);PairReceiveSessionC session=new PairReceiveSessionC{Id=id,Sender=sender,Secret=secret,Transcript=transcript,Code=NearbyPairingCryptoC.Code(secret,transcript)};lock(gate)sessions[id]=session;Respond(stream,200,new Dictionary<string,object>{{"sessionId",id},{"responderFingerprint",responderFp},{"responderPublicKey",responderPublic}});if(CodePrompt!=null)CodePrompt(sender,delegate(string entered){Verify(id,entered);});}}catch{Respond(stream,400,new Dictionary<string,object>{{"error","invalid pairing request"}});}}
    private void Verify(string id,string entered){lock(gate){PairReceiveSessionC s;if(!sessions.TryGetValue(id,out s)||s.Expires<DateTime.UtcNow)return;s.Verified=NearbyPairingCryptoC.Equal(Encoding.UTF8.GetBytes((entered??"").Trim()),Encoding.UTF8.GetBytes(s.Code));s.Rejected=!s.Verified;}}
    private void Complete(Stream stream,Dictionary<string,object> root,PairReceiveSessionC session){try{if(!session.Verified)throw new Exception();byte[] nonce=NearbyPairingCryptoC.Un64(Convert.ToString(root["nonce"])),cipher=NearbyPairingCryptoC.Un64(Convert.ToString(root["ciphertext"])),tag=NearbyPairingCryptoC.Un64(Convert.ToString(root["tag"]));if(nonce.Length!=16||cipher.Length>16384)throw new Exception();byte[] plain=NearbyPairingCryptoC.Open(cipher,tag,session.Secret,session.Transcript,nonce);string credential=plain==null?null:Encoding.UTF8.GetString(plain);if(credential==null||!credential.StartsWith("clipmesh://pair?",StringComparison.Ordinal)||CredentialConsumer==null||!CredentialConsumer(credential,session.Sender))throw new Exception();lock(gate)sessions.Remove(session.Id);Respond(stream,200,new Dictionary<string,object>{{"paired",true}});}catch{Respond(stream,403,new Dictionary<string,object>{{"error","authentication failed"}});}}
    private PairHttpResultC Post(TransferDeviceC device,string path,Dictionary<string,object> body){byte[] bytes=Encoding.UTF8.GetBytes(json.Serialize(body));HttpWebRequest request=(HttpWebRequest)WebRequest.Create("http://"+device.Address+":"+Port+path);request.Method="POST";request.ContentType="application/json";request.Timeout=65000;request.ReadWriteTimeout=65000;request.ContentLength=bytes.Length;using(Stream output=request.GetRequestStream())output.Write(bytes,0,bytes.Length);try{using(HttpWebResponse response=(HttpWebResponse)request.GetResponse())return Result(response);}catch(WebException e){HttpWebResponse response=e.Response as HttpWebResponse;return response==null?new PairHttpResultC{Status=0}:Result(response);}}
    private PairHttpResultC Result(HttpWebResponse response){using(response){string body;using(StreamReader reader=new StreamReader(response.GetResponseStream()))body=reader.ReadToEnd();Dictionary<string,object> parsed=null;try{parsed=json.Deserialize<Dictionary<string,object>>(body);}catch{}return new PairHttpResultC{Status=(int)response.StatusCode,Json=parsed};}}
    private void Cleanup(){DateTime now=DateTime.UtcNow;lock(gate){List<string> stale=new List<string>();foreach(KeyValuePair<string,PairReceiveSessionC> p in sessions)if(p.Value.Expires<now)stale.Add(p.Key);foreach(string id in stale)sessions.Remove(id);}}
    private void Respond(Stream output,int code,Dictionary<string,object> value){byte[] body=Encoding.UTF8.GetBytes(json.Serialize(value));string reason=code==200?"OK":code==400?"Bad Request":code==403?"Forbidden":code==404?"Not Found":"Error";byte[] header=Encoding.ASCII.GetBytes("HTTP/1.1 "+code+" "+reason+"\r\nContent-Type: application/json\r\nContent-Length: "+body.Length+"\r\nConnection: close\r\n\r\n");output.Write(header,0,header.Length);output.Write(body,0,body.Length);output.Flush();}
    private static string ReadLine(Stream input){MemoryStream b=new MemoryStream();while(b.Length<16384){int c=input.ReadByte();if(c<0)return b.Length==0?null:Encoding.GetEncoding(28591).GetString(b.ToArray());if(c==10)break;if(c!=13)b.WriteByte((byte)c);}return Encoding.GetEncoding(28591).GetString(b.ToArray());}
    private static byte[] ReadExact(Stream input,int length){byte[] data=new byte[length];int at=0;while(at<length){int n=input.Read(data,at,length-at);if(n<=0)throw new IOException("short body");at+=n;}return data;}
    public void Dispose(){Stop();}
}
