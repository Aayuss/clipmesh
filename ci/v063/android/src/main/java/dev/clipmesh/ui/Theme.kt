package dev.clipmesh.ui

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import dev.clipmesh.R

/** ClipMesh "Ember" tokens. Shared verbatim with the macOS and Windows clients. */
object Ember {
    val Background = Color(0xFF131314)
    val Surface = Color(0xFF222222)
    val Accent = Color(0xFFE55F11)
    val AccentPressed = Color(0xFFC9520E)
    val AccentSoft = Color(0x24E55F11)
    val White = Color(0xFFFFFFFF)

    val Text = Color(0xFFFFFFFF)
    val TextSoft = Color(0xFFDDDDDD)
    val TextMuted = Color(0x80FFFFFF)
    val TextFaint = Color(0x59FFFFFF)

    val Line = Color(0x14FFFFFF)
    val Fill05 = Color(0x0DFFFFFF)
    val Fill06 = Color(0x0FFFFFFF)
    val Fill07 = Color(0x12FFFFFF)
    val Fill20 = Color(0x33FFFFFF)

    val Positive = Color(0xFF3FD05E)
    val Negative = Color(0xFFFF6B5A)
    val ToggleOff = Color(0xFF3A3A3A)

    val ScreenGlow = Brush.radialGradient(
        colors = listOf(Color(0xFF272B22), Color(0xFF131314)),
        center = Offset(80f, 0f),
        radius = 900f,
    )
}

object Motion {
    const val Press = 100
    const val Small = 160
    const val Navigation = 220
    const val Sheet = 260
    val Emphasized: Easing = CubicBezierEasing(0.2f, 0f, 0f, 1f)
    fun <T> navSpring() = spring<T>(dampingRatio = 0.84f, stiffness = 520f)
    fun <T> softSpring() = spring<T>(dampingRatio = 0.86f, stiffness = Spring.StiffnessMediumLow)
}

val Sora = FontFamily(
    Font(R.font.sora_regular, FontWeight.Normal),
    Font(R.font.sora_medium, FontWeight.Medium),
    Font(R.font.sora_semibold, FontWeight.SemiBold),
    Font(R.font.sora_bold, FontWeight.Bold),
)

object Type {
    val PageTitle = TextStyle(fontFamily = Sora, fontWeight = FontWeight.SemiBold, fontSize = 26.sp, lineHeight = 32.sp, letterSpacing = (-0.3).sp, color = Ember.Text)
    val Section = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Medium, fontSize = 13.sp, lineHeight = 18.sp, color = Ember.TextMuted)
    val RowTitle = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Medium, fontSize = 15.sp, lineHeight = 20.sp, color = Ember.Text)
    val Body = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 20.sp, color = Ember.TextSoft)
    val Caption = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Normal, fontSize = 12.sp, lineHeight = 16.sp, color = Ember.TextMuted)
    val Badge = TextStyle(fontFamily = Sora, fontWeight = FontWeight.SemiBold, fontSize = 11.sp, lineHeight = 14.sp, letterSpacing = 0.2.sp, color = Ember.Text)
    val Button = TextStyle(fontFamily = Sora, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, lineHeight = 16.sp, color = Ember.Text)
}

@Composable
fun EmberTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Ember.Accent,
            onPrimary = Ember.White,
            background = Ember.Background,
            onBackground = Ember.Text,
            surface = Ember.Surface,
            onSurface = Ember.Text,
            error = Ember.Negative,
        ),
        content = content,
    )
}
