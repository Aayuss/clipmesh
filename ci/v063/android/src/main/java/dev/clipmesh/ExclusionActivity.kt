package dev.clipmesh

import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.Drawable
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.graphics.drawable.toBitmap
import dev.clipmesh.ui.Ember
import dev.clipmesh.ui.EmberTheme
import dev.clipmesh.ui.EmberToggle
import dev.clipmesh.ui.IconCircleButton
import dev.clipmesh.ui.PillButton
import dev.clipmesh.ui.PillStyle
import dev.clipmesh.ui.Type
import dev.clipmesh.ui.emberClick

/** Apps whose clipboard changes ClipMesh never syncs. */
class ExclusionActivity : ComponentActivity() {
    private lateinit var settingsStore: SettingsStore

    private data class AppEntry(val label: String, val pkg: String, val icon: Drawable?)

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(SystemBarStyle.dark(Color.TRANSPARENT), SystemBarStyle.dark(Color.TRANSPARENT))
        super.onCreate(savedInstanceState)
        settingsStore = SettingsStore(this)
        val launchIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = packageManager.queryIntentActivities(launchIntent, 0)
            .map { AppEntry(it.loadLabel(packageManager).toString(), it.activityInfo.packageName, runCatching { it.loadIcon(packageManager) }.getOrNull()) }
            .distinctBy { it.pkg }
            .filter { it.pkg != packageName }
            .sortedBy { it.label.lowercase() }
        setContent { EmberTheme { Screen(apps) } }
    }

    @Composable
    private fun Screen(apps: List<AppEntry>) {
        var excluded by remember { mutableStateOf(settingsStore.excludedPackages) }
        var query by remember { mutableStateOf("") }
        val icons = remember { HashMap<String, ImageBitmap?>() }
        val visible = apps.filter { query.isBlank() || it.label.contains(query, true) || it.pkg.contains(query, true) }
        Box(Modifier.fillMaxSize().background(Ember.Background).background(Ember.ScreenGlow)) {
            LazyColumn(
                contentPadding = PaddingValues(start = 18.dp, end = 18.dp, bottom = 32.dp),
                modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding(),
            ) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 14.dp, bottom = 12.dp)) {
                        IconCircleButton(Icons.AutoMirrored.Rounded.ArrowBack, "Back", onClick = { finish() }, size = 40.dp)
                        Spacer(Modifier.width(12.dp))
                        Text("Excluded apps", style = Type.PageTitle)
                    }
                    Text("ClipMesh won't sync anything you copy while these apps are open.", style = Type.Caption)
                    Spacer(Modifier.height(14.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth().height(48.dp).clip(RoundedCornerShape(16.dp)).background(Ember.Surface)
                            .border(1.dp, Ember.Line, RoundedCornerShape(16.dp)).padding(horizontal = 14.dp),
                    ) {
                        Icon(Icons.Rounded.Search, null, tint = Ember.TextMuted, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(10.dp))
                        Box(Modifier.weight(1f)) {
                            if (query.isEmpty()) Text("Search apps", style = Type.Body.copy(color = Ember.TextMuted))
                            BasicTextField(query, { query = it }, singleLine = true, textStyle = Type.Body.copy(color = Ember.Text), cursorBrush = SolidColor(Ember.Accent), modifier = Modifier.fillMaxWidth())
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    PillButton("Accessibility helper", onClick = { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }, style = PillStyle.Ghost, compact = true)
                    Spacer(Modifier.height(4.dp))
                }
                items(visible, key = { it.pkg }) { app ->
                    val checked = app.pkg in excluded
                    val toggle = {
                        val next = if (checked) excluded - app.pkg else excluded + app.pkg
                        excluded = next
                        settingsStore.excludedPackages = next
                    }
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth().animateItem().emberClick(pressedScale = 0.985f, onClick = toggle).padding(vertical = 10.dp),
                    ) {
                        val icon = icons.getOrPut(app.pkg) { runCatching { app.icon?.toBitmap(96, 96)?.asImageBitmap() }.getOrNull() }
                        if (icon != null) Image(icon, null, Modifier.size(38.dp).clip(RoundedCornerShape(10.dp)))
                        else Box(Modifier.size(38.dp).clip(RoundedCornerShape(10.dp)).background(Ember.Fill07))
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(app.label, style = Type.RowTitle, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(app.pkg, style = Type.Caption, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        EmberToggle(checked = checked, onCheckedChange = { toggle() })
                    }
                }
            }
        }
    }
}
