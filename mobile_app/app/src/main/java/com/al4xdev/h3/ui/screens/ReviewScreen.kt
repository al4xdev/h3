package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.OpKind
import com.al4xdev.h3.data.RoteiroLogic
import com.al4xdev.h3.data.RunStates
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.components.BlockedReason
import com.al4xdev.h3.ui.components.Expandable
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PendingCard
import com.al4xdev.h3.ui.components.StateDot
import com.al4xdev.h3.ui.components.VideoPlayer
import com.al4xdev.h3.ui.components.RunThumbnail
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.layout.ContentScale
import com.al4xdev.h3.ui.components.runVideoUri
import com.al4xdev.h3.ui.theme.H3Palette

/** T6: player fills the screen; state, collapsed prompt and Recusar/Aceitar below. */
@Composable
fun ReviewScreen(vm: AppViewModel, roteiroId: String, blockId: String, runId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    val doc = vm.doc(roteiroId) ?: return Loading()
    val attempt = doc.attempts.firstOrNull { it.runId == runId }
    val run = attempt?.run
    val index = doc.index(blockId)
    val pending = vm.pendingFor(roteiroId).filter { it.kind == OpKind.DECISION && it.id == runId }

    Column(Modifier.statusBarsPadding().verticalScroll(rememberScrollState())) {
        if (run != null && run.playable) {
            val local = remember(run.id) { vm.localVideo(run.id) }
            VideoPlayer(runVideoUri(vm.api.base(), run.id, local), Modifier.fillMaxWidth().height(560.dp)) {
                RunThumbnail(run.id, vm.api.url(run.videoPath), local, Modifier.fillMaxSize(), ContentScale.Fit)
            }
        } else {
            Muted("Nenhum vídeo publicado para esta tentativa.", Modifier.padding(16.dp))
        }
        Column(Modifier.padding(16.dp)) {
            if (attempt == null) {
                Muted("Esta tentativa não está mais no roteiro.")
                return@Column
            }
            StateDot(RoteiroLogic.stateOf(attempt), "Bloco ${index + 1} · ${RunStates.label(attempt.state)} · ${effectiveLabel(attempt.snapshot.durationSeconds)}")
            Expandable("Prompt enviado") {
                SelectionContainer { Text(attempt.effectivePrompt, color = H3Palette.TextPrimary, fontSize = 14.sp) }
            }
            Spacer(Modifier.height(8.dp))
            if (pending.isNotEmpty()) {
                PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
            } else if (attempt.state == RunStates.READY) {
                val fence = if (vm.batchOn(roteiroId) != null) "Lote em andamento neste roteiro: decisões bloqueadas." else null
                BlockedReason(fence)
                ReviewActions(vm, roteiroId, blockId, attempt, enabled = fence == null)
            }
        }
    }
}
