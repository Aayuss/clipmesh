package dev.clipmesh.network

import dev.clipmesh.SettingsStore
import dev.clipmesh.crypto.Crypto
import dev.clipmesh.model.ClipPayload
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.selects.select
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.*
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean

/** Bounded per-peer queue policy, separated for deterministic stress testing. */
internal class PeerOutgoingQueue(controlCapacity: Int = 64) {
    private val controlQueue = Channel<ByteArray>(capacity = controlCapacity)
    private val latestClipboard = Channel<ByteArray>(capacity = Channel.CONFLATED)
    private val closed = AtomicBoolean(false)

    suspend fun sendControl(bytes: ByteArray): Boolean {
        if (closed.get()) return false
        return runCatching { controlQueue.send(bytes); true }.getOrDefault(false)
    }

    fun sendLatest(bytes: ByteArray): Boolean =
        !closed.get() && latestClipboard.trySend(bytes).isSuccess

    suspend fun receive(): ByteArray? = controlQueue.tryReceive().getOrNull() ?: select {
        controlQueue.onReceiveCatching { it.getOrNull() }
        latestClipboard.onReceiveCatching { it.getOrNull() }
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return
        controlQueue.close()
        latestClipboard.close()
    }
}

internal fun interface ExpiryHandle {
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

/**
 * Push-only LAN transport (v063). Idle costs nothing: a listening TCP socket and
 * a UDP socket, no keepalive pings, no periodic discovery or redial loops. A copy
 * dials each paired peer at its last known address (a unicast connect also wakes
 * a sleeping device); the new link replays the latest clip, the peer ACKs, and
 * the link closes after [LINK_LINGER_MS]. A stale address triggers one discovery
 * broadcast; peers answer by unicast so the address is re-learned.
 */
class NetworkEngine(
    private val settings: SettingsStore,
    private val masterKey: ByteArray,
    private val onRemoteClip: (ClipPayload) -> Unit,
    private val onStatus: (String) -> Unit = {}
) {
    companion object {
        const val DISCOVERY_PORT = 41473
        const val TCP_PORT = 41474
        private const val MAX_DISCOVERY = 4096
        private const val HELLO_SIZE = 92
        private const val REPLAY_TTL_MS = 30_000L
        private const val LINK_LINGER_MS = 45_000
        private const val SEEN_LIMIT = 512
        private const val PEER_REPLACE_AFTER_MS = 10_000L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val peers = ConcurrentHashMap<UUID, PeerConnection>()
    private val seen = ConcurrentHashMap<UUID, Long>()
    private val pending = ConcurrentHashMap<UUID, PendingFrame>()
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

    fun start() {
        if (!running.compareAndSet(false, true)) return
        requireNotNull(settings.spaceId) { "ClipMesh is not paired" }
        scope.launch { tcpServerLoop() }
        scope.launch { discoveryLoop() }
        onStatus("LAN sync active")
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        runCatching { udp?.close() }
        runCatching { server?.close() }
        peers.values.forEach { it.close() }
        peers.clear()
        synchronized(retainedStateLock) {
            retryJobs.values.forEach { it.job.cancel() }
            retryJobs.clear()
            pending.clear()
            latestFrame.clear()
        }
        masterKey.fill(0)
        scope.cancel()
        onStatus("Stopped")
    }

    fun sendClipboard(payload: ClipPayload) {
        if (!running.get() || !settings.sendEnabled) return
        val bytes = runCatching { payload.toJsonBytes() }.getOrElse { return }
        val messageId = UUID.randomUUID()
        val frame = runCatching {
            Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.CLIPBOARD, 0, settings.deviceId, messageId, bytes)
        }.getOrElse { return }
        synchronized(retainedStateLock) {
            if (!running.get()) return
            latestFrame.store(LatestFrameRetention.Frame(android.os.SystemClock.elapsedRealtime(), messageId, frame))
        }
        peers.forEach { (peerId, connection) ->
            if (connection.sendLatest(frame)) {
                pending[peerId] = PendingFrame(peerId, messageId, frame)
                scheduleRetry(peerId, messageId, connection)
            }
        }
        // Paired peers without a live link: dial now; the link replays this frame.
        dialKnownPeers()
    }

    /** Dial every paired (or static) peer that currently has no live link. */
    fun dialKnownPeers() {
        if (!running.get()) return
        val targets = mutableListOf<Pair<InetAddress, Int>>()
        settings.staticPeers.forEach { entry -> parsePeer(entry)?.let { if (isLan(it.first)) targets += it } }
        for (known in settings.knownPeers()) {
            if (known.deviceId == settings.deviceId || peers.containsKey(known.deviceId) || settings.isPeerBlocked(known.deviceId)) continue
            val address = runCatching { InetAddress.getByName(known.address) }.getOrNull() ?: continue
            if (!isLan(address)) continue
            targets += address to (if (known.port in 1..65535) known.port else TCP_PORT)
        }
        targets.forEach { (address, port) -> scope.launch { connect(address, port) } }
    }

    /** On-demand reachability for the UI: TCP connect to each paired peer; success refreshes last-seen. */
    suspend fun probePeers() = coroutineScope {
        settings.knownPeers()
            .filter { it.deviceId != settings.deviceId && !settings.isPeerBlocked(it.deviceId) }
            .map { known ->
                async(Dispatchers.IO) {
                    val address = runCatching { InetAddress.getByName(known.address) }.getOrNull() ?: return@async
                    if (!isLan(address)) return@async
                    val ok = runCatching { Socket().use { it.connect(InetSocketAddress(address, if (known.port in 1..65535) known.port else TCP_PORT), 1500) } }.isSuccess
                    if (ok) settings.touchPeer(known.deviceId, known.address)
                }
            }.awaitAll()
        Unit
    }

    private val dialing = ConcurrentHashMap<InetAddress, Boolean>()
    private val replied = ConcurrentHashMap<UUID, Long>()
    @Volatile private var lastBroadcastMs = 0L

    /** One signed discovery broadcast, at most every 5s (start, stale address, rescan). */
    fun broadcastDiscovery() {
        val socket = udp ?: return
        val now = android.os.SystemClock.elapsedRealtime()
        if (now - lastBroadcastMs < 5_000L) return
        lastBroadcastMs = now
        scope.launch {
            runCatching {
                val data = Crypto.signedDiscovery(masterKey, requireNotNull(settings.spaceId), settings.deviceId, settings.deviceName, TCP_PORT)
                socket.send(DatagramPacket(data, data.size, InetAddress.getByName("255.255.255.255"), DISCOVERY_PORT))
            }
        }
    }

    fun peerCount(): Int = peers.size

    private suspend fun tcpServerLoop() {
        while (running.get() && currentCoroutineContext().isActive) {
            try {
                val s = ServerSocket().apply {
                    reuseAddress = true
                    bind(InetSocketAddress("0.0.0.0", TCP_PORT))
                }
                server = s
                while (running.get()) {
                    val socket = s.accept()
                    if (!isLan(socket.inetAddress)) {
                        socket.close(); continue
                    }
                    scope.launch { handleConnection(socket, outgoing = false) }
                }
            } catch (_: SocketException) {
                if (running.get()) delay(1000)
            } catch (_: Exception) {
                delay(1000)
            }
        }
    }

    private suspend fun discoveryLoop() {
        val socket = try {
            DatagramSocket(null).apply {
                reuseAddress = true
                broadcast = true
                bind(InetSocketAddress("0.0.0.0", DISCOVERY_PORT))
                soTimeout = 0
            }
        } catch (_: Exception) { return }
        udp = socket

        val receiver = scope.launch {
            val buf = ByteArray(MAX_DISCOVERY)
            while (running.get() && isActive) {
                try {
                    val packet = DatagramPacket(buf, buf.size)
                    socket.receive(packet)
                    if (!isLan(packet.address)) continue
                    val data = packet.data.copyOfRange(packet.offset, packet.offset + packet.length)
                    val d = runCatching { Crypto.verifyDiscovery(masterKey, requireNotNull(settings.spaceId), data) }.getOrNull() ?: continue
                    if (d.deviceId == settings.deviceId || settings.isPeerBlocked(d.deviceId)) continue
                    settings.rememberPeer(d.deviceId, d.name, packet.address.hostAddress.orEmpty(), d.port)
                    // Answer by unicast so the announcer learns our address (rate limited).
                    val nowMs = android.os.SystemClock.elapsedRealtime()
                    if (nowMs - (replied[d.deviceId] ?: 0L) > 30_000L) {
                        replied[d.deviceId] = nowMs
                        runCatching {
                            val ours = Crypto.signedDiscovery(masterKey, requireNotNull(settings.spaceId), settings.deviceId, settings.deviceName, TCP_PORT)
                            socket.send(DatagramPacket(ours, ours.size, packet.address, DISCOVERY_PORT))
                        }
                    }
                    // Only connect when a clip is waiting for this peer.
                    if (peers.containsKey(d.deviceId) || latestFrame.fresh() == null) continue
                    val address = packet.address
                    scope.launch { connect(address, d.port) }
                } catch (_: SocketTimeoutException) {
                } catch (_: Exception) {
                    if (running.get()) delay(250)
                }
            }
        }

        // Announce once at start so peers learn our current address; never periodically.
        broadcastDiscovery()
        receiver.join()
    }

    private suspend fun connect(address: InetAddress, port: Int) {
        if (!running.get() || !isLan(address)) return
        if (peers.values.any { it.remoteAddress == address }) return
        if (dialing.putIfAbsent(address, true) != null) return
        val socket = Socket()
        try {
            socket.connect(InetSocketAddress(address, port), 3000)
            dialing.remove(address)
            handleConnection(socket, outgoing = true)
        } catch (_: Exception) {
            dialing.remove(address)
            runCatching { socket.close() }
            // Stale address (DHCP / network change): ask peers to re-announce.
            broadcastDiscovery()
        }
    }

    private suspend fun handleConnection(socket: Socket, outgoing: Boolean) = withContext(Dispatchers.IO) {
        socket.tcpNoDelay = true
        socket.keepAlive = true
        // No keepalive pings: an unused link closes after the linger.
        socket.soTimeout = LINK_LINGER_MS
        if (!isLan(socket.inetAddress)) { socket.close(); return@withContext }
        val input = DataInputStream(BufferedInputStream(socket.getInputStream(), 64 * 1024))
        val output = DataOutputStream(BufferedOutputStream(socket.getOutputStream(), 64 * 1024))
        val ourHello = Crypto.buildHello(masterKey, requireNotNull(settings.spaceId), settings.deviceId)
        val remoteHello = ByteArray(HELLO_SIZE)
        try {
            if (outgoing) {
                output.write(ourHello); output.flush()
                input.readFully(remoteHello)
            } else {
                input.readFully(remoteHello)
                output.write(ourHello); output.flush()
            }
            val peerId = Crypto.verifyHello(masterKey, requireNotNull(settings.spaceId), remoteHello)
            if (peerId == settings.deviceId) throw IllegalStateException("self connection")
            if (settings.isPeerBlocked(peerId)) throw IllegalStateException("removed peer")
            val connection = PeerConnection(UUID.randomUUID(), peerId, socket.inetAddress, socket, output)
            var replaced: PeerConnection? = null
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
            if (!accepted) {
                connection.close()
                return@withContext
            }
            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())
            onStatus("Sync active")

            latestFrame.fresh()?.let { latest ->
                if (connection.sendLatest(latest.bytes)) {
                    pending[peerId] = PendingFrame(peerId, latest.message, latest.bytes)
                    scheduleRetry(peerId, latest.message, connection)
                }
            }

            val writer = scope.launch { connection.writerLoop() }
            try {
                while (running.get() && !socket.isClosed) {
                    val len = input.readInt()
                    if (len < Crypto.HEADER_SIZE + 16 || len > Crypto.MAX_FRAME_SIZE) throw IllegalArgumentException("invalid frame size")
                    val bytes = ByteArray(len)
                    input.readFully(bytes)
                    val frame = Crypto.decryptFrame(masterKey, requireNotNull(settings.spaceId), bytes)
                    if (frame.sender != peerId) throw SecurityException("authenticated peer/sender mismatch")
                    settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())
                    when (frame.kind) {
                        Crypto.Kind.CLIPBOARD -> {
                            if (seen.size > SEEN_LIMIT) {
                                val cutoff = System.currentTimeMillis() - 300_000L
                                seen.entries.removeIf { it.value < cutoff }
                            }
                            val duplicate = seen.putIfAbsent(frame.messageId, System.currentTimeMillis()) != null
                            val ack = Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.ACK, 0, settings.deviceId, frame.messageId, ByteArray(0))
                            connection.sendControl(ack)
                            if (!duplicate && settings.markClipboardMessageDelivered(peerId, frame.messageId) && settings.receiveEnabled) {
                                runCatching { ClipPayload.fromJsonBytes(frame.plaintext) }.getOrNull()?.let(onRemoteClip)
                            }
                        }
                        Crypto.Kind.ACK -> acknowledge(peerId, frame.messageId)
                        Crypto.Kind.PING -> {
                            val pong = Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.PONG, 0, settings.deviceId, frame.messageId, ByteArray(0))
                            connection.sendControl(pong)
                        }
                        Crypto.Kind.PONG -> Unit
                    }
                }
            } finally {
                writer.cancel()
                val wasCurrent = peers[peerId]?.id == connection.id
                if (wasCurrent) peers.remove(peerId)
                connection.close()
                if (wasCurrent) clearPeerRetry(peerId)
                onStatus("Sync active")
            }
        } catch (_: Exception) {
            runCatching { socket.close() }
        }
    }

    private fun scheduleRetry(peerId: UUID, messageId: UUID, connection: PeerConnection) {
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

    private fun shouldInitiate(local: UUID, remote: UUID): Boolean =
        local.toString().compareTo(remote.toString(), ignoreCase = true) < 0

    private fun parsePeer(text: String): Pair<InetAddress, Int>? = runCatching {
        val t = text.trim()
        val host: String
        val port: Int
        if (t.startsWith("[")) {
            val end = t.indexOf(']')
            host = t.substring(1, end)
            port = t.substring(end + 1).removePrefix(":").toIntOrNull() ?: TCP_PORT
        } else if (t.count { it == ':' } == 1) {
            host = t.substringBefore(':'); port = t.substringAfter(':').toInt()
        } else {
            host = t; port = TCP_PORT
        }
        InetAddress.getByName(host) to port
    }.getOrNull()

    private fun isLan(address: InetAddress): Boolean {
        if (address.isLoopbackAddress || address.isLinkLocalAddress || address.isSiteLocalAddress) return true
        val bytes = address.address
        return bytes.size == 16 && ((bytes[0].toInt() and 0xfe) == 0xfc)
    }

    private class PeerConnection(
        val id: UUID,
        val peerId: UUID,
        val remoteAddress: InetAddress,
        private val socket: Socket,
        private val output: DataOutputStream
    ) {
        // Control frames are small and lossless with backpressure. Clipboard
        // state is conflated: a stalled peer retains only the latest encrypted
        // state instead of an unbounded sequence of large ByteArrays.
        private val outgoing = PeerOutgoingQueue()
        private val closed = AtomicBoolean(false)
        val createdAt: Long = System.currentTimeMillis()

        suspend fun sendControl(bytes: ByteArray): Boolean =
            !closed.get() && outgoing.sendControl(bytes)

        fun sendLatest(bytes: ByteArray): Boolean =
            !closed.get() && outgoing.sendLatest(bytes)

        suspend fun writerLoop() {
            try {
                while (!closed.get()) {
                    val frame = outgoing.receive() ?: break
                    if (frame.size > Crypto.MAX_FRAME_SIZE) break
                    output.writeInt(frame.size)
                    output.write(frame)
                    output.flush()
                }
            } catch (_: Exception) {
            } finally {
                close()
            }
        }

        fun close() {
            if (!closed.compareAndSet(false, true)) return
            outgoing.close()
            runCatching { socket.close() }
        }
    }

}
