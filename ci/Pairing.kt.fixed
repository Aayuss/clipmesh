package dev.clipmesh

import android.net.Uri
import android.util.Base64
import java.security.SecureRandom
import java.util.UUID

object Pairing {
    data class PairingData(
        val spaceId: UUID,
        val key: ByteArray,
        val name: String?,
        val deviceId: UUID?
    )

    fun createSpace(name: String, deviceId: UUID): PairingData {
        val key = ByteArray(32).also { SecureRandom().nextBytes(it) }
        return PairingData(UUID.randomUUID(), key, SettingsStore.sanitizeDeviceName(name), deviceId)
    }

    fun toUri(data: PairingData): String {
        val key = Base64.encodeToString(data.key, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        val builder = Uri.Builder()
            .scheme("clipmesh")
            .authority("pair")
            .appendQueryParameter("v", "1")
            .appendQueryParameter("space", data.spaceId.toString())
            .appendQueryParameter("key", key)
        data.deviceId?.let { builder.appendQueryParameter("device", it.toString()) }
        data.name?.takeIf { it.isNotBlank() }?.let {
            builder.appendQueryParameter("name", SettingsStore.sanitizeDeviceName(it))
        }
        return builder.build().toString()
    }

    fun parse(uriText: String): PairingData {
        val uri = Uri.parse(uriText.trim())
        require(uri.scheme == "clipmesh" && uri.authority == "pair") { "Invalid ClipMesh pairing URI" }
        require(uri.getQueryParameter("v") == "1") { "Unsupported pairing version" }
        val space = UUID.fromString(requireNotNull(uri.getQueryParameter("space")))
        val keyText = requireNotNull(uri.getQueryParameter("key"))
        val key = Base64.decode(keyText, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        require(key.size == 32) { "Invalid pairing key" }
        val deviceId = uri.getQueryParameter("device")?.takeIf { it.isNotBlank() }?.let { UUID.fromString(it) }
        val name = uri.getQueryParameter("name")?.takeIf { it.isNotBlank() }?.let(SettingsStore::sanitizeDeviceName)
        return PairingData(space, key, name, deviceId)
    }
}
