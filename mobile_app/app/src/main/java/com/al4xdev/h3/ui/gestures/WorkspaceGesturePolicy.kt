package com.al4xdev.h3.ui.gestures

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.boundsInWindow
import kotlin.math.abs

internal enum class GestureAxis { Pending, Horizontal, Vertical }

/** Which edge swipe a touch can start: back from the left lane, forward from the right lane. */
internal enum class SwipeKind { Back, Forward }

internal object WorkspaceGesturePolicy {
    const val BodyLaneFraction = 0.45f

    /** Back swipe starts in the left 45% of the screen. */
    fun startAllowed(x: Float, width: Float, blocked: Boolean = false): Boolean =
        !blocked && width.isFinite() && width > 0f && x.isFinite() && x >= 0f && x <= width * BodyLaneFraction

    /** Forward swipe mirrors it: right 45%. */
    fun startAllowedForward(x: Float, width: Float, blocked: Boolean = false): Boolean =
        !blocked && width.isFinite() && width > 0f && x.isFinite() && x <= width && x >= width * (1f - BodyLaneFraction)

    /**
     * Lane for a touch at `x`; the left lane wins when both overlap (never on real phones).
     * Back needs a screen to pop, forward needs a popped screen to re-enter.
     */
    fun lane(x: Float, width: Float, blocked: Boolean, canBack: Boolean, canForward: Boolean): SwipeKind? = when {
        canBack && startAllowed(x, width, blocked) -> SwipeKind.Back
        canForward && startAllowedForward(x, width, blocked) -> SwipeKind.Forward
        else -> null
    }

    /**
     * `dx` is measured in the completing direction (rightward for back, leftward for forward).
     * `slop` is the platform touch slop in px, so a tap or a small wobble never starts a swipe.
     */
    fun axis(dx: Float, dy: Float, slop: Float): GestureAxis {
        val distance = maxOf(abs(dx), abs(dy))
        val threshold = slop.coerceAtLeast(12f)
        if (distance <= threshold) return GestureAxis.Pending
        if (dx > 0f && dx >= abs(dy) * 1.25f) return GestureAxis.Horizontal
        if (dx < 0f || abs(dy) >= abs(dx)) return GestureAxis.Vertical
        return GestureAxis.Pending
    }

    /**
     * Release decision, UIKit-like. `dx`/`velocity` are in the completing direction (px, px/s);
     * `density` is px per dp. A fling toward completion completes, a fling back cancels,
     * otherwise the screen completes once dragged past 40% of the width.
     */
    fun complete(dx: Float, width: Float, velocity: Float, density: Float = 1f): Boolean = when {
        dx <= 0f || width <= 0f -> false
        velocity >= 500f * density && dx >= 16f * density -> true
        velocity <= -300f * density -> false
        else -> dx >= width * 0.4f
    }
}

/** Rectangles where an edge swipe must not start; `active` lets a text field count only while focused. */
internal class GestureExclusions {
    private class Entry(val coordinates: LayoutCoordinates, val active: () -> Boolean)
    private val entries = LinkedHashMap<Any, Entry>()
    fun put(key: Any, coordinates: LayoutCoordinates, active: () -> Boolean) { entries[key] = Entry(coordinates, active) }
    fun remove(key: Any) { entries.remove(key) }
    fun contains(positionInWindow: Offset): Boolean = entries.values.any {
        it.active() && it.coordinates.isAttached && it.coordinates.boundsInWindow().contains(positionInWindow)
    }
}

internal val LocalGestureExclusions = staticCompositionLocalOf<GestureExclusions?> { null }
