package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.material3.OutlinedButton
import com.al4xdev.h3.ui.components.FastScroller
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.BlockState
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.MAX_BLOCKS
import com.al4xdev.h3.data.NextAction
import com.al4xdev.h3.data.OpKind
import com.al4xdev.h3.data.Roteiro
import com.al4xdev.h3.data.RoteiroLogic
import com.al4xdev.h3.data.Sequence
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.TextButton
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.Screen
import com.al4xdev.h3.ui.components.BlockTile
import com.al4xdev.h3.ui.components.BlockedReason
import com.al4xdev.h3.ui.components.BodyText
import com.al4xdev.h3.ui.components.Card
import com.al4xdev.h3.ui.components.ConfirmDialog
import com.al4xdev.h3.ui.components.CountSlider
import com.al4xdev.h3.ui.components.DurationSeedFields
import com.al4xdev.h3.ui.components.ErrorCard
import com.al4xdev.h3.ui.components.technical
import com.al4xdev.h3.ui.components.Expandable
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PendingCard
import com.al4xdev.h3.ui.components.PlanningWait
import com.al4xdev.h3.ui.components.PrimaryButton
import com.al4xdev.h3.ui.components.SceneTimeline
import com.al4xdev.h3.ui.components.SecondaryButton
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.components.VisionCard
import com.al4xdev.h3.ui.settingsAction
import com.al4xdev.h3.ui.theme.H3Palette

@Composable
fun RoteiroScreen(vm: AppViewModel, roteiroId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    val remote = vm.docs[roteiroId]
    val doc = remote?.value
    TopBar(doc?.title ?: "Roteiro", vm.settingsAction())
    when {
        doc == null && remote?.error != null -> Column(Modifier.padding(16.dp)) {
            ErrorCard("PC inacessível", technical(remote.error)) { vm.loadRoteiro(roteiroId) }
        }
        doc == null -> Loading()
        !doc.adopted -> ProposalGrid(vm, doc)
        else -> PlanGrid(vm, doc)
    }
}

private fun LazyGridScope.full(key: String, content: @Composable () -> Unit) =
    item(key = key, span = { GridItemSpan(maxLineSpan) }) { content() }

@Composable
private fun TileGrid(state: LazyGridState = rememberLazyGridState(), content: LazyGridScope.() -> Unit) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(4),
        state = state,
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 32.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        content = content,
    )
}

/** State A: plan proposed (or written by hand) and kept on the phone; nothing generated. */
@Composable
private fun ProposalGrid(vm: AppViewModel, doc: Roteiro) {
    val candidate = vm.candidate(doc.id)
    var confirmDiscard by remember { mutableStateOf(false) }
    var count by rememberSaveable { mutableIntStateOf(candidate?.blocks?.size ?: 3) }
    var durationText by rememberSaveable { mutableStateOf(candidate?.blocks?.firstOrNull()?.durationSeconds?.let(Durations::text) ?: Durations.DEFAULT_TEXT) }
    var seedText by rememberSaveable { mutableStateOf((candidate?.blocks?.firstOrNull()?.seed ?: Durations.DEFAULT_SEED).toString()) }
    val proposing = vm.isBusy("propose:${doc.id}")

    TileGrid {
        full("idea") { Expandable("Ideia original") { BodyText(doc.idea) } }
        if (candidate == null) {
            full("none") {
                Card {
                    Muted("Nenhuma proposta guardada neste aparelho. Peça ao Grok ou escreva à mão.")
                    Spacer(Modifier.height(8.dp))
                    CountSlider("Blocos", count, 1..MAX_BLOCKS, { count = it })
                    DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
                    filmLength(count, durationText)?.let { Muted(it) }
                    Spacer(Modifier.height(10.dp))
                    PrimaryButton("Propor com Grok", { vm.reproposal(doc.id, count, durationText, seedText) }, busy = proposing)
                    PlanningWait(proposing)
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Escrever blocos à mão", { vm.manualCandidate(doc.id, count, durationText, seedText) }, enabled = !proposing)
                }
            }
            return@TileGrid
        }
        full("head") {
            Column {
                Text(if (candidate.fromGrok) "Proposta do Grok · nada gerado" else "Rascunho manual · nada gerado",
                    color = H3Palette.TealPrimary, fontWeight = FontWeight.SemiBold)
                val total = candidate.blocks.sumOf { Durations.effectiveSeconds(Durations.frames(it.durationSeconds)) }
                Muted("${candidate.blocks.size} blocos · ${com.al4xdev.h3.ui.components.minutesLabel(total)}")
                if (candidate.stale) BlockedReason("O roteiro mudou no PC depois desta proposta.")
            }
        }
        full("vision") { VisionCard(candidate.vision) }
        full("scenes") { SceneTimeline(candidate.scenes) }
        items(candidate.blocks.size, key = { candidate.blocks[it].id }) { i ->
            val block = candidate.blocks[i]
            BlockTile(i + 1, BlockState.PLANNED, null, { "" }, { null }, block.action, false,
                onClick = { vm.push(Screen.Block(doc.id, block.id)) }, onCut = {})
        }
        full("hint") { Muted("Toque num bloco para ler ou editar.") }
        full("actions") {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                PrimaryButton("Usar este roteiro", { vm.adoptCandidate(doc.id) }, busy = vm.isBusy("adopt:${doc.id}"), enabled = !proposing)
                Expandable("Propor outra versão") {
                    CountSlider("Blocos", count, 1..MAX_BLOCKS, { count = it })
                    DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Propor outra versão", { vm.reproposal(doc.id, count, durationText, seedText) }, busy = proposing)
                    PlanningWait(proposing)
                }
                SecondaryButton("Descartar proposta", { confirmDiscard = true }, danger = true, enabled = !proposing)
            }
        }
    }
    if (confirmDiscard) {
        ConfirmDialog("Descartar a proposta?", "Os blocos propostos saem deste aparelho. O roteiro continua no PC sem blocos.",
            "Descartar", danger = true, onConfirm = { vm.saveCandidate(doc.id, null) }, onDismiss = { confirmDiscard = false })
    }
}

/** State B: adopted plan, grid of blocks with real states, cuts and the next real action. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PlanGrid(vm: AppViewModel, doc: Roteiro) {
    val states = remember(doc) { RoteiroLogic.states(doc) }
    val cuts = remember(doc) { RoteiroLogic.cuts(doc) }
    val thumbs = remember(doc) {
        doc.blocks.map { b -> RoteiroLogic.currentAttempt(doc, b.id)?.run?.takeIf { it.playable }?.id }
    }
    val pendingCount = remember(doc) { RoteiroLogic.neverSent(doc).size }
    val batchHere = vm.batchOn(doc.id)
    val pending = vm.pendingFor(doc.id)
    val next = vm.nextAction(doc)
    var confirmBatch by remember { mutableStateOf(false) }
    var confirmStop by remember { mutableStateOf(false) }
    var cutAt by remember { mutableStateOf<Int?>(null) }
    var menuAt by remember { mutableStateOf<Int?>(null) }
    val firstPlayable = remember(doc) { Sequence.firstPlayable(doc) }
    val fence = when {
        batchHere != null -> "Lote em andamento neste roteiro: geração, decisões e edições ficam bloqueadas."
        pending.isNotEmpty() -> "Há pedido sem resposta confirmada; consulte-o antes de gerar."
        else -> null
    }
    val base = vm.api.base()

    val gridState = rememberLazyGridState()
    // Header items precede the tiles; the fast scroller maps block index → grid item with this offset.
    val headerKeys = listOfNotNull("summary", "actions", "batch".takeIf { batchHere != null },
        "pending".takeIf { pending.isNotEmpty() }, "cuts".takeIf { cuts.isNotEmpty() })

    Box(Modifier.fillMaxSize()) {
        TileGrid(gridState) {
            full("summary") {
                Column {
                    val accepted = states.count { it == BlockState.ACCEPTED }
                    val review = states.count { it == BlockState.REVIEW }
                    Text("${doc.blocks.size} blocos · $accepted aceitos" + if (review > 0) " · $review revisar" else "",
                        color = H3Palette.TextPrimary, fontWeight = FontWeight.SemiBold)
                    if (doc.removedBlockCount > 0) Muted("${doc.removedBlockCount} fora da sequência (preservados no PC)")
                    if (!vm.live) Muted("Sem atualização ao vivo do PC no momento.")
                }
            }
            // Actions live above the grid: with hundreds of blocks the end of the list is far away.
            full("actions") {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    BlockedReason(fence)
                    NextActionButton(vm, doc, next, fenced = fence != null, onBatch = { confirmBatch = true })
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (firstPlayable != null) {
                            CompactButton("▶ Assistir") { vm.push(Screen.Watch(doc.id, doc.blocks[firstPlayable].id)) }
                        }
                        if (pendingCount > 0 && next !is NextAction.GeneratePending) {
                            CompactButton("Gerar pendentes ($pendingCount)", enabled = fence == null && !vm.isBusy("batch:${doc.id}")) { confirmBatch = true }
                        }
                        CompactButton("+ No fim", enabled = batchHere == null && doc.blocks.size < MAX_BLOCKS) {
                            vm.push(Screen.Insert(doc.id, doc.blocks.lastOrNull()?.id))
                        }
                        if (next !is NextAction.Assemble) CompactButton("Montagem") { vm.push(Screen.Assembly(doc.id)) }
                        CompactButton(if (vm.docs[doc.id]?.loading == true) "Relendo…" else "Reler") { vm.loadRoteiro(doc.id) }
                    }
                }
            }
            if (batchHere != null) full("batch") {
                Card(border = H3Palette.TealSecondary) {
                    Text("⏵ Lote no PC", color = H3Palette.TealPrimary, fontWeight = FontWeight.SemiBold)
                    Muted(batchHere.describe())
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Parar…", { confirmStop = true }, danger = true, busy = vm.isBusy("stopbatch:${batchHere.id}"),
                        enabled = !batchHere.stopRequested)
                }
            }
            if (pending.isNotEmpty()) full("pending") {
                PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
            }
            if (cuts.isNotEmpty()) full("cuts") {
                Expandable("⚡ ${cuts.size} ${if (cuts.size == 1) "corte" else "cortes"} de continuidade") {
                    cuts.sorted().take(50).forEach { i ->
                        Text("⚡ entre ${i + 1} e ${i + 2} · toque para inserir blocos", color = H3Palette.Cut, fontSize = 14.sp,
                            modifier = Modifier.fillMaxWidth().clickable { cutAt = i }.padding(vertical = 12.dp))
                    }
                    if (cuts.size > 50) Muted("… e mais ${cuts.size - 50}")
                }
            }
            items(doc.blocks.size, key = { doc.blocks[it].id }) { i ->
                val block = doc.blocks[i]
                BlockTile(
                    number = i + 1, state = states[i], thumbRunId = thumbs[i],
                    videoUrl = { "$base/runs/$it/video" }, localFile = vm::localVideo,
                    caption = if (states[i] == BlockState.PLANNED) block.action else null,
                    cutBefore = (i - 1) in cuts,
                    onClick = { vm.push(Screen.Block(doc.id, block.id)) },
                    onCut = { cutAt = i - 1 },
                    onLongClick = { menuAt = i },
                )
            }
        }
        if (doc.blocks.size > 40) {
            FastScroller(gridState, headerKeys.size, doc.blocks.size) { i ->
                "Bloco ${i + 1} · " + doc.blocks[i].action.substringBefore(" — ").take(40)
            }
        }
    }

    if (confirmBatch) {
        ConfirmDialog(
            "Gerar $pendingCount blocos pendentes?",
            "O Grok melhora o prompt de cada bloco antes de gerar (custo do Grok por bloco). Os intermediários são aceitos " +
                "tecnicamente para continuar; o último fica para sua revisão. Blocos inseridos no meio ligam no bloco seguinte.",
            "Gerar", onConfirm = { vm.startBatch(doc.id) }, onDismiss = { confirmBatch = false },
        )
    }
    if (confirmStop && batchHere != null) {
        ConfirmDialog("Parar o lote?", "O bloco em geração é interrompido e o lote não continua.", "Confirmar parada", danger = true,
            onConfirm = { vm.stopBatch(batchHere) }, onDismiss = { confirmStop = false })
    }
    menuAt?.let { i ->
        val canWatch = remember(doc, i) { Sequence.playable(doc, i).isNotEmpty() }
        AlertDialog(
            onDismissRequest = { menuAt = null },
            title = { Text("Bloco ${i + 1}") },
            text = {
                Column {
                    TextButton(onClick = { menuAt = null; vm.push(Screen.Block(doc.id, doc.blocks[i].id)) }) { Text("Abrir bloco") }
                    if (canWatch) TextButton(onClick = { menuAt = null; vm.push(Screen.Watch(doc.id, doc.blocks[i].id)) }) { Text("▶ Assistir daqui") }
                    else Muted("Sem versão aceita ou pronta para assistir a partir daqui.")
                }
            },
            confirmButton = { TextButton(onClick = { menuAt = null }) { Text("Fechar") } },
            containerColor = H3Palette.SurfaceElevated,
        )
    }
    cutAt?.let { i ->
        ConfirmDialog(
            "Corte entre ${i + 1} e ${i + 2}",
            "Esses vídeos não são pai e filho. Você pode inserir blocos aqui; “Gerar pendentes” liga o último deles ao bloco ${i + 2}.",
            "Inserir blocos aqui", onConfirm = { vm.push(Screen.Insert(doc.id, doc.blocks[i].id)) }, onDismiss = { cutAt = null },
        )
    }
}

@Composable
private fun CompactButton(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, enabled = enabled, modifier = Modifier.heightIn(min = 44.dp),
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 6.dp)) { Text(text, fontSize = 14.sp) }
}

@Composable
private fun NextActionButton(vm: AppViewModel, doc: Roteiro, next: NextAction, fenced: Boolean, onBatch: () -> Unit) {
    fun open(i: Int) = vm.push(Screen.Block(doc.id, doc.blocks[i].id))
    when (next) {
        is NextAction.Review -> {
            val block = doc.blocks[next.index]
            val run = RoteiroLogic.currentAttempt(doc, block.id)?.runId
            PrimaryButton("Revisar bloco ${next.index + 1}", {
                if (run != null) vm.push(Screen.Review(doc.id, block.id, run)) else open(next.index)
            })
        }
        is NextAction.Consult -> {
            val op = vm.pendingFor(doc.id).firstOrNull { it.kind == OpKind.ATTEMPT && it.blockId == doc.blocks[next.index].id }
            PrimaryButton("Consultar envio do bloco ${next.index + 1}", { if (op != null) vm.consult(op) else open(next.index) },
                busy = op != null && vm.isBusy("consult:${op.id}"))
        }
        is NextAction.Generating -> PrimaryButton("Bloco ${next.index + 1} gerando · abrir", { open(next.index) })
        is NextAction.Resolve -> PrimaryButton("Resolver bloco ${next.index + 1}", { open(next.index) })
        is NextAction.GeneratePending -> PrimaryButton("Gerar pendentes (${next.count})", onBatch, enabled = !fenced,
            busy = vm.isBusy("batch:${doc.id}"))
        NextAction.Assemble -> PrimaryButton("Montar vídeo", { vm.push(Screen.Assembly(doc.id)) })
        NextAction.Adopt, NextAction.Empty -> Unit
    }
}
