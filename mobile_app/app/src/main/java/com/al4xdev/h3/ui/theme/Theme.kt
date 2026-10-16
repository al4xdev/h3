package com.al4xdev.h3.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val DarkColorScheme = darkColorScheme(
    primary = H3Palette.TealPrimary,
    secondary = H3Palette.TealSecondary,
    tertiary = H3Palette.TealDark,
    background = H3Palette.Midnight,
    surface = H3Palette.SurfaceDark,
    onPrimary = H3Palette.Midnight,
    onSecondary = H3Palette.Midnight,
    onBackground = H3Palette.TextPrimary,
    onSurface = H3Palette.TextPrimary,
    surfaceVariant = H3Palette.SurfaceCard,
    onSurfaceVariant = H3Palette.TextSecondary,
    outline = H3Palette.Outline
)

@Composable
fun H3Theme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        content = content
    )
}
