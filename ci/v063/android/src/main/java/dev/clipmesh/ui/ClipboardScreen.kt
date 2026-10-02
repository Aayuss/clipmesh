package dev.clipmesh.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.InsertDriveFile
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

interface ClipboardActions {
    fun refreshDevices()
    fun pairWithCode()
    fun pairNearby(device: DeviceUi)
    fun removePeer(peer: PeerUi)
    fun openPreview()
}

@Composable
fun ClipboardScreen(ui: ClipMeshUi, actions: ClipboardActions) {
    PageTitle("Clipboard", subtitle = ui.deviceName.takeIf { it.isNotBlank() }?.let { "This device · $it" }) {
        StatusPill(ui.health, ui.healthText)
    }

    EmberCard(onClick = actions::openPreview, padding = 12.dp, modifier = Modifier.animateContentSize(tween(Motion.Navigation, easing = Motion.Emphasized))) {
        AnimatedContent(
            targetState = ui.preview,
            transitionSpec = { fadeIn(tween(Motion.Navigation)) togetherWith fadeOut(tween(Motion.Small)) },
            contentKey = { it::class },
            label = "clip_preview",
        ) { preview -> ClipPreviewRow(preview) }
    }

    Spacer(Modifier.height(16.dp))
    val scope = rememberCoroutineScope()
    val spin = remember { Animatable(0f) }
    EmberCard(padding = 6.dp, modifier = Modifier.animateContentSize(tween(Motion.Navigation, easing = Motion.Emphasized))) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 10.dp, end = 4.dp, top = 2.dp)) {
            Text("Devices", style = Type.Section, modifier = Modifier.weight(1f))
            IconCircleButton(Icons.Rounded.Refresh, "Refresh devices", onClick = {
                actions.refreshDevices()
                scope.launch { spin.snapTo(0f); spin.animateTo(360f, tween(600, easing = Motion.Emphasized)) }
            }, rotation = spin.value, size = 32.dp, background = androidx.compose.ui.graphics.Color.Transparent, tint = Ember.TextMuted)
            IconCircleButton(Icons.Rounded.Add, "Pair with a code", onClick = actions::pairWithCode, size = 32.dp, background = androidx.compose.ui.graphics.Color.Transparent, tint = Ember.TextMuted)
        }
        if (ui.peers.isEmpty() && ui.nearby.isEmpty()) {
            MutedLine("No devices yet. Open ClipMesh on another device on this network.", Modifier.padding(horizontal = 10.dp))
        }
        AnimatedItems(ui.peers.toList(), key = { it.id }) { peer -> PeerRow(peer, onRemove = { actions.removePeer(peer) }) }
        if (ui.nearby.isNotEmpty()) {
            Text("Nearby", style = Type.Caption, modifier = Modifier.padding(start = 10.dp, top = 6.dp, bottom = 2.dp))
        }
        AnimatedItems(ui.nearby.toList(), key = { it.fingerprint }) { device ->
            NearbyRow(device, pairing = ui.pairingWith == device.fingerprint, onPair = { actions.pairNearby(device) })
        }
    }
}

@Composable
private fun PreviewTile(content: @Composable () -> Unit) {
    Box(Modifier.size(64.dp).clip(RoundedCornerShape(12.dp)).background(Ember.Fill07), contentAlignment = Alignment.Center) { content() }
}

@Composable
private fun ClipPreviewRow(preview: ClipPreview) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        val title: String
        val caption: String
        var body: String? = null
        when (preview) {
            ClipPreview.Loading, ClipPreview.Empty -> {
                PreviewTile { Icon(Icons.Rounded.ContentPaste, null, tint = Ember.TextFaint, modifier = Modifier.size(24.dp)) }
                title = if (preview == ClipPreview.Loading) "Reading clipboard…" else "Clipboard is empty"
                caption = "Copy something on any paired device"
            }
            is ClipPreview.Text -> {
                PreviewTile { Text("T", style = Type.PageTitle.copy(color = Ember.TextMuted)) }
                title = "Text"
                caption = "${preview.text.length} characters"
                body = preview.text.replace('\n', ' ').trim()
            }
            is ClipPreview.Image -> {
                PreviewTile { Image(preview.bitmap, "Clipboard image", contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize()) }
                title = preview.label.substringBefore(" · ").ifBlank { "Image" }
                caption = preview.label.substringAfter(" · ", "Image")
            }
            is ClipPreview.Files -> {
                PreviewTile {
                    if (preview.image != null) Image(preview.image, null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                    else Icon(Icons.Rounded.InsertDriveFile, null, tint = Ember.TextMuted, modifier = Modifier.size(24.dp))
                }
                title = if (preview.names.size == 1) preview.names.first() else "${preview.names.size} files"
                caption = preview.names.take(3).joinToString(", ")
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = Type.RowTitle, maxLines = 1, overflow = TextOverflow.MiddleEllipsis)
            Text(caption, style = Type.Caption, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (body != null) Text(body, style = Type.Body.copy(color = Ember.TextSoft), maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
        }
        if (preview !is ClipPreview.Empty && preview !is ClipPreview.Loading) {
            Icon(Icons.Rounded.ChevronRight, null, tint = Ember.TextFaint, modifier = Modifier.size(18.dp))
        }
    }
}

@Composable
private fun PeerRow(peer: PeerUi, onRemove: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 7.dp),
    ) {
        Box {
            Avatar(mobile = peer.mobile)
            if (peer.online) Box(
                Modifier.align(Alignment.BottomEnd).size(12.dp).clip(CircleShape).background(Ember.Surface).padding(2.dp).clip(CircleShape).background(Ember.Positive),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(peer.name, style = Type.RowTitle, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(peer.caption, style = Type.Caption.copy(color = if (peer.online) Ember.Positive else Ember.TextMuted))
        }
        IconCircleButton(Icons.Rounded.Close, "Remove ${peer.name}", onClick = onRemove, size = 30.dp, tint = Ember.TextFaint, background = androidx.compose.ui.graphics.Color.Transparent)
    }
}

@Composable
private fun NearbyRow(device: DeviceUi, pairing: Boolean, onPair: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 7.dp),
    ) {
        Avatar(mobile = device.mobile)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(device.alias, style = Type.RowTitle, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(if (pairing) "Waiting for confirmation…" else device.model.ifBlank { if (device.mobile) "Phone" else "Computer" }, style = Type.Caption)
        }
        PillButton(if (pairing) "Pairing" else "Pair", onClick = onPair, compact = true, enabled = !pairing)
    }
}

internal fun guessMobile(name: String): Boolean {
    val n = name.lowercase()
    return listOf("phone", "pixel", "galaxy", "android", "iphone", "samsung", "oneplus", "xiaomi", "redmi", "moto", "s2", "ultra").any { n.contains(it) } &&
        listOf("mac", "book", "pc", "desktop", "laptop", "windows").none { n.contains(it) }
}

@Composable
fun ClipPreviewFull(preview: ClipPreview) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        when (preview) {
            ClipPreview.Loading, ClipPreview.Empty -> Text("Clipboard is empty", style = Type.Body.copy(color = Ember.TextMuted))
            is ClipPreview.Text -> androidx.compose.foundation.text.selection.SelectionContainer {
                Text(preview.text.take(16_000), style = Type.Body.copy(color = Ember.Text))
            }
            is ClipPreview.Image -> {
                Text(preview.label, style = Type.Caption)
                Image(preview.bitmap, "Clipboard image", contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)))
            }
            is ClipPreview.Files -> {
                if (preview.image != null) Image(preview.image, null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)))
                preview.names.forEach { name ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.InsertDriveFile, null, tint = Ember.TextMuted, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(10.dp))
                        Text(name, style = Type.Body.copy(color = Ember.Text))
                    }
                }
            }
        }
    }
}
