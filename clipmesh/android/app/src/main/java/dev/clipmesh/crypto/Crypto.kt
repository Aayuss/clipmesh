package dev.clipmesh.crypto

import android.util.Base64
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import kotlin.math.abs

object Crypto {
    const val PROTOCOL_VERSION: Byte = 1
    private val MAGIC = byteArrayOf('C'.code.toByte(), 'M'.code.toByte(), '0'.code.toByte(), '1'.code.toByte())
    private val HELLO_MAGIC = byteArrayOf('C'.code.toByte(), 'M'.code.toByte(), 'H'.code.toByte(), '1'.code.toByte())
    const val HEADER_SIZE = 64
    const val MAX_FRAME_SIZE = 72 * 1024 * 1024
    private const val MAX_CLOCK_SKEW_MS = 120_000L

    enum class Kind(val wire: Byte) { CLIPBOARD(1), ACK(2), PING(3), PONG(4) }

    data class Frame(
        val kind: Kind,
        val flags: Short,
        val sender: UUID,
        val messageId: UUID,
        val timestampMs: Long,
        val plaintext: ByteArray
    )

    fun deriveDataKey(master: ByteArray, spaceId: UUID, sender: UUID): ByteArray {
        val info = "clipmesh/aead/v1".toByteArray() + uuidBytes(sender)
        return hkdfSha256(master, uuidBytes(spaceId), info, 32)
    }

    fun deriveDiscoveryKey(master: ByteArray, spaceId: UUID): ByteArray {
        return hkdfSha256(master, uuidBytes(spaceId), "clipmesh/discovery/v1".toByteArray(), 32)
    }

    fun encryptFrame(
        master: ByteArray,
        spaceId: UUID,
        kind: Kind,
        flags: Short,
        sender: UUID,
        messageId: UUID,
        plaintext: ByteArray,
        timestampMs: Long = System.currentTimeMillis()
    ): ByteArray {
        require(plaintext.size <= MAX_FRAME_SIZE - HEADER_SIZE - 16)
        val nonce = ByteArray(12).also { SecureRandom().nextBytes(it) }
        val ciphertextSize = plaintext.size + 16
        val header = ByteBuffer.allocate(HEADER_SIZE).order(ByteOrder.BIG_ENDIAN).apply {
            put(MAGIC)
            put(PROTOCOL_VERSION)
            put(kind.wire)
            putShort(flags)
            put(uuidBytes(sender))
            put(uuidBytes(messageId))
            putLong(timestampMs)
            put(nonce)
            putInt(ciphertextSize)
        }.array()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(deriveDataKey(master, spaceId, sender), "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD(header)
        return header + cipher.doFinal(plaintext)
    }

    fun decryptFrame(master: ByteArray, spaceId: UUID, bytes: ByteArray): Frame {
        require(bytes.size >= HEADER_SIZE + 16) { "Frame too short" }
        require(bytes.size <= MAX_FRAME_SIZE) { "Frame too large" }
        val header = bytes.copyOfRange(0, HEADER_SIZE)
        val b = ByteBuffer.wrap(header).order(ByteOrder.BIG_ENDIAN)
        val magic = ByteArray(4).also { b.get(it) }
        require(magic.contentEquals(MAGIC)) { "Invalid frame magic" }
        require(b.get() == PROTOCOL_VERSION) { "Unsupported protocol" }
        val kindWire = b.get()
        val kind = Kind.entries.firstOrNull { it.wire == kindWire } ?: error("Invalid frame kind")
        val flags = b.short
        val sender = readUuid(b)
        val messageId = readUuid(b)
        val timestamp = b.long
        require(abs(System.currentTimeMillis() - timestamp) <= MAX_CLOCK_SKEW_MS) { "Frame timestamp outside replay window" }
        val nonce = ByteArray(12).also { b.get(it) }
        val ciphertextLen = b.int
        require(ciphertextLen == bytes.size - HEADER_SIZE) { "Frame length mismatch" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(deriveDataKey(master, spaceId, sender), "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD(header)
        val plaintext = cipher.doFinal(bytes, HEADER_SIZE, ciphertextLen)
        return Frame(kind, flags, sender, messageId, timestamp, plaintext)
    }

    fun buildHello(master: ByteArray, spaceId: UUID, deviceId: UUID): ByteArray {
        val timestamp = System.currentTimeMillis()
        val nonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
        val body = ByteBuffer.allocate(4 + 16 + 16 + 8 + 16).order(ByteOrder.BIG_ENDIAN).apply {
            put(HELLO_MAGIC)
            put(uuidBytes(spaceId))
            put(uuidBytes(deviceId))
            putLong(timestamp)
            put(nonce)
        }.array()
        val mac = hmac(deriveDiscoveryKey(master, spaceId), body)
        return body + mac
    }

    fun verifyHello(master: ByteArray, expectedSpace: UUID, bytes: ByteArray): UUID {
        require(bytes.size == 92) { "Invalid hello size" }
        val body = bytes.copyOfRange(0, 60)
        val supplied = bytes.copyOfRange(60, 92)
        val b = ByteBuffer.wrap(body).order(ByteOrder.BIG_ENDIAN)
        val magic = ByteArray(4).also { b.get(it) }
        require(magic.contentEquals(HELLO_MAGIC)) { "Invalid hello magic" }
        val space = readUuid(b)
        require(space == expectedSpace) { "Wrong space" }
        val device = readUuid(b)
        val timestamp = b.long
        require(abs(System.currentTimeMillis() - timestamp) <= MAX_CLOCK_SKEW_MS) { "Hello expired" }
        val expected = hmac(deriveDiscoveryKey(master, expectedSpace), body)
        require(MessageDigest.isEqual(supplied, expected)) { "Invalid hello MAC" }
        return device
    }

    fun signedDiscovery(master: ByteArray, spaceId: UUID, deviceId: UUID, name: String, port: Int): ByteArray {
        val ts = System.currentTimeMillis()
        val canonical = listOf("1", spaceId.toString(), deviceId.toString(), name, port.toString(), ts.toString()).joinToString("\u0000")
        val mac = Base64.encodeToString(
            hmac(deriveDiscoveryKey(master, spaceId), canonical.toByteArray(StandardCharsets.UTF_8)),
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
        )
        return JSONObject().apply {
            put("v", 1)
            put("space_id", spaceId.toString())
            put("device_id", deviceId.toString())
            put("name", name)
            put("port", port)
            put("timestamp_ms", ts)
            put("mac", mac)
        }.toString().toByteArray(StandardCharsets.UTF_8)
    }

    data class Discovery(val deviceId: UUID, val name: String, val port: Int)

    fun verifyDiscovery(master: ByteArray, spaceId: UUID, bytes: ByteArray): Discovery {
        val o = JSONObject(String(bytes, StandardCharsets.UTF_8))
        require(o.getInt("v") == 1)
        val wireSpace = UUID.fromString(o.getString("space_id"))
        require(wireSpace == spaceId)
        val device = UUID.fromString(o.getString("device_id"))
        val name = o.getString("name")
        val port = o.getInt("port")
        val ts = o.getLong("timestamp_ms")
        require(abs(System.currentTimeMillis() - ts) <= MAX_CLOCK_SKEW_MS)
        val canonical = listOf("1", spaceId.toString(), device.toString(), name, port.toString(), ts.toString()).joinToString("\u0000")
        val expected = hmac(deriveDiscoveryKey(master, spaceId), canonical.toByteArray(StandardCharsets.UTF_8))
        val supplied = Base64.decode(o.getString("mac"), Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        require(supplied.size == 32 && MessageDigest.isEqual(expected, supplied))
        return Discovery(device, name, port)
    }

    fun sha256(data: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(data)
    fun hex(data: ByteArray): String = data.joinToString("") { "%02x".format(it) }

    private fun hkdfSha256(ikm: ByteArray, salt: ByteArray, info: ByteArray, len: Int): ByteArray {
        val prk = hmac(salt, ikm)
        val out = ByteArray(len)
        var t = ByteArray(0)
        var offset = 0
        var counter = 1
        while (offset < len) {
            t = hmac(prk, t + info + byteArrayOf(counter.toByte()))
            val n = minOf(t.size, len - offset)
            System.arraycopy(t, 0, out, offset, n)
            offset += n
            counter++
        }
        return out
    }

    private fun hmac(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(data)
    }

    fun uuidBytes(id: UUID): ByteArray = ByteBuffer.allocate(16).order(ByteOrder.BIG_ENDIAN)
        .putLong(id.mostSignificantBits).putLong(id.leastSignificantBits).array()

    private fun readUuid(b: ByteBuffer): UUID = UUID(b.long, b.long)
}
