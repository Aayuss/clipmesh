package dev.clipmesh.model

import android.util.Base64
import dev.clipmesh.crypto.Crypto
import org.json.JSONArray
import org.json.JSONObject
import java.nio.charset.StandardCharsets

private const val MAX_PAYLOAD = 64 * 1024 * 1024

data class Representation(val mime: String, val data: ByteArray)
data class PortableFile(val name: String, val data: ByteArray, val sha256: String)

data class ClipPayload(
    val representations: List<Representation> = emptyList(),
    val files: List<PortableFile> = emptyList(),
    val sourceApp: String? = null
) {
    /** Exact JSON wire schema used by the Rust clipmesh-core crate. */
    fun toJsonBytes(): ByteArray {
        val reps = JSONArray()
        representations.forEach { r -> reps.put(JSONObject().put("mime", r.mime).put("data_b64", b64(r.data))) }
        val fs = JSONArray()
        files.forEach { f -> fs.put(JSONObject().put("name", f.name).put("sha256", f.sha256).put("data_b64", b64(f.data))) }
        val bytes = JSONObject().apply {
            put("schema", 1)
            if (sourceApp == null) put("source_app", JSONObject.NULL) else put("source_app", sourceApp)
            put("representations", reps)
            put("files", fs)
        }.toString().toByteArray(StandardCharsets.UTF_8)
        require(bytes.size <= MAX_PAYLOAD) { "Clipboard payload exceeds 64 MiB" }
        return bytes
    }

    /** Source app is intentionally excluded so remote-write echo suppression is cross-device stable. */
    fun stableFingerprint(): String {
        val parts = mutableListOf<ByteArray>()
        representations.sortedBy { it.mime }.forEach {
            parts += it.mime.toByteArray(StandardCharsets.UTF_8)
            parts += Crypto.sha256(it.data)
        }
        files.sortedBy { it.name }.forEach {
            parts += it.name.toByteArray(StandardCharsets.UTF_8)
            parts += it.sha256.lowercase().toByteArray(StandardCharsets.UTF_8)
        }
        val combined = parts.fold(ByteArray(0)) { a, b -> a + b }
        return Crypto.hex(Crypto.sha256(combined))
    }

    companion object {
        fun fromJsonBytes(bytes: ByteArray): ClipPayload {
            require(bytes.size <= MAX_PAYLOAD) { "Encoded payload too large" }
            val o = JSONObject(String(bytes, StandardCharsets.UTF_8))
            require(o.getInt("schema") == 1)
            val reps = mutableListOf<Representation>()
            val r = o.getJSONArray("representations")
            for (i in 0 until r.length()) {
                val x = r.getJSONObject(i)
                reps += Representation(x.getString("mime"), unb64(x.getString("data_b64")))
            }
            val files = mutableListOf<PortableFile>()
            val f = o.getJSONArray("files")
            for (i in 0 until f.length()) {
                val x = f.getJSONObject(i)
                val data = unb64(x.getString("data_b64"))
                val expected = x.getString("sha256").lowercase()
                require(Crypto.hex(Crypto.sha256(data)) == expected) { "File hash mismatch" }
                files += PortableFile(x.getString("name"), data, expected)
            }
            return ClipPayload(
                reps,
                files,
                o.optString("source_app").takeIf { !o.isNull("source_app") && it.isNotBlank() }
            )
        }

        private fun b64(data: ByteArray) = Base64.encodeToString(data, Base64.NO_WRAP)
        private fun unb64(text: String) = Base64.decode(text, Base64.NO_WRAP)
    }
}
