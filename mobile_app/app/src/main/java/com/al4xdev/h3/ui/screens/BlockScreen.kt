package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.Attempt
import com.al4xdev.h3.data.Block
import com.al4xdev.h3.data.BlockState
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.OpKind
import com.al4xdev.h3.data.Roteiro
import com.al4xdev.h3.data.RoteiroLogic
import com.al4xdev.h3.data.RunStates
import com.al4xdev.h3.data.Sequence
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.Screen
import com.al4xdev.h3.ui.components.BlockedReason
import com.al4xdev.h3.ui.components.BodyText
import com.al4xdev.h3.ui.components.Card
import com.al4xdev.h3.ui.components.ConfirmDialog
import com.al4xdev.h3.ui.components.DurationSeedFields
import com.al4xdev.h3.ui.components.ErrorCard
import com.al4xdev.h3.ui.components.technical
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
import com.al4xdev.h3.ui.components.RunThumbnail
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.layout.ContentScale
import com.al4xdev.h3.ui.components.runVideoUri
import com.al4xdev.h3.ui.settingsAction
import com.al4xdev.h3.ui.theme.H3Palette

fun effectiveLabel(seconds: Double?): String =
    seconds?.let { "${Durations.label(Durations.effectiveSeconds(Durations.frames(it)))} s" } ?: "—"

@Composable
fun BlockScreen(vm: AppViewModel, roteiroId: String, blockId: String) {
    LaunchedEffect(roteiroId) { vm.ensureRoteiro(roteiroId) }
    val remote = vm.docs[roteiroId]
    val doc = remote?.value
    if (doc == null) {
        TopBar("Bloco", vm.settingsAction())
        if (remote?.error != null) Box(Modifier.padding(16.dp)) { ErrorCard("PC inacessível", technical(remote.error)) { vm.loadRoteiro(roteiroId) } }
        else Loading()
        return
    }
    val blocks = if (doc.adopted) doc.blocks else vm.candidate(roteiroId)?.blocks.orEmpty()
    val index = blocks.indexOfFirst { it.id == blockId }
    if (index < 0) {
        TopBar("Bloco", vm.settingsAction())
        Muted("Este bloco não está mais no roteiro.", Modifier.padding(16.dp))
        return
    }
    val block = blocks[index]
    val attempts = if (doc.adopted) RoteiroLogic.attemptsFor(doc, blockId) else emptyList()
    val attempt = if (doc.adopted) RoteiroLogic.currentAttempt(doc, blockId) else null
    val state = RoteiroLogic.stateOf(attempt)
    val batchHere = vm.batchOn(roteiroId)
    val pending = vm.pendingFor(roteiroId).filter {
        (it.kind == OpKind.ATTEMPT && it.blockId == blockId) || (it.kind == OpKind.DECISION && it.id == attempt?.runId)
    }
    val fence = if (batchHere != null) "Lote em andamento neste roteiro: ações de geração, decisão e edição ficam bloqueadas." else null
    var confirmRemove by remember { mutableStateOf(false) }
    var confirmStop by remember { mutableStateOf(false) }

    TopBar("Bloco ${index + 1} de ${blocks.size}", vm.settingsAction())
    Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        val run = attempt?.run
        if (run != null && run.playable) {
            val local = remember(run.id) { vm.localVideo(run.id) }
            VideoPlayer(runVideoUri(vm.api.base(), run.id, local), Modifier.height(420.dp)) {
                RunThumbnail(run.id, vm.api.url(run.videoPath), local, Modifier.fillMaxSize(), ContentScale.Fit)
            }
            Spacer(Modifier.height(8.dp))
        }
        StateDot(state, buildString {
            append(if (attempt == null) "Planejado" else RunStates.label(attempt.state))
            append(" · ").append(effectiveLabel(attempt?.snapshot?.durationSeconds ?: block.durationSeconds))
            append(" · seed ").append(attempt?.snapshot?.seed ?: block.seed)
            if (attempt?.isBridge == true) append(" · ponte")
        })
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            if (index > 0) TextButton(onClick = { vm.replaceTop(Screen.Block(roteiroId, blocks[index - 1].id)) }) { Text("‹ bloco $index") }
            Spacer(Modifier.weight(1f))
            if (index < blocks.size - 1) TextButton(onClick = { vm.replaceTop(Screen.Block(roteiroId, blocks[index + 1].id)) }) { Text("bloco ${index + 2} ›") }
        }

        if (attempts.isEmpty()) {
            PlannedEditor(vm, doc, block, index)
        } else {
            SectionTitle("Ação do roteiro")
            BodyText(block.action)
            SectionTitle("Prompt enviado")
            Card { SelectionContainer { Text(attempt!!.effectivePrompt, color = H3Palette.TextPrimary, fontSize = 14.sp) } }
            (attempt?.run?.error ?: attempt?.error)?.let { Text("Erro: $it", color = H3Palette.StateError, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp)) }
            Spacer(Modifier.height(12.dp))
            BlockedReason(fence)
            if (pending.isNotEmpty()) {
                PendingCard(pending, { vm.isBusy("consult:${it.id}") }, vm::inFlight, vm::consult)
            } else when (state) {
                BlockState.REVIEW -> ReviewActions(vm, roteiroId, blockId, attempt!!, enabled = fence == null)
                BlockState.ACTIVE -> {
                    Muted("${RunStates.label(attempt!!.state)} no PC. O app avisa quando terminar.")
                    Spacer(Modifier.height(8.dp))
                    SecondaryButton("Parar…", { confirmStop = true }, danger = true, busy = vm.isBusy("stop:${attempt.runId}"))
                }
                BlockState.UNCERTAIN -> Muted("O PC ainda não confirmou este envio. Use “Reler do PC” no roteiro.")
                BlockState.FAILED -> RetrySection(vm, doc, blockId, enabled = fence == null)
                else -> Unit
            }
            Versions(vm, doc, blockId, attempts, enabled = fence == null)
        }

        if (doc.adopted && remember(doc, index) { Sequence.playable(doc, index).isNotEmpty() }) {
            Spacer(Modifier.height(12.dp))
            SecondaryButton("▶ Assistir em sequência daqui", { vm.push(Screen.Watch(roteiroId, blockId)) })
        }
        if (doc.adopted) {
            SectionTitle("Mexer na sequência")
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (state == BlockState.ACCEPTED) {
                    SecondaryButton("Refazer este bloco (nova versão)", { vm.push(Screen.Redo(roteiroId, blockId)) }, enabled = fence == null)
                }
                SecondaryButton("Inserir blocos antes", { vm.push(Screen.Insert(roteiroId, blocks.getOrNull(index - 1)?.id)) }, enabled = fence == null)
                SecondaryButton("Inserir blocos depois", { vm.push(Screen.Insert(roteiroId, blockId)) }, enabled = fence == null)
                // The PC refuses removing a block awaiting review (decide first) or the last block.
                val removeBlocked = when {
                    state == BlockState.REVIEW -> "Aceite ou recuse o vídeo antes de tirar o bloco da sequência."
                    blocks.size <= 1 -> "Um roteiro adotado precisa de ao menos um bloco."
                    else -> null
                }
                SecondaryButton(if (attempts.isEmpty()) "Apagar bloco…" else "Tirar da sequência…", { confirmRemove = true }, danger = true,
                    enabled = fence == null && removeBlocked == null, busy = vm.isBusy("remove:$blockId"))
                BlockedReason(removeBlocked)
            }
        }
        Spacer(Modifier.height(32.dp))
    }

    if (confirmRemove) {
        val prev = index
        val next = index + 2
        ConfirmDialog(
            if (attempts.isEmpty()) "Apagar o bloco ${index + 1}?" else "Tirar o bloco ${index + 1} da sequência?",
            if (attempts.isEmpty()) "O bloco planejado sai do roteiro. Nada foi gerado para ele."
            else "O vídeo e o histórico continuam no PC; só deixa de entrar na montagem." +
                (if (index > 0 && index < blocks.size - 1) " Entre $prev e $next vai aparecer um corte ⚡, que você pode fechar inserindo blocos." else ""),
            if (attempts.isEmpty()) "Apagar" else "Tirar da sequência", danger = true,
            onConfirm = { if (attempts.isEmpty()) vm.deletePlanned(roteiroId, blockId) else vm.removeFromSequence(roteiroId, blockId) },
            onDismiss = { confirmRemove = false },
        )
    }
    if (confirmStop && attempt != null) {
        ConfirmDialog("Parar este bloco?", if (batchHere != null) "Ele pertence ao lote ativo: o lote inteiro será parado." else "A geração é interrompida no PC.",
            "Confirmar parada", danger = true, onConfirm = { vm.stopRun(roteiroId, attempt.runId) }, onDismiss = { confirmStop = false })
    }
}

/** Planned (never sent) block: edit action/prompt/duration/seed; save locally (proposal) or on the PC. */
@Composable
private fun PlannedEditor(vm: AppViewModel, doc: Roteiro, block: Block, index: Int) {
    var action by rememberSaveable(block.id) { mutableStateOf(block.action) }
    var prompt by rememberSaveable(block.id) { mutableStateOf(block.prompt) }
    var durationText by rememberSaveable(block.id) { mutableStateOf(Durations.text(block.durationSeconds)) }
    var seedText by rememberSaveable(block.id) { mutableStateOf(block.seed.toString()) }
    val duration = Durations.parse(durationText)?.toDouble()
    val seed = Durations.parseSeed(seedText)
    val edited = duration != null && seed != null && action.isNotBlank() && prompt.isNotBlank()
    val candidate = if (edited) block.copy(action = action, prompt = prompt, durationSeconds = duration!!, seed = seed!!) else null
    val dirty = candidate != null && candidate != block
    val batchHere = vm.batchOn(doc.id)

    SectionTitle("Ação do roteiro")
    TextArea(action, { action = it }, "Ação (resumo)", minLines = 2)
    SectionTitle("Prompt base")
    TextArea(prompt, { prompt = it }, "Instrução para o vídeo", minLines = 4)
    Spacer(Modifier.height(8.dp))
    DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
    Spacer(Modifier.height(12.dp))
    PrimaryButton(if (doc.adopted) "Salvar no PC" else "Salvar rascunho", { candidate?.let { vm.saveBlock(doc.id, it) } },
        enabled = dirty && batchHere == null, busy = vm.isBusy("save:${block.id}"))
    if (doc.adopted) {
        Spacer(Modifier.height(10.dp))
        val parent = RoteiroLogic.parentForFirstAttempt(doc, index)
        val nextHasVideo = doc.blocks.getOrNull(index + 1)?.let { RoteiroLogic.attemptsFor(doc, it.id).isNotEmpty() } == true
        val reason = when {
            batchHere != null -> "Lote em andamento neste roteiro."
            dirty -> "Salve as mudanças antes de gerar."
            parent.isFailure -> parent.exceptionOrNull()?.message
            nextHasVideo -> "O bloco seguinte já tem vídeo: use “Gerar pendentes” no roteiro para ligar os dois."
            else -> null
        }
        SecondaryButton("Gerar só este bloco (prompt como está)", { vm.generateBlock(doc.id, block.id) }, enabled = reason == null,
            busy = vm.isBusy("attempt:${doc.id}"))
        BlockedReason(reason)
        Muted("“Gerar pendentes” no roteiro melhora o prompt com o Grok antes de gerar.")
    } else {
        Spacer(Modifier.height(10.dp))
        Muted("Proposta ainda não adotada: as mudanças ficam neste aparelho até “Usar este roteiro”.")
    }
}

@Composable
fun ReviewActions(vm: AppViewModel, roteiroId: String, blockId: String, attempt: Attempt, enabled: Boolean) {
    val busy = vm.isBusy("decide:${attempt.runId}")
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        SecondaryButton("Recusar", { vm.decide(roteiroId, blockId, attempt.runId, accept = false) }, Modifier.weight(1f), enabled = enabled, busy = busy, danger = true)
        PrimaryButton("Aceitar", { vm.decide(roteiroId, blockId, attempt.runId, accept = true) }, Modifier.weight(1f), enabled = enabled, busy = busy)
    }
    Spacer(Modifier.height(8.dp))
    SecondaryButton("Ver em tela cheia", { vm.push(Screen.Review(roteiroId, blockId, attempt.runId)) })
}

/** Rejected/interrupted: new attempt pre-filled with the prompt actually sent, same seed/duration/parent. */
@Composable
private fun RetrySection(vm: AppViewModel, doc: Roteiro, blockId: String, enabled: Boolean) {
    val plan = RoteiroLogic.retryPlan(doc, blockId)
    if (plan == null) {
        Muted("Uma falha do PC não aceita nova tentativa por aqui. Você pode tirar o bloco da sequência.")
        return
    }
    var open by rememberSaveable(blockId) { mutableStateOf(false) }
    var prompt by rememberSaveable(blockId) { mutableStateOf(plan.prompt) }
    var durationText by rememberSaveable(blockId) { mutableStateOf(Durations.text(plan.durationSeconds)) }
    var seedText by rememberSaveable(blockId) { mutableStateOf(plan.seed.toString()) }
    if (!open) {
        PrimaryButton("Preparar nova tentativa", { open = true }, enabled = enabled)
        return
    }
    Card {
        Text(if (plan.targetRunId != null) "Nova tentativa · mesmo pai e mesmo destino (ponte)" else "Nova tentativa · mesmo pai",
            color = H3Palette.TealPrimary, fontWeight = FontWeight.SemiBold)
        Muted("Preenchida com o prompt efetivamente enviado. Só gera ao tocar em Gerar; o vídeo novo volta para revisão.")
        Spacer(Modifier.height(8.dp))
        TextArea(prompt, { prompt = it }, "Prompt", minLines = 4)
        Spacer(Modifier.height(8.dp))
        DurationSeedFields(durationText, { durationText = it }, seedText, { seedText = it })
        Spacer(Modifier.height(10.dp))
        PrimaryButton("Gerar", { vm.retryBlock(doc.id, blockId, prompt, durationText, seedText) }, enabled = enabled,
            busy = vm.isBusy("attempt:${doc.id}"))
        TextButton(onClick = { open = false }) { Text("Fechar") }
    }
}

@Composable
private fun Versions(vm: AppViewModel, doc: Roteiro, blockId: String, attempts: List<Attempt>, enabled: Boolean) {
    val selected = RoteiroLogic.selectedAttempt(doc, blockId)
    SectionTitle("Versões (${attempts.size})")
    attempts.asReversed().forEach { a ->
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp)
                .clickable(enabled = a.run?.playable == true) { vm.push(Screen.Review(doc.id, blockId, a.runId)) },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val inUse = a.runId == selected?.runId
            Text((if (inUse) "◉ " else "○ ") + a.runId.take(8) + " · " + RunStates.label(a.state) + (if (inUse) " · em uso" else "") +
                (if (a.isBridge) " · ponte" else ""),
                color = if (inUse) H3Palette.TealPrimary else H3Palette.TextPrimary, fontSize = 14.sp, modifier = Modifier.weight(1f))
            if (!inUse && a.state == RunStates.ACCEPTED) {
                TextButton(onClick = { vm.selectVersion(doc.id, blockId, a.runId) }, enabled = enabled && !vm.isBusy("version:$blockId")) { Text("Usar") }
            }
        }
    }
}
