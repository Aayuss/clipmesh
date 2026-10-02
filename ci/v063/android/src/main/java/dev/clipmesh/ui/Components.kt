package dev.clipmesh.ui

import android.view.HapticFeedbackConstants
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.LaptopMac
import androidx.compose.material.icons.rounded.PhoneAndroid
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

/** No-ripple click with Ember press feedback: quick spring scale + light haptic. */
@Composable
fun Modifier.emberClick(
    enabled: Boolean = true,
    pressedScale: Float = 0.96f,
    onClick: () -> Unit,
): Modifier {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed && enabled) pressedScale else 1f,
        animationSpec = spring(dampingRatio = 0.55f, stiffness = 900f),
        label = "press_scale",
    )
    val view = LocalView.current
    return this
        .graphicsLayer { scaleX = scale; scaleY = scale }
        .clickable(interactionSource = interaction, indication = null, enabled = enabled) {
            view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
            onClick()
        }
}

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

@Composable
fun EmberCard(
    modifier: Modifier = Modifier,
    padding: Dp = 16.dp,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(20.dp)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.emberClick(pressedScale = 0.985f, onClick = onClick) else Modifier)
            .clip(shape)
            .background(Ember.Surface)
            .border(1.dp, Ember.Line, shape)
            .padding(padding),
        content = content,
    )
}

@Composable
fun SectionHeader(text: String, modifier: Modifier = Modifier, trailing: @Composable RowScope.() -> Unit = {}) {
    Row(
        modifier = modifier.fillMaxWidth().heightIn(min = 36.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, style = Type.Section, modifier = Modifier.weight(1f))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically, content = trailing)
    }
}

@Composable
fun Hairline(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(1.dp).background(Ember.Line))
}

@Composable
fun PageTitle(title: String, subtitle: String? = null, trailing: @Composable RowScope.() -> Unit = {}) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = Type.PageTitle)
            if (!subtitle.isNullOrBlank()) Text(subtitle, style = Type.Caption, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically, content = trailing)
    }
}

/** Determinate ring used in place of the Send button while a transfer runs. */
@Composable
fun ProgressRing(fraction: Float, modifier: Modifier = Modifier, size: Dp = 30.dp, color: Color = Ember.Accent) {
    val animated by animateFloatAsState(fraction.coerceIn(0f, 1f), tween(Motion.Small), label = "ring")
    androidx.compose.foundation.Canvas(modifier.size(size)) {
        val stroke = 2.5.dp.toPx()
        val inset = stroke / 2
        val arcSize = androidx.compose.ui.geometry.Size(this.size.width - stroke, this.size.height - stroke)
        val topLeft = androidx.compose.ui.geometry.Offset(inset, inset)
        drawArc(Ember.Fill07, 0f, 360f, false, topLeft, arcSize, style = androidx.compose.ui.graphics.drawscope.Stroke(stroke))
        drawArc(color, -90f, 360f * animated, false, topLeft, arcSize, style = androidx.compose.ui.graphics.drawscope.Stroke(stroke, cap = androidx.compose.ui.graphics.StrokeCap.Round))
    }
}

// ---------------------------------------------------------------------------
// Buttons & controls
// ---------------------------------------------------------------------------

enum class PillStyle { Primary, Secondary, Destructive, Ghost }

@Composable
fun PillButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    style: PillStyle = PillStyle.Primary,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    compact: Boolean = false,
) {
    val bg by animateColorAsState(
        when {
            !enabled -> Ember.Fill05
            style == PillStyle.Primary -> Ember.Accent
            style == PillStyle.Destructive -> Ember.Negative.copy(alpha = 0.16f)
            style == PillStyle.Ghost -> Color.Transparent
            else -> Ember.Fill07
        },
        tween(Motion.Small),
        label = "pill_bg",
    )
    val fg = when {
        !enabled -> Ember.TextFaint
        style == PillStyle.Destructive -> Ember.Negative
        else -> Ember.Text
    }
    Row(
        modifier = modifier
            .emberClick(enabled = enabled, onClick = onClick)
            .clip(CircleShape)
            .background(bg)
            .heightIn(min = if (compact) 34.dp else 44.dp)
            .padding(horizontal = if (compact) 14.dp else 18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(if (compact) 16.dp else 18.dp))
            Spacer(Modifier.width(7.dp))
        }
        Text(text, style = Type.Button.copy(color = fg), maxLines = 1)
    }
}

@Composable
fun IconCircleButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 36.dp,
    tint: Color = Ember.Text,
    background: Color = Ember.Fill07,
    rotation: Float = 0f,
    enabled: Boolean = true,
) {
    Box(
        modifier = modifier
            .size(size)
            .emberClick(enabled = enabled, pressedScale = 0.9f, onClick = onClick)
            .clip(CircleShape)
            .background(background),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon,
            contentDescription = contentDescription,
            tint = if (enabled) tint else Ember.TextFaint,
            modifier = Modifier.size(size * 0.5f).graphicsLayer { rotationZ = rotation },
        )
    }
}

@Composable
fun EmberToggle(checked: Boolean, onCheckedChange: (Boolean) -> Unit, enabled: Boolean = true) {
    val track by animateColorAsState(if (checked) Ember.Accent else Ember.ToggleOff, tween(Motion.Small), label = "toggle_track")
    val knobX by animateDpAsState(if (checked) 20.dp else 2.dp, spring(dampingRatio = 0.7f, stiffness = 700f), label = "toggle_knob")
    Box(
        modifier = Modifier
            .size(width = 46.dp, height = 28.dp)
            .graphicsLayer { alpha = if (enabled) 1f else 0.45f }
            .emberClick(enabled = enabled, pressedScale = 0.94f) { onCheckedChange(!checked) }
            .clip(CircleShape)
            .background(track),
    ) {
        Box(
            Modifier
                .offset(x = knobX, y = 2.dp)
                .size(24.dp)
                .clip(CircleShape)
                .background(Ember.White),
        )
    }
}

@Composable
fun SettingRow(
    title: String,
    caption: String? = null,
    onClick: (() -> Unit)? = null,
    titleColor: Color = Ember.Text,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.emberClick(pressedScale = 0.985f, onClick = onClick) else Modifier)
            .heightIn(min = 50.dp)
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = Type.RowTitle.copy(color = titleColor))
            if (!caption.isNullOrBlank()) {
                Spacer(Modifier.height(2.dp))
                Text(caption, style = Type.Caption, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
        Spacer(Modifier.width(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp), content = trailing)
    }
}

@Composable
fun ToggleRow(title: String, caption: String? = null, checked: Boolean, enabled: Boolean = true, onChange: (Boolean) -> Unit) {
    SettingRow(title = title, caption = caption, onClick = if (enabled) ({ onChange(!checked) }) else null) {
        EmberToggle(checked = checked, onCheckedChange = onChange, enabled = enabled)
    }
}

@Composable
fun Avatar(mobile: Boolean, modifier: Modifier = Modifier, highlighted: Boolean = false) {
    Box(
        modifier = modifier
            .size(36.dp)
            .clip(CircleShape)
            .background(if (highlighted) Ember.AccentSoft else Ember.Fill07),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            if (mobile) Icons.Rounded.PhoneAndroid else Icons.Rounded.LaptopMac,
            contentDescription = null,
            tint = if (highlighted) Ember.Accent else Ember.TextSoft,
            modifier = Modifier.size(18.dp),
        )
    }
}

@Composable
fun StatusPill(health: SyncHealth, text: String) {
    val color = when (health) {
        SyncHealth.ON -> Ember.Positive
        SyncHealth.OFF -> Ember.TextMuted
        SyncHealth.RECOVERING -> Ember.Accent
        SyncHealth.STOPPED -> Ember.Negative
    }
    val pulse = rememberInfiniteTransition(label = "status_pulse")
    val pulseAlpha by pulse.animateFloat(
        initialValue = 1f,
        targetValue = if (health == SyncHealth.RECOVERING) 0.3f else 1f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
        label = "status_pulse_alpha",
    )
    Row(
        modifier = Modifier.clip(CircleShape).background(Ember.Fill07).padding(horizontal = 12.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(7.dp).graphicsLayer { alpha = pulseAlpha }.clip(CircleShape).background(color))
        Spacer(Modifier.width(7.dp))
        Text(text, style = Type.Badge.copy(color = Ember.TextSoft), maxLines = 1)
    }
}

@Composable
fun Badge(text: String, color: Color = Ember.Accent) {
    Text(
        text,
        style = Type.Badge.copy(color = color),
        modifier = Modifier.clip(CircleShape).background(color.copy(alpha = 0.14f)).padding(horizontal = 9.dp, vertical = 4.dp),
    )
}

@Composable
fun ThinProgress(fraction: Float, modifier: Modifier = Modifier, color: Color = Ember.Accent) {
    val animated by animateFloatAsState(fraction.coerceIn(0f, 1f), tween(Motion.Small), label = "thin_progress")
    Box(modifier.fillMaxWidth().height(4.dp).clip(CircleShape).background(Ember.Fill07)) {
        Box(Modifier.fillMaxWidth(animated).height(4.dp).clip(CircleShape).background(color))
    }
}

@Composable
fun MutedLine(text: String, modifier: Modifier = Modifier) {
    Text(text, style = Type.Body.copy(color = Ember.TextMuted), modifier = modifier.padding(vertical = 10.dp))
}

// ---------------------------------------------------------------------------
// Animated list: rows fade/expand in and collapse out instead of popping.
// ---------------------------------------------------------------------------

private class AnimatedEntry<T>(val key: Any, item: T, val state: MutableTransitionState<Boolean>) {
    // Snapshot-backed so a changed row (thumbnail loaded, star toggled) recomposes even when skipping applies.
    var item by androidx.compose.runtime.mutableStateOf(item)
}

/** Remembered (non-snapshot) cache that merges list updates while exiting rows finish animating. */
private class AnimatedListCache<T> {
    var entries: List<AnimatedEntry<T>> = emptyList()
    var initialized = false

    fun update(items: List<T>, key: (T) -> Any): List<AnimatedEntry<T>> {
        val nextKeys = items.map(key)
        val nextKeySet = nextKeys.toHashSet()
        val old = entries.associateBy { it.key }
        val fresh = items.mapIndexed { index, item ->
            val k = nextKeys[index]
            (old[k] ?: AnimatedEntry(k, item, MutableTransitionState(!initialized))).also {
                if (it.item != item) it.item = item
                if (!it.state.targetState) it.state.targetState = true
            }
        }.toMutableList()
        // Keep exiting rows next to the row that preceded them so they collapse in place.
        entries.forEachIndexed { index, entry ->
            if (entry.key in nextKeySet) return@forEachIndexed
            if (entry.state.targetState) entry.state.targetState = false
            if (entry.state.isIdle && !entry.state.currentState) return@forEachIndexed
            val previousKey = entries.getOrNull(index - 1)?.key
            val anchor = fresh.indexOfFirst { it.key == previousKey }
            fresh.add(if (anchor >= 0) anchor + 1 else 0.coerceAtMost(fresh.size), entry)
        }
        initialized = true
        entries = fresh
        return fresh
    }
}

@Composable
fun <T> AnimatedItems(
    items: List<T>,
    key: (T) -> Any,
    horizontal: Boolean = false,
    spacing: Dp = 0.dp,
    content: @Composable (T) -> Unit,
) {
    val cache = remember { AnimatedListCache<T>() }
    val entries = cache.update(items, key)
    val render: @Composable () -> Unit = {
        for (entry in entries) {
            androidx.compose.runtime.key(entry.key) {
                AnimatedVisibility(
                    visibleState = entry.state,
                    enter = if (horizontal) {
                        fadeIn(tween(Motion.Navigation)) + scaleIn(tween(Motion.Navigation, easing = Motion.Emphasized), initialScale = 0.85f) + expandHorizontally(tween(Motion.Navigation, easing = Motion.Emphasized))
                    } else {
                        fadeIn(tween(Motion.Navigation)) + expandVertically(tween(Motion.Navigation, easing = Motion.Emphasized))
                    },
                    exit = if (horizontal) {
                        fadeOut(tween(Motion.Small)) + scaleOut(tween(Motion.Small), targetScale = 0.85f) + shrinkHorizontally(tween(Motion.Navigation, easing = Motion.Emphasized))
                    } else {
                        fadeOut(tween(Motion.Small)) + shrinkVertically(tween(Motion.Navigation, easing = Motion.Emphasized))
                    },
                ) {
                    Box(if (horizontal) Modifier.padding(end = spacing) else Modifier.padding(bottom = spacing)) { content(entry.item) }
                }
            }
        }
    }
    if (horizontal) Row { render() } else Column { render() }
}

// ---------------------------------------------------------------------------
// Bottom navigation — a port of Suya Phot's SuyaBottomNav.
// ---------------------------------------------------------------------------

@Composable
fun EmberBottomNav(selected: Tab, onSelect: (Tab) -> Unit, modifier: Modifier = Modifier) {
    val selectedWidth = 124.dp
    val iconOnlyWidth = 52.dp
    val gap = 6.dp
    val tabs = Tab.entries
    val selectedIndex = tabs.indexOf(selected).coerceAtLeast(0)
    val indicatorX by animateDpAsState(
        targetValue = (iconOnlyWidth + gap) * selectedIndex,
        animationSpec = Motion.navSpring(),
        label = "bottom_nav_indicator_x",
    )
    val view = LocalView.current
    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier.navigationBarsPadding().fillMaxWidth().padding(top = 6.dp, bottom = 10.dp),
    ) {
        Box(
            modifier = Modifier
                .wrapContentWidth()
                .clip(RoundedCornerShape(30.dp))
                .background(Color(0xF0222222))
                .border(1.dp, Ember.Line, RoundedCornerShape(30.dp))
                .padding(6.dp),
        ) {
            Box(Modifier.width(selectedWidth + iconOnlyWidth * (tabs.size - 1) + gap * (tabs.size - 1)).height(50.dp)) {
                Box(
                    Modifier
                        .offset(x = indicatorX)
                        .width(selectedWidth)
                        .height(50.dp)
                        .background(Ember.Accent, RoundedCornerShape(25.dp)),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(gap), verticalAlignment = Alignment.CenterVertically) {
                    tabs.forEach { tab ->
                        val isSelected = tab == selected
                        val itemWidth by animateDpAsState(
                            targetValue = if (isSelected) selectedWidth else iconOnlyWidth,
                            animationSpec = spring(dampingRatio = 0.86f, stiffness = 620f),
                            label = "bottom_nav_item_width",
                        )
                        val tint by animateColorAsState(if (isSelected) Ember.White else Ember.TextMuted, tween(Motion.Small), label = "nav_tint")
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .width(itemWidth)
                                .height(50.dp)
                                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {
                                    if (!isSelected) {
                                        view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                                        onSelect(tab)
                                    }
                                },
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
                                Icon(tab.icon, contentDescription = tab.title, tint = tint, modifier = Modifier.size(22.dp))
                                AnimatedVisibility(
                                    visible = isSelected,
                                    enter = expandHorizontally(expandFrom = Alignment.Start, animationSpec = spring(dampingRatio = 0.86f, stiffness = 650f)) + fadeIn(tween(Motion.Small)),
                                    exit = shrinkHorizontally(shrinkTowards = Alignment.Start, animationSpec = spring(dampingRatio = 0.9f, stiffness = 700f)) + fadeOut(tween(Motion.Press)),
                                ) {
                                    Text(tab.title, style = Type.Badge.copy(fontSize = Type.Button.fontSize, color = Ember.White), modifier = Modifier.padding(start = 7.dp), maxLines = 1)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

@Composable
fun BoxScope.ToastHost(toast: ToastMessage?, bottomPadding: Dp, onDismiss: () -> Unit) {
    LaunchedEffect(toast?.id) {
        if (toast != null) { delay(2400); onDismiss() }
    }
    AnimatedVisibility(
        visible = toast != null,
        enter = fadeIn(tween(Motion.Small)) + slideInVertically(tween(Motion.Sheet, easing = Motion.Emphasized)) { it / 2 },
        exit = fadeOut(tween(Motion.Small)) + slideOutVertically(tween(Motion.Small)) { it / 3 },
        modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = bottomPadding, start = 24.dp, end = 24.dp),
    ) {
        val last = remember { arrayOfNulls<String>(1) }
        if (toast != null) last[0] = toast.text
        Text(
            last[0].orEmpty(),
            style = Type.Body.copy(color = Ember.Text),
            modifier = Modifier
                .clip(CircleShape)
                .background(Color(0xFF2B2B2C))
                .border(1.dp, Ember.Line, CircleShape)
                .padding(horizontal = 18.dp, vertical = 11.dp),
        )
    }
}

@Composable
fun Modifier.pulse(active: Boolean): Modifier {
    if (!active) return this
    val transition = rememberInfiniteTransition(label = "pulse")
    val s by transition.animateFloat(0.85f, 1.15f, infiniteRepeatable(tween(900), RepeatMode.Reverse), label = "pulse_scale")
    return this.scale(s)
}
