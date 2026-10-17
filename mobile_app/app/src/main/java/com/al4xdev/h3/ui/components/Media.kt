package com.al4xdev.h3.ui.components

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.annotation.OptIn
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import com.al4xdev.h3.data.MediaCache
import com.al4xdev.h3.ui.gestures.noSwipeBack
import com.al4xdev.h3.ui.theme.H3Palette
import java.io.File

@Composable
fun RemoteImage(url: String?, maxPx: Int, modifier: Modifier = Modifier, contentScale: ContentScale = ContentScale.Fit,
                description: String? = null) {
    val context = LocalContext.current
    // key(): produceState keeps its value across key changes; a new url must start empty.
    val bitmap: Bitmap? = key(url, maxPx) {
        produceState(url?.let { MediaCache.cachedImage(it, maxPx) }, url, maxPx) {
            if (url != null && value == null) value = MediaCache.image(context, url, maxPx)
        }.value
    }
    Box(modifier.background(H3Palette.SurfaceElevated), contentAlignment = Alignment.Center) {
        bitmap?.let { Image(it.asImageBitmap(), description, Modifier.fillMaxSize(), contentScale = contentScale) }
            ?: Muted(if (url == null) "—" else "…")
    }
}

/** First frame of the run video, extracted on the phone; nothing is drawn until it exists. */
@Composable
fun RunThumbnail(runId: String, videoUrl: String, localFile: File?, modifier: Modifier = Modifier,
                 contentScale: ContentScale = ContentScale.Crop) {
    val context = LocalContext.current
    val bitmap: Bitmap? = key(runId) {
        produceState(MediaCache.cachedThumb(runId), runId) {
            if (value == null) value = MediaCache.runThumbnail(context, runId, videoUrl, localFile)
        }.value
    }
    bitmap?.let { Image(it.asImageBitmap(), null, modifier, contentScale = contentScale) }
}

/**
 * ExoPlayer over HTTP Range (or the offline copy). Never autoplays; pauses when the app stops;
 * keeps the position across rotation. `poster` (the run's first frame) covers the black surface
 * until playback starts; after the end the last frame stays. Only the control row blocks the
 * swipe-back, the picture itself does not.
 */
@Composable
fun VideoPlayer(uri: String, modifier: Modifier = Modifier, poster: (@Composable () -> Unit)? = null) {
    val context = LocalContext.current
    val position = rememberSaveable(uri) { mutableLongStateOf(0L) }
    var player by remember(uri) { mutableStateOf<ExoPlayer?>(null) }
    var started by rememberSaveable(uri) { mutableStateOf(false) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    // Created in an effect (not during composition) so a discarded composition never leaks it.
    DisposableEffect(uri, lifecycle) {
        val p = ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(uri))
            playWhenReady = false
            prepare()
            if (position.longValue > 0) seekTo(position.longValue)
        }
        p.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) { if (isPlaying) started = true }
        })
        player = p
        val observer = LifecycleEventObserver { _, event ->
            // ON_STOP runs before the state is saved, so rotation restores the position.
            if (event == Lifecycle.Event.ON_STOP) { p.pause(); position.longValue = p.currentPosition }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            position.longValue = p.currentPosition
            player = null
            p.release()
        }
    }
    Box(modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(H3Palette.Midnight)) {
        AndroidView(
            factory = { playerView(it) },
            update = { it.player = player },
            modifier = Modifier.fillMaxSize(),
        )
        if (!started && position.longValue == 0L && poster != null) {
            Box(Modifier.fillMaxSize().padding(bottom = CONTROLS_HEIGHT), contentAlignment = Alignment.Center) { poster() }
        }
        ControlsExclusion()
    }
}

/** Height of PlayerView's bottom control row (seek bar + buttons): the only no-swipe zone. */
internal val CONTROLS_HEIGHT = 88.dp

/** Invisible, non-interactive marker over the control row; touches pass through to the player. */
@Composable
internal fun BoxScope.ControlsExclusion() {
    Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(CONTROLS_HEIGHT).noSwipeBack())
}

/** Keeps the last frame after the end and no black shutter while buffering. */
@OptIn(UnstableApi::class)
internal fun playerView(context: android.content.Context): PlayerView = PlayerView(context).apply {
    useController = true
    setKeepContentOnPlayerReset(true)
    setShutterBackgroundColor(android.graphics.Color.TRANSPARENT)
}

/** Local offline copy when the push already downloaded it, else the PC stream. */
fun runVideoUri(base: String, runId: String, local: File?): String =
    local?.let { android.net.Uri.fromFile(it).toString() } ?: "$base/runs/$runId/video"
