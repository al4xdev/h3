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
    TopBar(doc?.title ?: "Script", vm.settingsAction())
    when {
        doc == null && remote?.error != null -> Column(Modifier.padding(16.dp)) {
            ErrorCard("PC unreachable", technical(remote.error)) { vm.loadRoteiro(roteiroId) }
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
        full("idea") { Expandable("Original idea") { BodyText(doc.idea) } }
        if (candidate == null) {
            full("none") {
                Card {
                    Muted("No proposal saved on this device. Ask Grok or write manually.")
                    Spacer(Modifier.height(8.dp))
                    CountSlider("Blocks", count, 1..MAX_BLOCKS, { count = it })
                    DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
                    filmLength(count, durationText)?.let { Muted(it) }
                    Spacer(Modifier.height(10.dp))
                    PrimaryButton("Propose with Grok", { vm.reproposal(doc.id, count, durationText, seedText) }, busy = proposing)
                    PlanningWait(proposing)
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Write blocks manually", { vm.manualCandidate(doc.id, count, durationText, seedText) }, enabled = !proposing)
                }
            }
            return@TileGrid
        }
        full("head") {
            Column {
                Text(if (candidate.fromGrok) "Grok proposal · nothing generated" else "Manual draft · nothing generated",
                    color = H3Palette.TealPrimary, fontWeight = FontWeight.SemiBold)
                val total = candidate.blocks.sumOf { Durations.effectiveSeconds(Durations.frames(it.durationSeconds)) }
                Muted("${candidate.blocks.size} blocks · ${com.al4xdev.h3.ui.components.minutesLabel(total)}")
                if (candidate.stale) BlockedReason("The script changed on PC after this proposal.")
            }
        }
        full("vision") { VisionCard(candidate.vision) }
        full("scenes") { SceneTimeline(candidate.scenes) }
        items(candidate.blocks.size, key = { candidate.blocks[it].id }) { i ->
            val block = candidate.blocks[i]
            BlockTile(i + 1, BlockState.PLANNED, null, { "" }, { null }, block.action, false,
                onClick = { vm.push(Screen.Block(doc.id, block.id)) }, onCut = {})
        }
        full("hint") { Muted("Tap a block to view or edit.") }
        full("actions") {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                PrimaryButton("Use this script", { vm.adoptCandidate(doc.id) }, busy = vm.isBusy("adopt:${doc.id}"), enabled = !proposing)
                Expandable("Propose another version") {
                    CountSlider("Blocks", count, 1..MAX_BLOCKS, { count = it })
                    DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Propose another version", { vm.reproposal(doc.id, count, durationText, seedText) }, busy = proposing)
                    PlanningWait(proposing)
                }
                SecondaryButton("Discard proposal", { confirmDiscard = true }, danger = true, enabled = !proposing)
            }
        }
    }
    if (confirmDiscard) {
        ConfirmDialog("Discard proposal?", "Proposed blocks will be removed from this device. The script remains on PC without blocks.",
            "Discard", danger = true, onConfirm = { vm.saveCandidate(doc.id, null) }, onDismiss = { confirmDiscard = false })
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
        batchHere != null -> "Batch in progress for this script: generation, decisions, and edits are blocked."
        pending.isNotEmpty() -> "Pending request without confirmed response; check it before generating."
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
                    Text("${doc.blocks.size} blocks · $accepted accepted" + if (review > 0) " · $review to review" else "",
                        color = H3Palette.TextPrimary, fontWeight = FontWeight.SemiBold)
                    if (doc.removedBlockCount > 0) Muted("${doc.removedBlockCount} out of sequence (preserved on PC)")
                    if (!vm.live) Muted("No live updates from PC right now.")
                }
            }
            // Actions live above the grid: with hundreds of blocks the end of the list is far away.
            full("actions") {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    BlockedReason(fence)
                    NextActionButton(vm, doc, next, fenced = fence != null, onBatch = { confirmBatch = true })
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (firstPlayable != null) {
                            CompactButton("▶ Watch") { vm.push(Screen.Watch(doc.id, doc.blocks[firstPlayable].id)) }
                        }
                        if (pendingCount > 0 && next !is NextAction.GeneratePending) {
                            CompactButton("Generate pending ($pendingCount)", enabled = fence == null && !vm.isBusy("batch:${doc.id}")) { confirmBatch = true }
                        }
                        CompactButton("+ At end", enabled = batchHere == null && doc.blocks.size < MAX_BLOCKS) {
                            vm.push(Screen.Insert(doc.id, doc.blocks.lastOrNull()?.id))
                        }
                        if (next !is NextAction.Assemble) CompactButton("Assembly") { vm.push(Screen.Assembly(doc.id)) }
                        CompactButton(if (vm.docs[doc.id]?.loading == true) "Reloading…" else "Reload") { vm.loadRoteiro(doc.id) }
                    }
                }
            }
            if (batchHere != null) full("batch") {
                Card(border = H3Palette.TealSecondary) {
                    Text("⏵ Batch on PC", color = H3Palette.TealPrimary, fontWeight = FontWeight.SemiBold)
                    Muted(batchHere.describe())
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Stop…", { confirmStop = true }, danger = true, busy = vm.isBusy("stopbatch:${batchHere.id}"),
                        enabled = !batchHere.stopRequested)
                }
            }
            if (pending.isNotEmpty()) full("pending") {
                PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
            }
            if (cuts.isNotEmpty()) full("cuts") {
                Expandable("⚡ ${cuts.size} continuity ${if (cuts.size == 1) "cut" else "cuts"}") {
                    cuts.sorted().take(50).forEach { i ->
                        Text("⚡ between ${i + 1} and ${i + 2} · tap to insert blocks", color = H3Palette.Cut, fontSize = 14.sp,
                            modifier = Modifier.fillMaxWidth().clickable { cutAt = i }.padding(vertical = 12.dp))
                    }
                    if (cuts.size > 50) Muted("… and ${cuts.size - 50} more")
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
                "Block ${i + 1} · " + doc.blocks[i].action.substringBefore(" — ").take(40)
            }
        }
    }

    if (confirmBatch) {
        ConfirmDialog(
            "Generate $pendingCount pending blocks?",
            "Grok refines each block's prompt before generating (Grok cost per block). Intermediates are technically accepted " +
                "to continue; the last one awaits your review. Blocks inserted in-between connect to the next block.",
            "Generate", onConfirm = { vm.startBatch(doc.id) }, onDismiss = { confirmBatch = false },
        )
    }
    if (confirmStop && batchHere != null) {
        ConfirmDialog("Stop batch?", "The generating block will be interrupted and the batch will stop.", "Confirm stop", danger = true,
            onConfirm = { vm.stopBatch(batchHere) }, onDismiss = { confirmStop = false })
    }
    menuAt?.let { i ->
        val canWatch = remember(doc, i) { Sequence.playable(doc, i).isNotEmpty() }
        AlertDialog(
            onDismissRequest = { menuAt = null },
            title = { Text("Block ${i + 1}") },
            text = {
                Column {
                    TextButton(onClick = { menuAt = null; vm.push(Screen.Block(doc.id, doc.blocks[i].id)) }) { Text("Open block") }
                    if (canWatch) TextButton(onClick = { menuAt = null; vm.push(Screen.Watch(doc.id, doc.blocks[i].id)) }) { Text("▶ Watch from here") }
                    else Muted("No accepted or ready version to watch from here.")
                }
            },
            confirmButton = { TextButton(onClick = { menuAt = null }) { Text("Close") } },
            containerColor = H3Palette.SurfaceElevated,
        )
    }
    cutAt?.let { i ->
        ConfirmDialog(
            "Cut between ${i + 1} and ${i + 2}",
            "These videos are not parent and child. You can insert blocks here; “Generate pending” connects the last one to block ${i + 2}.",
            "Insert blocks here", onConfirm = { vm.push(Screen.Insert(doc.id, doc.blocks[i].id)) }, onDismiss = { cutAt = null },
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
            PrimaryButton("Review block ${next.index + 1}", {
                if (run != null) vm.push(Screen.Review(doc.id, block.id, run)) else open(next.index)
            })
        }
        is NextAction.Consult -> {
            val op = vm.pendingFor(doc.id).firstOrNull { it.kind == OpKind.ATTEMPT && it.blockId == doc.blocks[next.index].id }
            PrimaryButton("Check submission for block ${next.index + 1}", { if (op != null) vm.consult(op) else open(next.index) },
                busy = op != null && vm.isBusy("consult:${op.id}"))
        }
        is NextAction.Generating -> PrimaryButton("Block ${next.index + 1} generating · open", { open(next.index) })
        is NextAction.Resolve -> PrimaryButton("Resolve block ${next.index + 1}", { open(next.index) })
        is NextAction.GeneratePending -> PrimaryButton("Generate pending (${next.count})", onBatch, enabled = !fenced,
            busy = vm.isBusy("batch:${doc.id}"))
        NextAction.Assemble -> PrimaryButton("Assemble video", { vm.push(Screen.Assembly(doc.id)) })
        NextAction.Adopt, NextAction.Empty -> Unit
    }
}
