package dev.clipmesh.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/** Read-only snapshot of everything the Settings tab renders. Rebuilt whenever settingsRevision changes. */
data class SettingsSnapshot(
    val deviceName: String,
    val deviceId: String,
    val backgroundSync: Boolean,
    val sendEnabled: Boolean,
    val receiveEnabled: Boolean,
    val syncText: Boolean,
    val syncImages: Boolean,
    val syncFiles: Boolean,
    val remotePopup: Boolean,
    val watchdog: Boolean,
    val receiveInBackground: Boolean,
    val autoAcceptFavorites: Boolean,
    val outputFolder: String,
    val shizukuStatus: String,
    val shizukuAction: String,
    val shizukuActionEnabled: Boolean,
    val staticPeers: String,
    val batteryUnrestricted: Boolean,
    val version: String,
)

interface SettingsActions {
    fun snapshot(): SettingsSnapshot
    fun rename()
    fun setBackgroundSync(value: Boolean)
    fun setSend(value: Boolean)
    fun setReceive(value: Boolean)
    fun setSyncText(value: Boolean)
    fun setSyncImages(value: Boolean)
    fun setSyncFiles(value: Boolean)
    fun setRemotePopup(value: Boolean)
    fun setWatchdog(value: Boolean)
    fun setReceiveInBackground(value: Boolean)
    fun setAutoAcceptFavorites(value: Boolean)
    fun chooseOutputFolder()
    fun shizuku()
    fun battery()
    fun accessibility()
    fun exclusions()
    fun appInfo()
    fun pairWithCode()
    fun copyPairingCode()
    fun resetPairing()
    fun saveStaticPeers(value: String)
}

@Composable
fun SettingsScreen(ui: ClipMeshUi, actions: SettingsActions) {
    val s = remember(ui.settingsRevision) { actions.snapshot() }
    PageTitle("Settings", subtitle = "ClipMesh ${s.version}")

    SectionHeader("This device")
    EmberCard(padding = 4.dp) {
        Column(Modifier.padding(horizontal = 12.dp)) {
            SettingRow("Device name", s.deviceName, onClick = actions::rename) {
                PillButton("Rename", onClick = actions::rename, style = PillStyle.Secondary, compact = true)
            }
            Hairline()
            SettingRow("Device ID", s.deviceId)
        }
    }

    Group("Clipboard") {
        ToggleRow("Background sync", "Keep clipboard sync running when ClipMesh is closed", s.backgroundSync, onChange = actions::setBackgroundSync)
        Hairline()
        ToggleRow("Send clipboard", checked = s.sendEnabled, onChange = actions::setSend)
        Hairline()
        ToggleRow("Receive clipboard", checked = s.receiveEnabled, onChange = actions::setReceive)
        Hairline()
        ToggleRow("Text", checked = s.syncText, onChange = actions::setSyncText)
        Hairline()
        ToggleRow("Images and screenshots", checked = s.syncImages, onChange = actions::setSyncImages)
        Hairline()
        ToggleRow("Files", checked = s.syncFiles, onChange = actions::setSyncFiles)
        Hairline()
        ToggleRow("Copy popup", "Show a small popup when another device copies", s.remotePopup, onChange = actions::setRemotePopup)
        Hairline()
        ToggleRow("Compatibility watchdog", "Uses more battery. Only for ROMs that miss clipboard events", s.watchdog, onChange = actions::setWatchdog)
    }

    Group("File transfer") {
        ToggleRow("Receive in background", "Accept files when ClipMesh isn't open", s.receiveInBackground, onChange = actions::setReceiveInBackground)
        Hairline()
        ToggleRow("Auto-save from trusted devices", "Other devices always ask first", s.autoAcceptFavorites, onChange = actions::setAutoAcceptFavorites)
        Hairline()
        SettingRow("Receive folder", s.outputFolder, onClick = actions::chooseOutputFolder) {
            PillButton("Change", onClick = actions::chooseOutputFolder, style = PillStyle.Secondary, compact = true)
        }
    }

    Group("Stay connected") {
        SettingRow(
            "Run unrestricted",
            if (s.batteryUnrestricted) "Allowed · stays connected while the phone is locked" else "Keeps sync and transfers alive while the phone is locked",
            onClick = actions::battery,
        ) {
            if (s.batteryUnrestricted) Badge("On", Ember.Positive) else PillButton("Allow", onClick = actions::battery, compact = true)
        }
    }

    Group("Background clipboard access") {
        SettingRow("Shizuku", s.shizukuStatus) {
            PillButton(s.shizukuAction, onClick = actions::shizuku, compact = true, enabled = s.shizukuActionEnabled)
        }
        Hairline()
        SettingRow("Accessibility helper", "Wakes ClipMesh when you copy", onClick = actions::accessibility) {
            PillButton("Open", onClick = actions::accessibility, style = PillStyle.Secondary, compact = true)
        }
        Hairline()
        SettingRow("Excluded apps", "Never sync what you copy in these apps", onClick = actions::exclusions) {
            PillButton("Choose", onClick = actions::exclusions, style = PillStyle.Secondary, compact = true)
        }
        Hairline()
        SettingRow("App info", onClick = actions::appInfo) {
            PillButton("Open", onClick = actions::appInfo, style = PillStyle.Secondary, compact = true)
        }
    }

    Group("Pairing") {
        SettingRow("Pair with a code", "Paste a code from a trusted device", onClick = actions::pairWithCode) {
            PillButton("Pair", onClick = actions::pairWithCode, compact = true)
        }
        Hairline()
        SettingRow("Copy my pairing code", "Treat it like a password", onClick = actions::copyPairingCode) {
            PillButton("Copy", onClick = actions::copyPairingCode, style = PillStyle.Secondary, compact = true)
        }
        Hairline()
        SettingRow("Reset all pairing", "Every device will need to pair again", onClick = actions::resetPairing, titleColor = Ember.Negative) {
            PillButton("Reset", onClick = actions::resetPairing, style = PillStyle.Destructive, compact = true)
        }
    }

    Advanced(s.staticPeers, actions::saveStaticPeers)

    Spacer(Modifier.height(26.dp))
    Text(
        "ClipMesh ${s.version}\nEncrypted clipboard · Direct LAN transfer",
        style = Type.Caption.copy(color = Ember.TextFaint, textAlign = TextAlign.Center),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Group(title: String, content: @Composable () -> Unit) {
    Spacer(Modifier.height(16.dp))
    SectionHeader(title)
    EmberCard(padding = 4.dp) { Column(Modifier.padding(horizontal = 12.dp)) { content() } }
}

@Composable
private fun Advanced(staticPeers: String, onSave: (String) -> Unit) {
    var open by rememberSaveable { mutableStateOf(false) }
    var text by remember(staticPeers) { mutableStateOf(staticPeers) }
    val rotation by animateFloatAsState(if (open) 180f else 0f, tween(Motion.Navigation, easing = Motion.Emphasized), label = "advanced_chevron")
    Spacer(Modifier.height(22.dp))
    EmberCard(padding = 4.dp, modifier = Modifier.animateContentSize(tween(Motion.Navigation, easing = Motion.Emphasized))) {
        Column(Modifier.padding(horizontal = 12.dp)) {
            SettingRow("Advanced network", "Static peers for networks that block discovery", onClick = { open = !open }) {
                Icon(Icons.Rounded.ExpandMore, null, tint = Ember.TextMuted, modifier = Modifier.size(22.dp).graphicsLayer { rotationZ = rotation })
            }
            AnimatedVisibility(open, enter = fadeIn() + expandVertically(), exit = fadeOut() + shrinkVertically()) {
                Column(Modifier.padding(bottom = 12.dp)) {
                    BasicTextField(
                        value = text,
                        onValueChange = { text = it },
                        textStyle = Type.Body.copy(color = Ember.Text, fontFamily = FontFamily.Monospace),
                        cursorBrush = SolidColor(Ember.Accent),
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 88.dp)
                            .clip(RoundedCornerShape(14.dp))
                            .background(Ember.Fill05)
                            .border(1.dp, Ember.Line, RoundedCornerShape(14.dp))
                            .padding(12.dp),
                        decorationBox = { inner ->
                            if (text.isEmpty()) Text("192.168.1.10:41474", style = Type.Body.copy(color = Ember.TextFaint, fontFamily = FontFamily.Monospace))
                            inner()
                        },
                    )
                    Spacer(Modifier.height(10.dp))
                    PillButton("Save peers", onClick = { onSave(text) }, compact = true)
                }
            }
        }
    }
}
