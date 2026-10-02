package dev.clipmesh.ui

import android.net.Uri
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector

enum class Tab(val title: String, val icon: ImageVector) {
    CLIPBOARD("Clipboard", Icons.Rounded.ContentPaste),
    TRANSFER("Transfer", Icons.Rounded.SwapHoriz),
    SETTINGS("Settings", Icons.Rounded.Settings),
}

enum class SyncHealth { ON, OFF, RECOVERING, STOPPED }

sealed interface ClipPreview {
    data object Loading : ClipPreview
    data object Empty : ClipPreview
    data class Text(val text: String) : ClipPreview
    data class Image(val bitmap: ImageBitmap, val label: String) : ClipPreview
    data class Files(val names: List<String>, val image: ImageBitmap?) : ClipPreview
}

data class PeerUi(val id: String, val name: String, val online: Boolean, val caption: String, val mobile: Boolean)

data class DeviceUi(
    val fingerprint: String,
    val alias: String,
    val model: String,
    val mobile: Boolean,
    val favorite: Boolean,
)

data class SelectedFile(val uri: Uri, val name: String, val size: Long, val mime: String?, val thumbnail: ImageBitmap?)

sealed interface SendState {
    data class Sending(val fraction: Float, val label: String) : SendState
    data object Sent : SendState
}

data class IncomingBanner(val title: String, val fraction: Float, val complete: Boolean, val failed: Boolean)

data class ToastMessage(val text: String, val id: Long = System.nanoTime())

/** Single observable UI model shared by every tab. Mutated on the main thread only. */
class ClipMeshUi {
    var tab by mutableStateOf(Tab.CLIPBOARD)

    // Clipboard
    var deviceName by mutableStateOf("")
    var addMenuOpen by mutableStateOf(false)
    var health by mutableStateOf(SyncHealth.ON)
    var healthText by mutableStateOf("Starting…")
    var preview by mutableStateOf<ClipPreview>(ClipPreview.Loading)
    var previewOpen by mutableStateOf(false)
    val peers = mutableStateListOf<PeerUi>()
    val nearby = mutableStateListOf<DeviceUi>()
    var pairingWith by mutableStateOf<String?>(null)

    // Transfer
    val files = mutableStateListOf<SelectedFile>()
    val devices = mutableStateListOf<DeviceUi>()
    val sendStates = mutableStateMapOf<String, SendState>()
    var incoming by mutableStateOf<IncomingBanner?>(null)
    var transferStatus by mutableStateOf("Looking for devices on this network…")

    // Settings
    var settingsRevision by mutableIntStateOf(0)

    var toast by mutableStateOf<ToastMessage?>(null)
    fun toast(text: String) { toast = ToastMessage(text) }
}

fun <T> MutableList<T>.syncWith(next: List<T>) {
    if (this == next) return
    // Keep stable identities so lazy rows animate instead of rebuilding.
    var index = 0
    while (index < next.size) {
        if (index < size) { if (this[index] != next[index]) this[index] = next[index] } else add(next[index])
        index++
    }
    while (size > next.size) removeAt(size - 1)
}
