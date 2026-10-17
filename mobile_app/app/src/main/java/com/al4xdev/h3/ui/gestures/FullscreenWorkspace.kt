package com.al4xdev.h3.ui.gestures

import androidx.activity.BackEventCompat
import androidx.activity.compose.PredictiveBackHandler
import androidx.compose.ui.input.pointer.PointerEventPass
import kotlin.coroutines.cancellation.CancellationException
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.input.pointer.util.addPointerInputChange
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import com.al4xdev.h3.ui.components.reducedMotion
import kotlinx.coroutines.launch

/**
 * Marks a control (slider, seek bar/control row, focused text field, fast scroller) whose touches
 * must never start an edge swipe. `active` is re-read at touch time, e.g. "is this field focused".
 */
fun Modifier.noSwipeBack(active: () -> Boolean = { true }): Modifier = composed {
    val exclusions = LocalGestureExclusions.current
    if (exclusions == null) {
        this
    } else {
        val key = remember { Any() }
        val current = rememberUpdatedState(active)
        DisposableEffect(exclusions, key) { onDispose { exclusions.remove(key) } }
        this.onGloballyPositioned { exclusions.put(key, it) { current.value() } }
    }
}

private val EmphasizedDecelerate = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)
private const val PARALLAX = 0.3f
private const val SCRIM = 0.25f
private const val DURATION_MS = 350

/** Two layers: `over` is shifted right by fraction t of the width; `under` sits beneath with parallax. */
private data class Scene<T>(val under: T?, val over: T)

/** Animated push/pop that was not driven by a finger. */
private class Transition<T>(val scene: Scene<T>, val from: Float, val to: Float) {
    var started by mutableStateOf(false)
    var done by mutableStateOf(false)
}

/** Non-state bookkeeping read while computing the transition for a new stack. */
private class Memo<T>(var previous: List<T>) {
    var skipNext = false
}

/**
 * iOS-like navigation container.
 *  - Back: drag right from the left lane; the previous screen is rendered underneath from −30%
 *    with a fading scrim, the top follows the finger 1:1 and settles with a critically damped spring.
 *  - Forward: drag left from the right lane re-enters the most recently popped screen the same way.
 *  - Push/pop from taps or system back use the same geometry over 350 ms (emphasized decelerate).
 * Touches are swallowed while anything moves, so no action fires on a screen in transit, and a
 * second swipe cannot start until the first one settled (never pops twice).
 */
@Composable
fun <T : Any> FullscreenWorkspace(
    stack: List<T>,
    nextForward: T?,
    keyOf: (T) -> String,
    onBack: () -> Unit,
    onForward: () -> Unit,
    content: @Composable (T) -> Unit,
) {
    val exclusions = remember { GestureExclusions() }
    val reduced = reducedMotion()
    val density = LocalDensity.current.density
    val scope = rememberCoroutineScope()
    val t = remember { Animatable(0f) }
    var width by remember { mutableFloatStateOf(1f) }
    var gesture by remember { mutableStateOf<Scene<T>?>(null) }
    var settling by remember { mutableStateOf(false) }
    val coords = remember { arrayOfNulls<LayoutCoordinates>(1) }
    val memo = remember { Memo(stack) }

    val transition: Transition<T>? = remember(stack) {
        val old = memo.previous
        memo.previous = stack
        when {
            memo.skipNext -> { memo.skipNext = false; null } // a finished swipe already shows the result
            reduced -> null
            stack.size == old.size + 1 && stack.dropLast(1) == old -> Transition(Scene(old.last(), stack.last()), 1f, 0f)
            old.size == stack.size + 1 && old.dropLast(1) == stack -> Transition(Scene(stack.last(), old.last()), 0f, 1f)
            else -> null
        }
    }
    LaunchedEffect(transition) {
        if (transition == null) return@LaunchedEffect
        t.snapTo(transition.from)
        transition.started = true
        t.animateTo(transition.to, tween(DURATION_MS, easing = EmphasizedDecelerate))
        transition.done = true
        t.snapTo(0f)
    }

    val running = transition != null && !transition.done
    val scene: Scene<T> = gesture ?: if (running) transition!!.scene else Scene(null, stack.last())
    val busy = gesture != null || settling || running
    // Before the effect starts, draw the transition's first frame (avoids a one-frame flash).
    val fraction = { if (transition != null && !transition.started && gesture == null) transition.from else t.value }

    val latest = rememberUpdatedState(
        Triple(busy, stack.getOrNull(stack.size - 2), nextForward),
    )
    val top = rememberUpdatedState(stack.last())
    val back = rememberUpdatedState(onBack)
    val forward = rememberUpdatedState(onForward)

    suspend fun settleTo(kind: SwipeKind, done: Boolean, velocity: Float = 0f) {
        settling = true
        try {
            val target = when (kind) {
                SwipeKind.Back -> if (done) 1f else 0f
                SwipeKind.Forward -> if (done) 0f else 1f
            }
            if (reduced) t.snapTo(target) else t.animateTo(
                target, spring(dampingRatio = 1f, stiffness = Spring.StiffnessMedium),
                initialVelocity = (if (kind == SwipeKind.Back) velocity else -velocity) / width,
            )
            if (done) {
                memo.skipNext = true
                if (kind == SwipeKind.Back) back.value() else forward.value()
            }
        } finally {
            gesture = null
            t.snapTo(0f)
            settling = false
        }
    }

    fun settle(kind: SwipeKind, dx: Float, velocity: Float) {
        val done = WorkspaceGesturePolicy.complete(dx, width, velocity, density)
        settling = true
        scope.launch { settleTo(kind, done, velocity) }
    }

    // System back (gesture nav uses both edges): the right edge goes forward when possible, every
    // other back gesture pops; both follow the system progress with the same geometry.
    PredictiveBackHandler(enabled = stack.size > 1 || nextForward != null) { events ->
        val (isBusy, previous, next) = latest.value
        var kind: SwipeKind? = null
        var progress = 0f
        try {
            events.collect { e ->
                if (kind == null && !isBusy) {
                    kind = when {
                        e.swipeEdge == BackEventCompat.EDGE_RIGHT && next != null -> SwipeKind.Forward
                        previous != null -> SwipeKind.Back
                        else -> null // at the root a left-edge back with only a forward stack does nothing
                    }
                    when (kind) {
                        SwipeKind.Back -> gesture = Scene(previous, top.value)
                        SwipeKind.Forward -> gesture = Scene(top.value, next!!)
                        null -> Unit
                    }
                }
                progress = e.progress
                when (kind) {
                    SwipeKind.Back -> t.snapTo(progress)
                    SwipeKind.Forward -> t.snapTo(1f - progress)
                    null -> Unit
                }
            }
            val k = kind
            if (k != null) {
                scope.launch { settleTo(k, done = true) }
            } else if (!isBusy && previous != null) {
                back.value() // 3-button back key: no progress events, animated pop
            }
        } catch (e: CancellationException) {
            // The handler's coroutine is cancelled: settle in the composition scope instead.
            kind?.let { k -> scope.launch { settleTo(k, done = false) } }
            throw e
        }
    }

    CompositionLocalProvider(LocalGestureExclusions provides exclusions) {
        Box(
            Modifier
                .fillMaxSize()
                .onSizeChanged { width = it.width.toFloat().coerceAtLeast(1f) }
                .onGloballyPositioned { coords[0] = it }
                .pointerInput(Unit) {
                    val tracker = VelocityTracker()
                    awaitEachGesture {
                        // Initial pass: we see touches before children, so a video surface that
                        // consumes every touch no longer blocks the swipe; exclusions protect controls.
                        val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
                        val (isBusy, previous, next) = latest.value
                        if (isBusy) return@awaitEachGesture
                        val w = size.width.toFloat()
                        val inWindow = coords[0]?.takeIf { it.isAttached }?.localToWindow(down.position)
                        val blocked = inWindow != null && exclusions.contains(inWindow)
                        val kind = WorkspaceGesturePolicy.lane(down.position.x, w, blocked, previous != null, next != null)
                            ?: return@awaitEachGesture
                        val sign = if (kind == SwipeKind.Back) 1f else -1f
                        tracker.resetTracking()
                        tracker.addPointerInputChange(down)
                        var dragging = false
                        var dx = 0f
                        var dy = 0f
                        while (true) {
                            val change = awaitPointerEvent(PointerEventPass.Initial).changes.firstOrNull { it.id == down.id } ?: break
                            if (!change.pressed) {
                                if (dragging) settle(kind, dx, tracker.calculateVelocity().x * sign)
                                break
                            }
                            tracker.addPointerInputChange(change)
                            val step = (change.position.x - change.previousPosition.x) * sign
                            if (!dragging) {
                                dx += step
                                dy += change.position.y - change.previousPosition.y
                                when (WorkspaceGesturePolicy.axis(dx, dy, viewConfiguration.touchSlop)) {
                                    GestureAxis.Horizontal -> {
                                        dragging = true
                                        change.consume()
                                        gesture = if (kind == SwipeKind.Back) Scene(previous, top.value) else Scene(top.value, next!!)
                                        scope.launch { t.snapTo(if (kind == SwipeKind.Back) 0f else 1f) }
                                    }
                                    GestureAxis.Vertical -> break
                                    GestureAxis.Pending -> Unit
                                }
                            } else {
                                dx = (dx + step).coerceIn(0f, w)
                                change.consume()
                                val f = dx / w
                                scope.launch { t.snapTo(if (kind == SwipeKind.Back) f else 1f - f) }
                            }
                        }
                        // Finger lifted before the swipe was recognised, or the pointer was lost mid-drag.
                        if (dragging && gesture != null && !settling) settle(kind, 0f, 0f)
                    }
                },
        ) {
            val layers = listOfNotNull(scene.under?.let { it to false }, scene.over to true)
            for ((screen, isOver) in layers) {
                // Same call site + key: a screen moving between layers keeps its composition.
                key(keyOf(screen)) {
                    Box(
                        Modifier
                            .fillMaxSize()
                            .graphicsLayer {
                                translationX = if (isOver) fraction() * width
                                else if (reduced) 0f else -PARALLAX * width * (1f - fraction())
                            }
                            .drawBehind {
                                if (isOver && scene.under != null) {
                                    val edge = 24f * density
                                    drawRect(
                                        Brush.horizontalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = 0.3f)), -edge, 0f),
                                        topLeft = Offset(-edge, 0f), size = Size(edge, size.height),
                                    )
                                }
                            },
                    ) {
                        content(screen)
                        if (!isOver && !reduced) {
                            Box(Modifier.fillMaxSize().graphicsLayer { alpha = SCRIM * (1f - fraction()) }.background(Color.Black))
                        }
                    }
                }
            }
            if (busy) {
                // Swallow taps while screens move; the drag itself keeps its original hit path.
                Box(Modifier.fillMaxSize().pointerInput(Unit) {
                    awaitEachGesture {
                        awaitFirstDown(requireUnconsumed = false).consume()
                        do {
                            val event = awaitPointerEvent()
                            event.changes.forEach { it.consume() }
                        } while (event.changes.any { it.pressed })
                    }
                })
            }
        }
    }
}
