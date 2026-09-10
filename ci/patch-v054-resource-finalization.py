#!/usr/bin/env python3
"""Low-risk Android resource retention and debug observability finalization."""

from __future__ import annotations

import os
import platform
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"v054 {label} anchor changed in {path}: found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_network(path: Path) -> None:
    replace_once(
        path,
        "class NetworkEngine(\n",
        r'''internal fun interface ExpiryHandle {
    fun cancel()
}

/** Holds at most one reconnect-replay frame and owns exactly one expiry task. */
internal class LatestFrameRetention(
    private val ttlMs: Long,
    private val nowMs: () -> Long,
    private val scheduleExpiry: (Long, () -> Unit) -> ExpiryHandle,
) {
    data class Frame(val createdAtMs: Long, val message: UUID, val bytes: ByteArray)

    private var frame: Frame? = null
    private var expiry: ExpiryHandle? = null
    private var generation = 0L

    @Synchronized
    fun store(value: Frame) {
        expiry?.cancel()
        generation += 1L
        val expectedGeneration = generation
        val expectedMessage = value.message
        frame = value
        // Capture only small identity values; the expiry closure must not hold
        // a second reference to the frame's potentially large ByteArray.
        expiry = scheduleExpiry(ttlMs) { expire(expectedGeneration, expectedMessage) }
    }

    @Synchronized
    fun fresh(): Frame? {
        val current = frame ?: return null
        if (nowMs() - current.createdAtMs < ttlMs) return current
        clearLocked()
        return null
    }

    @Synchronized
    fun clear() {
        generation += 1L
        clearLocked()
    }

    @Synchronized
    internal fun retainedMessageForTest(): UUID? = frame?.message

    @Synchronized
    private fun expire(expectedGeneration: Long, expectedMessage: UUID) {
        val current = frame
        if (generation == expectedGeneration && current?.message == expectedMessage) {
            frame = null
            expiry = null
        }
    }

    private fun clearLocked() {
        expiry?.cancel()
        expiry = null
        frame = null
    }
}

class NetworkEngine(
''',
        "latest frame retention helper",
    )
    replace_once(
        path,
        '''        private const val MAX_DISCOVERY = 4096
        private const val HELLO_SIZE = 92
''',
        '''        private const val MAX_DISCOVERY = 4096
        private const val HELLO_SIZE = 92
        private const val REPLAY_TTL_MS = 30_000L
''',
        "replay ttl constant",
    )
    replace_once(
        path,
        '''    private val pending = ConcurrentHashMap<UUID, PendingFrame>()
    private val running = AtomicBoolean(false)
    private var udp: DatagramSocket? = null
    private var server: ServerSocket? = null
    @Volatile private var latestFrame: LatestFrame? = null

    data class LatestFrame(val createdAtMs: Long, val message: UUID, val bytes: ByteArray)
    data class PendingFrame(val peer: UUID, val message: UUID, val bytes: ByteArray)
''',
        '''    private val pending = ConcurrentHashMap<UUID, PendingFrame>()
    private val retryJobs = ConcurrentHashMap<UUID, RetryTask>()
    private val retainedStateLock = Any()
    private val running = AtomicBoolean(false)
    private var udp: DatagramSocket? = null
    private var server: ServerSocket? = null
    private val latestFrame = LatestFrameRetention(
        ttlMs = REPLAY_TTL_MS,
        nowMs = android.os.SystemClock::elapsedRealtime,
        scheduleExpiry = { delayMs, expire ->
            val job = scope.launch { delay(delayMs); expire() }
            ExpiryHandle { job.cancel() }
        },
    )

    data class PendingFrame(val peer: UUID, val message: UUID, val bytes: ByteArray)
    private data class RetryTask(val message: UUID, val job: Job)
''',
        "bounded retained network state",
    )
    replace_once(
        path,
        '''        peers.values.forEach { it.close() }
        peers.clear()
        pending.clear()
        masterKey.fill(0)
        scope.cancel()
''',
        '''        peers.values.forEach { it.close() }
        peers.clear()
        synchronized(retainedStateLock) {
            retryJobs.values.forEach { it.job.cancel() }
            retryJobs.clear()
            pending.clear()
            latestFrame.clear()
        }
        masterKey.fill(0)
        scope.cancel()
''',
        "network stop release",
    )
    replace_once(
        path,
        "        latestFrame = LatestFrame(System.currentTimeMillis(), messageId, frame)\n",
        '''        synchronized(retainedStateLock) {
            if (!running.get()) return
            latestFrame.store(LatestFrameRetention.Frame(android.os.SystemClock.elapsedRealtime(), messageId, frame))
        }
''',
        "latest frame store",
    )
    replace_once(
        path,
        "            latestFrame?.takeIf { System.currentTimeMillis() - it.createdAtMs < 30_000L }?.let { latest ->\n",
        "            latestFrame.fresh()?.let { latest ->\n",
        "latest frame replay",
    )
    replace_once(
        path,
        "                        Crypto.Kind.ACK -> pending.computeIfPresent(peerId) { _, value -> if (value.message == frame.messageId) null else value }\n",
        "                        Crypto.Kind.ACK -> acknowledge(peerId, frame.messageId)\n",
        "ack release",
    )
    replace_once(
        path,
        '''                connection.close()
                pending.remove(peerId)
                onStatus("Sync active")
''',
        '''                connection.close()
                clearPeerRetry(peerId)
                onStatus("Sync active")
''',
        "disconnect release",
    )
    replace_once(
        path,
        '''    private fun scheduleRetry(peerId: UUID, messageId: UUID, connection: PeerConnection) {
        scope.launch {
            for (delayMs in longArrayOf(750, 1500, 3000)) {
                delay(delayMs)
                val frame = pending[peerId] ?: return@launch
                if (frame.message != messageId) return@launch
                if (!connection.sendLatest(frame.bytes)) break
            }
            pending.computeIfPresent(peerId) { _, value -> if (value.message == messageId) null else value }
        }
    }
''',
        '''    private fun scheduleRetry(peerId: UUID, messageId: UUID, connection: PeerConnection) {
        synchronized(retainedStateLock) {
            val current = pending[peerId] ?: return
            if (current.message != messageId) return
            val job = scope.launch(start = CoroutineStart.LAZY) {
                try {
                    for (delayMs in longArrayOf(750, 1500, 3000)) {
                        delay(delayMs)
                        val frame = pending[peerId] ?: return@launch
                        if (frame.message != messageId) return@launch
                        if (!connection.sendLatest(frame.bytes)) break
                    }
                    pending.computeIfPresent(peerId) { _, value -> if (value.message == messageId) null else value }
                } finally {
                    val completedJob = currentCoroutineContext().job
                    retryJobs.computeIfPresent(peerId) { _, value -> if (value.job === completedJob) null else value }
                }
            }
            retryJobs.put(peerId, RetryTask(messageId, job))?.job?.cancel()
            job.start()
        }
    }

    private fun acknowledge(peerId: UUID, messageId: UUID) {
        synchronized(retainedStateLock) {
            val frame = pending[peerId] ?: return
            if (frame.message != messageId) return
            pending.remove(peerId, frame)
            retryJobs.computeIfPresent(peerId) { _, value ->
                if (value.message == messageId) {
                    value.job.cancel()
                    null
                } else value
            }
        }
    }

    private fun clearPeerRetry(peerId: UUID) {
        synchronized(retainedStateLock) {
            pending.remove(peerId)
            retryJobs.remove(peerId)?.job?.cancel()
        }
    }
''',
        "one retry job per peer",
    )

    test = PROJECT / "android/app/src/test/java/dev/clipmesh/network/LatestFrameRetentionTest.kt"
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text(r'''package dev.clipmesh.network

import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LatestFrameRetentionTest {
    private class FakeScheduler {
        data class Task(val dueAt: Long, val action: () -> Unit, var cancelled: Boolean = false)
        var now = 0L
        private val tasks = mutableListOf<Task>()

        fun schedule(delayMs: Long, action: () -> Unit): ExpiryHandle {
            val task = Task(now + delayMs, action)
            tasks += task
            return ExpiryHandle { task.cancelled = true }
        }

        fun advanceBy(deltaMs: Long) {
            now += deltaMs
            tasks.filter { !it.cancelled && it.dueAt <= now }.forEach {
                it.cancelled = true
                it.action()
            }
        }
    }

    @Test
    fun frameExpiresAtReplayTtl() {
        val scheduler = FakeScheduler()
        val retained = LatestFrameRetention(30_000L, { scheduler.now }, scheduler::schedule)
        val a = UUID.randomUUID()
        retained.store(LatestFrameRetention.Frame(scheduler.now, a, ByteArray(1024)))

        scheduler.advanceBy(29_999L)
        assertEquals(a, retained.retainedMessageForTest())
        scheduler.advanceBy(1L)
        assertNull(retained.retainedMessageForTest())
    }

    @Test
    fun staleExpiryCannotClearNewerFrame() {
        val scheduler = FakeScheduler()
        val retained = LatestFrameRetention(30_000L, { scheduler.now }, scheduler::schedule)
        val a = UUID.randomUUID()
        val b = UUID.randomUUID()
        retained.store(LatestFrameRetention.Frame(scheduler.now, a, ByteArray(1)))
        scheduler.advanceBy(10_000L)
        retained.store(LatestFrameRetention.Frame(scheduler.now, b, ByteArray(1)))

        scheduler.advanceBy(20_000L)
        assertEquals(b, retained.retainedMessageForTest())
        scheduler.advanceBy(10_000L)
        assertNull(retained.retainedMessageForTest())
    }
}
''', encoding="utf-8")


def patch_diagnostics(java: Path) -> None:
    diagnostics = java / "DebugResourceCounters.kt"
    diagnostics.write_text(r'''package dev.clipmesh

import android.os.SystemClock
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/** In-memory diagnostics compiled into all variants but active only in DEBUG. */
internal object DebugResourceCounters {
    private val knownCounters = setOf(
        "clipboard_edge_privileged_count",
        "clipboard_edge_secondary_count",
        "clipboard_snapshot_read_count",
        "clipboard_emit_count",
        "clipboard_duplicate_suppressed_count",
        "clipboard_remote_echo_suppressed_count",
        "screenshot_emit_count",
        "multicast_lock_acquire_count",
        "multicast_lock_release_count",
        "multicast_lock_total_held_ms",
        "multicast_packets_received_count",
        "direct_register_count",
    )
    private val counters = ConcurrentHashMap<String, AtomicLong>()
    private val multicastHeldSinceMs = AtomicLong(0L)

    fun increment(name: String) {
        if (BuildConfig.DEBUG) counters.computeIfAbsent(name) { AtomicLong() }.incrementAndGet()
    }

    fun multicastLockAcquired() {
        if (!BuildConfig.DEBUG) return
        increment("multicast_lock_acquire_count")
        multicastHeldSinceMs.compareAndSet(0L, SystemClock.elapsedRealtime())
    }

    fun multicastLockReleased() {
        if (!BuildConfig.DEBUG) return
        val startedAt = multicastHeldSinceMs.getAndSet(0L)
        if (startedAt > 0L) {
            counters.computeIfAbsent("multicast_lock_total_held_ms") { AtomicLong() }
                .addAndGet((SystemClock.elapsedRealtime() - startedAt).coerceAtLeast(0L))
        }
        increment("multicast_lock_release_count")
    }

    fun snapshot(): Map<String, Long> {
        if (!BuildConfig.DEBUG) return emptyMap()
        val values = knownCounters.associateWith { counters[it]?.get() ?: 0L }.toMutableMap()
        val startedAt = multicastHeldSinceMs.get()
        if (startedAt > 0L) {
            values["multicast_lock_total_held_ms"] =
                values.getOrDefault("multicast_lock_total_held_ms", 0L) +
                    (SystemClock.elapsedRealtime() - startedAt).coerceAtLeast(0L)
        }
        return values
    }

    fun reset() {
        if (!BuildConfig.DEBUG) return
        counters.clear()
        if (multicastHeldSinceMs.get() > 0L) {
            multicastHeldSinceMs.set(SystemClock.elapsedRealtime())
        }
    }
}
''', encoding="utf-8")


def patch_clipboard(path: Path) -> None:
    replace_once(
        path,
        "import android.provider.MediaStore\n",
        "import android.provider.MediaStore\nimport dev.clipmesh.DebugResourceCounters\n",
        "clipboard diagnostics import",
    )
    replace_once(
        path,
        "    fun captureNowForSystemEvent() = signalClipboardEvent(manual = false)\n",
        '''    fun captureNowForSystemEvent() {
        DebugResourceCounters.increment("clipboard_edge_privileged_count")
        signalClipboardEvent(manual = false)
    }
''',
        "privileged edge counter",
    )
    replace_once(
        path,
        '''        captureExecutor.shutdownNow()
    }

    fun setPrivilegedListenerRegistered(registered: Boolean?) {
''',
        '''        clipboardCapturePending.set(false)
        screenshotProbePending.set(false)
        debugInjectedClip.set(null)
        captureExecutor.shutdownNow()
    }

    fun setPrivilegedListenerRegistered(registered: Boolean?) {
''',
        "clipboard stop cleanup",
    )
    replace_once(
        path,
        '''    private fun signalSecondaryClipboardEvent() {
        // Normal-app and Accessibility listeners remain installed for OEM
''',
        '''    private fun signalSecondaryClipboardEvent() {
        DebugResourceCounters.increment("clipboard_edge_secondary_count")
        // Normal-app and Accessibility listeners remain installed for OEM
''',
        "secondary edge counter",
    )
    replace_once(
        path,
        '''        val observation = readCurrent(sourcePackage) ?: return
        val payload = observation.payload
''',
        '''        val observation = readCurrent(sourcePackage) ?: return
        val payload = observation.payload
''',
        "clipboard snapshot anchor",
    )
    replace_once(
        path,
        '''        if (suppressedFingerprint.compareAndSet(fp, null)) {
            recordObservedEvent(eventKey)
''',
        '''        if (suppressedFingerprint.compareAndSet(fp, null)) {
            DebugResourceCounters.increment("clipboard_remote_echo_suppressed_count")
            recordObservedEvent(eventKey)
''',
        "remote echo counter",
    )
    replace_once(
        path,
        "        if (lastObservedClipboardEvent.get() == eventKey) return\n",
        '''        if (lastObservedClipboardEvent.get() == eventKey) {
            DebugResourceCounters.increment("clipboard_duplicate_suppressed_count")
            return
        }
''',
        "event duplicate counter",
    )
    replace_once(
        path,
        '''        if (lastVisibleContentFingerprint.getAndSet(fingerprint) == fingerprint) {
            if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("adjacent_duplicate_suppressed_count")
''',
        '''        if (lastVisibleContentFingerprint.getAndSet(fingerprint) == fingerprint) {
            DebugResourceCounters.increment("clipboard_duplicate_suppressed_count")
            if (dev.clipmesh.BuildConfig.DEBUG) incrementDebugCounter("adjacent_duplicate_suppressed_count")
''',
        "content duplicate counter",
    )
    replace_once(
        path,
        '''        onLocalClip(payload)
    }
''',
        '''        DebugResourceCounters.increment("clipboard_emit_count")
        if (fromScreenshot) DebugResourceCounters.increment("screenshot_emit_count")
        onLocalClip(payload)
    }
''',
        "emit counters",
    )
    replace_once(
        path,
        '''    private fun latestScreenshot(): ScreenshotObservation? {
        val json = shizuku.readLatestScreenshotJson()
''',
        '''    private fun latestScreenshot(): ScreenshotObservation? {
        val json = shizuku.readLatestScreenshotJson()
''',
        "screenshot probe counter",
    )
    replace_once(
        path,
        '''        val copied = shizuku.copyUri(candidate.uri, temp)
        val bytes = if (copied) runCatching { temp.readBytes() }.getOrNull() else null
        temp.delete()
        val png = bytes?.let(::imageToPng)
''',
        '''        val bytes = try {
            if (shizuku.copyUri(candidate.uri, temp) && temp.length() <= MAX_ITEM_BYTES) {
                runCatching { temp.readBytes() }.getOrNull()
            } else null
        } finally {
            temp.delete()
        }
        val png = bytes?.let { imageToPng(it, candidate.mime) }
''',
        "screenshot temp cleanup",
    )
    replace_once(
        path,
        '''                captureExecutor.schedule(
                    { copyScreenshotCandidate(candidate, attempt + 1) },
                    delay,
                    TimeUnit.MILLISECONDS,
                )
''',
        '''                runCatching {
                    captureExecutor.schedule(
                        { copyScreenshotCandidate(candidate, attempt + 1) },
                        delay,
                        TimeUnit.MILLISECONDS,
                    )
                }
''',
        "stopped screenshot retry cleanup",
    )
    replace_once(
        path,
        "        val shizukuJson = shizuku.readSnapshotJson()\n",
        '''        DebugResourceCounters.increment("clipboard_snapshot_read_count")
        val shizukuJson = shizuku.readSnapshotJson()
''',
        "snapshot read counter",
    )
    replace_once(
        path,
        "                val png = readUriBytes(uri)?.let(::imageToPng) ?: continue\n",
        "                val png = readUriBytes(uri)?.let { imageToPng(it, mime) } ?: continue\n",
        "foreground image mime",
    )
    replace_once(
        path,
        "        if (clip.itemCount == 0 || isRemoteClip(clip)) return null\n",
        '''        if (clip.itemCount == 0) return null
        if (isRemoteClip(clip)) {
            DebugResourceCounters.increment("clipboard_remote_echo_suppressed_count")
            return null
        }
''',
        "foreground remote provenance counter",
    )
    replace_once(
        path,
        "        if (o.optBoolean(\"sensitive\", false) || o.optBoolean(\"remote\", false)) return null\n",
        '''        if (o.optBoolean("sensitive", false)) return null
        if (o.optBoolean("remote", false)) {
            DebugResourceCounters.increment("clipboard_remote_echo_suppressed_count")
            return null
        }
''',
        "privileged remote provenance counter",
    )
    replace_once(
        path,
        "                    if (rawBinaryBytes > 44L * 1024L * 1024L) break\n",
        "                    if (rawBinaryBytes > MAX_ITEM_BYTES) break\n",
        "shared payload limit",
    )
    replace_once(
        path,
        "                        val png = imageToPng(bytes)\n",
        "                        val png = imageToPng(bytes, mime)\n",
        "privileged image mime",
    )
    replace_once(
        path,
        '''                    val name = sanitizeName(item.optString("name", if (isImage) "clipboard.png" else "clipboard-$i"))
                    val hash = Crypto.hex(Crypto.sha256(bytes))
                    if (isImage && settings.syncImages && reps.none { it.mime.equals("image/png", ignoreCase = true) }) {
                        val png = imageToPng(bytes, mime)
                        if (png != null) {
                            reps += Representation("image/png", png)
                        } else if (settings.syncFiles) {
                            files += PortableFile(name, bytes, hash)
                        }
                    } else if (settings.syncFiles) {
                        files += PortableFile(name, bytes, hash)
                    }
''',
        '''                    val name = sanitizeName(item.optString("name", if (isImage) "clipboard.png" else "clipboard-$i"))
                    if (isImage && settings.syncImages && reps.none { it.mime.equals("image/png", ignoreCase = true) }) {
                        val png = imageToPng(bytes, mime)
                        if (png != null) {
                            reps += Representation("image/png", png)
                        } else if (settings.syncFiles) {
                            files += PortableFile(name, bytes, Crypto.hex(Crypto.sha256(bytes)))
                        }
                    } else if (settings.syncFiles) {
                        files += PortableFile(name, bytes, Crypto.hex(Crypto.sha256(bytes)))
                    }
''',
        "defer portable file hash",
    )
    old_reader = r'''    private fun readUriBytes(uri: Uri): ByteArray? = runCatching {
        context.contentResolver.openInputStream(uri)?.use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                total += n
                if (total > 44L * 1024L * 1024L) return@use null
                output.write(buffer, 0, n)
            }
            output.toByteArray()
        }
    }.getOrNull()
'''
    new_reader = r'''    private fun readUriBytes(uri: Uri): ByteArray? = runCatching {
        val descriptor = runCatching { context.contentResolver.openAssetFileDescriptor(uri, "r") }.getOrNull()
        if (descriptor != null) {
            descriptor.use { asset ->
                val knownLength = asset.length.takeIf { it >= 0L }
                if (knownLength != null && knownLength > MAX_ITEM_BYTES) return@use null
                asset.createInputStream().use { readBounded(it, knownLength) }
            }
        } else {
            context.contentResolver.openInputStream(uri)?.use { readBounded(it, null) }
        }
    }.getOrNull()

    private fun readBounded(input: java.io.InputStream, knownLength: Long?): ByteArray? {
        if (knownLength != null) {
            val bytes = ByteArray(knownLength.toInt())
            var offset = 0
            while (offset < bytes.size) {
                val count = input.read(bytes, offset, bytes.size - offset)
                if (count < 0) return bytes.copyOf(offset)
                if (count == 0) continue
                offset += count
            }
            val extra = input.read()
            if (extra < 0) return bytes
            val output = ByteArrayOutputStream((bytes.size + 1).coerceAtMost(MAX_ITEM_BYTES.toInt()))
            output.write(bytes)
            output.write(extra)
            return readUnknownLength(input, output, bytes.size.toLong() + 1L)
        }
        return readUnknownLength(input, ByteArrayOutputStream(), 0L)
    }

    private fun readUnknownLength(input: java.io.InputStream, output: ByteArrayOutputStream, initialSize: Long): ByteArray? {
        val buffer = ByteArray(64 * 1024)
        var total = initialSize
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            if (count == 0) continue
            total += count
            if (total > MAX_ITEM_BYTES) return null
            output.write(buffer, 0, count)
        }
        return output.toByteArray()
    }
'''
    replace_once(path, old_reader, new_reader, "bounded URI allocation")
    replace_once(
        path,
        '''    private fun imagePerceptualIdentity(bytes: ByteArray): ByteArray? {
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val orientation = runCatching {
            ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )
        }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
''',
        '''    private fun imagePerceptualIdentity(bytes: ByteArray): ByteArray? {
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val orientation = imageOrientation(bytes)
''',
        "perceptual orientation helper",
    )
    old_png = r'''    private fun imageToPng(bytes: ByteArray): ByteArray? {
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
'''
    new_png = r'''    private fun imageToPng(bytes: ByteArray, sourceMime: String? = null): ByteArray? {
        val orientation = imageOrientation(bytes)
        if (sourceMime?.substringBefore(';')?.equals("image/png", ignoreCase = true) == true &&
            (orientation == ExifInterface.ORIENTATION_NORMAL || orientation == ExifInterface.ORIENTATION_UNDEFINED) &&
            isDecodablePng(bytes)
        ) {
            // Preserve the exact PNG and avoid a full bitmap plus second encoded array.
            return bytes
        }
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val oriented = orientBitmap(decoded, orientation)
        return try {
            val output = ByteArrayOutputStream()
            if (!oriented.compress(Bitmap.CompressFormat.PNG, 100, output)) null else output.toByteArray()
        } finally {
            if (oriented !== decoded) oriented.recycle()
            decoded.recycle()
        }
    }

    private fun imageOrientation(bytes: ByteArray): Int = runCatching {
        ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(
            ExifInterface.TAG_ORIENTATION,
            ExifInterface.ORIENTATION_NORMAL,
        )
    }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)

    private fun isDecodablePng(bytes: ByteArray): Boolean {
        if (bytes.size < PNG_SIGNATURE.size || !bytes.copyOfRange(0, PNG_SIGNATURE.size).contentEquals(PNG_SIGNATURE)) return false
        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
        return options.outWidth > 0 && options.outHeight > 0
    }
'''
    replace_once(path, old_png, new_png, "PNG pass-through")
    replace_once(
        path,
        '''    private companion object {
        const val EDGE_COALESCE_MS = 60L
        const val SCREENSHOT_COPY_RETRIES = 8
''',
        '''    private companion object {
        const val EDGE_COALESCE_MS = 60L
        const val SCREENSHOT_COPY_RETRIES = 8
        const val MAX_ITEM_BYTES = 44L * 1024L * 1024L
        val PNG_SIGNATURE = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
''',
        "clipboard constants",
    )


def patch_user_service(path: Path) -> None:
    replace_once(
        path,
        "    @Volatile private var lastClip: ClipData? = null\n",
        "    @Volatile private var lastClipUris: Map<Int, Uri> = emptyMap()\n",
        "small URI snapshot state",
    )
    replace_once(
        path,
        '''        val clip = invokeClipboard("getPrimaryClip") as? ClipData ?: return ""
        if (clip.itemCount == 0) return ""
        lastClip = clip
        val description = clip.description
        val items = JSONArray()
''',
        '''        val clip = invokeClipboard("getPrimaryClip") as? ClipData ?: run {
            lastClipUris = emptyMap()
            return ""
        }
        if (clip.itemCount == 0) {
            lastClipUris = emptyMap()
            return ""
        }
        val description = clip.description
        val items = JSONArray()
        val itemUris = mutableMapOf<Int, Uri>()
''',
        "snapshot URI map",
    )
    replace_once(
        path,
        '''                if (uri != null) {
                    put("uri", uri.toString())
''',
        '''                if (uri != null) {
                    itemUris[i] = uri
                    put("uri", uri.toString())
''',
        "remember URI only",
    )
    replace_once(
        path,
        '''        val timestamp = description?.timestamp ?: 0L
        return JSONObject().put("sensitive", sensitive).put("remote", remote)
''',
        '''        val timestamp = description?.timestamp ?: 0L
        lastClipUris = itemUris.toMap()
        return JSONObject().put("sensitive", sensitive).put("remote", remote)
''',
        "publish URI map",
    )
    replace_once(
        path,
        '''    override fun copyPrimaryClipItemToFile(index: Int, destination: ParcelFileDescriptor): Boolean {
        val clip = lastClip ?: (invokeClipboard("getPrimaryClip") as? ClipData) ?: return false
        if (index !in 0 until clip.itemCount) return false
        val uri = clip.getItemAt(index).uri ?: return false
        return readUriAsShell(uri, destination) || readUriWithResolver(uri, destination)
    }
''',
        '''    override fun copyPrimaryClipItemToFile(index: Int, destination: ParcelFileDescriptor): Boolean {
        val uri = lastClipUris[index] ?: run {
            val clip = invokeClipboard("getPrimaryClip") as? ClipData ?: return false
            if (index !in 0 until clip.itemCount) return false
            clip.getItemAt(index).uri ?: return false
        }
        return readUriAsShell(uri, destination) || readUriWithResolver(uri, destination)
    }
''',
        "copy without retained ClipData",
    )
    replace_once(path, "        lastClip = null\n", "        lastClipUris = emptyMap()\n", "destroy retained URI map")


def patch_transfer(path: Path) -> None:
    replace_once(
        path,
        "import dev.clipmesh.SettingsStore\n",
        "import dev.clipmesh.DebugResourceCounters\nimport dev.clipmesh.SettingsStore\n",
        "transfer diagnostics import",
    )
    replace_once(
        path,
        '''        runCatching { multicastLock?.release() }
        multicast = null
        server = null
        multicastLock = null
''',
        '''        releaseMulticastLock()
        multicast = null
        server = null
''',
        "stop multicast release",
    )
    replace_once(
        path,
        '''            multicastLock = wifi.createMulticastLock("clipmesh-file-transfer").apply {
                setReferenceCounted(false)
                acquire()
            }
''',
        '''            multicastLock = wifi.createMulticastLock("clipmesh-file-transfer").apply {
                setReferenceCounted(false)
                acquire()
            }
            DebugResourceCounters.multicastLockAcquired()
''',
        "multicast acquire counter",
    )
    replace_once(
        path,
        '''                val raw = String(packet.data, packet.offset, packet.length, Charsets.UTF_8)
''',
        '''                DebugResourceCounters.increment("multicast_packets_received_count")
                val raw = String(packet.data, packet.offset, packet.length, Charsets.UTF_8)
''',
        "multicast packet counter",
    )
    replace_once(
        path,
        '''        } finally {
            runCatching { multicastLock?.release() }
            multicastLock = null
            multicast = null
        }
    }

    private fun sendAnnouncement(announce: Boolean) {
''',
        '''        } finally {
            releaseMulticastLock()
            multicast = null
        }
    }

    @Synchronized
    private fun releaseMulticastLock() {
        val lock = multicastLock ?: return
        multicastLock = null
        if (runCatching { lock.isHeld }.getOrDefault(false)) {
            runCatching { lock.release() }
            DebugResourceCounters.multicastLockReleased()
        }
    }

    private fun sendAnnouncement(announce: Boolean) {
''',
        "single multicast release helper",
    )
    replace_once(
        path,
        '''            method == "POST" && path == "/api/clipmesh/v1/register" -> {
                val body = readBody(input, length, MAX_METADATA) ?: return respond(output, 400, "Invalid body")
''',
        '''            method == "POST" && path == "/api/clipmesh/v1/register" -> {
                DebugResourceCounters.increment("direct_register_count")
                val body = readBody(input, length, MAX_METADATA) ?: return respond(output, 400, "Invalid body")
''',
        "direct register counter",
    )


def patch_dev_receiver(path: Path, manifest: Path) -> None:
    replace_once(
        path,
        '''            ACTION_INFO -> writeInfo(app)
            ACTION_FAVORITE -> {
''',
        r'''            ACTION_INFO -> writeInfo(app)
            ACTION_RESET_RESOURCE_COUNTERS -> {
                DebugResourceCounters.reset()
                app.getSharedPreferences("clipmesh_ci", Context.MODE_PRIVATE).edit().clear().apply()
                result(app, "resource_counters_reset=true\n")
            }
            ACTION_FAVORITE -> {
''',
        "debug counter reset action",
    )
    replace_once(
        path,
        r'''            append("last_remote_fallback_at=").append(ci.getLong("last_remote_fallback_at", 0L)).append('\n')
''',
        r'''            append("last_remote_fallback_at=").append(ci.getLong("last_remote_fallback_at", 0L)).append('\n')
            DebugResourceCounters.snapshot().toSortedMap().forEach { (name, value) ->
                append(name).append('=').append(value).append('\n')
            }
            append("broadcast_packets_received_count=-1").append('\n')
            append("discovery_packet_classification=shared_socket").append('\n')
''',
        "debug counter dump",
    )
    replace_once(
        path,
        '''        const val ACTION_INFO = "dev.clipmesh.devtest.INFO"
        const val ACTION_FAVORITE = "dev.clipmesh.devtest.FAVORITE"
''',
        '''        const val ACTION_INFO = "dev.clipmesh.devtest.INFO"
        const val ACTION_RESET_RESOURCE_COUNTERS = "dev.clipmesh.devtest.RESET_RESOURCE_COUNTERS"
        const val ACTION_FAVORITE = "dev.clipmesh.devtest.FAVORITE"
''',
        "debug reset constant",
    )
    replace_once(
        manifest,
        '''                <action android:name="dev.clipmesh.devtest.INFO" />
                <action android:name="dev.clipmesh.devtest.FAVORITE" />
''',
        '''                <action android:name="dev.clipmesh.devtest.INFO" />
                <action android:name="dev.clipmesh.devtest.RESET_RESOURCE_COUNTERS" />
                <action android:name="dev.clipmesh.devtest.FAVORITE" />
''',
        "debug reset manifest action",
    )


def patch_android() -> None:
    java = PROJECT / "android/app/src/main/java/dev/clipmesh"
    patch_diagnostics(java)
    patch_network(java / "network/NetworkEngine.kt")
    patch_clipboard(java / "clipboard/ClipboardBridge.kt")
    patch_user_service(java / "shizuku/ClipboardUserService.kt")
    patch_transfer(java / "fileshare/LocalTransferEngine.kt")
    patch_dev_receiver(
        PROJECT / "android/app/src/debug/java/dev/clipmesh/DevTestReceiver.kt",
        PROJECT / "android/app/src/debug/AndroidManifest.xml",
    )


if SYSTEM == "Linux":
    patch_android()

print(f"Applied ClipMesh v054 resource finalization on {SYSTEM}")
