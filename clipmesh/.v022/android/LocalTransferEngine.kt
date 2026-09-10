package dev.clipmesh.fileshare

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import dev.clipmesh.SettingsStore
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.MulticastSocket
import java.net.ServerSocket
import java.net.Socket
import java.net.URI
import java.net.URL
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Local-only file transfer engine. Its LAN discovery and upload endpoints follow
 * LocalSend protocol v2 semantics so ClipMesh can discover LocalSend-compatible
 * peers without depending on a cloud service.
 */
object LocalTransferEngine {
    const val PORT = 53317
    const val MULTICAST_GROUP = "224.0.0.167"
    private const val PROTOCOL_VERSION = "2.0"
    private const val PREFS = "clipmesh_file_transfer"
    private const val MAX_METADATA = 2 * 1024 * 1024
    private const val DEVICE_TTL_MS = 180_000L

    data class TransferDevice(
        val alias: String,
        val fingerprint: String,
        val address: String,
        val port: Int,
        val deviceModel: String,
        val deviceType: String,
        val lastSeenMs: Long
    )

    data class FileMeta(
        val id: String,
        val fileName: String,
        val size: Long,
        val fileType: String,
        val sha256: String?
    )

    private data class UploadSession(
        val id: String,
        val senderAlias: String,
        val senderFingerprint: String,
        val senderAddress: String,
        val files: Map<String, FileMeta>,
        val tokens: Map<String, String>,
        val received: MutableSet<String> = ConcurrentHashMap.newKeySet()
    )

    data class IncomingDecision(
        val requestId: String,
        val senderAlias: String,
        val senderFingerprint: String,
        val files: List<FileMeta>,
        val latch: CountDownLatch = CountDownLatch(1),
        @Volatile var accepted: Boolean = false
    )

    private data class HttpResult(val status: Int, val body: String)
    private data class SendMeta(val id: String, val uri: Uri, val name: String, val size: Long, val mime: String)
    private data class SaveTarget(val output: OutputStream, val finish: (Boolean) -> Unit)

    private val started = AtomicBoolean(false)
    private val executor = Executors.newCachedThreadPool()
    private val nearby = ConcurrentHashMap<String, TransferDevice>()
    private val sessions = ConcurrentHashMap<String, UploadSession>()
    private val pending = ConcurrentHashMap<String, IncomingDecision>()
    @Volatile private var appContext: Context? = null
    @Volatile private var multicast: MulticastSocket? = null
    @Volatile private var server: ServerSocket? = null
    @Volatile private var multicastLock: WifiManager.MulticastLock? = null

    fun start(context: Context) {
        appContext = context.applicationContext
        if (!started.compareAndSet(false, true)) return
        executor.execute(::runDiscovery)
        executor.execute(::runServer)
        executor.execute(::runAnnouncer)
    }

    fun stop() {
        started.set(false)
        runCatching { multicast?.close() }
        runCatching { server?.close() }
        runCatching { multicastLock?.release() }
        multicast = null
        server = null
        multicastLock = null
        nearby.clear()
        pending.values.forEach { it.latch.countDown() }
        pending.clear()
        sessions.clear()
    }

    fun nearbyDevices(): List<TransferDevice> {
        val now = System.currentTimeMillis()
        nearby.entries.removeIf { now - it.value.lastSeenMs > DEVICE_TTL_MS }
        return nearby.values
            .filter { it.fingerprint != fingerprint(requireContext()) }
            .sortedWith(compareByDescending<TransferDevice> { isFavorite(requireContext(), it.fingerprint) }
                .thenBy { it.alias.lowercase() })
    }

    fun isFavorite(context: Context, fingerprint: String): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getStringSet("favorites", emptySet())
            ?.contains(fingerprint) == true

    fun setFavorite(context: Context, fingerprint: String, favorite: Boolean) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val values = prefs.getStringSet("favorites", emptySet())?.toMutableSet() ?: mutableSetOf()
        if (favorite) values += fingerprint else values -= fingerprint
        prefs.edit().putStringSet("favorites", values).apply()
    }

    fun fingerprint(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return prefs.getString("fingerprint", null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString("fingerprint", it).apply()
        }
    }

    fun resolveIncoming(requestId: String, accepted: Boolean) {
        val request = pending[requestId] ?: return
        request.accepted = accepted
        request.latch.countDown()
    }

    /** Runs synchronously. Call from an IO thread. */
    fun sendUris(
        context: Context,
        uris: List<Uri>,
        target: TransferDevice,
        progress: (completed: Int, total: Int, status: String) -> Unit
    ) {
        require(uris.isNotEmpty()) { "No files selected" }
        val metas = uris.map { uri -> buildSendMeta(context, uri) }
        val files = JSONObject()
        metas.forEach { meta ->
            files.put(meta.id, JSONObject().apply {
                put("id", meta.id)
                put("fileName", meta.name)
                put("size", meta.size)
                put("fileType", meta.mime)
            })
        }
        val prepareBody = JSONObject().apply {
            put("info", myInfo(context, announce = false))
            put("files", files)
        }
        progress(0, metas.size, "Waiting for ${target.alias}…")
        val prepare = postJson(target, "/api/localsend/v2/prepare-upload", prepareBody)
        when (prepare.status) {
            200 -> Unit
            204 -> return
            403 -> throw IllegalStateException("${target.alias} declined the transfer")
            409 -> throw IllegalStateException("${target.alias} is busy with another transfer")
            429 -> throw IllegalStateException("${target.alias} is receiving too many requests")
            else -> throw IllegalStateException("Transfer request failed (${prepare.status})")
        }
        val response = JSONObject(prepare.body)
        val sessionId = response.getString("sessionId")
        val tokens = response.getJSONObject("files")
        metas.forEachIndexed { index, meta ->
            val token = tokens.optString(meta.id, "")
            if (token.isBlank()) return@forEachIndexed
            progress(index, metas.size, "Sending ${meta.name}")
            uploadUri(context, target, sessionId, meta, token)
            progress(index + 1, metas.size, "Sent ${index + 1} of ${metas.size}")
        }
    }

    private fun requireContext(): Context = requireNotNull(appContext) { "File transfer engine is not running" }

    private fun runAnnouncer() {
        while (started.get()) {
            runCatching { sendAnnouncement(true) }
            repeat(240) { if (!started.get()) return; try { Thread.sleep(500) } catch (_: InterruptedException) { return } }
        }
    }

    fun discoverNow() {
        if (!started.get()) return
        executor.execute { repeat(3) { index -> if (!started.get()) return@execute; runCatching { sendAnnouncement(true) }; if (index < 2) try { Thread.sleep(180) } catch (_: InterruptedException) { return@execute } } }
    }

    private fun runDiscovery() {
        val context = requireContext()
        try {
            val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            multicastLock = wifi.createMulticastLock("clipmesh-file-transfer").apply {
                setReferenceCounted(false)
                acquire()
            }
            val group = InetAddress.getByName(MULTICAST_GROUP)
            val socket = MulticastSocket(null).apply {
                reuseAddress = true
                bind(InetSocketAddress(PORT))
                joinGroup(group)
                soTimeout = 0
            }
            multicast = socket
            val buffer = ByteArray(64 * 1024)
            while (started.get()) {
                val packet = java.net.DatagramPacket(buffer, buffer.size)
                try {
                    socket.receive(packet)
                } catch (_: java.net.SocketTimeoutException) {
                    continue
                }
                val raw = String(packet.data, packet.offset, packet.length, Charsets.UTF_8)
                val json = runCatching { JSONObject(raw) }.getOrNull() ?: continue
                val remote = deviceFromJson(json, packet.address.hostAddress.orEmpty()) ?: continue
                remember(remote)
                if (json.optBoolean("announce", false)) runCatching { sendAnnouncement(false) }
            }
        } catch (_: Throwable) {
            // The service keeps running and HTTP discovery can still work on devices that block multicast.
        } finally {
            runCatching { multicastLock?.release() }
            multicastLock = null
            multicast = null
        }
    }

    private fun sendAnnouncement(announce: Boolean) {
        val context = requireContext()
        val bytes = myInfo(context, announce).toString().toByteArray(Charsets.UTF_8)
        val destination = InetAddress.getByName(MULTICAST_GROUP)
        val outbound = MulticastSocket().apply { timeToLive = 1 }
        outbound.use { it.send(java.net.DatagramPacket(bytes, bytes.size, destination, PORT)) }
    }

    private fun myInfo(context: Context, announce: Boolean): JSONObject = JSONObject().apply {
        put("alias", SettingsStore(context).deviceName)
        put("version", PROTOCOL_VERSION)
        put("deviceModel", (Build.MANUFACTURER + " " + Build.MODEL).trim())
        put("deviceType", "mobile")
        put("fingerprint", fingerprint(context))
        put("port", PORT)
        put("protocol", "http")
        put("download", false)
        put("announce", announce)
    }

    private fun deviceFromJson(json: JSONObject, address: String): TransferDevice? {
        val fp = json.optString("fingerprint").trim()
        if (fp.isBlank() || fp == fingerprint(requireContext())) return null
        return TransferDevice(
            alias = json.optString("alias", "Nearby device").ifBlank { "Nearby device" }.take(80),
            fingerprint = fp.take(256),
            address = address,
            port = json.optInt("port", PORT).coerceIn(1, 65535),
            deviceModel = json.optString("deviceModel", "").take(120),
            deviceType = json.optString("deviceType", "desktop").take(24),
            lastSeenMs = System.currentTimeMillis()
        )
    }

    private fun remember(device: TransferDevice) {
        nearby[device.fingerprint] = device.copy(lastSeenMs = System.currentTimeMillis())
    }

    private fun runServer() {
        try {
            val listener = ServerSocket().apply {
                reuseAddress = true
                bind(InetSocketAddress(PORT))
            }
            server = listener
            while (started.get()) {
                val socket = try { listener.accept() } catch (_: Throwable) { break }
                socket.soTimeout = 75_000
                executor.execute { runCatching { handleHttp(socket) }.also { runCatching { socket.close() } } }
            }
        } catch (_: Throwable) {
            // Another LocalSend-compatible process may already own the port.
        } finally {
            server = null
        }
    }

    private fun handleHttp(socket: Socket) {
        val input = BufferedInputStream(socket.getInputStream(), 64 * 1024)
        val output = BufferedOutputStream(socket.getOutputStream(), 32 * 1024)
        val requestLine = readLine(input) ?: return
        val parts = requestLine.split(' ')
        if (parts.size < 2) return respond(output, 400, "Invalid request")
        val method = parts[0].uppercase()
        val rawTarget = parts[1]
        val headers = linkedMapOf<String, String>()
        while (true) {
            val line = readLine(input) ?: break
            if (line.isEmpty()) break
            val colon = line.indexOf(':')
            if (colon > 0) headers[line.substring(0, colon).trim().lowercase()] = line.substring(colon + 1).trim()
        }
        val length = headers["content-length"]?.toLongOrNull()?.coerceAtLeast(0L) ?: 0L
        val uri = runCatching { URI("http://clipmesh$rawTarget") }.getOrNull()
            ?: return respond(output, 400, "Invalid target")
        val path = uri.path
        when {
            method == "GET" && path == "/api/localsend/v2/info" ->
                respond(output, 200, myInfo(requireContext(), false).toString(), "application/json")

            method == "POST" && path == "/api/localsend/v2/register" -> {
                val body = readBody(input, length, MAX_METADATA) ?: return respond(output, 400, "Invalid body")
                val json = runCatching { JSONObject(String(body, Charsets.UTF_8)) }.getOrNull()
                    ?: return respond(output, 400, "Invalid body")
                deviceFromJson(json, socket.inetAddress.hostAddress.orEmpty())?.let(::remember)
                respond(output, 200, myInfo(requireContext(), false).toString(), "application/json")
            }

            method == "POST" && path == "/api/localsend/v2/prepare-upload" -> {
                val body = readBody(input, length, MAX_METADATA) ?: return respond(output, 400, "Invalid body")
                handlePrepare(socket, output, body)
            }

            method == "POST" && path == "/api/localsend/v2/upload" ->
                handleUpload(input, output, uri, length)

            method == "POST" && path == "/api/localsend/v2/cancel" -> {
                query(uri)["sessionId"]?.let { sessions.remove(it) }
                respond(output, 200, "")
            }

            else -> respond(output, 404, "Not found")
        }
    }

    private fun handlePrepare(socket: Socket, output: OutputStream, body: ByteArray) {
        val root = runCatching { JSONObject(String(body, Charsets.UTF_8)) }.getOrNull()
            ?: return respond(output, 400, "Invalid body")
        val info = root.optJSONObject("info") ?: return respond(output, 400, "Missing sender")
        val sender = deviceFromJson(info, socket.inetAddress.hostAddress.orEmpty())
            ?: TransferDevice(
                alias = info.optString("alias", "Nearby device").ifBlank { "Nearby device" },
                fingerprint = info.optString("fingerprint", "unknown-${socket.inetAddress.hostAddress}"),
                address = socket.inetAddress.hostAddress.orEmpty(),
                port = info.optInt("port", PORT).coerceIn(1, 65535),
                deviceModel = info.optString("deviceModel", ""),
                deviceType = info.optString("deviceType", "desktop"),
                lastSeenMs = System.currentTimeMillis()
            )
        remember(sender)
        val filesObject = root.optJSONObject("files") ?: return respond(output, 400, "Missing files")
        val files = linkedMapOf<String, FileMeta>()
        val keys = filesObject.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val item = filesObject.optJSONObject(key) ?: continue
            val id = item.optString("id", key).ifBlank { key }.take(200)
            val fileName = sanitizeName(item.optString("fileName", "file"))
            val size = item.optLong("size", -1L)
            if (size < 0) continue
            files[id] = FileMeta(
                id = id,
                fileName = fileName,
                size = size,
                fileType = item.optString("fileType", "application/octet-stream").take(200),
                sha256 = item.optString("sha256", "").trim().ifBlank { null }?.lowercase()
            )
        }
        if (files.isEmpty()) return respond(output, 400, "No files")

        val accepted = if (isFavorite(requireContext(), sender.fingerprint) && SettingsStore(requireContext()).autoAcceptFavoriteFiles) {
            true
        } else {
            val request = IncomingDecision(UUID.randomUUID().toString(), sender.alias, sender.fingerprint, files.values.toList())
            pending[request.requestId] = request
            TransferNotifications.showIncoming(requireContext(), request)
            request.latch.await(60, TimeUnit.SECONDS)
            pending.remove(request.requestId)
            TransferNotifications.cancelIncoming(requireContext(), request.requestId)
            request.accepted
        }
        if (!accepted) return respond(output, 403, "Rejected")

        val sessionId = UUID.randomUUID().toString()
        val tokens = files.keys.associateWith { UUID.randomUUID().toString().replace("-", "") }
        sessions[sessionId] = UploadSession(
            id = sessionId,
            senderAlias = sender.alias,
            senderFingerprint = sender.fingerprint,
            senderAddress = sender.address,
            files = files,
            tokens = tokens
        )
        val tokenJson = JSONObject()
        tokens.forEach { (id, token) -> tokenJson.put(id, token) }
        respond(output, 200, JSONObject().put("sessionId", sessionId).put("files", tokenJson).toString(), "application/json")
    }

    private fun handleUpload(input: InputStream, output: OutputStream, uri: URI, length: Long) {
        val query = query(uri)
        val sessionId = query["sessionId"] ?: return respond(output, 400, "Missing session")
        val fileId = query["fileId"] ?: return respond(output, 400, "Missing file")
        val token = query["token"] ?: return respond(output, 403, "Missing token")
        val session = sessions[sessionId] ?: return respond(output, 403, "Unknown session")
        val meta = session.files[fileId] ?: return respond(output, 403, "Unknown file")
        if (session.tokens[fileId] != token) return respond(output, 403, "Invalid token")
        if (length != meta.size) return respond(output, 400, "Unexpected size")

        val target = runCatching { createSaveTarget(requireContext(), meta) }.getOrElse {
            return respond(output, 500, "Could not create destination")
        }
        val digest = meta.sha256?.let { MessageDigest.getInstance("SHA-256") }
        var remaining = length
        var success = false
        try {
            target.output.use { fileOutput ->
                val buffer = ByteArray(128 * 1024)
                while (remaining > 0) {
                    val count = input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
                    if (count <= 0) throw IllegalStateException("Upload ended early")
                    fileOutput.write(buffer, 0, count)
                    digest?.update(buffer, 0, count)
                    remaining -= count
                }
                fileOutput.flush()
            }
            if (remaining != 0L) throw IllegalStateException("Upload incomplete")
            if (digest != null) {
                val actual = digest.digest().joinToString("") { "%02x".format(it) }
                if (!actual.equals(meta.sha256, ignoreCase = true)) {
                    target.finish(false)
                    return respond(output, 422, "Checksum mismatch")
                }
            }
            success = true
            target.finish(true)
            session.received += fileId
            if (session.received.size >= session.files.size) {
                sessions.remove(sessionId)
                TransferNotifications.showCompleted(requireContext(), session.senderAlias, session.files.size)
            }
            respond(output, 200, "")
        } catch (_: Throwable) {
            if (!success) runCatching { target.finish(false) }
            respond(output, 500, "Transfer failed")
        }
    }

    private fun buildSendMeta(context: Context, uri: Uri): SendMeta {
        var name = "file"
        var size = -1L
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0) name = cursor.getString(nameIndex) ?: name
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) size = cursor.getLong(sizeIndex)
            }
        }
        if (size < 0) {
            size = context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
        }
        require(size >= 0) { "Could not determine file size for $name" }
        val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
        return SendMeta(UUID.randomUUID().toString(), uri, sanitizeName(name), size, mime)
    }

    private fun uploadUri(context: Context, target: TransferDevice, sessionId: String, meta: SendMeta, token: String) {
        val path = "/api/localsend/v2/upload?sessionId=${enc(sessionId)}&fileId=${enc(meta.id)}&token=${enc(token)}"
        val connection = URL("http://${hostForUrl(target.address)}:${target.port}$path").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 6_000
        connection.readTimeout = 120_000
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/octet-stream")
        connection.setFixedLengthStreamingMode(meta.size)
        context.contentResolver.openInputStream(meta.uri)?.use { input ->
            connection.outputStream.use { output -> input.copyTo(output, 128 * 1024) }
        } ?: throw IllegalStateException("Could not open ${meta.name}")
        val status = connection.responseCode
        connection.inputStreamOrError()?.close()
        connection.disconnect()
        if (status !in 200..299) throw IllegalStateException("${target.alias} rejected ${meta.name} ($status)")
    }

    private fun postJson(target: TransferDevice, path: String, json: JSONObject): HttpResult {
        val connection = URL("http://${hostForUrl(target.address)}:${target.port}$path").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 5_000
        connection.readTimeout = 75_000
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        val bytes = json.toString().toByteArray(Charsets.UTF_8)
        connection.setFixedLengthStreamingMode(bytes.size)
        connection.outputStream.use { it.write(bytes) }
        val status = connection.responseCode
        val text = connection.inputStreamOrError()?.use { String(it.readBytes(), Charsets.UTF_8) }.orEmpty()
        connection.disconnect()
        return HttpResult(status, text)
    }

    private fun HttpURLConnection.inputStreamOrError(): InputStream? =
        runCatching { if (responseCode >= 400) errorStream else inputStream }.getOrNull()

    private fun createSaveTarget(context: Context, meta: FileMeta): SaveTarget {
        val relative = when {
            meta.fileType.lowercase().startsWith("image/") -> "${Environment.DIRECTORY_DOWNLOADS}/ClipMesh/Images"
            meta.fileType.lowercase().startsWith("video/") -> "${Environment.DIRECTORY_DOWNLOADS}/ClipMesh/Videos"
            else -> "${Environment.DIRECTORY_DOWNLOADS}/ClipMesh"
        }
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, meta.fileName)
                put(MediaStore.MediaColumns.MIME_TYPE, meta.fileType)
                put(MediaStore.MediaColumns.RELATIVE_PATH, relative)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Could not create Downloads entry")
            val stream = context.contentResolver.openOutputStream(uri, "w")
                ?: throw IllegalStateException("Could not open Downloads entry")
            return SaveTarget(stream) { ok ->
                if (ok) {
                    val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
                    context.contentResolver.update(uri, done, null, null)
                } else context.contentResolver.delete(uri, null, null)
            }
        }
        @Suppress("DEPRECATION")
        val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val suffix = when {
            meta.fileType.lowercase().startsWith("image/") -> "ClipMesh/Images"
            meta.fileType.lowercase().startsWith("video/") -> "ClipMesh/Videos"
            else -> "ClipMesh"
        }
        val dir = File(downloads, suffix).apply { mkdirs() }
        val file = uniqueFile(dir, meta.fileName)
        return SaveTarget(FileOutputStream(file)) { ok -> if (!ok) file.delete() }
    }

    private fun uniqueFile(dir: File, name: String): File {
        var candidate = File(dir, name)
        if (!candidate.exists()) return candidate
        val dot = name.lastIndexOf('.')
        val stem = if (dot > 0) name.substring(0, dot) else name
        val ext = if (dot > 0) name.substring(dot) else ""
        var i = 2
        while (candidate.exists()) candidate = File(dir, "$stem ($i)$ext").also { i++ }
        return candidate
    }

    private fun sanitizeName(value: String): String {
        val cleaned = value.substringAfterLast('/').substringAfterLast('\\')
            .filterNot { it.code < 32 || it == ':' }
            .trim().take(180)
        return cleaned.ifBlank { "file" }
    }

    private fun readLine(input: InputStream): String? {
        val out = ByteArrayOutputStream(256)
        while (out.size() < 16 * 1024) {
            val b = input.read()
            if (b < 0) return if (out.size() == 0) null else String(out.toByteArray(), Charsets.ISO_8859_1)
            if (b == '\n'.code) break
            if (b != '\r'.code) out.write(b)
        }
        return String(out.toByteArray(), Charsets.ISO_8859_1)
    }

    private fun readBody(input: InputStream, length: Long, max: Int): ByteArray? {
        if (length < 0 || length > max) return null
        val bytes = ByteArray(length.toInt())
        var offset = 0
        while (offset < bytes.size) {
            val count = input.read(bytes, offset, bytes.size - offset)
            if (count <= 0) return null
            offset += count
        }
        return bytes
    }

    private fun respond(output: OutputStream, code: Int, body: String, contentType: String = "text/plain; charset=utf-8") {
        val bytes = body.toByteArray(Charsets.UTF_8)
        val reason = when (code) {
            200 -> "OK"; 204 -> "No Content"; 400 -> "Bad Request"; 403 -> "Forbidden"; 404 -> "Not Found"
            409 -> "Conflict"; 422 -> "Unprocessable Entity"; 429 -> "Too Many Requests"; else -> "Internal Server Error"
        }
        val header = buildString {
            append("HTTP/1.1 $code $reason\r\n")
            append("Content-Type: $contentType\r\n")
            append("Content-Length: ${bytes.size}\r\n")
            append("Connection: close\r\n\r\n")
        }.toByteArray(Charsets.ISO_8859_1)
        output.write(header)
        if (code != 204) output.write(bytes)
        output.flush()
    }

    private fun query(uri: URI): Map<String, String> = uri.rawQuery.orEmpty().split('&')
        .filter { it.isNotBlank() }
        .associate { part ->
            val index = part.indexOf('=')
            val key = if (index >= 0) part.substring(0, index) else part
            val value = if (index >= 0) part.substring(index + 1) else ""
            java.net.URLDecoder.decode(key, "UTF-8") to java.net.URLDecoder.decode(value, "UTF-8")
        }

    private fun enc(value: String): String = java.net.URLEncoder.encode(value, "UTF-8")
    private fun hostForUrl(value: String): String = if (value.contains(':') && !value.startsWith("[")) "[$value]" else value
}
