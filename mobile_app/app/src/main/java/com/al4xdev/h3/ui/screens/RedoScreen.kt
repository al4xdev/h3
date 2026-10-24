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
 * "Redo this block": the backend's anchored edit in `replace` mode. Bridge from the previous
 * accepted block's last frame to the next one's first frame → review → apply as a new version.
 */
@Composable
fun RedoScreen(vm: AppViewModel, roteiroId: String, blockId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    LaunchedEffect(roteiroId, blockId) { vm.ensureRedo(roteiroId, blockId) }
    val doc = vm.doc(roteiroId)
    val index = doc?.index(blockId) ?: -1
    TopBar(if (index >= 0) "New version of block ${index + 1}" else "New version", vm.settingsAction())
    if (doc == null) {
        val error = vm.docs[roteiroId]?.error
        if (error != null) Box(Modifier.padding(16.dp)) { ErrorCard("PC unreachable", technical(error)) { vm.loadRoteiro(roteiroId) } } else Loading()
        return
    }
    if (index < 0) { Muted("This block is no longer in the script.", Modifier.padding(16.dp)); return }
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
        Expandable("Prompts sent to neighbors") {
            listOf(index - 1 to "Previous", index + 1 to "Next").forEach { (i, label) ->
                doc.blocks.getOrNull(i)?.let { b ->
                    RoteiroLogic.selectedAttempt(doc, b.id)?.let { a ->
                        SectionTitle("$label (block ${i + 1})")
                        BodyText(a.effectivePrompt)
                    }
                }
            }
        }
        if (pending.isNotEmpty()) PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
        BlockedReason(if (batchHere != null) "Batch in progress for this script." else null)

        when {
            record == null && remote?.loading == true -> Loading()
            record == null -> {
                if (previousRun == null || nextRun == null) {
                    BlockedReason(
                        if (previousRun == null) "Redoing requires an accepted previous block; the first block has no such anchor."
                        else "Redoing requires an accepted next block. For the last block, use “Insert blocks after”.",
                    )
                    return@Column
                }
                var idea by rememberSaveable { mutableStateOf("") }
                var durationText by rememberSaveable { mutableStateOf(Durations.text(block.durationSeconds)) }
                var seedText by rememberSaveable { mutableStateOf(block.seed.toString()) }
                SectionTitle("What should change in this version?")
                TextArea(idea, { idea = it }, "Idea")
                Spacer(Modifier.height(8.dp))
                DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
                Spacer(Modifier.height(12.dp))
                PrimaryButton("Propose with Grok", { vm.proposeRedo(roteiroId, blockId, idea, durationText, seedText) },
                    enabled = batchHere == null && pending.isEmpty(), busy = busy)
            }
            else -> EditProgress(vm, roteiroId, blockId, record, busy, batchHere == null && pending.isEmpty(), onDiscard = { confirmDiscard = true })
        }
        Spacer(Modifier.height(32.dp))
    }
    if (confirmDiscard) {
        ConfirmDialog("Discard this edit?", "The script does not change. Any already generated video remains on the PC.", "Discard", danger = true,
            onConfirm = { vm.discardRedo(roteiroId, blockId) }, onDismiss = { confirmDiscard = false })
    }
}

@Composable
private fun EditProgress(vm: AppViewModel, roteiroId: String, blockId: String, record: com.al4xdev.h3.data.EditRecord,
                         busy: Boolean, enabled: Boolean, onDiscard: () -> Unit) {
    val run = record.run
    val stale = vm.doc(roteiroId)?.revision?.let { it != record.sourceRevision } == true
    Muted("Edit ${record.id.take(8)} · ${record.state}")
    if (stale && record.state in setOf("proposed", "generating")) BlockedReason("The script has changed since this edit. Discard it and prepare another.")
    record.error?.let { BlockedReason("Error: $it") }
    when (record.state) {
        "proposed" -> {
            var prompt by rememberSaveable(record.id) { mutableStateOf(record.prompt.orEmpty()) }
            SectionTitle("Proposed prompt (editable)")
            TextArea(prompt, { prompt = it }, "Prompt")
            Spacer(Modifier.height(12.dp))
            PrimaryButton("Generate new version", { vm.generateRedo(roteiroId, blockId, prompt) }, enabled = enabled && !stale, busy = busy)
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
                    SecondaryButton("Reject", { vm.decide(roteiroId, blockId, run.id, false) { vm.loadEdit(roteiroId, blockId, record.id) } },
                        Modifier.weight(1f), enabled = enabled, busy = deciding, danger = true)
                    PrimaryButton("Approve", { vm.decide(roteiroId, blockId, run.id, true) { vm.loadEdit(roteiroId, blockId, record.id) } },
                        Modifier.weight(1f), enabled = enabled, busy = deciding)
                }
                RunStates.ACCEPTED -> if (record.state != "applied") {
                    PrimaryButton("Use this version in the script", { vm.applyRedo(roteiroId, blockId) }, enabled = enabled && !stale, busy = busy)
                }
                RunStates.REJECTED, RunStates.INTERRUPTED, RunStates.FAILED ->
                    PrimaryButton("Prepare retry (same prompt)", { vm.retryRedo(roteiroId, blockId) }, enabled = enabled, busy = busy)
                else -> Muted("Generating on PC. The app will notify when done.")
            }
        } else {
            Muted(if (record.state == "uncertain") "Uncertain response on PC." else "Waiting for PC to register generation.")
            SecondaryButton("Reload this edit", { vm.loadEdit(roteiroId, blockId, record.id) })
        }
        "failed" -> PrimaryButton("Prepare retry (same prompt)", { vm.retryRedo(roteiroId, blockId) }, enabled = enabled, busy = busy)
        "improving" -> SecondaryButton("Reload this edit", { vm.loadEdit(roteiroId, blockId, record.id) })
    }
    if (record.state != "applied") {
        Spacer(Modifier.height(10.dp))
        SecondaryButton("Discard edit…", onDiscard, danger = true, enabled = !busy)
    }
}
