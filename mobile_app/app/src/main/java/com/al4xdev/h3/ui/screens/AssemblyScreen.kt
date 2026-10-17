package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.OpKind
import com.al4xdev.h3.data.RoteiroLogic
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.components.BlockedReason
import com.al4xdev.h3.ui.components.ErrorCard
import com.al4xdev.h3.ui.components.technical
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PendingCard
import com.al4xdev.h3.ui.components.PrimaryButton
import com.al4xdev.h3.ui.components.SecondaryButton
import com.al4xdev.h3.ui.components.SectionTitle
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.components.VideoPlayer
import com.al4xdev.h3.ui.settingsAction
import com.al4xdev.h3.ui.theme.H3Palette

/** T8: editorial assembly of the selected versions; "Montar de novo" only after the selection changed. */
@Composable
fun AssemblyScreen(vm: AppViewModel, roteiroId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId); vm.loadAssemblies() }
    val doc = vm.doc(roteiroId)
    TopBar("Montagem", vm.settingsAction())
    if (doc == null) { Loading(); return }
    val runs = RoteiroLogic.selectedAcceptedRuns(doc)
    val list = vm.assemblies.value.orEmpty().filter { it.roteiroId == roteiroId }.sortedByDescending { it.createdAt.orEmpty() }
    val current = list.firstOrNull { it.completed && it.inputIds == runs }
    var shownId by rememberSaveable { mutableStateOf<String?>(null) }
    val shown = list.firstOrNull { it.id == shownId } ?: current ?: list.firstOrNull { it.completed }
    val pending = vm.pendingFor(roteiroId).filter { it.kind == OpKind.ASSEMBLY }
    val assembling = vm.isBusy("assemble:$roteiroId")

    Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        if (vm.assemblies.error != null && vm.assemblies.value == null) {
            ErrorCard("PC inacessível", technical(vm.assemblies.error)) { vm.loadAssemblies() }
        }
        if (shown != null && shown.completed) {
            VideoPlayer(vm.api.url("/assemblies/${shown.id}/video"), Modifier.height(460.dp))
            Spacer(Modifier.height(6.dp))
            Muted("${shown.frames ?: "?"} frames · ${shown.fps ?: 24} fps · ID ${shown.id.take(8)}" +
                if (shown.inputIds == runs) " · seleção atual" else " · seleção anterior")
            Spacer(Modifier.height(8.dp))
            SecondaryButton("Baixar no celular", { vm.downloadAssembly(shown, roteiroId) })
        } else if (vm.assemblies.loading) Loading() else Muted("Nenhuma montagem pronta deste roteiro.")

        Spacer(Modifier.height(12.dp))
        if (pending.isNotEmpty()) PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
        val reason = when {
            runs == null -> "Todos os blocos precisam de uma versão aceita para montar."
            vm.batchOn(roteiroId) != null -> "Lote em andamento neste roteiro."
            pending.isNotEmpty() -> "Consulte a montagem sem resposta antes."
            else -> null
        }
        if (current == null) {
            BlockedReason(reason)
            PrimaryButton(if (list.isEmpty()) "Montar vídeo" else "Montar de novo (seleção mudou)", { vm.assemble(roteiroId) },
                enabled = reason == null, busy = assembling)
            if (assembling) Muted("Montando no PC (FFmpeg). Com muitos blocos leva alguns minutos.")
        }

        if (list.isNotEmpty()) {
            SectionTitle("Montagens deste roteiro")
            list.forEach { a ->
                Text(
                    "${if (a.id == shown?.id) "▶ " else ""}${a.id.take(8)} · ${a.state} · ${a.frames ?: "?"} frames · ${a.createdAt.orEmpty().take(16)}",
                    color = if (a.id == shown?.id) H3Palette.TealPrimary else H3Palette.TextPrimary, fontSize = 14.sp,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 44.dp).clickable(enabled = a.completed) { shownId = a.id }.padding(vertical = 12.dp),
                )
            }
        }
        Spacer(Modifier.height(32.dp))
    }
}
