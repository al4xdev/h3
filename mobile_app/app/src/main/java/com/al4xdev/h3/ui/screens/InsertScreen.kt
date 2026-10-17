package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.Block
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.MAX_BLOCKS
import com.al4xdev.h3.data.OpKind
import com.al4xdev.h3.data.Roteiro
import com.al4xdev.h3.data.RoteiroLogic
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.components.BlockedReason
import com.al4xdev.h3.ui.components.Card
import com.al4xdev.h3.ui.components.appearOnce
import com.al4xdev.h3.ui.components.ConfirmDialog
import com.al4xdev.h3.ui.components.CountSlider
import com.al4xdev.h3.ui.components.DurationSeedFields
import com.al4xdev.h3.ui.components.ErrorCard
import com.al4xdev.h3.ui.components.technical
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PlanningWait
import com.al4xdev.h3.ui.components.PendingCard
import com.al4xdev.h3.ui.components.PrimaryButton
import com.al4xdev.h3.ui.components.RemoteImage
import com.al4xdev.h3.ui.components.SceneTimeline
import com.al4xdev.h3.ui.components.SecondaryButton
import com.al4xdev.h3.ui.components.SectionTitle
import com.al4xdev.h3.ui.components.TextArea
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.components.VisionCard
import com.al4xdev.h3.ui.settingsAction
import com.al4xdev.h3.ui.theme.H3Palette

/** Identity + last frame of the block before + first frame of the block after (when they exist). */
@Composable
fun AnchorRow(vm: AppViewModel, doc: Roteiro, previousRun: String?, nextRun: String?) {
    val identity = doc.reference?.imagePath()?.let { vm.api.url(it) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf(
            Triple(identity, "identidade", true),
            Triple(previousRun?.let { vm.api.url("/roteiro-edits/anchors/$it/last") }, "fim do anterior", previousRun != null),
            Triple(nextRun?.let { vm.api.url("/roteiro-edits/anchors/$it/first") }, "início do seguinte", nextRun != null),
        ).filter { it.third }.forEach { (url, label, _) ->
            Column(Modifier.weight(1f)) {
                RemoteImage(url, 360, Modifier.aspectRatio(0.5625f), ContentScale.Fit, label)
                Text(label, color = H3Palette.TextSecondary, fontSize = 11.sp)
            }
        }
    }
}

/** T4/T7: insert N planned blocks after a block (or before the first); at the end this is Tail. */
@Composable
fun InsertScreen(vm: AppViewModel, roteiroId: String, afterBlockId: String?) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    LaunchedEffect(roteiroId, afterBlockId) { vm.ensureSegment(roteiroId, afterBlockId) }
    val remote = vm.docs[roteiroId]
    val doc = remote?.value
    if (doc == null) {
        TopBar("Inserir blocos", vm.settingsAction())
        if (remote?.error != null) Box(Modifier.padding(16.dp)) { ErrorCard("PC inacessível", technical(remote.error)) { vm.loadRoteiro(roteiroId) } }
        else Loading()
        return
    }
    val afterIndex = afterBlockId?.let { doc.index(it) } ?: -1
    if (afterBlockId != null && afterIndex < 0) {
        TopBar("Inserir blocos", vm.settingsAction())
        Muted("O bloco de referência não está mais no roteiro.", Modifier.padding(16.dp))
        return
    }
    val atEnd = afterIndex == doc.blocks.size - 1
    val title = when {
        afterBlockId == null -> "Antes do bloco 1"
        atEnd -> "Continuar no fim"
        else -> "Entre ${afterIndex + 1} e ${afterIndex + 2}"
    }
    val d = vm.insertDraft(roteiroId, afterBlockId)
    val pending = vm.pendingFor(roteiroId).filter { it.kind == OpKind.SEGMENT }
    val planning = vm.isBusy("segment:$roteiroId")
    val segment = d.segmentId?.let { vm.segments[it] }
    val batchHere = vm.batchOn(roteiroId)
    val room = MAX_BLOCKS - doc.blocks.size
    var confirmDiscard by remember { mutableStateOf(false) }
    var editing by rememberSaveable { mutableStateOf<String?>(null) }
    fun update(transform: (com.al4xdev.h3.data.InsertDraft) -> com.al4xdev.h3.data.InsertDraft) =
        vm.updateInsert(roteiroId, afterBlockId, transform(vm.insertDraft(roteiroId, afterBlockId)))

    TopBar(title, vm.settingsAction())
    LazyColumn(
        state = rememberLazyListState(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item("anchors") {
            AnchorRow(vm, doc, RoteiroLogic.acceptedRun(doc, afterBlockId), RoteiroLogic.acceptedRun(doc, doc.blocks.getOrNull(afterIndex + 1)?.id))
        }
        if (pending.isNotEmpty()) item("pending") {
            PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
        }
        if (d.blocks.isEmpty()) {
            item("form") {
                Column {
                    SectionTitle("O que acontece nesses blocos?")
                    TextArea(d.idea, { v -> update { it.copy(idea = v) } }, "Ideia")
                    Spacer(Modifier.height(8.dp))
                    if (room > 0) CountSlider("Blocos a inserir", d.count.coerceAtMost(room), 1..room, { v -> update { it.copy(count = v) } })
                    else BlockedReason("O roteiro já tem $MAX_BLOCKS blocos.")
                    DurationSeedFields(d.durationText, { v -> update { it.copy(durationText = v) } }, d.seedText, { v -> update { it.copy(seedText = v) } })
                    filmLength(d.count, d.durationText)?.let { Muted(it) }
                    Spacer(Modifier.height(12.dp))
                    val reason = when {
                        batchHere != null -> "Lote em andamento neste roteiro."
                        pending.isNotEmpty() -> "Consulte o planejamento sem resposta antes."
                        room <= 0 -> "Sem espaço para novos blocos."
                        else -> null
                    }
                    BlockedReason(reason)
                    PrimaryButton("Planejar com Grok", { vm.planSegment(roteiroId, afterBlockId) }, enabled = reason == null, busy = planning)
                    PlanningWait(planning)
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Escrever à mão", { vm.manualInsert(roteiroId, afterBlockId) }, enabled = reason == null && !planning)
                    segment?.takeIf { it.state == "invalid" }?.let {
                        Spacer(Modifier.height(8.dp))
                        BlockedReason("Último planejamento inválido: ${it.error ?: it.detail ?: "resposta fora do formato"}. Nada foi inserido.")
                    }
                }
            }
        } else {
            item("head") {
                Column {
                    Text("${d.blocks.size} blocos para inserir · nada gerado", color = H3Palette.TealPrimary, fontWeight = FontWeight.SemiBold)
                    if (segment?.stale == true) BlockedReason("O roteiro mudou no PC depois deste planejamento; confira antes de inserir.")
                    Muted("Toque num bloco para editar. Depois de inserir, use “Gerar pendentes” no roteiro.")
                }
            }
            item("vision") { VisionCard(d.vision) }
            item("scenes") { SceneTimeline(d.scenes) }
            itemsIndexed(d.blocks, key = { _, b -> b.id }) { i, block ->
                ProposedBlockCard(
                    number = afterIndex + 2 + i, block = block, editing = editing == block.id,
                    onEdit = { editing = if (editing == block.id) null else block.id },
                    onSave = { updated -> update { it.copy(blocks = it.blocks.map { b -> if (b.id == updated.id) updated else b }) }; editing = null },
                    onDelete = { update { it.copy(blocks = it.blocks.filter { b -> b.id != block.id }) } },
                )
            }
            item("actions") {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    BlockedReason(if (batchHere != null) "Lote em andamento neste roteiro." else null)
                    PrimaryButton("Inserir no roteiro", { vm.applyInsert(roteiroId, afterBlockId) }, enabled = batchHere == null,
                        busy = vm.isBusy("insert:$roteiroId"))
                    SecondaryButton("Descartar", { confirmDiscard = true }, danger = true)
                }
            }
        }
    }
    if (confirmDiscard) {
        ConfirmDialog("Descartar estes blocos?", "Nada foi inserido no roteiro; o planejamento sai deste aparelho.", "Descartar", danger = true,
            onConfirm = { vm.discardInsert(roteiroId, afterBlockId) }, onDismiss = { confirmDiscard = false })
    }
}

@Composable
private fun ProposedBlockCard(number: Int, block: Block, editing: Boolean, onEdit: () -> Unit, onSave: (Block) -> Unit, onDelete: () -> Unit) {
    Card(Modifier.appearOnce()) {
        Row {
            Text("$number", color = H3Palette.TealPrimary, fontWeight = FontWeight.Bold, modifier = Modifier.padding(end = 10.dp))
            Column(Modifier.weight(1f)) {
                Text(block.action, color = H3Palette.TextPrimary, fontSize = 14.sp)
                Muted("${effectiveLabel(block.durationSeconds)} · seed ${block.seed}")
            }
        }
        if (!editing) {
            Row {
                TextButton(onClick = onEdit) { Text("Editar") }
                TextButton(onClick = onDelete) { Text("Remover", color = H3Palette.StateError) }
            }
            return@Card
        }
        var action by rememberSaveable(block.id) { mutableStateOf(block.action) }
        var prompt by rememberSaveable(block.id) { mutableStateOf(block.prompt) }
        var durationText by rememberSaveable(block.id) { mutableStateOf(Durations.text(block.durationSeconds)) }
        var seedText by rememberSaveable(block.id) { mutableStateOf(block.seed.toString()) }
        Spacer(Modifier.height(8.dp))
        TextArea(action, { action = it }, "Ação", minLines = 2)
        TextArea(prompt, { prompt = it }, "Prompt base", minLines = 3)
        DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
        val duration = Durations.parse(durationText)?.toDouble()
        val seed = Durations.parseSeed(seedText)
        Row {
            TextButton(onClick = onEdit) { Text("Cancelar") }
            TextButton(
                onClick = { onSave(block.copy(action = action, prompt = prompt, durationSeconds = duration!!, seed = seed!!)) },
                enabled = duration != null && seed != null && action.isNotBlank() && prompt.isNotBlank(),
            ) { Text("Salvar") }
        }
    }
}
