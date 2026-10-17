package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.al4xdev.h3.data.Sequence
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.Screen
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.SequencePlayer
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.components.minutesLabel
import com.al4xdev.h3.ui.components.runVideoUri
import com.al4xdev.h3.ui.settingsAction

/** "Assistir em sequência": consecutive playable blocks from `fromBlockId`, no server-side file. */
@Composable
fun WatchScreen(vm: AppViewModel, roteiroId: String, fromBlockId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    TopBar("Assistir em sequência", vm.settingsAction())
    val doc = vm.doc(roteiroId) ?: return Loading()
    val from = doc.index(fromBlockId)
    // Snapshot at entry: SSE refreshes of the roteiro must not rebuild the player mid-film.
    val items = remember(roteiroId, fromBlockId, doc.id) { if (from < 0) emptyList() else Sequence.playable(doc, from) }
    if (items.isEmpty()) {
        Muted("O bloco ${from + 1} não tem versão aceita ou pronta para assistir.", Modifier.padding(16.dp))
        return
    }
    val base = vm.api.base()
    Column {
        SequencePlayer(
            items = items,
            uriFor = { runVideoUri(base, it.runId, vm.localVideo(it.runId)) },
            onOpenBlock = { vm.push(Screen.Block(roteiroId, it.blockId)) },
            modifier = Modifier.fillMaxWidth().height(600.dp),
        )
        val last = items.last().blockIndex + 1
        val stop = doc.blocks.getOrNull(items.last().blockIndex + 1)
        Muted(
            "Blocos ${items.first().blockIndex + 1}–$last · ${minutesLabel(items.sumOf { it.placeholderMs } / 1000.0)}" +
                (if (stop != null) " · para antes do bloco ${last + 1} (sem versão para assistir)" else ""),
            Modifier.padding(16.dp),
        )
    }
}
