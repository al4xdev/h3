package com.al4xdev.h3.ui.screens

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.al4xdev.h3.data.Sequence
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.Screen
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.SequencePlayer
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.components.minutesLabel
import com.al4xdev.h3.ui.components.rememberSequencePlayer
import com.al4xdev.h3.ui.components.runVideoUri
import com.al4xdev.h3.ui.settingsAction
import com.al4xdev.h3.ui.theme.H3Palette

/** "Watch sequence": consecutive playable blocks from `fromBlockId`, no server-side file. */
@Composable
fun WatchScreen(vm: AppViewModel, roteiroId: String, fromBlockId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    var fullscreen by rememberSaveable { mutableStateOf(false) }
    if (!fullscreen) TopBar("Watch sequence", vm.settingsAction())
    val doc = vm.doc(roteiroId) ?: return Loading()
    val from = doc.index(fromBlockId)
    // Snapshot at entry: SSE refreshes of the roteiro must not rebuild the player mid-film.
    val items = remember(roteiroId, fromBlockId, doc.id) { if (from < 0) emptyList() else Sequence.playable(doc, from) }
    if (items.isEmpty()) {
        Muted("Block ${from + 1} has no accepted or ready version to watch.", Modifier.padding(16.dp))
        return
    }
    val base = vm.api.base()
    // The session lives above the layout the toggle replaces, so the film keeps its position.
    val session = rememberSequencePlayer(items) { runVideoUri(base, it.runId, vm.localVideo(it.runId)) }
    val view = LocalView.current
    DisposableEffect(fullscreen) {
        val window = view.context.findActivity()?.window
        val bars = window?.let { WindowCompat.getInsetsController(it, view) }
        if (fullscreen) {
            bars?.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            bars?.hide(WindowInsetsCompat.Type.systemBars())
        }
        onDispose { bars?.show(WindowInsetsCompat.Type.systemBars()) }
    }
    BackHandler(enabled = fullscreen) { fullscreen = false }

    val player: @Composable (Modifier) -> Unit = { modifier ->
        SequencePlayer(
            controller = session,
            onOpenBlock = { vm.push(Screen.Block(roteiroId, it.blockId)) },
            fullscreen = fullscreen,
            onToggleFullscreen = { fullscreen = !fullscreen },
            modifier = modifier,
        )
    }
    if (fullscreen) {
        Box(Modifier.fillMaxSize().background(H3Palette.Midnight)) { player(Modifier.fillMaxSize()) }
        return
    }
    Column {
        player(Modifier.fillMaxWidth().height(600.dp))
        val last = items.last().blockIndex + 1
        val stop = doc.blocks.getOrNull(items.last().blockIndex + 1)
        Muted(
            "Blocks ${items.first().blockIndex + 1}–$last · ${minutesLabel(items.sumOf { it.placeholderMs } / 1000.0)}" +
                (if (stop != null) " · stops before block ${last + 1} (no version to watch)" else ""),
            Modifier.padding(16.dp),
        )
    }
}

private fun Context.findActivity(): Activity? {
    var current: Context = this
    while (current is ContextWrapper) {
        if (current is Activity) return current
        current = current.baseContext
    }
    return null
}
