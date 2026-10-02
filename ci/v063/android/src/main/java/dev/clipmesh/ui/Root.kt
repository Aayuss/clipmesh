package dev.clipmesh.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material3.Text
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material3.Icon
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp

@Composable
fun ClipMeshRoot(ui: ClipMeshUi, clipboard: ClipboardActions, transfer: TransferActions, settings: SettingsActions) {
    val scrolls = remember { HashMap<Tab, androidx.compose.foundation.ScrollState>() }
    Box(Modifier.fillMaxSize().background(Ember.Background).background(Ember.ScreenGlow)) {
        AnimatedContent(
            targetState = ui.tab,
            transitionSpec = {
                val direction = if (targetState.ordinal > initialState.ordinal) 1 else -1
                (fadeIn(tween(Motion.Navigation, delayMillis = 40)) +
                    slideInHorizontally(tween(Motion.Navigation + 60, easing = Motion.Emphasized)) { direction * it / 10 }) togetherWith
                    (fadeOut(tween(Motion.Small - 40)) + slideOutHorizontally(tween(Motion.Navigation, easing = Motion.Emphasized)) { -direction * it / 14 })
            },
            label = "tab_content",
        ) { tab ->
            val scroll = scrolls.getOrPut(tab) { androidx.compose.foundation.ScrollState(0) }
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(scroll)
                    .statusBarsPadding()
                    .padding(horizontal = 18.dp)
                    .padding(bottom = 120.dp),
            ) {
                when (tab) {
                    Tab.CLIPBOARD -> ClipboardScreen(ui, clipboard)
                    Tab.TRANSFER -> TransferScreen(ui, transfer)
                    Tab.SETTINGS -> SettingsScreen(ui, settings)
                }
            }
        }

        // Content fades out beneath the floating navigation pill.
        Box(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(120.dp)
                .background(Brush.verticalGradient(listOf(Color.Transparent, Ember.Background.copy(alpha = 0.92f), Ember.Background))),
        )
        EmberBottomNav(selected = ui.tab, onSelect = { ui.tab = it; ui.addMenuOpen = false }, modifier = Modifier.align(Alignment.BottomCenter))
        AddFilesButton(ui, transfer)
        ToastHost(ui.toast, bottomPadding = 104.dp) { ui.toast = null }

        EmberModal(visible = ui.previewOpen, title = "Current clipboard", onDismiss = { ui.previewOpen = false }) {
            ClipPreviewFull(ui.preview)
        }
    }
}

@Composable
fun BoxScope.EmberModal(visible: Boolean, title: String, onDismiss: () -> Unit, content: @Composable () -> Unit) {
    BackHandler(enabled = visible, onBack = onDismiss)
    AnimatedVisibility(visible, enter = fadeIn(tween(Motion.Sheet)), exit = fadeOut(tween(180)), modifier = Modifier.matchParentSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.55f))
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = onDismiss),
        )
    }
    val maxHeight = (LocalConfiguration.current.screenHeightDp * 0.78f).dp
    AnimatedVisibility(
        visible,
        enter = fadeIn(tween(Motion.Sheet)) + scaleIn(tween(Motion.Sheet, easing = Motion.Emphasized), initialScale = 0.94f),
        exit = fadeOut(tween(180)) + scaleOut(tween(180), targetScale = 0.96f),
        modifier = Modifier.align(Alignment.Center).systemBarsPadding().padding(horizontal = 18.dp),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .heightIn(max = maxHeight)
                .clip(RoundedCornerShape(22.dp))
                .background(Ember.Surface)
                .border(1.dp, Ember.Line, RoundedCornerShape(22.dp))
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}
                .padding(20.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = Type.RowTitle.copy(fontSize = Type.PageTitle.fontSize * 0.7f), modifier = Modifier.weight(1f))
                IconCircleButton(Icons.Rounded.Close, "Close", onClick = onDismiss, size = 34.dp)
            }
            Spacer(Modifier.height(14.dp))
            Column(Modifier.verticalScroll(rememberScrollState())) { content() }
        }
    }
}

/** Transfer's floating "+" with a two-choice menu: the system photo picker or the file picker. */
@Composable
private fun BoxScope.AddFilesButton(ui: ClipMeshUi, actions: TransferActions) {
    val visible = ui.tab == Tab.TRANSFER
    BackHandler(enabled = ui.addMenuOpen) { ui.addMenuOpen = false }
    AnimatedVisibility(ui.addMenuOpen && visible, enter = fadeIn(tween(Motion.Small)), exit = fadeOut(tween(Motion.Small)), modifier = Modifier.matchParentSize()) {
        Box(
            Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.35f))
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) { ui.addMenuOpen = false },
        )
    }
    Column(
        horizontalAlignment = Alignment.End,
        modifier = Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(end = 18.dp, bottom = 84.dp),
    ) {
        AnimatedVisibility(
            ui.addMenuOpen && visible,
            enter = fadeIn(tween(Motion.Small)) + scaleIn(tween(Motion.Sheet, easing = Motion.Emphasized), initialScale = 0.85f, transformOrigin = androidx.compose.ui.graphics.TransformOrigin(1f, 1f)),
            exit = fadeOut(tween(Motion.Press)) + scaleOut(tween(Motion.Small), targetScale = 0.9f, transformOrigin = androidx.compose.ui.graphics.TransformOrigin(1f, 1f)),
        ) {
            Column(
                Modifier.padding(bottom = 12.dp).width(220.dp).clip(RoundedCornerShape(20.dp)).background(Ember.Surface)
                    .border(1.dp, Ember.Line, RoundedCornerShape(20.dp)).padding(6.dp),
            ) {
                MenuRow(Icons.Rounded.PhotoLibrary, "Photos & videos") { ui.addMenuOpen = false; actions.choosePhotos() }
                MenuRow(Icons.Rounded.FolderOpen, "Files") { ui.addMenuOpen = false; actions.chooseFiles() }
            }
        }
        AnimatedVisibility(
            visible,
            enter = fadeIn(tween(Motion.Navigation)) + scaleIn(tween(Motion.Navigation, easing = Motion.Emphasized), initialScale = 0.6f),
            exit = fadeOut(tween(Motion.Small)) + scaleOut(tween(Motion.Small), targetScale = 0.6f),
        ) {
            val rotation by animateFloatAsState(if (ui.addMenuOpen) 45f else 0f, Motion.navSpring(), label = "fab_rotation")
            Box(
                Modifier.size(56.dp).emberClick(pressedScale = 0.92f) { ui.addMenuOpen = !ui.addMenuOpen }
                    .clip(RoundedCornerShape(18.dp)).background(Ember.Accent),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Rounded.Add, "Add files", tint = Ember.White, modifier = Modifier.size(26.dp).graphicsLayer { rotationZ = rotation })
            }
        }
    }
}

@Composable
private fun MenuRow(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, onClick: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().emberClick(pressedScale = 0.97f, onClick = onClick).clip(RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 12.dp),
    ) {
        Icon(icon, null, tint = Ember.Accent, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(12.dp))
        Text(label, style = Type.RowTitle)
    }
}
