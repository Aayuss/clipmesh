package dev.clipmesh.testdriver

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File

class TestImageProvider : ContentProvider() {
    override fun onCreate() = true
    private fun image(uri: Uri): File {
        val name = uri.lastPathSegment?.takeIf {
            it == "clipmesh-e2e-image.png" || it == "clipmesh-e2e-oriented.jpg"
        } ?: "clipmesh-e2e-image.png"
        return File(requireNotNull(context).cacheDir, name)
    }
    override fun getType(uri: Uri): String =
        if (uri.lastPathSegment?.endsWith(".jpg") == true) "image/jpeg" else "image/png"
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        require(mode == "r")
        return ParcelFileDescriptor.open(image(uri), ParcelFileDescriptor.MODE_READ_ONLY)
    }
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor =
        MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)).apply {
            val file = image(uri)
            addRow(arrayOf<Any?>(file.name, file.length()))
        }
    override fun insert(uri: Uri, values: ContentValues?): Uri? = throw UnsupportedOperationException()
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0
}
