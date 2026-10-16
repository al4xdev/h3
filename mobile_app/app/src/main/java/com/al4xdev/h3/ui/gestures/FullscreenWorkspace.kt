package com.al4xdev.h3.ui.gestures

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.input.pointer.util.addPointerInputChange
import kotlinx.coroutines.launch

@Composable
fun FullscreenWorkspace(
    canDismiss: Boolean = true,
    onDismiss: () -> Unit,
    content: @Composable () -> Unit
) {
    if (!canDismiss) {
        Box(modifier = Modifier.fillMaxSize()) {
            content()
        }
        return
    }

    BackHandler(enabled = true) {
        onDismiss()
    }

    val coroutineScope = rememberCoroutineScope()
    val offsetX = remember { Animatable(0f) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(canDismiss) {
                if (!canDismiss) return@pointerInput
                val velocityTracker = VelocityTracker()
                val screenWidth = size.width.toFloat()

                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    val startX = down.position.x

                    if (!WorkspaceGesturePolicy.startAllowed(startX, screenWidth)) {
                        return@awaitEachGesture
                    }

                    velocityTracker.resetTracking()
                    velocityTracker.addPointerInputChange(down)

                    var isDragging = false
                    var totalDx = 0f

                    while (true) {
                        val event = awaitPointerEvent()
                        val change = event.changes.firstOrNull() ?: break
                        if (!change.pressed) {
                            // Up or Cancel
                            val velocity = velocityTracker.calculateVelocity().x
                            val shouldDismiss = WorkspaceGesturePolicy.dismiss(totalDx, screenWidth, velocity)

                            coroutineScope.launch {
                                if (shouldDismiss) {
                                    offsetX.animateTo(screenWidth, tween(180))
                                    onDismiss()
                                    offsetX.snapTo(0f)
                                } else {
                                    offsetX.animateTo(0f, spring())
                                }
                            }
                            break
                        }

                        velocityTracker.addPointerInputChange(change)
                        val dx = change.position.x - change.previousPosition.x
                        val dy = change.position.y - change.previousPosition.y

                        if (!isDragging) {
                            totalDx += dx
                            val axis = WorkspaceGesturePolicy.axis(totalDx, dy)
                            if (axis == GestureAxis.Horizontal) {
                                isDragging = true
                                change.consume()
                            } else if (axis == GestureAxis.Vertical) {
                                break
                            }
                        } else {
                            totalDx = (totalDx + dx).coerceAtLeast(0f)
                            change.consume()
                            coroutineScope.launch {
                                offsetX.snapTo(totalDx)
                            }
                        }
                    }
                }
            }
            .graphicsLayer {
                translationX = offsetX.value
            }
            .background(Color.Black)
    ) {
        content()
    }
}
