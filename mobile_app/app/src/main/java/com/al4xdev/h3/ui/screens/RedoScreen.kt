package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.OpKind
import com.al4xdev.h3.data.RoteiroLogic
import com.al4xdev.h3.data.RunStates
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.components.BlockedReason
import com.al4xdev.h3.ui.components.BodyText
import com.al4xdev.h3.ui.components.ConfirmDialog
import com.al4xdev.h3.ui.components.DurationSeedFields
import com.al4xdev.h3.ui.components.ErrorCard
import com.al4xdev.h3.ui.components.technical
import com.al4xdev.h3.ui.components.Expandable
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PendingCard
import com.al4xdev.h3.ui.components.PrimaryButton
import com.al4xdev.h3.ui.components.SecondaryButton
import com.al4xdev.h3.ui.components.SectionTitle
import com.al4xdev.h3.ui.components.StateDot
import com.al4xdev.h3.ui.components.TextArea
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.components.VideoPlayer
import com.al4xdev.h3.ui.components.runVideoUri
import com.al4xdev.h3.ui.settingsAction

/**
 * "Refazer este bloco": the backend's anchored edit in `replace` mode. Bridge from the previous
 * accepted block's last frame to the next one's first frame → review → apply as a new version.
 */
@Composable
fun RedoScreen(vm: AppViewModel, roteiroId: String, blockId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    LaunchedEffect(roteiroId, blockId) { vm.ensureRedo(roteiroId, blockId) }
    val doc = vm.doc(roteiroId)
    val index = doc?.index(blockId) ?: -1
    TopBar(if (index >= 0) "Nova versão do bloco ${index + 1}" else "Nova versão", vm.settingsAction())
    if (doc == null) {
        val error = vm.docs[roteiroId]?.error
        if (error != null) Box(Modifier.padding(16.dp)) { ErrorCard("PC inacessível", technical(error)) { vm.loadRoteiro(roteiroId) } } else Loading()
        return
    }
    if (index < 0) { Muted("Este bloco não está mais no roteiro.", Modifier.padding(16.dp)); return }
    val block = doc.blocks[index]
    val previousRun = RoteiroLogic.acceptedRun(doc, doc.blocks.getOrNull(index - 1)?.id)
    val nextRun = RoteiroLogic.acceptedRun(doc, doc.blocks.getOrNull(index + 1)?.id)
    val remote = vm.edits["$roteiroId:$blockId"]
    val record = remote?.value
    val pending = vm.pendingFor(roteiroId).filter {
        it.kind == OpKind.EDIT || (it.kind == OpKind.DECISION && it.id == record?.runId)
    }
    val busy = vm.isBusy("redo:$blockId")
    val batchHere = vm.batchOn(roteiroId)
    var confirmDiscard by remember { mutableStateOf(false) }

    Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        AnchorRow(vm, doc, previousRun, nextRun)
        Spacer(Modifier.height(8.dp))
        Expandable("Prompts enviados nos vizinhos") {
            listOf(index - 1 to "Anterior", index + 1 to "Seguinte").forEach { (i, label) ->
                doc.blocks.getOrNull(i)?.let { b ->
                    RoteiroLogic.selectedAttempt(doc, b.id)?.let { a ->
                        SectionTitle("$label (bloco ${i + 1})")
                        BodyText(a.effectivePrompt)
                    }
                }
            }
        }
        if (pending.isNotEmpty()) PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
        BlockedReason(if (batchHere != null) "Lote em andamento neste roteiro." else null)

        when {
            record == null && remote?.loading == true -> Loading()
            record == null -> {
                if (previousRun == null || nextRun == null) {
                    BlockedReason(
                        if (previousRun == null) "Refazer exige o bloco anterior aceito; o primeiro bloco não tem essa âncora."
                        else "Refazer exige o bloco seguinte aceito. No último bloco, use “Inserir blocos no fim”.",
                    )
                    return@Column
                }
                var idea by rememberSaveable { mutableStateOf("") }
                var durationText by rememberSaveable { mutableStateOf(Durations.text(block.durationSeconds)) }
                var seedText by rememberSaveable { mutableStateOf(block.seed.toString()) }
                SectionTitle("O que deve mudar nesta versão?")
                TextArea(idea, { idea = it }, "Ideia")
                Spacer(Modifier.height(8.dp))
                DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
                Spacer(Modifier.height(12.dp))
                PrimaryButton("Propor com Grok", { vm.proposeRedo(roteiroId, blockId, idea, durationText, seedText) },
                    enabled = batchHere == null && pending.isEmpty(), busy = busy)
            }
            else -> EditProgress(vm, roteiroId, blockId, record, busy, batchHere == null && pending.isEmpty(), onDiscard = { confirmDiscard = true })
        }
        Spacer(Modifier.height(32.dp))
    }
    if (confirmDiscard) {
        ConfirmDialog("Descartar esta edição?", "O roteiro não muda. Um vídeo já gerado continua no PC.", "Descartar", danger = true,
            onConfirm = { vm.discardRedo(roteiroId, blockId) }, onDismiss = { confirmDiscard = false })
    }
}

@Composable
private fun EditProgress(vm: AppViewModel, roteiroId: String, blockId: String, record: com.al4xdev.h3.data.EditRecord,
                         busy: Boolean, enabled: Boolean, onDiscard: () -> Unit) {
    val run = record.run
    val stale = vm.doc(roteiroId)?.revision?.let { it != record.sourceRevision } == true
    Muted("Edição ${record.id.take(8)} · ${record.state}")
    if (stale && record.state in setOf("proposed", "generating")) BlockedReason("O roteiro mudou desde esta edição. Descarte-a e prepare outra.")
    record.error?.let { BlockedReason("Erro: $it") }
    when (record.state) {
        "proposed" -> {
            var prompt by rememberSaveable(record.id) { mutableStateOf(record.prompt.orEmpty()) }
            SectionTitle("Prompt proposto (editável)")
            TextArea(prompt, { prompt = it }, "Prompt")
            Spacer(Modifier.height(12.dp))
            PrimaryButton("Gerar nova versão", { vm.generateRedo(roteiroId, blockId, prompt) }, enabled = enabled && !stale, busy = busy)
        }
        // "uncertain" with a run means the generate answer was lost but the run exists: review it normally.
        "generating", "applied", "uncertain" -> if (run != null) {
            StateDot(RoteiroLogic.stateOf(run.state), RunStates.label(run.state))
            if (run.playable) {
                Spacer(Modifier.height(8.dp))
                VideoPlayer(runVideoUri(vm.api.base(), run.id, null), Modifier.height(420.dp))
            }
            Spacer(Modifier.height(10.dp))
            when (run.state) {
                RunStates.READY -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    val deciding = vm.isBusy("decide:${run.id}")
                    SecondaryButton("Recusar", { vm.decide(roteiroId, blockId, run.id, false) { vm.loadEdit(roteiroId, blockId, record.id) } },
                        Modifier.weight(1f), enabled = enabled, busy = deciding, danger = true)
                    PrimaryButton("Aceitar", { vm.decide(roteiroId, blockId, run.id, true) { vm.loadEdit(roteiroId, blockId, record.id) } },
                        Modifier.weight(1f), enabled = enabled, busy = deciding)
                }
                RunStates.ACCEPTED -> if (record.state != "applied") {
                    PrimaryButton("Usar esta versão no roteiro", { vm.applyRedo(roteiroId, blockId) }, enabled = enabled && !stale, busy = busy)
                }
                RunStates.REJECTED, RunStates.INTERRUPTED, RunStates.FAILED ->
                    PrimaryButton("Preparar outra tentativa (mesmo prompt)", { vm.retryRedo(roteiroId, blockId) }, enabled = enabled, busy = busy)
                else -> Muted("Gerando no PC. O app avisa quando terminar.")
            }
        } else {
            Muted(if (record.state == "uncertain") "Resposta incerta no PC." else "Aguardando o PC registrar a geração.")
            SecondaryButton("Reler esta edição", { vm.loadEdit(roteiroId, blockId, record.id) })
        }
        "failed" -> PrimaryButton("Preparar outra tentativa (mesmo prompt)", { vm.retryRedo(roteiroId, blockId) }, enabled = enabled, busy = busy)
        "improving" -> SecondaryButton("Reler esta edição", { vm.loadEdit(roteiroId, blockId, record.id) })
    }
    if (record.state != "applied") {
        Spacer(Modifier.height(10.dp))
        SecondaryButton("Descartar edição…", onDiscard, danger = true, enabled = !busy)
    }
}
