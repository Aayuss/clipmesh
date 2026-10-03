# v063 Android build integration: Jetpack Compose + Sora, single-activity host.
# Executed by ci/patch-v063-ember-ui.py with ROOT, PROJECT, LAYER, replace_once, regex_once in scope.
android = PROJECT / "android"
gradle = android / "app/build.gradle.kts"
manifest = android / "app/src/main/AndroidManifest.xml"

replace_once(
    android / "build.gradle.kts",
    '    id("org.jetbrains.kotlin.android") version "2.3.21" apply false\n',
    '    id("org.jetbrains.kotlin.android") version "2.3.21" apply false\n'
    '    id("org.jetbrains.kotlin.plugin.compose") version "2.3.21" apply false\n',
    "v063 root Compose compiler plugin",
)
replace_once(
    gradle,
    '    id("org.jetbrains.kotlin.android")\n}',
    '    id("org.jetbrains.kotlin.android")\n    id("org.jetbrains.kotlin.plugin.compose")\n}',
    "v063 app Compose compiler plugin",
)
replace_once(
    gradle,
    "        buildConfig = true\n        aidl = true\n",
    "        buildConfig = true\n        aidl = true\n        compose = true\n",
    "v063 Compose build feature",
)
replace_once(
    gradle,
    '    implementation("dev.rikka.shizuku:provider:13.1.5")\n',
    '''    implementation("dev.rikka.shizuku:provider:13.1.5")
    implementation(platform("androidx.compose:compose-bom:2025.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.animation:animation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.core:core-ktx:1.16.0")
''',
    "v063 Compose dependencies",
)

# One Compose host for every entry point; survive rotation/theme changes without
# recreating the activity (selection and transfer state live in the host).
config = 'android:configChanges="orientation|screenSize|screenLayout|smallestScreenSize|keyboardHidden|uiMode|density" android:windowSoftInputMode="adjustResize"'
replace_once(
    manifest,
    '<activity android:name=".MainActivity" android:exported="true">',
    f'<activity android:name=".MainActivity" android:exported="true" {config}>',
    "v063 MainActivity host attributes",
)
replace_once(
    manifest,
    '<activity android:name=".fileshare.FileShareActivity" android:exported="true" android:label="Send with ClipMesh">',
    f'<activity android:name=".fileshare.FileShareActivity" android:exported="true" android:label="Send with ClipMesh" {config}>',
    "v063 FileShareActivity host attributes",
)
replace_once(
    manifest,
    '<activity android:name=".SettingsActivity" android:exported="false" />',
    '<activity android:name=".SettingsActivity" android:exported="false" android:theme="@android:style/Theme.Translucent.NoTitleBar" />',
    "v063 SettingsActivity forwarder",
)

# Screenshot edges: Samsung inserts the MediaStore row before the image bytes are
# final and then updates it once. The old 2s throttle *dropped* those follow-up
# edges, so the screenshot only synced on the next unrelated MediaStore change
# (typically when the preview toolbar closed). Never drop an edge: defer it, and
# give a not-yet-visible capture a few bounded, event-armed follow-ups.
bridge = android / "app/src/main/java/dev/clipmesh/clipboard/ClipboardBridge.kt"
replace_once(
    bridge,
    '''        val now = android.os.SystemClock.elapsedRealtime()
        val previous = lastScreenshotProbeAt.get()
        if (now - previous < 2_000L || !lastScreenshotProbeAt.compareAndSet(previous, now)) return
        // Discover exactly one candidate for this coalesced MediaStore edge.
        val candidate = latestScreenshot() ?: return
        if (candidate.id <= lastScreenshotId.get()) return
        copyScreenshotCandidate(candidate, attempt = 0)''',
    '''        val now = android.os.SystemClock.elapsedRealtime()
        val previous = lastScreenshotProbeAt.get()
        val elapsed = now - previous
        if (elapsed < SCREENSHOT_MIN_PROBE_SPACING_MS) {
            // Defer instead of dropping: one shot exactly when spacing allows.
            scheduleScreenshotFollowUp(SCREENSHOT_MIN_PROBE_SPACING_MS - elapsed)
            return
        }
        if (!lastScreenshotProbeAt.compareAndSet(previous, now)) return
        // Discover exactly one candidate for this coalesced MediaStore edge.
        val candidate = latestScreenshot()
        if (candidate == null || candidate.id <= lastScreenshotId.get()) {
            // The row for a capture in progress may not be queryable yet.
            val step = screenshotFollowUps.getAndIncrement()
            if (step < SCREENSHOT_FOLLOW_UP_DELAYS_MS.size) scheduleScreenshotFollowUp(SCREENSHOT_FOLLOW_UP_DELAYS_MS[step])
            return
        }
        screenshotFollowUps.set(0)
        copyScreenshotCandidate(candidate, attempt = 0)''',
    "v063 screenshot edge deferral",
)
replace_once(
    bridge,
    "    private fun copyScreenshotCandidate(candidate: ScreenshotObservation, attempt: Int) {\n",
    '''    private val screenshotFollowUps = java.util.concurrent.atomic.AtomicInteger(0)

    private fun scheduleScreenshotFollowUp(delayMs: Long) {
        if (!started) return
        runCatching {
            captureExecutor.schedule({ signalScreenshotProbe() }, delayMs.coerceAtLeast(1L), TimeUnit.MILLISECONDS)
        }
    }

    private fun copyScreenshotCandidate(candidate: ScreenshotObservation, attempt: Int) {
''',
    "v063 screenshot follow-up scheduler",
)
replace_once(
    bridge,
    "        const val SCREENSHOT_COPY_RETRIES = 8\n",
    "        const val SCREENSHOT_COPY_RETRIES = 8\n        const val SCREENSHOT_MIN_PROBE_SPACING_MS = 250L\n        val SCREENSHOT_FOLLOW_UP_DELAYS_MS = longArrayOf(150L, 350L, 800L)\n",
    "v063 screenshot timing constants",
)
# A fresh MediaStore edge (a new capture) restarts the bounded follow-up budget.
replace_once(
    bridge,
    '''    private val screenshotObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) {
            signalScreenshotProbe()''',
    '''    private val screenshotObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) {
            screenshotFollowUps.set(0)
            signalScreenshotProbe()''',
    "v063 screenshot edge resets follow-ups",
)

# Event-driven UI: the transfer engine announces nearby-device changes and the
# runtime announces status changes, so no screen ever needs a refresh ticker.
engine = android / "app/src/main/java/dev/clipmesh/fileshare/LocalTransferEngine.kt"
replace_once(
    engine,
    '''    private fun remember(device: TransferDevice) {
        nearby[device.fingerprint] = device.copy(lastSeenMs = System.currentTimeMillis())
''',
    '''    @Volatile private var devicesListener: (() -> Unit)? = null

    /** Invoked (any thread) when the set of nearby devices or their identity changes. */
    fun setDevicesListener(listener: (() -> Unit)?) { devicesListener = listener }

    /** Milliseconds until the soonest nearby device expires, or null when none are known. */
    fun nextDeviceExpiryInMs(): Long? {
        val now = System.currentTimeMillis()
        return nearby.values.minOfOrNull { it.lastSeenMs }?.let { (it + DEVICE_TTL_MS - now).coerceAtLeast(0L) + 50L }
    }

    private fun remember(device: TransferDevice) {
        val previous = nearby[device.fingerprint]
        nearby[device.fingerprint] = device.copy(lastSeenMs = System.currentTimeMillis())
        if (previous == null || previous.copy(lastSeenMs = 0L) != device.copy(lastSeenMs = 0L)) devicesListener?.invoke()
''',
    "v063 nearby device change events",
)
replace_once(
    engine,
    "        nearby.entries.removeIf { now - it.value.lastSeenMs > DEVICE_TTL_MS }\n",
    "        if (nearby.entries.removeIf { now - it.value.lastSeenMs > DEVICE_TTL_MS }) devicesListener?.invoke()\n",
    "v063 nearby expiry event",
)
runtime = android / "app/src/main/java/dev/clipmesh/BackgroundRuntime.kt"
replace_once(
    runtime,
    '    @Volatile var status: String = "Stopped"\n        private set\n',
    '''    @Volatile var statusListener: (() -> Unit)? = null
    @Volatile var status: String = "Stopped"
        private set(value) { val changed = field != value; field = value; if (changed) statusListener?.invoke() }
''',
    "v063 runtime status events",
)

# Photo-picker items arrive as "<id>.jpg"; send them with IMG_/VID_ capture-date names.
replace_once(
    engine,
    "        return SendMeta(UUID.randomUUID().toString(), uri, sanitizeName(name), size, mime)\n",
    "        return SendMeta(UUID.randomUUID().toString(), uri, sanitizeName(PickerNames.friendly(context, uri, name, mime)), size, mime)\n",
    "v063 friendly picker names",
)

# A half-open socket must not keep a peer "connected" forever: desktops ping every
# 30s and Android peers every 120s, so a 300s read timeout tears down and
# reconnects only a genuinely silent link.
network_kt = android / "app/src/main/java/dev/clipmesh/network/NetworkEngine.kt"
replace_once(
    network_kt,
    "        socket.keepAlive = true\n        socket.soTimeout = 0\n        if (!isLan(socket.inetAddress)) { socket.close(); return@withContext }\n",
    "        socket.keepAlive = true\n        socket.soTimeout = PEER_IDLE_TIMEOUT_MS\n        if (!isLan(socket.inetAddress)) { socket.close(); return@withContext }\n",
    "v063 Android peer idle timeout",
)
replace_once(
    network_kt,
    "        private const val REPLAY_TTL_MS = 30_000L\n",
    "        private const val REPLAY_TTL_MS = 30_000L\n        private const val PEER_IDLE_TIMEOUT_MS = 300_000\n",
    "v063 Android idle timeout constant",
)

# Same policy on Android: a newer authenticated connection replaces one older
# than 10s instead of being rejected, so a dozed-through dead link can't block
# the desktop from reconnecting.
replace_once(
    network_kt,
    '''            val accepted = synchronized(peers) {
                if (peers.containsKey(peerId)) {
                    false
                } else {
                    peers[peerId] = connection
                    true
                }
            }
            if (!accepted) {''',
    '''            var replaced: PeerConnection? = null
            val accepted = synchronized(peers) {
                val existing = peers[peerId]
                if (existing != null && System.currentTimeMillis() - existing.createdAt < PEER_REPLACE_AFTER_MS) {
                    false
                } else {
                    replaced = existing
                    peers[peerId] = connection
                    true
                }
            }
            replaced?.close()
            if (!accepted) {''',
    "v063 Android newer connection replaces stale",
)
replace_once(
    network_kt,
    '''                if (peers[peerId]?.id == connection.id) peers.remove(peerId)
                connection.close()
                clearPeerRetry(peerId)''',
    '''                val wasCurrent = peers[peerId]?.id == connection.id
                if (wasCurrent) peers.remove(peerId)
                connection.close()
                if (wasCurrent) clearPeerRetry(peerId)''',
    "v063 Android replaced connection keeps the new link's retries",
)
replace_once(
    network_kt,
    '''        private val closed = AtomicBoolean(false)
''',
    '''        private val closed = AtomicBoolean(false)
        val createdAt: Long = System.currentTimeMillis()
''',
    "v063 Android connection age",
)
replace_once(
    network_kt,
    "        private const val PEER_IDLE_TIMEOUT_MS = 300_000\n",
    "        private const val PEER_IDLE_TIMEOUT_MS = 300_000\n        private const val PEER_REPLACE_AFTER_MS = 10_000L\n",
    "v063 Android replace threshold",
)

# Dial paired peers at their last known LAN address too, so reconnecting never
# depends on catching a broadcast. 30s while a paired peer is missing, else 120s.
replace_once(
    network_kt,
    '''            for (entry in settings.staticPeers) {
                parsePeer(entry)?.let { (address, port) -> if (isLan(address)) scope.launch { connect(address, port) } }
            }
            delay(120_000L)''',
    '''            for (entry in settings.staticPeers) {
                parsePeer(entry)?.let { (address, port) -> if (isLan(address)) scope.launch { connect(address, port) } }
            }
            var missing = false
            for (known in settings.knownPeers()) {
                if (known.deviceId == settings.deviceId || peers.containsKey(known.deviceId) || settings.isPeerBlocked(known.deviceId)) continue
                val address = runCatching { InetAddress.getByName(known.address) }.getOrNull() ?: continue
                if (!isLan(address) || known.port !in 1..65535) continue
                missing = true
                scope.launch { connect(address, known.port) }
            }
            delay(if (missing) 30_000L else 120_000L)''',
    "v063 Android known-peer redial",
)

# One-tap battery exemption so Samsung/OEM power management can't park the sync
# service while the phone is locked.
manifest_text = manifest.read_text(encoding="utf-8")
if "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" not in manifest_text:
    replace_once(
        manifest,
        '<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />',
        '<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />\n    <uses-permission android:name="android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" />',
        "v063 battery exemption permission",
    )
