package com.al4xdev.h3.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp

private val EmphasizedDecelerate = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)

/**
 * Visual press feedback: scale to 0.97 and spring back. Only the drawing shrinks; the touch
 * target keeps its layout size. Static under reduced motion (the ripple still highlights).
 */
@Composable
fun Modifier.pressScale(interaction: MutableInteractionSource): Modifier {
    val pressed by interaction.collectIsPressedAsState()
    val reduced = reducedMotion()
    val scale by animateFloatAsState(
        if (pressed && !reduced) 0.97f else 1f,
        spring(dampingRatio = 0.6f, stiffness = Spring.StiffnessMedium), label = "press",
    )
    return graphicsLayer { scaleX = scale; scaleY = scale }
}

/**
 * Fade + 12 dp rise the first time an item appears. rememberSaveable (kept by lazy lists for
 * items scrolled away) makes it run once per item, not on every scroll back.
 */
@Composable
fun Modifier.appearOnce(): Modifier {
    val reduced = reducedMotion()
    val seen = rememberSaveable { mutableStateOf(reduced) }
    val progress = remember { Animatable(if (seen.value) 1f else 0f) }
    LaunchedEffect(Unit) {
        if (!seen.value) {
            progress.animateTo(1f, tween(240, easing = EmphasizedDecelerate))
            seen.value = true
        }
    }
    return graphicsLayer {
        alpha = progress.value
        translationY = (1f - progress.value) * 12.dp.toPx()
    }
}
