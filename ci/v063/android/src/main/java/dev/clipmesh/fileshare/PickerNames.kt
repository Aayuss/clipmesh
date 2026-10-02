package dev.clipmesh.fileshare

import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The system photo picker exposes items as "<media id>.<ext>". Receivers should
 * get a recognisable name instead, so derive IMG_/VID_ names from the capture date.
 */
object PickerNames {
    private val numeric = Regex("""^\d+\.[A-Za-z0-9]{2,5}$""")

    fun friendly(context: Context, uri: Uri, name: String, mime: String?): String {
        if (!numeric.matches(name) || !(uri.authority.orEmpty().contains("photopicker") || uri.authority == MediaStore.AUTHORITY)) return name
        val taken = runCatching {
            context.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.DATE_TAKEN), null, null, null)?.use { c ->
                if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null
            }
        }.getOrNull()?.takeIf { it > 0 } ?: System.currentTimeMillis()
        val prefix = if (mime?.startsWith("video/") == true) "VID" else "IMG"
        val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date(taken))
        val id = name.substringBefore('.').takeLast(4)
        return "${prefix}_${stamp}_$id.${name.substringAfterLast('.').lowercase()}"
    }
}
