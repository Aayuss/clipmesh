#!/usr/bin/env python3
"""Sync automatic Android screenshots and suppress only adjacent duplicate content."""

from pathlib import Path
import os
import platform


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Desktop: skip a remote write when the canonical content is already current.
# ClipboardState already suppresses adjacent identical local observations. This
# receive-side check prevents a fresh transport message containing the same top
# item from creating a second adjacent entry in CopyLess or another history app.
# ---------------------------------------------------------------------------
clipboard = PROJECT / "apps/desktop/src/clipboard.rs"
desktop_text = clipboard.read_text(encoding="utf-8")

old_apply = r'''    if contents.is_empty() { return Ok(()); }
    let fp=observation_fingerprint(&payload)?;
    state.begin_remote_write(fp);

    // Keep suppression scoped to this exact remote write. ctx.set() is
    // synchronous, but native clipboard watchers may run on another thread while
    // it is executing, so should_emit() suppresses only while remote_write_depth
    // is non-zero. Once the write completes, read the actual OS representation
    // back and seed its fingerprint before clearing the gate. This handles macOS
    // image re-encoding without leaving a sticky flag that can swallow the next
    // genuine local copy.
    let set_result=ctx.set(contents).map_err(|e| anyhow::anyhow!(e.to_string()));
    let mut actual_fingerprint=None;
    if set_result.is_ok() {
        let mut observe_cfg=cfg.clone();
        // Remote-write observation must not depend on whichever foreground app is
        // excluded by the user; this is internal dedupe bookkeeping only.
        observe_cfg.exclusions.clear();
        for _ in 0..4 {
            if let Ok(Some(observed))=read_payload(&ctx,&observe_cfg) {
                if let Ok(observed_fp)=observation_fingerprint(&observed) {
                    actual_fingerprint=Some(observed_fp);
                    break;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
'''

new_apply = r'''    if contents.is_empty() { return Ok(()); }
    let fp=observation_fingerprint(&payload)?;
    let mut observe_cfg=cfg.clone();
    // Duplicate suppression is based on canonical current content, independent
    // of source application metadata or image container re-encoding.
    observe_cfg.exclusions.clear();
    if let Ok(Some(current))=read_payload(&ctx,&observe_cfg) {
        if observation_fingerprint(&current).ok()==Some(fp) {
            state.seed(fp);
            debug!("ignored adjacent duplicate remote clipboard content");
            return Ok(());
        }
    }
    state.begin_remote_write(fp);

    // Keep suppression scoped to this exact remote write. ctx.set() is
    // synchronous, but native clipboard watchers may run on another thread while
    // it is executing, so should_emit() suppresses only while remote_write_depth
    // is non-zero. Once the write completes, read the actual OS representation
    // back and seed its fingerprint before clearing the gate. This handles macOS
    // image re-encoding without leaving a sticky flag that can swallow the next
    // genuine local copy.
    let set_result=ctx.set(contents).map_err(|e| anyhow::anyhow!(e.to_string()));
    let mut actual_fingerprint=None;
    if set_result.is_ok() {
        for _ in 0..4 {
            if let Ok(Some(observed))=read_payload(&ctx,&observe_cfg) {
                if let Ok(observed_fp)=observation_fingerprint(&observed) {
                    actual_fingerprint=Some(observed_fp);
                    break;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
'''
if desktop_text.count(old_apply) != 1:
    raise SystemExit("desktop adjacent remote-content gate anchor changed")
desktop_text = desktop_text.replace(old_apply, new_apply, 1)

test_anchor = r'''        assert_eq!(observation_fingerprint(&first).unwrap(),observation_fingerprint(&second).unwrap());
    }
}
'''
test_replacement = r'''        assert_eq!(observation_fingerprint(&first).unwrap(),observation_fingerprint(&second).unwrap());
    }

    #[test]
    fn adjacent_duplicates_are_suppressed_but_separated_recopies_are_emitted() {
        let state=ClipboardState::new();
        let image=[1_u8;32];
        let text=[2_u8;32];
        assert!(state.should_emit(&image));
        assert!(!state.should_emit(&image));
        assert!(state.should_emit(&text));
        assert!(state.should_emit(&image));
    }
}
'''
if desktop_text.count(test_anchor) != 1:
    raise SystemExit("desktop adjacent-dedupe unit-test anchor changed")
desktop_text = desktop_text.replace(test_anchor, test_replacement, 1)

desktop_identity_anchor = r'''fn observation_fingerprint(payload: &ClipPayload) -> Result<[u8; 32]> {
    let mut normalized=payload.clone();
    for representation in &mut normalized.representations {
        if representation.mime.to_ascii_lowercase().starts_with("image/") {
            let bytes=representation.bytes()?;
            let image=RustImageData::from_bytes(&bytes)
                .map_err(|e| anyhow::anyhow!(e.to_string()))?;
            let png=image.to_png().map_err(|e| anyhow::anyhow!(e.to_string()))?;
            *representation=Representation::from_bytes("image/png",png.get_bytes());
        }
    }
    normalized.stable_fingerprint()
}
'''
desktop_identity_replacement = r'''fn observation_fingerprint(payload: &ClipPayload) -> Result<[u8; 32]> {
    let mut normalized=payload.clone();
    for representation in &mut normalized.representations {
        if representation.mime.to_ascii_lowercase().starts_with("image/") {
            let bytes=representation.bytes()?;
            let image=RustImageData::from_bytes(&bytes)
                .map_err(|e| anyhow::anyhow!(e.to_string()))?;
            let identity=image_perceptual_identity(&image)?;
            *representation=Representation::from_bytes("image/x-clipmesh-perceptual",&identity);
        }
    }
    normalized.stable_fingerprint()
}

fn image_perceptual_identity(image: &RustImageData) -> Result<Vec<u8>> {
    let rgba=image.to_rgba8().map_err(|e| anyhow::anyhow!(e.to_string()))?;
    let (width,height)=image.get_size();
    if width==0 || height==0 { return Err(anyhow::anyhow!("empty image")); }
    let mut luminance=[0_u32;64];
    let (mut sum_r,mut sum_g,mut sum_b)=(0_u32,0_u32,0_u32);
    for gy in 0..8_u32 {
        for gx in 0..8_u32 {
            let x=((((2*gx+1) as u64)*(width as u64))/16).min((width-1) as u64) as u32;
            let y=((((2*gy+1) as u64)*(height as u64))/16).min((height-1) as u64) as u32;
            let pixel=rgba.get_pixel(x,y).0;
            let index=(gy*8+gx) as usize;
            sum_r+=pixel[0] as u32; sum_g+=pixel[1] as u32; sum_b+=pixel[2] as u32;
            luminance[index]=299*(pixel[0] as u32)+587*(pixel[1] as u32)+114*(pixel[2] as u32);
        }
    }
    let average=luminance.iter().sum::<u32>()/64;
    let mut hash=[0_u8;8];
    for (index,value) in luminance.iter().enumerate() {
        if *value>=average { hash[index/8]|=1_u8 << (7-(index%8)); }
    }
    let mut identity=Vec::with_capacity(19);
    identity.extend_from_slice(&width.to_be_bytes());
    identity.extend_from_slice(&height.to_be_bytes());
    identity.extend_from_slice(&hash);
    identity.push((sum_r/64/16) as u8);
    identity.push((sum_g/64/16) as u8);
    identity.push((sum_b/64/16) as u8);
    Ok(identity)
}
'''
if desktop_text.count(desktop_identity_anchor) != 1:
    raise SystemExit("desktop perceptual image identity anchor changed")
desktop_text = desktop_text.replace(desktop_identity_anchor, desktop_identity_replacement, 1)
clipboard.write_text(desktop_text, encoding="utf-8")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    bridge = java / "clipboard/ClipboardBridge.kt"
    service = java / "shizuku/ClipboardUserService.kt"
    manager = java / "shizuku/ShizukuManager.kt"
    aidl = PROJECT / "android/app/src/main/aidl/dev/clipmesh/shizuku/IClipboardUserService.aidl"

    bridge_text = bridge.read_text(encoding="utf-8")
    bridge_text = bridge_text.replace(
        "import android.content.Context\n",
        "import android.content.Context\nimport android.database.ContentObserver\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "import android.graphics.Bitmap\n",
        "import android.graphics.Bitmap\nimport android.graphics.Color\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "import android.os.Looper\n",
        "import android.os.Looper\nimport android.provider.MediaStore\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "import java.util.concurrent.atomic.AtomicBoolean\n",
        "import java.util.concurrent.atomic.AtomicBoolean\nimport java.util.concurrent.atomic.AtomicLong\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "import java.io.ByteArrayInputStream\n",
        "import java.io.ByteArrayInputStream\nimport java.nio.ByteBuffer\n",
        1,
    )

    android_identity_anchor = '''    private fun echoFingerprint(payload: ClipPayload): String {
        val normalized = payload.representations.map { representation ->
            if (representation.mime.lowercase(Locale.ROOT).startsWith("image/")) {
                imageToPng(representation.data)?.let { Representation("image/png", it) } ?: representation
            } else representation
        }
        return payload.copy(representations = normalized).stableFingerprint()
    }
'''
    android_identity_replacement = '''    private fun echoFingerprint(payload: ClipPayload): String {
        val normalized = payload.representations.map { representation ->
            if (representation.mime.lowercase(Locale.ROOT).startsWith("image/")) {
                imagePerceptualIdentity(representation.data)?.let {
                    Representation("image/x-clipmesh-perceptual", it)
                } ?: representation
            } else representation
        }
        return payload.copy(representations = normalized).stableFingerprint()
    }

    private fun imagePerceptualIdentity(bytes: ByteArray): ByteArray? {
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val orientation = runCatching {
            ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )
        }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
        val bitmap = orientBitmap(decoded, orientation)
        return try {
            if (bitmap.width <= 0 || bitmap.height <= 0) return null
            val luminance = IntArray(64)
            var sumR = 0L; var sumG = 0L; var sumB = 0L
            for (gy in 0 until 8) {
                for (gx in 0 until 8) {
                    val x = ((((2L * gx + 1L) * bitmap.width) / 16L).toInt()).coerceAtMost(bitmap.width - 1)
                    val y = ((((2L * gy + 1L) * bitmap.height) / 16L).toInt()).coerceAtMost(bitmap.height - 1)
                    val pixel = bitmap.getPixel(x, y)
                    val r = Color.red(pixel); val g = Color.green(pixel); val b = Color.blue(pixel)
                    val index = gy * 8 + gx
                    sumR += r; sumG += g; sumB += b
                    luminance[index] = 299 * r + 587 * g + 114 * b
                }
            }
            val average = luminance.sum() / 64
            val hash = ByteArray(8)
            luminance.forEachIndexed { index, value ->
                if (value >= average) {
                    hash[index / 8] = (hash[index / 8].toInt() or (1 shl (7 - index % 8))).toByte()
                }
            }
            ByteBuffer.allocate(19)
                .putInt(bitmap.width)
                .putInt(bitmap.height)
                .put(hash)
                .put((sumR / 64L / 16L).toByte())
                .put((sumG / 64L / 16L).toByte())
                .put((sumB / 64L / 16L).toByte())
                .array()
        } finally {
            if (bitmap !== decoded) bitmap.recycle()
            decoded.recycle()
        }
    }
'''
    if bridge_text.count(android_identity_anchor) != 1:
        raise SystemExit("Android perceptual image identity anchor changed")
    bridge_text = bridge_text.replace(android_identity_anchor, android_identity_replacement, 1)

    fields_anchor = '''    private val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val main = Handler(Looper.getMainLooper())
    private val suppressedFingerprint = RecentRemoteFingerprintSuppressor()
    private val accessibilityClip = AtomicReference<ClipData?>(null)
    private val lastObservedClipboardEvent = AtomicReference<String?>(null)
    private val captureInFlight = AtomicBoolean(false)
    private val capturePending = AtomicBoolean(false)
    private val captureExecutor = Executors.newSingleThreadExecutor { r -> Thread(r, "ClipMesh-ClipboardCapture").apply { isDaemon = true } }
    private var started = false
    private val listener = ClipboardManager.OnPrimaryClipChangedListener { captureAsync(fromWatchdog = false) }
'''
    fields_replacement = '''    private val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val main = Handler(Looper.getMainLooper())
    private val statePrefs = context.getSharedPreferences("clipmesh_clipboard_state", Context.MODE_PRIVATE)
    private val suppressedFingerprint = RecentRemoteFingerprintSuppressor()
    private val accessibilityClip = AtomicReference<ClipData?>(null)
    private val lastObservedClipboardEvent = AtomicReference(statePrefs.getString("last_event", null))
    private val lastVisibleContentFingerprint = AtomicReference(statePrefs.getString("last_content", null))
    private val lastScreenshotId = AtomicLong(statePrefs.getLong("last_screenshot_id", -1L))
    private val lastScreenshotProbeAt = AtomicLong(0L)
    private val captureInFlight = AtomicBoolean(false)
    private val capturePending = AtomicBoolean(false)
    private val captureExecutor = Executors.newSingleThreadExecutor { r -> Thread(r, "ClipMesh-ClipboardCapture").apply { isDaemon = true } }
    private var started = false
    private val listener = ClipboardManager.OnPrimaryClipChangedListener { captureAsync(fromWatchdog = false) }
    private val screenshotObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) {
            probeLatestScreenshotIfDue()
        }
    }
'''
    if bridge_text.count(fields_anchor) != 1:
        raise SystemExit("Android persistent adjacent/screenshot state anchor changed")
    bridge_text = bridge_text.replace(fields_anchor, fields_replacement, 1)

    start_anchor = '''        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }
        main.post { clipboard.addPrimaryClipChangedListener(listener) }
'''
    start_replacement = '''        ForegroundTracker.clipboardChanged = { clip -> captureNowForAccessibility(clip) }
        main.post {
            clipboard.addPrimaryClipChangedListener(listener)
            runCatching {
                context.contentResolver.registerContentObserver(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    true,
                    screenshotObserver
                )
            }
            captureExecutor.execute { seedLatestScreenshot() }
        }
'''
    if bridge_text.count(start_anchor) != 1:
        raise SystemExit("Android screenshot observer start anchor changed")
    bridge_text = bridge_text.replace(start_anchor, start_replacement, 1)

    stop_anchor = '''        ForegroundTracker.clipboardChanged = null
        main.post { clipboard.removePrimaryClipChangedListener(listener) }
        captureExecutor.shutdownNow()
'''
    stop_replacement = '''        ForegroundTracker.clipboardChanged = null
        main.post {
            clipboard.removePrimaryClipChangedListener(listener)
            runCatching { context.contentResolver.unregisterContentObserver(screenshotObserver) }
        }
        captureExecutor.shutdownNow()
'''
    if bridge_text.count(stop_anchor) != 1:
        raise SystemExit("Android screenshot observer stop anchor changed")
    bridge_text = bridge_text.replace(stop_anchor, stop_replacement, 1)

    watchdog_anchor = '''    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)
    fun captureNowForBackgroundMonitor() = captureAsync(fromWatchdog = true)
    fun captureNowForForeground() = captureAsync(fromWatchdog = true)
'''
    watchdog_replacement = '''    fun captureNowForWatchdog() = captureAsync(fromWatchdog = true)
    fun captureNowForBackgroundMonitor() = captureAsync(fromWatchdog = true)
    fun captureNowForForeground() {
        captureAsync(fromWatchdog = true)
        // Samsung/Gboard records screenshots in MediaStore without changing the
        // system clipboard and does not notify observers lacking broad gallery
        // permission. Reuse the already-running interactive watchdog as a
        // low-frequency Shizuku wake-up; persisted media IDs make it one-shot.
        probeLatestScreenshotIfDue()
    }
'''
    if bridge_text.count(watchdog_anchor) != 1:
        raise SystemExit("Android screenshot watchdog fallback anchor changed")
    bridge_text = bridge_text.replace(watchdog_anchor, watchdog_replacement, 1)

    event_anchor = '''                val eventKey = if (observation.generation > 0L) {
                    "generation:${observation.generation}"
                } else {
                    "fingerprint:$fp"
                }
                if (suppressedFingerprint.compareAndSet(fp, null)) {
                    lastObservedClipboardEvent.set(eventKey)
                    return@execute
                }
                if (lastObservedClipboardEvent.getAndSet(eventKey) == eventKey) return@execute
                if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("outgoing_clip_count")
                onLocalClip(payload)
'''
    event_replacement = '''                val eventKey = if (observation.generation > 0L) {
                    "generation:${observation.generation}:$fp"
                } else {
                    "fingerprint:$fp"
                }
                if (suppressedFingerprint.compareAndSet(fp, null)) {
                    recordObservedEvent(eventKey)
                    recordVisibleContent(echoFingerprint(payload))
                    return@execute
                }
                if (lastObservedClipboardEvent.get() == eventKey) return@execute
                recordObservedEvent(eventKey)
                emitLocal(payload, fromScreenshot = false)
'''
    if bridge_text.count(event_anchor) != 1:
        raise SystemExit("Android adjacent local-content gate anchor changed")
    bridge_text = bridge_text.replace(event_anchor, event_replacement, 1)

    helper_anchor = '''    private fun isPairingPayload(payload: ClipPayload): Boolean {
'''
    helper = r'''    private fun recordObservedEvent(eventKey: String) {
        lastObservedClipboardEvent.set(eventKey)
        statePrefs.edit().putString("last_event", eventKey).commit()
    }

    private fun recordVisibleContent(fingerprint: String) {
        lastVisibleContentFingerprint.set(fingerprint)
        statePrefs.edit().putString("last_content", fingerprint).commit()
    }

    private fun emitLocal(payload: ClipPayload, fromScreenshot: Boolean) {
        val fingerprint = echoFingerprint(payload)
        if (lastVisibleContentFingerprint.getAndSet(fingerprint) == fingerprint) {
            if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("adjacent_duplicate_suppressed_count")
            statePrefs.edit().putString("last_content", fingerprint).commit()
            return
        }
        statePrefs.edit().putString("last_content", fingerprint).commit()
        if (dev.clipmesh.BuildConfig.DEBUG) {
            incrementDebugCounter("outgoing_clip_count")
            if (fromScreenshot) incrementDebugCounter("screenshot_send_count")
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putString("last_outgoing_content_fingerprint", fingerprint)
                .commit()
        }
        onLocalClip(payload)
    }

    private data class ScreenshotObservation(
        val id: Long,
        val uri: Uri,
        val mime: String,
        val name: String,
    )

    private fun latestScreenshot(): ScreenshotObservation? {
        val json = shizuku.readLatestScreenshotJson()
        if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("screenshot_probe_count")
        val value = runCatching { JSONObject(json) }.getOrNull() ?: return null
        val id = value.optLong("id", -1L)
        val uri = value.optString("uri").takeIf { it.isNotBlank() }?.let(Uri::parse)
        if (id < 0L || uri == null) return null
        if (dev.clipmesh.BuildConfig.DEBUG) {
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putLong("last_screenshot_candidate_id", id)
                .commit()
        }
        return ScreenshotObservation(
            id,
            uri,
            value.optString("mime", "image/png"),
            sanitizeName(value.optString("name", "screenshot.png")),
        )
    }

    private fun seedLatestScreenshot() {
        if (lastScreenshotId.get() >= 0L) return
        val latest = latestScreenshot() ?: return
        lastScreenshotId.set(latest.id)
        statePrefs.edit().putLong("last_screenshot_id", latest.id).commit()
    }

    private fun probeLatestScreenshotIfDue() {
        val now = android.os.SystemClock.elapsedRealtime()
        val previous = lastScreenshotProbeAt.get()
        if (now - previous >= 2_000L && lastScreenshotProbeAt.compareAndSet(previous, now)) {
            captureLatestScreenshot(0)
        }
    }

    private fun captureLatestScreenshot(attempt: Int) {
        if (!started || !settings.sendEnabled || !settings.syncImages) return
        captureExecutor.execute {
            val latest = latestScreenshot() ?: return@execute
            if (latest.id <= lastScreenshotId.get()) return@execute
            val temp = File(context.cacheDir, "outgoing/screenshot-${latest.id}")
            val copied = shizuku.copyUri(latest.uri, temp)
            val bytes = if (copied) runCatching { temp.readBytes() }.getOrNull() else null
            temp.delete()
            val png = bytes?.let(::imageToPng)
            if (png == null) {
                if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("screenshot_copy_fail_count")
                if (attempt < 8 && started) {
                    main.postDelayed({ captureLatestScreenshot(attempt + 1) }, 250L)
                }
                return@execute
            }
            lastScreenshotId.set(latest.id)
            statePrefs.edit().putLong("last_screenshot_id", latest.id).commit()
            emitLocal(
                ClipPayload(
                    representations = listOf(Representation("image/png", png)),
                    sourceApp = "android.screenshot",
                ),
                fromScreenshot = true,
            )
        }
    }

'''
    if bridge_text.count(helper_anchor) != 1:
        raise SystemExit("Android screenshot/adjacent helper insertion anchor changed")
    bridge_text = bridge_text.replace(helper_anchor, helper + helper_anchor, 1)

    remote_anchor = '''        val remoteFingerprint = echoFingerprint(payload)
        val now = System.currentTimeMillis()
        if (dev.clipmesh.BuildConfig.DEBUG) {
'''
    remote_replacement = '''        val remoteFingerprint = echoFingerprint(payload)
        if (lastVisibleContentFingerprint.getAndSet(remoteFingerprint) == remoteFingerprint) {
            if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("adjacent_duplicate_suppressed_count")
            statePrefs.edit().putString("last_content", remoteFingerprint).commit()
            return
        }
        statePrefs.edit().putString("last_content", remoteFingerprint).commit()
        val now = System.currentTimeMillis()
        if (dev.clipmesh.BuildConfig.DEBUG) {
'''
    if bridge_text.count(remote_anchor) != 1:
        raise SystemExit("Android adjacent remote-apply gate anchor changed")
    bridge_text = bridge_text.replace(remote_anchor, remote_replacement, 1)
    bridge.write_text(bridge_text, encoding="utf-8")

    aidl_text = aidl.read_text(encoding="utf-8")
    aidl_anchor = '''    boolean copyPrimaryClipItemToFile(int index, in ParcelFileDescriptor destination);
    boolean setPrimaryClipText(String text);
'''
    aidl_replacement = '''    boolean copyPrimaryClipItemToFile(int index, in ParcelFileDescriptor destination);
    String getLatestScreenshotJson();
    boolean copyUriToFile(String uri, in ParcelFileDescriptor destination);
    boolean setPrimaryClipText(String text);
'''
    if aidl_text.count(aidl_anchor) != 1:
        raise SystemExit("Shizuku screenshot AIDL anchor changed")
    aidl.write_text(aidl_text.replace(aidl_anchor, aidl_replacement, 1), encoding="utf-8")

    service_text = service.read_text(encoding="utf-8")
    service_anchor = '''    override fun copyPrimaryClipItemToFile(index: Int, destination: ParcelFileDescriptor): Boolean {
        val clip = lastClip ?: (invokeClipboard("getPrimaryClip") as? ClipData) ?: return false
        if (index !in 0 until clip.itemCount) return false
        val uri = clip.getItemAt(index).uri ?: return false
        return readUriAsShell(uri, destination) || readUriWithResolver(uri, destination)
    }

'''
    service_replacement = service_anchor + r'''    override fun getLatestScreenshotJson(): String = runCatching {
        // Samsung attributes ContentResolver media queries to the ClipMesh
        // package even inside a shell-UID UserService, which denies the query
        // without broad gallery permission. The platform content utility keeps
        // the Shizuku shell attribution and needs no user photo-library grant.
        val collection = "content://media/external/images/media"
        val recentCutoff = System.currentTimeMillis() / 1000L - 30L
        val process = ProcessBuilder(
            "/system/bin/content",
            "query",
            "--uri", collection,
            "--projection", "_id:_display_name:relative_path:mime_type:date_added",
            "--where", "(relative_path LIKE '%Screenshots/%' OR _display_name LIKE 'Screenshot_%') AND date_added >= $recentCutoff",
            "--sort", "date_added DESC",
        ).redirectErrorStream(true).start()
        val output = process.inputStream.bufferedReader().use { it.readText() }
        if (process.waitFor() != 0) return@runCatching ""
        val first = output.lineSequence().firstOrNull { it.startsWith("Row:") } ?: return@runCatching ""
        val id = Regex("""_id=(\d+)""").find(first)?.groupValues?.get(1)?.toLongOrNull()
            ?: return@runCatching ""
        val name = Regex("""_display_name=(.*?), relative_path=""").find(first)?.groupValues?.get(1).orEmpty()
        val mime = Regex("""mime_type=(.*?), date_added=""").find(first)?.groupValues?.get(1).orEmpty()
        val added = Regex("""date_added=(\d+)""").find(first)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        JSONObject()
            .put("id", id)
            .put("uri", "$collection/$id")
            .put("name", name)
            .put("mime", mime.ifBlank { "image/png" })
            .put("date_added", added)
            .toString()
    }.getOrDefault("")

    override fun copyUriToFile(uri: String, destination: ParcelFileDescriptor): Boolean {
        val parsed = runCatching { Uri.parse(uri) }.getOrNull() ?: return false
        if (parsed.scheme != "content" || parsed.authority?.startsWith("media") != true) return false
        return readUriAsShell(parsed, destination) || readUriWithResolver(parsed, destination)
    }

'''
    if service_text.count(service_anchor) != 1:
        raise SystemExit("Shizuku screenshot MediaStore service anchor changed")
    service.write_text(service_text.replace(service_anchor, service_replacement, 1), encoding="utf-8")

    manager_text = manager.read_text(encoding="utf-8")
    manager_anchor = '''    fun copyItem(index: Int, destination: File): Boolean {
        destination.parentFile?.mkdirs()
        val descriptor = ParcelFileDescriptor.open(
            destination,
            ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE
        )
        return try {
            ensureConnected()?.copyPrimaryClipItemToFile(index, descriptor) == true
        } catch (_: Exception) {
            false
        } finally {
            descriptor.close()
        }
    }

'''
    manager_replacement = manager_anchor + '''    fun readLatestScreenshotJson(): String = runCatching {
        ensureConnected()?.latestScreenshotJson.orEmpty()
    }.getOrDefault("")

    fun copyUri(uri: android.net.Uri, destination: File): Boolean {
        destination.parentFile?.mkdirs()
        val descriptor = ParcelFileDescriptor.open(
            destination,
            ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE
        )
        return try {
            ensureConnected()?.copyUriToFile(uri.toString(), descriptor) == true
        } catch (_: Exception) {
            false
        } finally {
            descriptor.close()
        }
    }

'''
    if manager_text.count(manager_anchor) != 1:
        raise SystemExit("Shizuku screenshot manager anchor changed")
    manager_text = manager_text.replace(manager_anchor, manager_replacement, 1)
    manager_text = manager_text.replace("            .version(8)\n", "            .version(11)\n", 1)
    manager.write_text(manager_text, encoding="utf-8")

    android_final = bridge.read_text(encoding="utf-8")
    for needle in (
        'registerContentObserver(',
        'MediaStore.Images.Media.EXTERNAL_CONTENT_URI',
        'shizuku.readLatestScreenshotJson()',
        'shizuku.copyUri(latest.uri, temp)',
        'sourceApp = "android.screenshot"',
        'lastVisibleContentFingerprint.getAndSet(fingerprint) == fingerprint',
        'lastVisibleContentFingerprint.getAndSet(remoteFingerprint) == remoteFingerprint',
        'incrementDebugCounter("adjacent_duplicate_suppressed_count")',
        'incrementDebugCounter("screenshot_send_count")',
        'private fun probeLatestScreenshotIfDue()',
        'now - previous >= 2_000L',
        'incrementDebugCounter("screenshot_probe_count")',
        'incrementDebugCounter("screenshot_copy_fail_count")',
        'Representation("image/x-clipmesh-perceptual", it)',
        'private fun imagePerceptualIdentity(bytes: ByteArray)',
        'last_outgoing_content_fingerprint',
        '"generation:${observation.generation}:$fp"',
    ):
        if needle not in android_final:
            raise SystemExit(f"Android screenshot/adjacent guard missing: {needle}")

    for path, needles in (
        (aidl, ("getLatestScreenshotJson", "copyUriToFile")),
        (service, ("/system/bin/content", "date_added >= $recentCutoff", "copyUriToFile")),
        (manager, ("readLatestScreenshotJson", "copyUri", ".version(11)")),
    ):
        final = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in final:
                raise SystemExit(f"Android screenshot Shizuku guard missing in {path}: {needle}")


desktop_final = clipboard.read_text(encoding="utf-8")
for needle in (
    'debug!("ignored adjacent duplicate remote clipboard content")',
    "observation_fingerprint(&current).ok()==Some(fp)",
    "fn image_perceptual_identity(image: &RustImageData)",
    'Representation::from_bytes("image/x-clipmesh-perceptual",&identity)',
    "adjacent_duplicates_are_suppressed_but_separated_recopies_are_emitted",
):
    if needle not in desktop_final:
        raise SystemExit(f"desktop adjacent clipboard guard missing: {needle}")

print(f"Applied ClipMesh v045 automatic screenshot sync and adjacent-only content dedupe on {SYSTEM}")
