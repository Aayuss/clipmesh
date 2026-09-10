package dev.clipmesh.fileshare

import android.content.Context
import android.util.Base64
import dev.clipmesh.BackgroundRuntime
import dev.clipmesh.Pairing
import dev.clipmesh.SecretStore
import dev.clipmesh.SettingsStore
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.math.BigInteger
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URI
import java.net.URL
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.ECPoint
import java.security.spec.ECPublicKeySpec
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object NearbyPairingCrypto {
    const val PROTOCOL_NAME = "ClipMesh-Pair-v1"
    private val utf8 = Charsets.UTF_8

    fun b64(value: ByteArray): String = Base64.encodeToString(value, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
    fun un64(value: String): ByteArray = Base64.decode(value, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
    fun transcript(session:String, nonce:String, initiatorFp:String, responderFp:String, initiatorPublic:String, responderPublic:String):ByteArray = "$PROTOCOL_NAME\n$session\n$nonce\n$initiatorFp\n$responderFp\n$initiatorPublic\n$responderPublic".toByteArray(utf8)
    private fun hmac(key:ByteArray,data:ByteArray):ByteArray=Mac.getInstance("HmacSHA256").run{init(SecretKeySpec(key,"HmacSHA256"));doFinal(data)}
    private fun join(vararg values:ByteArray):ByteArray=ByteArrayOutputStream().use{out->values.forEach(out::write);out.toByteArray()}
    private fun expand(prk:ByteArray,info:ByteArray,count:Int):ByteArray{val out=ByteArrayOutputStream();var previous=byteArrayOf();var counter=1;while(out.size()<count){previous=hmac(prk,join(previous,info,byteArrayOf(counter.toByte())));out.write(previous);counter++};return out.toByteArray().copyOf(count)}
    private fun keys(agreementSecret:ByteArray,transcript:ByteArray):Pair<ByteArray,ByteArray>{val salt=MessageDigest.getInstance("SHA-256").digest(transcript);val material=expand(hmac(salt,agreementSecret),"clipmesh-nearby-pair-v1".toByteArray(utf8),64);return material.copyOfRange(0,32) to material.copyOfRange(32,64)}
    fun code(secret:ByteArray,transcript:ByteArray):String{val digest=hmac(keys(secret,transcript).second,join("sas\n".toByteArray(utf8),transcript));val number=(((digest[0].toLong()and 255L)shl 24)or((digest[1].toLong()and 255L)shl 16)or((digest[2].toLong()and 255L)shl 8)or(digest[3].toLong()and 255L))%1_000_000;return number.toString().padStart(6,'0')}
    private fun stream(key:ByteArray,nonce:ByteArray,count:Int):ByteArray{val out=ByteArrayOutputStream();var c=0;while(out.size()<count){out.write(hmac(key,join("stream\n".toByteArray(utf8),nonce,byteArrayOf((c ushr 24).toByte(),(c ushr 16).toByte(),(c ushr 8).toByte(),c.toByte()))));c++};return out.toByteArray().copyOf(count)}
    fun seal(plain:ByteArray,secret:ByteArray,transcript:ByteArray,nonce:ByteArray):Pair<ByteArray,ByteArray>{val keys=keys(secret,transcript);val pad=stream(keys.first,nonce,plain.size);val cipher=ByteArray(plain.size){(plain[it].toInt() xor pad[it].toInt()).toByte()};return cipher to hmac(keys.second,join("payload\n".toByteArray(utf8),transcript,nonce,cipher))}
    fun open(cipher:ByteArray,tag:ByteArray,secret:ByteArray,transcript:ByteArray,nonce:ByteArray):ByteArray?{val keys=keys(secret,transcript);val expected=hmac(keys.second,join("payload\n".toByteArray(utf8),transcript,nonce,cipher));if(!MessageDigest.isEqual(tag,expected))return null;val pad=stream(keys.first,nonce,cipher.size);return ByteArray(cipher.size){(cipher[it].toInt() xor pad[it].toInt()).toByte()}}

    fun newKey():KeyPair=KeyPairGenerator.getInstance("EC").apply{initialize(ECGenParameterSpec("secp256r1"),SecureRandom())}.generateKeyPair()
    private fun fixed(value:BigInteger):ByteArray{val raw=value.toByteArray();return when{raw.size==32->raw;raw.size>32->raw.copyOfRange(raw.size-32,raw.size);else->ByteArray(32-raw.size)+raw}}
    fun publicKey(pair:KeyPair):ByteArray{val p=(pair.public as java.security.interfaces.ECPublicKey).w;return byteArrayOf(4)+fixed(p.affineX)+fixed(p.affineY)}
    fun agree(pair:KeyPair,peer:ByteArray):ByteArray{require(peer.size==65&&peer[0].toInt()==4){"Invalid P-256 key"};val params=AlgorithmParameters.getInstance("EC").apply{init(ECGenParameterSpec("secp256r1"))}.getParameterSpec(ECParameterSpec::class.java);val point=ECPoint(BigInteger(1,peer.copyOfRange(1,33)),BigInteger(1,peer.copyOfRange(33,65)));val public=KeyFactory.getInstance("EC").generatePublic(ECPublicKeySpec(point,params));val raw=KeyAgreement.getInstance("ECDH").run{init(pair.private);doPhase(public,true);generateSecret()};return MessageDigest.getInstance("SHA-256").digest(raw)}
    fun selfTest(){val a=newKey();val b=newKey();val ab=agree(a,publicKey(b));val ba=agree(b,publicKey(a));check(MessageDigest.isEqual(ab,ba));val tr="self-test".toByteArray();val nonce=ByteArray(16);val plain="clipmesh://pair?self-test".toByteArray();val sealed=seal(plain,ab,tr,nonce);check(open(sealed.first,sealed.second,ba,tr,nonce)?.contentEquals(plain)==true)}
}

object NearbyPairingManager {
    const val PORT=53422
    private const val MAX_BODY=65_536
    private data class Session(val id:String,val sender:String,val code:String,val secret:ByteArray,val transcript:ByteArray,val expires:Long=System.currentTimeMillis()+120_000,@Volatile var verified:Boolean=false,@Volatile var rejected:Boolean=false)
    private data class HttpResult(val status:Int,val json:JSONObject?)
    private val started=java.util.concurrent.atomic.AtomicBoolean(false)
    private val executor=Executors.newCachedThreadPool()
    private val sessions=ConcurrentHashMap<String,Session>()
    @Volatile private var server:ServerSocket?=null
    @Volatile private var appContext:Context?=null

    fun start(context:Context){appContext=context.applicationContext;if(!started.compareAndSet(false,true))return;NearbyPairingCrypto.selfTest();executor.execute(::serverLoop)}
    fun stop(){started.set(false);runCatching{server?.close()};server=null;sessions.clear()}
    fun pairClipboard(context:Context,target:LocalTransferEngine.TransferDevice,credential:String,onCode:(String)->Unit,done:(Result<Unit>)->Unit){start(context);executor.execute{runCatching{pair(target,credential,onCode)}.fold({done(Result.success(Unit))},{done(Result.failure(it))})}}
    private fun pair(target:LocalTransferEngine.TransferDevice,credential:String,onCode:(String)->Unit){val key=NearbyPairingCrypto.newKey();val initiatorPublic=NearbyPairingCrypto.b64(NearbyPairingCrypto.publicKey(key));val requestNonce=NearbyPairingCrypto.b64(ByteArray(16).also(SecureRandom()::nextBytes));val context=requireNotNull(appContext);val initiatorFp=LocalTransferEngine.fingerprint(context);val response=post(target,"/api/clipmesh/v1/pair/start",JSONObject().put("alias",SettingsStore(context).deviceName).put("fingerprint",initiatorFp).put("publicKey",initiatorPublic).put("requestNonce",requestNonce));check(response.status==200&&response.json!=null){"Pairing request was rejected"};val root=requireNotNull(response.json);val id=root.getString("sessionId");val responderFp=root.getString("responderFingerprint");val responderPublic=root.getString("responderPublicKey");val secret=NearbyPairingCrypto.agree(key,NearbyPairingCrypto.un64(responderPublic));val transcript=NearbyPairingCrypto.transcript(id,requestNonce,initiatorFp,responderFp,initiatorPublic,responderPublic);onCode(NearbyPairingCrypto.code(secret,transcript));var verified=false;for(i in 0 until 160){val state=post(target,"/api/clipmesh/v1/pair/status",JSONObject().put("sessionId",id));if(state.status==200&&state.json?.optBoolean("verified")==true){verified=true;break};if(state.status==403)throw IllegalStateException("Verification code rejected");Thread.sleep(750)};check(verified){"The verification code was not confirmed"};val nonce=ByteArray(16).also(SecureRandom()::nextBytes);val sealed=NearbyPairingCrypto.seal(credential.toByteArray(),secret,transcript,nonce);val complete=post(target,"/api/clipmesh/v1/pair/complete",JSONObject().put("sessionId",id).put("nonce",NearbyPairingCrypto.b64(nonce)).put("ciphertext",NearbyPairingCrypto.b64(sealed.first)).put("tag",NearbyPairingCrypto.b64(sealed.second)));check(complete.status==200){"Receiving device could not apply pairing"}}

    private fun serverLoop(){try{val listener=ServerSocket().apply{reuseAddress=true;bind(InetSocketAddress(PORT))};server=listener;while(started.get()){val socket=runCatching{listener.accept()}.getOrNull()?:break;executor.execute{runCatching{handle(socket)};runCatching{socket.close()}}}}finally{server=null}}
    private fun handle(socket:Socket){socket.soTimeout=70_000;val input=BufferedInputStream(socket.getInputStream());val output=BufferedOutputStream(socket.getOutputStream());val first=readLine(input)?.split(' ')?:return;val headers=mutableMapOf<String,String>();while(true){val line=readLine(input)?:break;if(line.isEmpty())break;val colon=line.indexOf(':');if(colon>0)headers[line.substring(0,colon).trim().lowercase()]=line.substring(colon+1).trim()};val length=headers["content-length"]?.toIntOrNull()?:0;if(first.size<2||first[0]!="POST"||length !in 0..MAX_BODY)return respond(output,400,JSONObject().put("error","invalid request"));val root=runCatching{JSONObject(String(readExact(input,length),Charsets.UTF_8))}.getOrElse{return respond(output,400,JSONObject().put("error","invalid json"))};cleanup();route(output,first[1],root)}
    private fun route(output:OutputStream,path:String,root:JSONObject){if(path=="/api/clipmesh/v1/pair/start")return begin(output,root);val id=root.optString("sessionId");val session=sessions[id]?.takeIf{it.expires>System.currentTimeMillis()}?:return respond(output,404,JSONObject().put("error","expired"));when(path){"/api/clipmesh/v1/pair/status"->respond(output,if(session.rejected)403 else 200,JSONObject().put("verified",session.verified).put("rejected",session.rejected));"/api/clipmesh/v1/pair/complete"->complete(output,root,session);else->respond(output,404,JSONObject().put("error","not found"))}}
    private fun begin(output:OutputStream,root:JSONObject){val sender=root.optString("alias").take(80);val initiatorFp=root.optString("fingerprint").take(200);val initiatorPublic=root.optString("publicKey");val requestNonce=root.optString("requestNonce").take(100);if(sender.isBlank()||initiatorFp.isBlank()||runCatching{NearbyPairingCrypto.un64(initiatorPublic).size==65}.getOrDefault(false).not())return respond(output,400,JSONObject().put("error","invalid request"));if(!NearbyPairingUi.approve(sender))return respond(output,403,JSONObject().put("error","rejected"));runCatching{val key=NearbyPairingCrypto.newKey();val responderPublic=NearbyPairingCrypto.b64(NearbyPairingCrypto.publicKey(key));val id=UUID.randomUUID().toString();val context=requireNotNull(appContext);val responderFp=LocalTransferEngine.fingerprint(context);val secret=NearbyPairingCrypto.agree(key,NearbyPairingCrypto.un64(initiatorPublic));val transcript=NearbyPairingCrypto.transcript(id,requestNonce,initiatorFp,responderFp,initiatorPublic,responderPublic);sessions[id]=Session(id,sender,NearbyPairingCrypto.code(secret,transcript),secret,transcript);respond(output,200,JSONObject().put("sessionId",id).put("responderFingerprint",responderFp).put("responderPublicKey",responderPublic));NearbyPairingUi.promptCode(sender){entered->verify(id,entered)}}.onFailure{respond(output,400,JSONObject().put("error","invalid public key"))}}
    private fun verify(id:String,entered:String?){sessions[id]?.takeIf{it.expires>System.currentTimeMillis()}?.let{it.verified=MessageDigest.isEqual(entered.orEmpty().trim().toByteArray(),it.code.toByteArray());it.rejected=!it.verified}}
    private fun complete(output:OutputStream,root:JSONObject,session:Session){val accepted=runCatching{check(session.verified);val nonce=NearbyPairingCrypto.un64(root.getString("nonce"));val cipher=NearbyPairingCrypto.un64(root.getString("ciphertext"));val tag=NearbyPairingCrypto.un64(root.getString("tag"));check(nonce.size==16&&cipher.size<=16_384);val plain=NearbyPairingCrypto.open(cipher,tag,session.secret,session.transcript,nonce)?:error("auth");val uri=String(plain,Charsets.UTF_8);check(uri.startsWith("clipmesh://pair?"));applyCredential(uri);true}.getOrDefault(false);if(!accepted)return respond(output,403,JSONObject().put("error","authentication failed"));sessions.remove(session.id);respond(output,200,JSONObject().put("paired",true))}
    private fun applyCredential(uri:String){val context=requireNotNull(appContext);val parsed=Pairing.parse(uri);val settings=SettingsStore(context);val secrets=SecretStore(context);settings.spaceId=parsed.spaceId;secrets.saveSpaceKey(parsed.key);settings.clearKnownPeers();parsed.deviceId?.takeIf{it!=settings.deviceId}?.let{settings.seedPeer(it,parsed.name)};settings.backgroundSync=true;executor.execute{Thread.sleep(500);BackgroundRuntime.restart(context)}}
    private fun post(target:LocalTransferEngine.TransferDevice,path:String,body:JSONObject):HttpResult{val connection=(URL("http://${target.address}:$PORT$path").openConnection()as HttpURLConnection).apply{requestMethod="POST";connectTimeout=65_000;readTimeout=65_000;doOutput=true;setRequestProperty("Content-Type","application/json")};connection.outputStream.use{it.write(body.toString().toByteArray())};val status=runCatching{connection.responseCode}.getOrDefault(0);val stream=if(status in 200..399)connection.inputStream else connection.errorStream;val text=stream?.bufferedReader()?.use{it.readText()}.orEmpty();connection.disconnect();return HttpResult(status,runCatching{JSONObject(text)}.getOrNull())}
    private fun cleanup(){val now=System.currentTimeMillis();sessions.entries.removeIf{it.value.expires<now}}
    private fun respond(output:OutputStream,code:Int,json:JSONObject){val body=json.toString().toByteArray();val reason=if(code==200)"OK"else if(code==400)"Bad Request"else if(code==403)"Forbidden"else if(code==404)"Not Found"else"Error";output.write("HTTP/1.1 $code $reason\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray(Charsets.US_ASCII));output.write(body);output.flush()}
    private fun readLine(input:InputStream):String?{val out=ByteArrayOutputStream();while(out.size()<16_384){val b=input.read();if(b<0)return if(out.size()==0)null else out.toString("ISO-8859-1");if(b==10)break;if(b!=13)out.write(b)};return out.toString("ISO-8859-1")}
    private fun readExact(input:InputStream,length:Int):ByteArray{val data=ByteArray(length);var at=0;while(at<length){val n=input.read(data,at,length-at);if(n<=0)error("short body");at+=n};return data}
}
