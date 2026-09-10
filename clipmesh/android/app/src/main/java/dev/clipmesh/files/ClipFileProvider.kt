package dev.clipmesh.files

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File

/** Read-only provider for files received from trusted ClipMesh peers. */
class ClipFileProvider : ContentProvider() {
    override fun onCreate() = true

    override fun getType(uri: Uri): String? = uri.getQueryParameter("mime") ?: "application/octet-stream"

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        require(mode == "r") { "Read-only" }
        val name = uri.lastPathSegment?.substringAfterLast('/') ?: error("Missing file")
        val file = File(requireNotNull(context).cacheDir, "received/$name").canonicalFile
        val root = File(requireNotNull(context).cacheDir, "received").canonicalFile
        require(file.path.startsWith(root.path + File.separator)) { "Invalid path" }
        require(file.isFile) { "File not found" }
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    }

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
        val storageName = uri.lastPathSegment?.substringAfterLast('/') ?: "clipboard"
        val displayName = uri.getQueryParameter("display") ?: storageName
        val file = File(requireNotNull(context).cacheDir, "received/$storageName")
        return MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)).apply {
            addRow(arrayOf<Any?>(displayName, file.length()))
        }
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = throw UnsupportedOperationException()
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0
}
