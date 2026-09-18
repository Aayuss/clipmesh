from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"


def replace(path: Path, old: str, new: str, label: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8"); found = text.count(old)
    if found != count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")

def regex(path: Path, pattern: str, repl: str, label: str, count: int = 1, flags: int = re.S) -> None:
    text = path.read_text(encoding="utf-8"); updated, found = re.subn(pattern, lambda _m: repl, text, count=count, flags=flags)
    if found != count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(updated, encoding="utf-8")

main = PROJECT / "android/app/src/main/java/dev/clipmesh/MainActivity.kt"
pairing = PROJECT / "android/app/src/main/java/dev/clipmesh/fileshare/NearbyPairingManager.kt"
pair_ui = PROJECT / "android/app/src/main/java/dev/clipmesh/fileshare/NearbyPairingUi.kt"
dialog_ui = PROJECT / "android/app/src/main/java/dev/clipmesh/ClipMeshDialog.kt"
regex(pairing,r"    private fun pair\(target:LocalTransferEngine\.TransferDevice,credential:String,onCode:\(String\)->Unit\)\{.*?\}\n\n    private fun serverLoop",r'''    private fun pair(target:LocalTransferEngine.TransferDevice,credential:String,onCode:(String)->Unit){
        val key=NearbyPairingCrypto.newKey();val initiatorPublic=NearbyPairingCrypto.b64(NearbyPairingCrypto.publicKey(key));val requestNonce=NearbyPairingCrypto.b64(ByteArray(16).also(SecureRandom()::nextBytes));val context=requireNotNull(appContext);val initiatorFp=LocalTransferEngine.fingerprint(context)
        val response=post(target,"/api/clipmesh/v1/pair/start",JSONObject().put("alias",SettingsStore(context).deviceName).put("fingerprint",initiatorFp).put("publicKey",initiatorPublic).put("requestNonce",requestNonce));check(response.status==200&&response.json!=null){"Pairing request was rejected"}
        val root=requireNotNull(response.json);val id=root.getString("sessionId");val responderFp=root.getString("responderFingerprint");val responderPublic=root.getString("responderPublicKey");val responderId=UUID.fromString(root.getString("responderDeviceId"));val responderName=root.optString("responderName",target.alias).ifBlank{target.alias}
        val secret=NearbyPairingCrypto.agree(key,NearbyPairingCrypto.un64(responderPublic));val transcript=NearbyPairingCrypto.transcript(id,requestNonce,initiatorFp,responderFp,initiatorPublic,responderPublic);onCode(NearbyPairingCrypto.code(secret,transcript))
        var verified=false;for(i in 0 until 80){val state=post(target,"/api/clipmesh/v1/pair/status",JSONObject().put("sessionId",id));if(state.status==200&&state.json?.optBoolean("verified")==true){verified=true;break};if(state.status==403)throw IllegalStateException("Verification code rejected");Thread.sleep(1500)};check(verified){"The verification code was not confirmed"}
        val nonce=ByteArray(16).also(SecureRandom()::nextBytes);val sealed=NearbyPairingCrypto.seal(credential.toByteArray(),secret,transcript,nonce);val complete=post(target,"/api/clipmesh/v1/pair/complete",JSONObject().put("sessionId",id).put("nonce",NearbyPairingCrypto.b64(nonce)).put("ciphertext",NearbyPairingCrypto.b64(sealed.first)).put("tag",NearbyPairingCrypto.b64(sealed.second)));check(complete.status==200){"Receiving device could not apply pairing"}
        val settings=SettingsStore(context);settings.seedPeer(responderId,responderName);settings.backgroundSync=true;BackgroundRuntime.restart(context)
    }

    private fun serverLoop''',"android bidirectional nearby pairing")
replace(pairing,'respond(output,200,JSONObject().put("sessionId",id).put("responderFingerprint",responderFp).put("responderPublicKey",responderPublic));NearbyPairingUi.promptCode(sender){entered->verify(id,entered)}','respond(output,200,JSONObject().put("sessionId",id).put("responderFingerprint",responderFp).put("responderPublicKey",responderPublic).put("responderDeviceId",SettingsStore(context).deviceId.toString()).put("responderName",SettingsStore(context).deviceName));NearbyPairingUi.promptCode(sender){entered->verify(id,entered)}',"android advertise clipboard identity")
replace(pairing,'settings.spaceId=parsed.spaceId;secrets.saveSpaceKey(parsed.key);settings.clearKnownPeers();parsed.deviceId?.takeIf{it!=settings.deviceId}?.let{settings.seedPeer(it,parsed.name)};','val previousSpace=settings.spaceId;settings.spaceId=parsed.spaceId;secrets.saveSpaceKey(parsed.key);if(previousSpace!=parsed.spaceId)settings.clearKnownPeers();parsed.deviceId?.takeIf{it!=settings.deviceId}?.let{settings.seedPeer(it,parsed.name)};NearbyPairingUi.notifyPaired();',"android preserve same-space peer list")
replace(main,"    private lateinit var nearbyPairContainer: LinearLayout","    private lateinit var nearbyPairContainer: LinearLayout\n    private var nearbyCodeDialog: android.app.AlertDialog? = null","android pair dialog property")
regex(main,r"    private fun startNearbyPair\(device:LocalTransferEngine\.TransferDevice\)\{.*?\}\n\n    private fun renderPeers",r'''    private fun startNearbyPair(device: LocalTransferEngine.TransferDevice) {
        val space=settings.spaceId?:run{toast("Create or join a clipboard space first");return}
        val key=secrets.loadSpaceKey()?:run{toast("Clipboard key is unavailable");return}
        val credential=Pairing.toUri(Pairing.PairingData(space,key,settings.deviceName,settings.deviceId))
        status.text="Waiting for ${device.alias}…"
        NearbyPairingManager.pairClipboard(this,device,credential,{value->runOnUiThread{showNearbyCode(device.alias,value)}},{result->runOnUiThread{
            nearbyCodeDialog?.dismiss();nearbyCodeDialog=null
            result.fold({status.text="Paired with ${device.alias}";LocalTransferEngine.discoverNow();refreshHome();renderNearbyPairDevices()},{toast(it.message?:"Pairing failed");refreshHome()})
        }})
    }

    private fun showNearbyCode(device: String, value: String) {
        nearbyCodeDialog?.dismiss()
        val code=android.widget.TextView(this).apply{text=value;textSize=46f;typeface=android.graphics.Typeface.MONOSPACE;gravity=Gravity.CENTER;setTextColor(ink);setPadding(dp(8),dp(20),dp(8),dp(20));letterSpacing=.14f}
        nearbyCodeDialog=android.app.AlertDialog.Builder(this).setTitle("Verification code").setMessage("Type this code on $device. This closes automatically when pairing completes.").setView(code).create().also{it.setCanceledOnTouchOutside(false);it.show()}
    }

    private fun renderPeers''',"android auto-dismiss large pair code")


replace(main,
    "        NearbyPairingUi.attach(this)",
    "        NearbyPairingUi.attach(this) { refreshHome(); renderNearbyPairDevices() }",
    "android automatic receiver pairing refresh")

replace(dialog_ui,
    "fun prompt(activity: Activity, title: String, message: String, initial: String = \"\", numeric: Boolean = false, multiline: Boolean = false, done: (String?) -> Unit) {",
    "fun prompt(activity: Activity, title: String, message: String, initial: String = \"\", numeric: Boolean = false, multiline: Boolean = false, emphasized: Boolean = false, done: (String?) -> Unit) {",
    "android emphasized prompt signature")
replace(dialog_ui,
    "setText(initial); setTextColor(INK); setHintTextColor(MUTED); textSize = 15f",
    "setText(initial); setTextColor(INK); setHintTextColor(MUTED); textSize = if (emphasized) 34f else 15f; if (emphasized) { typeface = Typeface.MONOSPACE; gravity = Gravity.CENTER; letterSpacing = .16f; hint = \"000000\" }",
    "android emphasized pairing input")
pair_ui.write_text(r'''package dev.clipmesh.fileshare

import android.app.Activity
import dev.clipmesh.ClipMeshDialog
import java.lang.ref.WeakReference
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object NearbyPairingUi {
    @Volatile private var visible = WeakReference<Activity>(null)
    @Volatile private var pairedCallback: (() -> Unit)? = null

    fun attach(activity: Activity, onPaired: (() -> Unit)? = null) {
        visible = WeakReference(activity)
        pairedCallback = onPaired
    }

    fun detach(activity: Activity) {
        if (visible.get() === activity) {
            visible.clear()
            pairedCallback = null
        }
    }

    fun approve(sender: String): Boolean {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return false
        val latch = CountDownLatch(1)
        var accepted = false
        activity.runOnUiThread {
            ClipMeshDialog.confirm(activity, "Clipboard pairing request", "$sender wants to pair with this device for encrypted clipboard sync.") {
                accepted = it
                latch.countDown()
            }
        }
        latch.await(60, TimeUnit.SECONDS)
        return accepted
    }

    fun promptCode(sender: String, submit: (String?) -> Unit) {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return submit(null)
        activity.runOnUiThread {
            ClipMeshDialog.prompt(
                activity,
                "Verify $sender",
                "Type the six-digit code shown on $sender. This authenticates the encrypted connection.",
                numeric = true,
                emphasized = true,
            ) { submit(it) }
        }
    }

    fun notifyPaired() {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return
        activity.runOnUiThread { pairedCallback?.invoke() }
    }
}
''', encoding="utf-8")
