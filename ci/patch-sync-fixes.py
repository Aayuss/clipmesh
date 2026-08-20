from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
ci = root / "ci"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Shizuku: use the lifecycle-safe implementation with sticky binder delivery and
# permission-result listeners. It never asks Shizuku to kill/remove its server.
shutil.copyfile(
    ci / "ShizukuManager.kt.sync-fixed",
    project / "android/app/src/main/java/dev/clipmesh/shizuku/ShizukuManager.kt",
)

user_service = project / "android/app/src/main/java/dev/clipmesh/shizuku/ClipboardUserService.kt"
replace_once(
    user_service,
    """        init {\n            if (android.os.Process.myUid() == 0) {\n                runCatching {\n                    android.system.Os.setgid(2000)\n                    android.system.Os.setuid(2000)\n                }\n            }\n        }\n\n""",
    """        // Shizuku owns the UserService execution identity. Do not mutate\n        // process UID/GID ourselves; doing so is brittle on OEM Android builds.\n\n""",
    "Shizuku UserService UID mutation removal",
)
replace_once(
    user_service,
    """    override fun init(callerToken: IBinder) {\n        runCatching { callerToken.linkToDeath({ destroy() }, 0) }\n    }\n""",
    """    override fun init(callerToken: IBinder) {\n        // Shizuku owns this process lifecycle. Never terminate a process from a\n        // caller-token death callback.\n    }\n""",
    "Shizuku caller death shutdown removal",
)
replace_once(
    user_service,
    """    override fun destroy() {\n        lastClip = null\n        clipboardService = null\n        kotlin.system.exitProcess(0)\n    }\n""",
    """    override fun destroy() {\n        lastClip = null\n        clipboardService = null\n    }\n""",
    "Shizuku exitProcess removal",
)

# Android clipboard bridge: prevent capture work from queueing behind a first-time
# Shizuku bind, and make remote clipboard writes failure-safe.
bridge = project / "android/app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
replace_once(
    bridge,
    "import java.util.concurrent.atomic.AtomicReference",
    "import java.util.concurrent.atomic.AtomicBoolean\nimport java.util.concurrent.atomic.AtomicReference",
    "Clipboard capture AtomicBoolean import",
)
replace_once(
    bridge,
    """    private val lastWatchdogFingerprint = AtomicReference<String?>(null)\n    private val captureExecutor""",
    """    private val lastWatchdogFingerprint = AtomicReference<String?>(null)\n    private val captureInFlight = AtomicBoolean(false)\n    private val captureExecutor""",
    "Clipboard capture in-flight flag",
)
replace_once(
    bridge,
    """    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)\n\n    private fun captureAsync(fromWatchdog: Boolean) {\n        if (!started || !settings.sendEnabled) return\n        val sourcePackage = ForegroundTracker.currentPackage\n        if (sourcePackage != null && settings.excludedPackages.contains(sourcePackage)) return\n        captureExecutor.execute {\n            val payload = readCurrent(sourcePackage) ?: return@execute\n            val fp = payload.stableFingerprint()\n            if (suppressedFingerprint.compareAndSet(fp, null)) {\n                lastWatchdogFingerprint.set(fp)\n                return@execute\n            }\n            if (fromWatchdog && lastWatchdogFingerprint.getAndSet(fp) == fp) return@execute\n            lastWatchdogFingerprint.set(fp)\n            onLocalClip(payload)\n        }\n    }""",
    """    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)\n    fun captureNowForBackgroundMonitor() = captureAsync(fromWatchdog = true)\n\n    private fun captureAsync(fromWatchdog: Boolean) {\n        if (!started || !settings.sendEnabled) return\n        val sourcePackage = ForegroundTracker.currentPackage\n        if (sourcePackage != null && settings.excludedPackages.contains(sourcePackage)) return\n        if (!captureInFlight.compareAndSet(false, true)) return\n        captureExecutor.execute {\n            try {\n                val payload = readCurrent(sourcePackage) ?: return@execute\n                val fp = payload.stableFingerprint()\n                if (suppressedFingerprint.compareAndSet(fp, null)) {\n                    lastWatchdogFingerprint.set(fp)\n                    return@execute\n                }\n                if (fromWatchdog && lastWatchdogFingerprint.getAndSet(fp) == fp) return@execute\n                lastWatchdogFingerprint.set(fp)\n                onLocalClip(payload)\n            } finally {\n                captureInFlight.set(false)\n            }\n        }\n    }""",
    "Clipboard capture serialization",
)
replace_once(
    bridge,
    """        if (plain != null && html == null && shizuku.hasPermission()) {\n            val text = String(plain.data)\n            if (shizuku.setText(text)) return\n        }\n        main.post {\n            when {\n                payload.files.isNotEmpty() -> setFiles(payload.files)\n                image != null -> setSingleBinary(\"clipboard-${System.currentTimeMillis()}.${extension(image.mime)}\", image.mime, image.data)\n                plain != null -> {\n                    val text = String(plain.data)\n                    val htmlText = html?.let { String(it.data) }\n                    if (htmlText != null) clipboard.setPrimaryClip(ClipData.newHtmlText(\"ClipMesh\", text, htmlText))\n                    else clipboard.setPrimaryClip(ClipData.newPlainText(\"ClipMesh\", text))\n                }\n            }\n        }""",
    """        if (plain != null && html == null && shizuku.hasPermission()) {\n            val text = plain.data.toString(Charsets.UTF_8)\n            if (shizuku.setText(text)) return\n        }\n        main.post {\n            runCatching {\n                when {\n                    payload.files.isNotEmpty() -> setFiles(payload.files)\n                    image != null -> setSingleBinary(\"clipboard-${System.currentTimeMillis()}.${extension(image.mime)}\", image.mime, image.data)\n                    plain != null -> {\n                        val text = plain.data.toString(Charsets.UTF_8)\n                        val htmlText = html?.let { it.data.toString(Charsets.UTF_8) }\n                        if (htmlText != null) clipboard.setPrimaryClip(ClipData.newHtmlText(\"ClipMesh\", text, htmlText))\n                        else clipboard.setPrimaryClip(ClipData.newPlainText(\"ClipMesh\", text))\n                    }\n                }\n            }\n        }""",
    "Android remote clipboard safe write",
)

# Android sync service: background ClipboardManager callbacks are not reliable on
# Android 10+. Use Shizuku snapshots while the screen is interactive and a real,
# authenticated peer is connected. No wake lock is held, and the loop backs off
# completely when there is no peer. Upstream UniClip polls every 500 ms; ClipMesh
# uses 750 ms only in the active/connected state to reduce battery use.
sync = project / "android/app/src/main/java/dev/clipmesh/SyncService.kt"
replace_once(sync, "    private var shizuku: ShizukuManager? = null\n    private var watchdog: Job? = null",
             "    private var shizuku: ShizukuManager? = null\n    private var shizukuMonitor: Job? = null\n    private var watchdog: Job? = null", "Shizuku monitor field")
replace_once(sync, "    override fun onDestroy() {\n        watchdog?.cancel()",
             "    override fun onDestroy() {\n        shizukuMonitor?.cancel()\n        watchdog?.cancel()", "Shizuku monitor shutdown")
replace_once(
    sync,
    """        bridge.start()\n        net.start()\n\n        // Optional compatibility watchdog: OFF by default. It runs only while the\n        // screen is interactive and exists for OEMs that suppress clipboard callbacks.\n        if (settings.compatibilityWatchdog) {\n            val power = getSystemService(Context.POWER_SERVICE) as PowerManager\n            watchdog = scope.launch {\n                while (isActive) {\n                    if (power.isInteractive) bridge.captureNowForWatchdog()\n                    delay(5_000L)\n                }\n            }\n        }""",
    """        bridge.start()\n        net.start()\n\n        val power = getSystemService(Context.POWER_SERVICE) as PowerManager\n        shizukuMonitor = scope.launch {\n            while (isActive) {\n                val connected = net.peerCount() > 0\n                if (connected && power.isInteractive && settings.sendEnabled && sh.hasPermission()) {\n                    bridge.captureNowForBackgroundMonitor()\n                    delay(750L)\n                } else {\n                    delay(if (connected) 1_500L else 3_000L)\n                }\n            }\n        }\n\n        // Optional non-Shizuku OEM fallback. OFF by default.\n        if (settings.compatibilityWatchdog) {\n            watchdog = scope.launch {\n                while (isActive) {\n                    if (power.isInteractive && !sh.hasPermission()) bridge.captureNowForWatchdog()\n                    delay(5_000L)\n                }\n            }\n        }""",
    "Android active-peer Shizuku monitor",
)
sync_text = sync.read_text(encoding="utf-8")
if ".setSmallIcon(android.R.drawable.ic_menu_share)" in sync_text:
    sync.write_text(sync_text.replace(".setSmallIcon(android.R.drawable.ic_menu_share)", ".setSmallIcon(R.drawable.ic_clipmesh_notification)", 1), encoding="utf-8")
elif ".setSmallIcon(R.drawable.ic_clipmesh_notification)" not in sync_text:
    raise SystemExit("Android notification icon source was not found")

# The peer list could update from discovery even while the actual TCP connection was
# repeatedly destroyed by simultaneous dual-connect races. Make connection ownership
# deterministic: the lexicographically smaller UUID initiates; the larger accepts.
android_network = project / "android/app/src/main/java/dev/clipmesh/network/NetworkEngine.kt"
replace_once(
    android_network,
    """                    if (peers.containsKey(d.deviceId)) continue\n                    scope.launch { connect(packet.address, d.port) }""",
    """                    if (peers.containsKey(d.deviceId)) continue\n                    if (shouldInitiate(settings.deviceId, d.deviceId)) {\n                        scope.launch { connect(packet.address, d.port) }\n                    }""",
    "Android deterministic discovery connection",
)
replace_once(
    android_network,
    """            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())\n\n            val connection = PeerConnection""",
    """            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())\n            val preferredOutgoing = shouldInitiate(settings.deviceId, peerId)\n            if (outgoing != preferredOutgoing) {\n                socket.close()\n                return@withContext\n            }\n\n            val connection = PeerConnection""",
    "Android deterministic authenticated connection",
)
replace_once(
    android_network,
    """    private fun pendingKey(peer: UUID, message: UUID) = \"$peer|$message\"\n\n    private fun parsePeer""",
    """    private fun pendingKey(peer: UUID, message: UUID) = \"$peer|$message\"\n\n    private fun shouldInitiate(local: UUID, remote: UUID): Boolean =\n        local.toString().compareTo(remote.toString(), ignoreCase = true) < 0\n\n    private fun parsePeer""",
    "Android deterministic initiator helper",
)

desktop_network = project / "apps/desktop/src/network.rs"
replace_once(
    desktop_network,
    """                if peers.contains_key(&packet.device_id) { continue; }\n                let target=SocketAddr::new(addr.ip(),packet.port);""",
    """                if peers.contains_key(&packet.device_id) { continue; }\n                if cfg.device_id.as_bytes() >= packet.device_id.as_bytes() { continue; }\n                let target=SocketAddr::new(addr.ip(),packet.port);""",
    "desktop deterministic discovery connection",
)
replace_once(
    desktop_network,
    """    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());\n    info!(peer=%peer_id,addr=%peer_addr,\"peer authenticated\");""",
    """    let _=Config::touch_peer(cfg.space_id,peer_id,&peer_addr.ip().to_string());\n    let preferred_outgoing = cfg.device_id.as_bytes() < peer_id.as_bytes();\n    if outgoing != preferred_outgoing {\n        debug!(peer=%peer_id,addr=%peer_addr,\"closing non-preferred duplicate connection\");\n        return Ok(());\n    }\n    info!(peer=%peer_id,addr=%peer_addr,\"peer authenticated\");""",
    "desktop deterministic authenticated connection",
)

manifest = project / "android/app/src/main/AndroidManifest.xml"
replace_once(
    manifest,
    '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_SPECIAL_USE" />',
    '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_SPECIAL_USE" />\n    <uses-permission android:name="moe.shizuku.manager.permission.API_V23" />',
    "explicit Shizuku permission",
)
replace_once(
    manifest,
    """    <queries>\n        <intent>""",
    """    <queries>\n        <package android:name=\"moe.shizuku.privileged.api\" />\n        <intent>""",
    "Shizuku package visibility",
)
replace_once(
    manifest,
    """        <activity\n            android:name=\".SettingsActivity\"\n            android:exported=\"false\" />""",
    """        <activity\n            android:name=\".SettingsActivity\"\n            android:exported=\"false\" />\n\n        <activity\n            android:name=\".ExclusionActivity\"\n            android:exported=\"false\" />""",
    "ExclusionActivity registration",
)
replace_once(
    manifest,
    """        <service\n            android:name=\".exclusion.ExclusionAccessibilityService\"\n            android:permission=\"android.permission.BIND_ACCESSIBILITY_SERVICE\"""",
    """        <service\n            android:name=\".exclusion.ExclusionAccessibilityService\"\n            android:label=\"@string/exclusion_service_label\"\n            android:permission=\"android.permission.BIND_ACCESSIBILITY_SERVICE\"""",
    "Accessibility service label",
)

strings = project / "android/app/src/main/res/values/strings.xml"
replace_once(strings, "</resources>", "    <string name=\"exclusion_service_label\">ClipMesh app exclusions</string>\n</resources>", "Accessibility service label string")

settings_activity = project / "android/app/src/main/java/dev/clipmesh/SettingsActivity.kt"
replace_once(settings_activity, "import android.graphics.Color", "import android.graphics.Color\nimport android.net.Uri", "Settings Uri import")
replace_once(
    settings_activity,
    """        accessCard.addView(button(\"Request Shizuku permission\") {\n            when {\n                !shizuku.isAvailable() -> toast(\"Start or install Shizuku first\")\n                shizuku.hasPermission() -> toast(\"Shizuku is already authorized\")\n                else -> shizuku.requestPermission()\n            }\n        })""",
    """        accessCard.addView(button(\"Request Shizuku permission\") {\n            when {\n                !shizuku.isAvailable() -> {\n                    packageManager.getLaunchIntentForPackage(\"moe.shizuku.privileged.api\")?.let { startActivity(it) }\n                    toast(\"Shizuku is not connected. Start it, then return to ClipMesh and tap this button again.\")\n                }\n                shizuku.hasPermission() -> toast(\"Shizuku is authorized and ready\")\n                shizuku.requestPermission() -> toast(\"Shizuku permission request sent\")\n                else -> toast(\"Shizuku permission is unavailable. Check Shizuku and try again.\")\n            }\n        })""",
    "Shizuku permission UX",
)
replace_once(
    settings_activity,
    """        privacyCard.addView(button(\"Choose excluded apps\", false) {\n            startActivity(Intent(this, ExclusionActivity::class.java))\n        })\n        privacyCard.addView(button(\"Accessibility settings\", false) {\n            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))\n        }, fullWidthParams(dp(48)).apply { topMargin = dp(8) })""",
    """        privacyCard.addView(button(\"Choose excluded apps\", false) {\n            startActivity(Intent(this, ExclusionActivity::class.java))\n        })\n        privacyCard.addView(label(\n            \"Android 13+ restricts Accessibility for sideloaded APKs. If ClipMesh is missing or blocked there: open ClipMesh app info, use the top-right menu → Allow restricted settings, then return to Accessibility and enable ‘ClipMesh app exclusions’.\",\n            12f, false, muted\n        ).apply { setPadding(0, dp(10), 0, dp(8)) })\n        privacyCard.addView(button(\"Open ClipMesh app info\", false) {\n            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse(\"package:$packageName\")))\n        }, fullWidthParams(dp(48)))\n        privacyCard.addView(button(\"Accessibility settings\", false) {\n            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))\n        }, fullWidthParams(dp(48)).apply { topMargin = dp(8) })""",
    "Android restricted Accessibility guidance",
)

print("Applied v0.1.4 Android Shizuku, clipboard transport, accessibility, and exclusion fixes")
