package com.al4xdev.h3.ui.theme

import androidx.compose.ui.graphics.Color
import com.al4xdev.h3.data.BlockState

object H3Palette {
    val Midnight = Color(0xFF000000)
    val SurfaceDark = Color(0xFF0B191E)
    val SurfaceCard = Color(0xFF112429)
    val SurfaceElevated = Color(0xFF173136)
    val Outline = Color(0xFF2A4A50)

    // Teal / turquoise identity (distinct from ha_app)
    val TealPrimary = Color(0xFF00E5FF)
    val TealSecondary = Color(0xFF00B4D8)
    val TealDark = Color(0xFF0077B6)
    val TealGlow = Color(0x3300E5FF)

    val TextPrimary = Color(0xFFE4EEF0)
    val TextSecondary = Color(0xFFA2B6BA)
    val TextTertiary = Color(0xFF6F8589)

    val StateAccepted = Color(0xFF00E676)
    val StateReady = Color(0xFF00E5FF)
    val StateActive = Color(0xFF4DB6AC)
    val StateUncertain = Color(0xFFFFB300)
    val StatePlanned = Color(0xFF5F7A7F)
    val StateError = Color(0xFFFF5252)
    val Cut = Color(0xFFFFC400)

    fun of(state: BlockState): Color = when (state) {
        BlockState.ACCEPTED -> StateAccepted
        BlockState.REVIEW -> StateReady
        BlockState.ACTIVE -> StateActive
        BlockState.UNCERTAIN -> StateUncertain
        BlockState.FAILED -> StateError
        BlockState.PLANNED -> StatePlanned
    }
}
