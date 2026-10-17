package com.al4xdev.h3.ui.components

import android.content.Context
import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ConcatenatingMediaSource2
import androidx.media3.ui.PlayerView
import com.al4xdev.h3.data.SeqItem
import com.al4xdev.h3.data.Sequence
import com.al4xdev.h3.ui.gestures.noSwipeBack
import com.al4xdev.h3.ui.theme.H3Palette

/**
 * Seamless playback of consecutive blocks without any server-side file. Each playlist entry is a
 * ConcatenatingMediaSource2 of up to [Sequence.WINDOW] clips: one timeline window (one seek bar)
 * whose periods are the blocks. All clips share codec/size/fps, so the decoder is reused across
 * period boundaries. Long films use a sliding window: the next window is appended when playback
 * reaches the last [Sequence.LOOKAHEAD] clips, and windows two behind are dropped (bounded memory).
 */
@OptIn(UnstableApi::class)
private class SequenceController(
    private val context: Context,
    val player: ExoPlayer,
    private val items: List<SeqItem>,
    private val uriFor: (SeqItem) -> String,
) : Player.Listener {
    /** Ranges into `items`, aligned 1:1 with the player's playlist entries. */
    private val windows = ArrayDeque<IntRange>()
    var current by mutableStateOf(items.firstOrNull())
        private set

    fun start() {
        append(0)
        player.addListener(this)
        player.prepare()
        player.playWhenReady = true // explicit "Assistir" tap, not autoplay on open
    }

    private fun append(start: Int) {
        val range = Sequence.window(items.size, start)
        if (range.isEmpty()) return
        val source = ConcatenatingMediaSource2.Builder().useDefaultMediaSourceFactory(context).apply {
            for (i in range) add(MediaItem.fromUri(uriFor(items[i])), items[i].placeholderMs)
        }.build()
        player.addMediaSource(source)
        windows.addLast(range)
    }

    private fun sync() {
        val timeline = player.currentTimeline
        val w = player.currentMediaItemIndex
        if (timeline.isEmpty || w !in windows.indices || w >= timeline.windowCount) return
        val window = timeline.getWindow(w, Timeline.Window())
        val range = windows[w]
        val clip = (player.currentPeriodIndex - window.firstPeriodIndex).coerceIn(0, range.last - range.first)
        current = items[range.first + clip]
        if (w == windows.size - 1 && Sequence.shouldExtend(range, clip, items.size)) append(range.last + 1)
        if (w >= 2) {
            // Keep one previous window for short seeks back; older ones only cost memory.
            player.removeMediaItems(0, w - 1)
            repeat(w - 1) { windows.removeFirst() }
        }
    }

    override fun onPositionDiscontinuity(oldPosition: Player.PositionInfo, newPosition: Player.PositionInfo, reason: Int) = sync()
    override fun onTimelineChanged(timeline: Timeline, reason: Int) = sync()
    override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) = sync()

    fun release() {
        player.removeListener(this)
        player.release()
    }
}

@Composable
fun SequencePlayer(items: List<SeqItem>, uriFor: (SeqItem) -> String, onOpenBlock: (SeqItem) -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    var controller by remember(items) { mutableStateOf<SequenceController?>(null) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    // Player lives in the effect, never created during composition.
    DisposableEffect(items, lifecycle) {
        val c = SequenceController(context, ExoPlayer.Builder(context).build(), items, uriFor).also { it.start() }
        controller = c
        val observer = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_STOP) c.player.pause() }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            controller = null
            c.release()
        }
    }
    Box(modifier) {
        AndroidView(
            factory = { playerView(it) },
            update = { it.player = controller?.player },
            modifier = Modifier.fillMaxSize().background(H3Palette.Midnight),
        )
        ControlsExclusion()
        controller?.current?.let { item ->
            Text(
                item.label, color = H3Palette.TextPrimary, fontSize = 13.sp, maxLines = 1,
                modifier = Modifier.align(Alignment.TopStart).padding(10.dp)
                    .background(H3Palette.Midnight.copy(alpha = 0.65f), RoundedCornerShape(8.dp))
                    .clickable { onOpenBlock(item) }.padding(horizontal = 10.dp, vertical = 6.dp),
            )
        }
    }
}
