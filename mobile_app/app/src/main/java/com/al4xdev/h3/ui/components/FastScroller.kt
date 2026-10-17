package com.al4xdev.h3.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.ui.gestures.noSwipeBack
import com.al4xdev.h3.ui.theme.H3Palette
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/** Pure mapping used by the scroller: touch y on the track → item index (0 until count). */
fun fastScrollIndex(y: Float, trackHeight: Float, count: Int): Int {
    if (count <= 1 || trackHeight <= 0f) return 0
    return ((y / trackHeight).coerceIn(0f, 1f) * (count - 1)).roundToInt()
}

/**
 * Draggable thumb on the right edge of a long grid, shown while scrolling (and briefly after).
 * Dragging jumps straight to the block under the finger and shows a bubble with its label.
 * The strip only takes touches (and only blocks the edge swipe) while visible.
 */
@Composable
fun BoxScope.FastScroller(state: LazyGridState, firstItem: Int, count: Int, label: (Int) -> String) {
    val scope = rememberCoroutineScope()
    var dragging by remember { mutableStateOf(false) }
    var dragIndex by remember { mutableIntStateOf(0) }
    var shown by remember { mutableStateOf(false) }
    var trackHeight by remember { mutableFloatStateOf(0f) }
    val active = state.isScrollInProgress || dragging
    LaunchedEffect(active) {
        if (active) shown = true else { delay(1200); shown = false }
    }
    val alpha by animateFloatAsState(if (shown) 1f else 0f, tween(180), label = "scroller")
    val index by remember(firstItem, count) {
        derivedStateOf { (state.firstVisibleItemIndex - firstItem).coerceIn(0, (count - 1).coerceAtLeast(0)) }
    }
    val current = if (dragging) dragIndex else index
    val density = LocalDensity.current
    val thumbHeight = with(density) { 48.dp.toPx() }
    val thumbY = if (count <= 1) 0f else current.toFloat() / (count - 1) * (trackHeight - thumbHeight).coerceAtLeast(0f)

    fun jump(y: Float) {
        dragIndex = fastScrollIndex(y, trackHeight, count)
        scope.launch { state.scrollToItem(firstItem + dragIndex) }
    }

    if (alpha <= 0f) return
    if (dragging) {
        Text(
            label(current), color = H3Palette.TextPrimary, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.align(Alignment.TopEnd).offset { IntOffset(0, thumbY.roundToInt()) }
                .padding(end = 52.dp).widthIn(max = 260.dp)
                .background(H3Palette.SurfaceElevated, RoundedCornerShape(10.dp)).padding(horizontal = 12.dp, vertical = 10.dp),
        )
    }
    Box(
        Modifier.align(Alignment.CenterEnd).fillMaxHeight().width(44.dp).alpha(alpha)
            .onSizeChanged { trackHeight = it.height.toFloat() }
            .noSwipeBack { shown }
            .then(
                if (shown) Modifier.pointerInput(count, firstItem) {
                    detectVerticalDragGestures(
                        onDragStart = { dragging = true; jump(it.y) },
                        onDragEnd = { dragging = false },
                        onDragCancel = { dragging = false },
                        onVerticalDrag = { change, _ -> change.consume(); jump(change.position.y) },
                    )
                } else Modifier,
            ),
    ) {
        Box(
            Modifier.align(Alignment.TopEnd).offset { IntOffset(0, thumbY.roundToInt()) }.padding(end = 6.dp)
                .size(width = 8.dp, height = 48.dp)
                .background(if (dragging) H3Palette.TealPrimary else H3Palette.TealSecondary, RoundedCornerShape(4.dp)),
        )
    }
}
