from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]; PROJECT=ROOT/"clipmesh"
def replace(path:Path,old:str,new:str,label:str,count:int=1)->None:
 text=path.read_text(encoding="utf-8"); found=text.count(old)
 if found!=count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
 path.write_text(text.replace(old,new,count),encoding="utf-8")
def regex(path:Path,pattern:str,repl:str,label:str,count:int=1,flags:int=re.S)->None:
 text=path.read_text(encoding="utf-8"); updated,found=re.subn(pattern,lambda _m:repl,text,count=count,flags=flags)
 if found!=count: raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
 path.write_text(updated,encoding="utf-8")
transfer=PROJECT/"android/app/src/main/java/dev/clipmesh/fileshare/LocalTransferEngine.kt"
replace(transfer,"import android.provider.MediaStore","import android.provider.MediaStore\nimport android.provider.DocumentsContract","android SAF import")
replace(transfer,"    fun fingerprint(context: Context): String {","""    fun outputTreeUri(context: Context): Uri? = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("output_tree_uri", null)?.let(Uri::parse)

    fun setOutputTreeUri(context: Context, uri: Uri?) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().apply {
            if (uri == null) remove("output_tree_uri") else putString("output_tree_uri", uri.toString())
        }.apply()
    }

    fun outputFolderLabel(context: Context): String = outputTreeUri(context)?.let { "Selected folder • " + (queryDocumentName(context, it) ?: it.toString()) } ?: "Downloads/ClipMesh"

    fun fingerprint(context: Context): String {""","android output tree preferences")
regex(transfer,r"    private fun createSaveTarget\(context: Context, meta: FileMeta\): SaveTarget \{.*?\n    \}\n\n    private fun uniqueFile",r'''    private fun createSaveTarget(context: Context, meta: FileMeta): SaveTarget {
        outputTreeUri(context)?.let { tree -> return createTreeSaveTarget(context, tree, meta) }
        val relative = when {
            meta.fileType.lowercase().startsWith("image/") -> "${Environment.DIRECTORY_DOWNLOADS}/ClipMesh/images"
            meta.fileType.lowercase().startsWith("video/") -> "${Environment.DIRECTORY_DOWNLOADS}/ClipMesh/video"
            else -> "${Environment.DIRECTORY_DOWNLOADS}/ClipMesh"
        }
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply { put(MediaStore.MediaColumns.DISPLAY_NAME, meta.fileName); put(MediaStore.MediaColumns.MIME_TYPE, meta.fileType); put(MediaStore.MediaColumns.RELATIVE_PATH, relative); put(MediaStore.MediaColumns.IS_PENDING, 1) }
            val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: throw IllegalStateException("Could not create Downloads entry")
            val stream = context.contentResolver.openOutputStream(uri, "w") ?: throw IllegalStateException("Could not open Downloads entry")
            return SaveTarget(stream) { ok -> if (ok) context.contentResolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null) else context.contentResolver.delete(uri, null, null) }
        }
        @Suppress("DEPRECATION") val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val suffix = when { meta.fileType.lowercase().startsWith("image/") -> "ClipMesh/images"; meta.fileType.lowercase().startsWith("video/") -> "ClipMesh/video"; else -> "ClipMesh" }
        val dir = File(downloads, suffix).apply { mkdirs() }; val file = uniqueFile(dir, meta.fileName)
        return SaveTarget(FileOutputStream(file)) { ok -> if (!ok) file.delete() }
    }

    private fun createTreeSaveTarget(context: Context, tree: Uri, meta: FileMeta): SaveTarget {
        var parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val childFolder = when { meta.fileType.lowercase().startsWith("image/") -> "images"; meta.fileType.lowercase().startsWith("video/") -> "video"; else -> null }
        if (childFolder != null) parent = ensureTreeDirectory(context, tree, parent, childFolder)
        val name = uniqueTreeName(context, tree, parent, meta.fileName)
        val uri = DocumentsContract.createDocument(context.contentResolver, parent, meta.fileType.ifBlank { "application/octet-stream" }, name) ?: throw IllegalStateException("Could not create file in the selected folder")
        val stream = context.contentResolver.openOutputStream(uri, "w") ?: throw IllegalStateException("Could not open selected folder")
        return SaveTarget(stream) { ok -> if (!ok) runCatching { DocumentsContract.deleteDocument(context.contentResolver, uri) } }
    }
    private fun ensureTreeDirectory(context: Context, tree: Uri, parent: Uri, name: String): Uri { findTreeChild(context, tree, parent, name)?.let { return it }; return DocumentsContract.createDocument(context.contentResolver, parent, DocumentsContract.Document.MIME_TYPE_DIR, name) ?: throw IllegalStateException("Could not create $name folder") }
    private fun findTreeChild(context: Context, tree: Uri, parent: Uri, name: String): Uri? {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getDocumentId(parent))
        context.contentResolver.query(children, arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)?.use { c ->
            val idCol=c.getColumnIndex(DocumentsContract.Document.COLUMN_DOCUMENT_ID); val nameCol=c.getColumnIndex(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
            while(c.moveToNext()) if(c.getString(nameCol)==name) return DocumentsContract.buildDocumentUriUsingTree(tree,c.getString(idCol))
        }; return null
    }
    private fun uniqueTreeName(context: Context, tree: Uri, parent: Uri, requested: String): String {
        if(findTreeChild(context,tree,parent,requested)==null)return requested
        val dot=requested.lastIndexOf('.'); val stem=if(dot>0)requested.substring(0,dot) else requested; val ext=if(dot>0)requested.substring(dot) else ""; var i=2
        while(true){val candidate="$stem ($i)$ext";if(findTreeChild(context,tree,parent,candidate)==null)return candidate;i++}
    }
    private fun queryDocumentName(context: Context, uri: Uri): String? = runCatching { val document=DocumentsContract.buildDocumentUriUsingTree(uri,DocumentsContract.getTreeDocumentId(uri)); context.contentResolver.query(document,arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME),null,null,null)?.use{c->if(c.moveToFirst())c.getString(0) else null} }.getOrNull()

    private fun uniqueFile''',"android selected output destination")
