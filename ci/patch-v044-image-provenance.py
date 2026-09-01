#!/usr/bin/env python3
"""Stop image ping-pong by tracking remote provenance and canonical image content."""

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
# Desktop: compare the image representation produced by clipboard-rs, not the
# container bytes received on the wire. macOS legitimately re-encodes PNG data
# when an image is written to NSPasteboard. Those byte changes are not a new copy.
# ---------------------------------------------------------------------------
clipboard = PROJECT / "apps/desktop/src/clipboard.rs"
desktop_text = clipboard.read_text(encoding="utf-8")

if desktop_text.count("payload.stable_fingerprint()") != 4:
    raise SystemExit(
        "desktop observation fingerprint call shape changed; expected four payload calls"
    )
desktop_text = desktop_text.replace(
    "payload.stable_fingerprint()", "observation_fingerprint(&payload)"
)
if desktop_text.count("observed.stable_fingerprint()") != 1:
    raise SystemExit("desktop readback observation fingerprint call shape changed")
desktop_text = desktop_text.replace(
    "observed.stable_fingerprint()", "observation_fingerprint(&observed)", 1
)

helper_anchor = "fn safe_filename(name: &str) -> String {\n"
desktop_helper = r'''fn observation_fingerprint(payload: &ClipPayload) -> Result<[u8; 32]> {
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
if desktop_text.count(helper_anchor) != 1:
    raise SystemExit("desktop canonical image fingerprint insertion anchor changed")
desktop_text = desktop_text.replace(helper_anchor, desktop_helper + helper_anchor, 1)

desktop_tests = r'''

#[cfg(test)]
mod image_echo_tests {
    use super::*;

    #[test]
    fn image_observation_fingerprint_ignores_png_container_reencoding() {
        let original=include_bytes!("../assets/clipmesh.png");
        let decoded=RustImageData::from_bytes(original).unwrap();
        let mut alternate=decoded.to_png().unwrap().get_bytes().to_vec();
        // PNG decoders ignore trailing non-image data. It models metadata/chunk
        // differences without changing a single displayed pixel.
        alternate.extend_from_slice(b"clipmesh-reencoded-container");

        let mut first=ClipPayload::new();
        first.representations.push(Representation::from_bytes("image/png",original));
        let mut second=ClipPayload::new();
        second.representations.push(Representation::from_bytes("image/png",&alternate));

        assert_ne!(first.stable_fingerprint().unwrap(),second.stable_fingerprint().unwrap());
        assert_eq!(observation_fingerprint(&first).unwrap(),observation_fingerprint(&second).unwrap());
    }
}
'''
if "mod image_echo_tests" in desktop_text:
    raise SystemExit("desktop canonical image regression test already present")
desktop_text = desktop_text.rstrip() + desktop_tests + "\n"
clipboard.write_text(desktop_text, encoding="utf-8")


if SYSTEM == "Linux":
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    bridge = java / "clipboard/ClipboardBridge.kt"
    background_runtime = java / "BackgroundRuntime.kt"
    user_service = java / "shizuku/ClipboardUserService.kt"
    shizuku_manager = java / "shizuku/ShizukuManager.kt"

    bridge_text = bridge.read_text(encoding="utf-8")
    bridge_text = bridge_text.replace(
        "import android.graphics.BitmapFactory\n",
        "import android.graphics.Bitmap\n"
        "import android.graphics.BitmapFactory\n"
        "import android.graphics.Matrix\n"
        "import android.media.ExifInterface\n",
        1,
    )
    bridge_text = bridge_text.replace(
        "import java.io.ByteArrayOutputStream\n",
        "import java.io.ByteArrayInputStream\nimport java.io.ByteArrayOutputStream\n",
        1,
    )

    observation_field = '''    private val lastWatchdogFingerprint = AtomicReference<String?>(null)
'''
    observation_field_replacement = '''    private val lastObservedClipboardEvent = AtomicReference<String?>(null)
'''
    if bridge_text.count(observation_field) != 1:
        raise SystemExit("Android clipboard observation field anchor changed")
    bridge_text = bridge_text.replace(observation_field, observation_field_replacement, 1)

    capture_anchor = '''                val payload = readCurrent(sourcePackage, accessibilityClip.getAndSet(null)) ?: return@execute
                if (isPairingPayload(payload)) return@execute
                val fp = payload.stableFingerprint()
                if (suppressedFingerprint.compareAndSet(fp, null)) {
                    lastWatchdogFingerprint.set(fp)
                    return@execute
                }
                if (fromWatchdog && lastWatchdogFingerprint.getAndSet(fp) == fp) return@execute
                lastWatchdogFingerprint.set(fp)
'''
    capture_replacement = '''                val observation = readCurrent(sourcePackage, accessibilityClip.getAndSet(null)) ?: return@execute
                val payload = observation.payload
                if (isPairingPayload(payload)) return@execute
                val fp = payload.stableFingerprint()
                // ClipDescription.timestamp identifies the actual clipboard SET
                // operation. Watchdogs and duplicate OEM callbacks for that same
                // event must never create new transport messages. If an OEM omits
                // timestamps, canonical content remains the safe fallback.
                val eventKey = if (observation.generation > 0L) {
                    "generation:${observation.generation}"
                } else {
                    "fingerprint:$fp"
                }
                if (suppressedFingerprint.compareAndSet(fp, null)) {
                    lastObservedClipboardEvent.set(eventKey)
                    return@execute
                }
                if (lastObservedClipboardEvent.getAndSet(eventKey) == eventKey) return@execute
'''
    if bridge_text.count(capture_anchor) != 1:
        raise SystemExit("Android per-event clipboard dedupe anchor changed")
    bridge_text = bridge_text.replace(capture_anchor, capture_replacement, 1)

    read_current_anchor = '''    private fun readCurrent(sourcePackage: String?, preferredClip: ClipData? = null): ClipPayload? {
        // AccessibilityService is the most reliable source for copied gallery and
        // screenshot URIs because it receives the URI grant with the event.
        preferredClip?.let { readClipData(it, sourcePackage)?.let { payload -> return payload } }
        // Shizuku remains the fallback for OEMs that restrict app clipboard reads.
        val shizukuJson = if (shizuku.hasPermission()) shizuku.readSnapshotJson() else ""
        if (shizukuJson.isNotBlank()) return readShizukuSnapshot(shizukuJson, sourcePackage)

        // Fallback works while ClipMesh has input focus and on some OEM combinations.
        return clipboard.primaryClip?.let { readClipData(it, sourcePackage) }
    }
'''
    read_current_replacement = '''    private data class ClipboardObservation(val payload: ClipPayload, val generation: Long)

    private fun readCurrent(sourcePackage: String?, preferredClip: ClipData? = null): ClipboardObservation? {
        // AccessibilityService is the most reliable source for copied gallery and
        // screenshot URIs because it receives the URI grant with the event.
        preferredClip?.let { clip ->
            readClipData(clip, sourcePackage)?.let { payload ->
                return ClipboardObservation(payload, clip.description.timestamp)
            }
        }
        // Shizuku remains the fallback for OEMs that restrict app clipboard reads.
        val shizukuJson = if (shizuku.hasPermission()) shizuku.readSnapshotJson() else ""
        if (shizukuJson.isNotBlank()) {
            val snapshot = runCatching { JSONObject(shizukuJson) }.getOrNull()
            readShizukuSnapshot(shizukuJson, sourcePackage)?.let { payload ->
                return ClipboardObservation(payload, snapshot?.optLong("timestamp", 0L) ?: 0L)
            }
        }

        // Fallback works while ClipMesh has input focus and on some OEM combinations.
        return clipboard.primaryClip?.let { clip ->
            readClipData(clip, sourcePackage)?.let { payload ->
                ClipboardObservation(payload, clip.description.timestamp)
            }
        }
    }
'''
    if bridge_text.count(read_current_anchor) != 1:
        raise SystemExit("Android clipboard generation read anchor changed")
    bridge_text = bridge_text.replace(read_current_anchor, read_current_replacement, 1)

    read_clip_anchor = '''    private fun readClipData(clip: ClipData, sourcePackage: String?): ClipPayload? {
        if (clip.itemCount == 0) return null
'''
    read_clip_replacement = '''    private fun readClipData(clip: ClipData, sourcePackage: String?): ClipPayload? {
        if (clip.itemCount == 0 || isRemoteClip(clip)) return null
'''
    if bridge_text.count(read_clip_anchor) != 1:
        raise SystemExit("Android ClipData remote-provenance anchor changed")
    bridge_text = bridge_text.replace(read_clip_anchor, read_clip_replacement, 1)

    read_shizuku_anchor = '''    private fun readShizukuSnapshot(json: String, sourcePackage: String?): ClipPayload? {
        val o = runCatching { JSONObject(json) }.getOrNull() ?: return null
        if (o.optBoolean("sensitive", false)) return null
'''
    read_shizuku_replacement = '''    private fun readShizukuSnapshot(json: String, sourcePackage: String?): ClipPayload? {
        val o = runCatching { JSONObject(json) }.getOrNull() ?: return null
        if (o.optBoolean("sensitive", false) || o.optBoolean("remote", false)) return null
'''
    if bridge_text.count(read_shizuku_anchor) != 1:
        raise SystemExit("Android Shizuku remote-provenance anchor changed")
    bridge_text = bridge_text.replace(read_shizuku_anchor, read_shizuku_replacement, 1)

    bridge_text = bridge_text.replace(
        "        val remoteFingerprint = payload.stableFingerprint()\n",
        "        val remoteFingerprint = echoFingerprint(payload)\n",
        1,
    )

    outgoing_anchor = "                onLocalClip(payload)\n"
    outgoing_replacement = '''                if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("outgoing_clip_count")
                onLocalClip(payload)
'''
    if bridge_text.count(outgoing_anchor) != 1:
        raise SystemExit("Android outgoing clipboard counter anchor changed")
    bridge_text = bridge_text.replace(outgoing_anchor, outgoing_replacement, 1)

    apply_counter_anchor = '''        if (dev.clipmesh.BuildConfig.DEBUG) {
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putLong("last_remote_apply_at", now)
'''
    apply_counter_replacement = '''        if (dev.clipmesh.BuildConfig.DEBUG) {
            incrementDebugCounter("remote_apply_count")
            context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit()
                .putLong("last_remote_apply_at", now)
'''
    if bridge_text.count(apply_counter_anchor) != 1:
        raise SystemExit("Android remote apply counter anchor changed")
    bridge_text = bridge_text.replace(apply_counter_anchor, apply_counter_replacement, 1)

    old_image_helper = '''    private fun imageToPng(bytes: ByteArray): ByteArray? {
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        return try {
            val output = ByteArrayOutputStream()
            if (!bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output)) null else output.toByteArray()
        } finally {
            bitmap.recycle()
        }
    }

    private fun markRemote(clip: ClipData): ClipData {
        if (settings.showRemoteCopyOverlay) return clip
        val extras = android.os.PersistableBundle().apply {
            putBoolean("com.android.systemui.SUPPRESS_CLIPBOARD_OVERLAY", true)
            putBoolean("android.content.extra.IS_REMOTE_DEVICE", true)
        }
        clip.description.extras = extras
        return clip
    }
'''
    new_image_helper = r'''    private fun echoFingerprint(payload: ClipPayload): String {
        val normalized = payload.representations.map { representation ->
            if (representation.mime.lowercase(Locale.ROOT).startsWith("image/")) {
                imageToPng(representation.data)?.let { Representation("image/png", it) } ?: representation
            } else representation
        }
        return payload.copy(representations = normalized).stableFingerprint()
    }

    private fun imageToPng(bytes: ByteArray): ByteArray? {
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val orientation = runCatching {
            ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )
        }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
        val oriented = orientBitmap(decoded, orientation)
        return try {
            val output = ByteArrayOutputStream()
            if (!oriented.compress(Bitmap.CompressFormat.PNG, 100, output)) null else output.toByteArray()
        } finally {
            if (oriented !== decoded) oriented.recycle()
            decoded.recycle()
        }
    }

    private fun orientBitmap(bitmap: Bitmap, orientation: Int): Bitmap {
        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
            ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.setRotate(-90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(-90f)
            else -> return bitmap
        }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    }

    private fun isRemoteClip(clip: ClipData): Boolean {
        val extras = clip.description.extras
        val markedRemote = extras?.getBoolean("dev.clipmesh.extra.REMOTE", false) == true ||
            extras?.getBoolean("android.content.extra.IS_REMOTE_DEVICE", false) == true
        if (markedRemote) return true
        // URI ownership is a second provenance signal in case an OEM strips
        // ClipDescription extras. This provider is used only for remote writes.
        val remoteAuthority = "${context.packageName}.files"
        return (0 until clip.itemCount).any { clip.getItemAt(it).uri?.authority == remoteAuthority }
    }

    private fun incrementDebugCounter(name: String) {
        val prefs = context.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE)
        prefs.edit().putInt(name, prefs.getInt(name, 0) + 1).commit()
    }

    private fun markRemote(clip: ClipData): ClipData {
        val extras = clip.description.extras ?: android.os.PersistableBundle()
        extras.putBoolean("dev.clipmesh.extra.REMOTE", true)
        if (!settings.showRemoteCopyOverlay) {
            extras.putBoolean("com.android.systemui.SUPPRESS_CLIPBOARD_OVERLAY", true)
            extras.putBoolean("android.content.extra.IS_REMOTE_DEVICE", true)
        }
        clip.description.extras = extras
        return clip
    }
'''
    if bridge_text.count(old_image_helper) != 1:
        raise SystemExit("Android image canonicalization/provenance helper anchor changed")
    bridge_text = bridge_text.replace(old_image_helper, new_image_helper, 1)
    bridge.write_text(bridge_text, encoding="utf-8")

    runtime_text = background_runtime.read_text(encoding="utf-8")
    runtime_anchor = '''    fun debugPeerCount(): Int = network?.peerCount() ?: 0
'''
    runtime_replacement = '''    fun debugPeerCount(): Int = network?.peerCount() ?: 0
    fun debugShizukuBound(): Boolean = shizuku?.isBound() == true
'''
    if runtime_text.count(runtime_anchor) != 1:
        raise SystemExit("Android runtime Shizuku readiness anchor changed")
    background_runtime.write_text(
        runtime_text.replace(runtime_anchor, runtime_replacement, 1), encoding="utf-8"
    )

    service_text = user_service.read_text(encoding="utf-8")
    old_service_result = '''        return JSONObject().put("sensitive", sensitive).put("items", items).toString()
'''
    new_service_result = '''        val remote = (extras?.getBoolean("dev.clipmesh.extra.REMOTE", false) ?: false) ||
            (extras?.getBoolean("android.content.extra.IS_REMOTE_DEVICE", false) ?: false)
        val timestamp = description?.timestamp ?: 0L
        return JSONObject().put("sensitive", sensitive).put("remote", remote)
            .put("timestamp", timestamp).put("items", items).toString()
'''
    if service_text.count(old_service_result) != 1:
        raise SystemExit("Shizuku snapshot remote marker anchor changed")
    service_text = service_text.replace(old_service_result, new_service_result, 1)
    user_service.write_text(service_text, encoding="utf-8")

    replace_once(
        shizuku_manager,
        "            .version(6)\n",
        "            .version(8)\n",
        "Shizuku remote-provenance service version",
    )

    android_final = bridge.read_text(encoding="utf-8")
    for needle in (
        'if (clip.itemCount == 0 || isRemoteClip(clip)) return null',
        'o.optBoolean("remote", false)',
        'val remoteFingerprint = echoFingerprint(payload)',
        'incrementDebugCounter("outgoing_clip_count")',
        'incrementDebugCounter("remote_apply_count")',
        'val eventKey = if (observation.generation > 0L)',
        'lastObservedClipboardEvent.getAndSet(eventKey) == eventKey',
        'snapshot?.optLong("timestamp", 0L)',
        'ExifInterface.TAG_ORIENTATION',
        'ExifInterface.ORIENTATION_ROTATE_90',
        'extras.putBoolean("dev.clipmesh.extra.REMOTE", true)',
        'clip.getItemAt(it).uri?.authority == remoteAuthority',
    ):
        if needle not in android_final:
            raise SystemExit(f"Android image provenance/orientation guard missing: {needle}")

    service_final = user_service.read_text(encoding="utf-8")
    if '.put("remote", remote)' not in service_final or '.put("timestamp", timestamp)' not in service_final:
        raise SystemExit("Shizuku snapshot does not preserve remote clipboard provenance")
    if "fun debugShizukuBound(): Boolean" not in background_runtime.read_text(encoding="utf-8"):
        raise SystemExit("Android runtime Shizuku readiness probe missing")


desktop_final = clipboard.read_text(encoding="utf-8")
for needle in (
    "fn observation_fingerprint(payload: &ClipPayload)",
    "RustImageData::from_bytes(&bytes)",
    '*representation=Representation::from_bytes("image/png",png.get_bytes())',
    "image_observation_fingerprint_ignores_png_container_reencoding",
):
    if needle not in desktop_final:
        raise SystemExit(f"desktop canonical image fingerprint guard missing: {needle}")

print(f"Applied ClipMesh v044 remote image provenance, canonical echo identity, and EXIF orientation on {SYSTEM}")
