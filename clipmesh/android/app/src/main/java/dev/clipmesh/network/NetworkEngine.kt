package dev.clipmesh.network

import dev.clipmesh.SettingsStore
import dev.clipmesh.crypto.Crypto
import dev.clipmesh.model.ClipPayload
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.*
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean

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
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val peers = ConcurrentHashMap<UUID, PeerConnection>()
    private val seen = ConcurrentHashMap<UUID, Long>()
    private val pending = ConcurrentHashMap<String, PendingFrame>()
    private val running = AtomicBoolean(false)
    private var udp: DatagramSocket? = null
    private var server: ServerSocket? = null
    @Volatile private var latestFrame: LatestFrame? = null

    data class LatestFrame(val createdAtMs: Long, val message: UUID, val bytes: ByteArray)
    data class PendingFrame(val peer: UUID, val message: UUID, val bytes: ByteArray)

    fun start() {
        if (!running.compareAndSet(false, true)) return
        requireNotNull(settings.spaceId) { "ClipMesh is not paired" }
        scope.launch { tcpServerLoop() }
        scope.launch { discoveryLoop() }
        scope.launch { staticPeerLoop() }
        scope.launch { maintenanceLoop() }
        onStatus("LAN sync active")
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        runCatching { udp?.close() }
        runCatching { server?.close() }
        peers.values.forEach { it.close() }
        peers.clear()
        pending.clear()
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
        latestFrame = LatestFrame(System.currentTimeMillis(), messageId, frame)
        peers.forEach { (peerId, connection) ->
            if (connection.send(frame)) {
                val key = pendingKey(peerId, messageId)
                pending[key] = PendingFrame(peerId, messageId, frame)
                scheduleRetry(key, connection)
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
                    if (peers.containsKey(d.deviceId)) continue
                    val preferred = shouldInitiate(settings.deviceId, d.deviceId)
                    scope.launch {
                        if (!preferred) {
                            delay(2_500L)
                            if (peers.containsKey(d.deviceId)) return@launch
                        }
                        connect(packet.address, d.port)
                    }
                } catch (_: SocketTimeoutException) {
                } catch (_: Exception) {
                    if (running.get()) delay(250)
                }
            }
        }

        while (running.get() && currentCoroutineContext().isActive) {
            runCatching {
                val data = Crypto.signedDiscovery(masterKey, requireNotNull(settings.spaceId), settings.deviceId, settings.deviceName, TCP_PORT)
                val p = DatagramPacket(data, data.size, InetAddress.getByName("255.255.255.255"), DISCOVERY_PORT)
                socket.send(p)
            }
            delay(if (peers.isEmpty()) 60_000L else 180_000L)
        }
        receiver.cancelAndJoin()
    }

    private suspend fun staticPeerLoop() {
        while (running.get() && currentCoroutineContext().isActive) {
            for (entry in settings.staticPeers) {
                parsePeer(entry)?.let { (address, port) -> if (isLan(address)) scope.launch { connect(address, port) } }
            }
            delay(120_000L)
        }
    }

    private suspend fun maintenanceLoop() {
        while (running.get() && currentCoroutineContext().isActive) {
            val now = System.currentTimeMillis()
            seen.entries.removeIf { now - it.value > 300_000L }
            peers.values.forEach { p ->
                val pingId = UUID.randomUUID()
                runCatching {
                    Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.PING, 0, settings.deviceId, pingId, ByteArray(0))
                }.getOrNull()?.let { p.send(it) }
            }
            onStatus("Sync active")
            delay(120_000L)
        }
    }

    private suspend fun connect(address: InetAddress, port: Int) {
        if (!running.get() || !isLan(address)) return
        if (peers.values.any { it.remoteAddress == address }) return
        val socket = Socket()
        try {
            socket.connect(InetSocketAddress(address, port), 2000)
            handleConnection(socket, outgoing = true)
        } catch (_: Exception) {
            runCatching { socket.close() }
        }
    }

    private suspend fun handleConnection(socket: Socket, outgoing: Boolean) = withContext(Dispatchers.IO) {
        socket.tcpNoDelay = true
        socket.keepAlive = true
        socket.soTimeout = 0
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
            val accepted = synchronized(peers) {
                if (peers.containsKey(peerId)) {
                    false
                } else {
                    peers[peerId] = connection
                    true
                }
            }
            if (!accepted) {
                connection.close()
                return@withContext
            }
            settings.touchPeer(peerId, socket.inetAddress.hostAddress.orEmpty())
            onStatus("Sync active")

            latestFrame?.takeIf { System.currentTimeMillis() - it.createdAtMs < 30_000L }?.let { latest ->
                if (connection.send(latest.bytes)) {
                    val key = pendingKey(peerId, latest.message)
                    pending[key] = PendingFrame(peerId, latest.message, latest.bytes)
                    scheduleRetry(key, connection)
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
                            val duplicate = seen.putIfAbsent(frame.messageId, System.currentTimeMillis()) != null
                            val ack = Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.ACK, 0, settings.deviceId, frame.messageId, ByteArray(0))
                            connection.send(ack)
                            if (!duplicate && settings.markClipboardMessageDelivered(peerId, frame.messageId) && settings.receiveEnabled) {
                                runCatching { ClipPayload.fromJsonBytes(frame.plaintext) }.getOrNull()?.let(onRemoteClip)
                            }
                        }
                        Crypto.Kind.ACK -> pending.remove(pendingKey(peerId, frame.messageId))
                        Crypto.Kind.PING -> {
                            val pong = Crypto.encryptFrame(masterKey, requireNotNull(settings.spaceId), Crypto.Kind.PONG, 0, settings.deviceId, frame.messageId, ByteArray(0))
                            connection.send(pong)
                        }
                        Crypto.Kind.PONG -> Unit
                    }
                }
            } finally {
                writer.cancel()
                if (peers[peerId]?.id == connection.id) peers.remove(peerId)
                connection.close()
                pending.keys.removeIf { it.startsWith("$peerId|") }
                onStatus("Sync active")
            }
        } catch (_: Exception) {
            runCatching { socket.close() }
        }
    }

    private fun scheduleRetry(key: String, connection: PeerConnection) {
        scope.launch {
            for (delayMs in longArrayOf(750, 1500, 3000)) {
                delay(delayMs)
                val p = pending[key] ?: return@launch
                if (!connection.send(p.bytes)) break
            }
            pending.remove(key)
        }
    }

    private fun pendingKey(peer: UUID, message: UUID) = "$peer|$message"

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
        private val queue = Channel<ByteArray>(capacity = Channel.UNLIMITED)
        private val closed = AtomicBoolean(false)

        fun send(bytes: ByteArray): Boolean = !closed.get() && queue.trySend(bytes).isSuccess

        suspend fun writerLoop() {
            try {
                for (frame in queue) {
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
            queue.close()
            runCatching { socket.close() }
        }
    }
}
