package com.al4xdev.h3.ui.gestures

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.boundsInWindow
import kotlin.math.abs

internal enum class GestureAxis { Pending, Horizontal, Vertical }

internal object WorkspaceGesturePolicy {
    const val BodyLaneFraction = 0.45f

    fun startAllowed(x: Float, width: Float, blocked: Boolean = false): Boolean =
        !blocked && width.isFinite() && width > 0f && x.isFinite() && x >= 0f && x <= width * BodyLaneFraction

    fun axis(dx: Float, dy: Float, slop: Float = 12f): GestureAxis {
        val distance = maxOf(abs(dx), abs(dy))
        val threshold = slop.coerceAtLeast(12f)
        if (distance <= threshold) return GestureAxis.Pending
        if (dx > 0f && dx >= abs(dy) * 1.25f) return GestureAxis.Horizontal
        if (dx < 0f || abs(dy) >= abs(dx)) return GestureAxis.Vertical
        return GestureAxis.Pending
    }

    fun dismiss(dx: Float, width: Float, velocity: Float): Boolean {
        val distance = (width * 0.25f).coerceIn(80f, 120f)
        return dx > 0f && (dx >= distance || (dx >= 40f && velocity >= 600f))
    }
}

internal class GestureExclusions {
    private val entries = LinkedHashMap<Any, LayoutCoordinates>()
    fun put(key: Any, coordinates: LayoutCoordinates) { entries[key] = coordinates }
    fun remove(key: Any) { entries.remove(key) }
    fun contains(positionInWindow: Offset): Boolean = entries.values.any {
        it.isAttached && it.boundsInWindow().contains(positionInWindow)
    }
}

internal val LocalGestureExclusions = staticCompositionLocalOf<GestureExclusions?> { null }
