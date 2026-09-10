package dev.clipmesh.exclusion

object ForegroundTracker {
    @Volatile var currentPackage: String? = null
    @Volatile var clipboardChanged: ((android.content.ClipData?) -> Unit)? = null
    @Volatile var accessibilityConnected: Boolean = false
}
