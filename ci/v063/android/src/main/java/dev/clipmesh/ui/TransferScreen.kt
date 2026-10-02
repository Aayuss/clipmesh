package dev.clipmesh.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.FileDownload
import androidx.compose.material.icons.rounded.InsertDriveFile
import androidx.compose.material.icons.rounded.Star
import androidx.compose.material.icons.rounded.StarBorder
import androidx.compose.material.icons.rounded.UploadFile
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

interface TransferActions {
    fun choosePhotos()
    fun chooseFiles()
    fun clearFiles()
    fun removeFile(file: SelectedFile)
    fun send(device: DeviceUi)
    fun toggleFavorite(device: DeviceUi)
}

@Composable
fun TransferScreen(ui: ClipMeshUi, actions: TransferActions) {
    PageTitle("Transfer", subtitle = "Files go directly over your local network")

    AnimatedVisibility(
        visible = ui.incoming != null,
        enter = fadeIn(tween(Motion.Navigation)) + expandVertically(tween(Motion.Navigation, easing = Motion.Emphasized)),
        exit = fadeOut(tween(Motion.Small)) + shrinkVertically(tween(Motion.Navigation)),
    ) {
        val banner = ui.incoming
        if (banner != null) IncomingBannerCard(banner)
    }

    EmberCard(padding = 0.dp, modifier = Modifier.animateContentSize(tween(Motion.Navigation, easing = Motion.Emphasized))) {
        AnimatedContent(
            targetState = ui.files.isEmpty(),
            transitionSpec = { fadeIn(tween(Motion.Navigation)) togetherWith fadeOut(tween(Motion.Small)) },
            label = "selection_state",
        ) { empty ->
            if (empty) DropZone { ui.addMenuOpen = true } else SelectionStrip(ui, actions)
        }
    }

    Spacer(Modifier.height(16.dp))
    EmberCard(padding = 6.dp, modifier = Modifier.animateContentSize(tween(Motion.Navigation, easing = Motion.Emphasized))) {
        Text("Send to", style = Type.Section, modifier = Modifier.padding(start = 10.dp, top = 6.dp, bottom = 2.dp))
        if (ui.devices.isEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)) {
                Box(Modifier.size(8.dp).pulse(true).clip(CircleShape).background(Ember.Accent))
                Spacer(Modifier.width(12.dp))
                MutedLine(ui.transferStatus)
            }
        }
        AnimatedItems(ui.devices.toList(), key = { it.fingerprint }) { device ->
            DeviceSendRow(
                device = device,
                state = ui.sendStates[device.fingerprint],
                busy = ui.sendStates.values.any { it is SendState.Sending },
                hasFiles = ui.files.isNotEmpty(),
                onSend = { actions.send(device) },
                onFavorite = { actions.toggleFavorite(device) },
            )
        }
    }
    if (ui.devices.isNotEmpty()) {
        Text("Star a device to trust it: it can send to you without asking.", style = Type.Caption.copy(color = Ember.TextFaint), modifier = Modifier.padding(start = 6.dp, top = 10.dp))
    }
}

@Composable
private fun DropZone(onChoose: () -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxWidth()
            .emberClick(pressedScale = 0.985f, onClick = onChoose)
            .padding(14.dp)
            .drawBehind {
                drawRoundRect(
                    color = Ember.Fill20,
                    cornerRadius = CornerRadius(16.dp.toPx()),
                    style = Stroke(width = 1.5.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 10f))),
                )
            }
            .padding(vertical = 18.dp, horizontal = 16.dp),
    ) {
        Box(Modifier.size(42.dp).clip(CircleShape).background(Ember.AccentSoft), contentAlignment = Alignment.Center) {
            Icon(Icons.Rounded.UploadFile, null, tint = Ember.Accent, modifier = Modifier.size(24.dp))
        }
        Spacer(Modifier.height(12.dp))
        Text("Nothing selected", style = Type.RowTitle)
        Spacer(Modifier.height(3.dp))
        Text("Tap + to pick photos, videos or files", style = Type.Caption, textAlign = TextAlign.Center)
    }
}

@Composable
private fun SelectionStrip(ui: ClipMeshUi, actions: TransferActions) {
    Column(Modifier.padding(vertical = 14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 16.dp)) {
            val total = ui.files.sumOf { it.size.coerceAtLeast(0L) }
            Text(
                "${ui.files.size} file${if (ui.files.size == 1) "" else "s"}" + if (total > 0) " · ${formatBytes(total)}" else "",
                style = Type.RowTitle, modifier = Modifier.weight(1f),
            )
            PillButton("Clear", onClick = actions::clearFiles, style = PillStyle.Ghost, compact = true)
        }
        Spacer(Modifier.height(10.dp))
        Box(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            AnimatedItems(ui.files.toList(), key = { it.uri }, horizontal = true, spacing = 10.dp) { file ->
                FileTile(file, onRemove = { actions.removeFile(file) })
            }
        }
    }
}

@Composable
private fun FileTile(file: SelectedFile, onRemove: () -> Unit) {
    Column(Modifier.width(92.dp)) {
        Box(Modifier.size(92.dp).clip(RoundedCornerShape(14.dp)).background(Ember.Fill07)) {
            if (file.thumbnail != null) {
                Image(file.thumbnail, null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else {
                Icon(Icons.Rounded.InsertDriveFile, null, tint = Ember.TextMuted, modifier = Modifier.size(30.dp).align(Alignment.Center))
            }
            IconCircleButton(
                Icons.Rounded.Close, "Remove ${file.name}", onClick = onRemove,
                modifier = Modifier.align(Alignment.TopEnd).padding(5.dp), size = 24.dp,
                background = androidx.compose.ui.graphics.Color(0xB3131314),
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(file.name, style = Type.Caption.copy(color = Ember.TextSoft), maxLines = 1, overflow = TextOverflow.MiddleEllipsis)
    }
}

@Composable
private fun DeviceSendRow(device: DeviceUi, state: SendState?, busy: Boolean, hasFiles: Boolean, onSend: () -> Unit, onFavorite: () -> Unit) {
    val sending = state as? SendState.Sending
    Column(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 7.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Avatar(mobile = device.mobile, highlighted = sending != null)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(device.alias, style = Type.RowTitle, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val base = device.model.ifBlank { if (device.mobile) "Phone" else "Computer" }
                Text(
                    when {
                        sending != null -> "${(sending.fraction * 100).toInt()}% · ${sending.label}"
                        state == SendState.Sent -> "Sent"
                        device.favorite -> "$base · Trusted"
                        else -> base
                    },
                    style = Type.Caption.copy(color = when { state == SendState.Sent -> Ember.Positive; sending != null -> Ember.Accent; else -> Ember.TextMuted }),
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
            val starBg by animateColorAsState(if (device.favorite) Ember.AccentSoft else androidx.compose.ui.graphics.Color.Transparent, tween(Motion.Small), label = "star_bg")
            val starTint by animateColorAsState(if (device.favorite) Ember.Accent else Ember.TextFaint, tween(Motion.Small), label = "star")
            IconCircleButton(
                if (device.favorite) Icons.Rounded.Star else Icons.Rounded.StarBorder,
                if (device.favorite) "Untrust ${device.alias}" else "Trust ${device.alias}",
                onClick = onFavorite, size = 34.dp, tint = starTint, background = starBg,
            )
            Spacer(Modifier.width(6.dp))
            AnimatedContent(
                targetState = when { sending != null -> 1; state == SendState.Sent -> 2; else -> 0 },
                transitionSpec = { (fadeIn(tween(Motion.Small)) + scaleIn(initialScale = 0.8f)) togetherWith fadeOut(tween(Motion.Press)) },
                label = "send_button",
            ) { mode ->
                Box(Modifier.width(64.dp), contentAlignment = Alignment.Center) {
                    when (mode) {
                        1 -> ProgressRing(sending?.fraction ?: 0f)
                        2 -> Box(Modifier.size(30.dp).clip(CircleShape).background(Ember.Positive.copy(alpha = 0.16f)), contentAlignment = Alignment.Center) {
                            Icon(Icons.Rounded.Check, "Sent", tint = Ember.Positive, modifier = Modifier.size(18.dp))
                        }
                        else -> PillButton("Send", onClick = onSend, compact = true, enabled = !busy, style = if (hasFiles) PillStyle.Primary else PillStyle.Secondary)
                    }
                }
            }
        }
        if (sending != null) {
            Spacer(Modifier.height(8.dp))
            ThinProgress(sending.fraction, Modifier.padding(start = 48.dp, end = 4.dp))
        }
    }
}

@Composable
private fun IncomingBannerCard(banner: IncomingBanner) {
    val tint = when { banner.failed -> Ember.Negative; banner.complete -> Ember.Positive; else -> Ember.Accent }
    Column(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(tint.copy(alpha = 0.10f))
            .border(1.dp, tint.copy(alpha = 0.25f), RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                when { banner.failed -> Icons.Rounded.ErrorOutline; banner.complete -> Icons.Rounded.Check; else -> Icons.Rounded.FileDownload },
                null, tint = tint, modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text(banner.title, style = Type.Body.copy(color = Ember.Text), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        }
        if (!banner.complete && !banner.failed) {
            Spacer(Modifier.height(8.dp))
            ThinProgress(banner.fraction)
        }
    }
}

fun formatBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = arrayOf("KB", "MB", "GB", "TB")
    var value = bytes / 1024.0
    var unit = 0
    while (value >= 1024 && unit < units.lastIndex) { value /= 1024; unit++ }
    return if (value >= 100) "%.0f %s".format(value, units[unit]) else "%.1f %s".format(value, units[unit])
}
