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
share=PROJECT/"android/app/src/main/java/dev/clipmesh/fileshare/FileShareActivity.kt"
replace(share,"    private lateinit var status: TextView","    private lateinit var status: TextView\n    private lateinit var outputFolderLabel: TextView","android output label property")
regex(share,r"    override fun onActivityResult\(requestCode: Int, resultCode: Int, data: Intent\?\) \{.*?\n    \}",r'''    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == PICK_OUTPUT_FOLDER) {
            if (resultCode != RESULT_OK || data?.data == null) return
            val uri = data.data!!
            val flags = data.flags and (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            runCatching { contentResolver.takePersistableUriPermission(uri, flags) }
            LocalTransferEngine.setOutputTreeUri(this, uri)
            if (::outputFolderLabel.isInitialized) outputFolderLabel.text = LocalTransferEngine.outputFolderLabel(this)
            return
        }
        if (requestCode != PICK_FILES || resultCode != RESULT_OK || data == null) return
        selected.clear(); data.clipData?.let { clip -> for (i in 0 until clip.itemCount) selected += clip.getItemAt(i).uri }; data.data?.let { selected += it }
        selected.distinct().forEach { uri -> runCatching { contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) } }
        refreshFiles()
    }''',"android output picker result")
replace(share,"        val nearbyCard = card(glass2)","""        val outputCard = card(glass)
        val outputRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val outputTexts = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        outputTexts.addView(text("Receive folder", 13f, true, muted))
        outputFolderLabel = text(LocalTransferEngine.outputFolderLabel(this), 14f, false, ink).apply { maxLines = 2 }
        outputTexts.addView(outputFolderLabel); outputRow.addView(outputTexts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        outputRow.addView(pillButton("Choose folder", false) { chooseOutputFolder() }, LinearLayout.LayoutParams(dp(132), dp(43)))
        outputCard.addView(outputRow); root.addView(outputCard, fullWidth(ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(14) })

        val nearbyCard = card(glass2)""","android receive folder UI")
replace(share,'    private fun chooseFiles(mime: String = "*/*") {',"""    private fun chooseOutputFolder() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply { addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or Intent.FLAG_GRANT_PREFIX_URI_PERMISSION) }, PICK_OUTPUT_FOLDER)
    }

    private fun chooseFiles(mime: String = "*/*") {""","android output folder chooser")
replace(share,"    companion object { private const val PICK_FILES = 2201 }","    companion object { private const val PICK_FILES = 2201; private const val PICK_OUTPUT_FOLDER = 2202 }","android output picker request code")
