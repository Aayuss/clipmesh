package dev.clipmesh.exclusion

import android.accessibilityservice.AccessibilityService
import android.content.ClipboardManager
import android.view.accessibility.AccessibilityEvent
import dev.clipmesh.BackgroundRuntime
import dev.clipmesh.BackgroundService

/** Source-app tracking plus an optional clipboard edge source. The callback never
 * reads ClipboardManager; privileged bytes are captured by ClipboardUserService. */
class ExclusionAccessibilityService : AccessibilityService() {
    private var clipboard: ClipboardManager? = null
    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        BackgroundRuntime.start(this)
        BackgroundRuntime.captureAccessibility()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        ForegroundTracker.accessibilityConnected = true
        BackgroundService.start(this)
        clipboard = getSystemService(ClipboardManager::class.java)
        clipboard?.addPrimaryClipChangedListener(clipboardListener)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val pkg = event?.packageName?.toString()
        if (!pkg.isNullOrBlank()) ForegroundTracker.currentPackage = pkg
    }

    override fun onDestroy() {
        ForegroundTracker.accessibilityConnected = false
        clipboard?.removePrimaryClipChangedListener(clipboardListener)
        clipboard = null
        super.onDestroy()
    }

    override fun onInterrupt() = Unit
}
