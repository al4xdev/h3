package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.interaction.MutableInteractionSource
import com.al4xdev.h3.ui.components.appearOnce
import com.al4xdev.h3.ui.components.pressScale
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.BatchRecord
import com.al4xdev.h3.data.BlockState
import com.al4xdev.h3.data.SummaryItem
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.Screen
import com.al4xdev.h3.ui.components.Card
import com.al4xdev.h3.ui.components.ConfirmDialog
import com.al4xdev.h3.ui.components.ErrorCard
import com.al4xdev.h3.ui.components.technical
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PrimaryButton
import com.al4xdev.h3.ui.components.SecondaryButton
import com.al4xdev.h3.ui.components.Title
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.settingsAction
import com.al4xdev.h3.ui.theme.H3Palette

@Composable
fun LibraryScreen(vm: AppViewModel) {
    LaunchedEffect(Unit) { if (vm.library.value == null) vm.loadLibrary() }
    var onlyFavorites by rememberSaveable { mutableStateOf(false) }
    var menuFor by remember { mutableStateOf<SummaryItem?>(null) }
    var confirmDelete by remember { mutableStateOf<SummaryItem?>(null) }
    var confirmStop by remember { mutableStateOf<BatchRecord?>(null) }
    val library = vm.library
    val items = library.value.orEmpty().let { list ->
        val sorted = list.sortedWith(compareByDescending<SummaryItem> { it.id in vm.favorites }.thenByDescending { it.updatedAt.orEmpty() })
        if (onlyFavorites) sorted.filter { it.id in vm.favorites } else sorted
    }

    TopBar("H3 Studio", vm.settingsAction())
    LazyColumn(
        state = rememberLazyListState(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        vm.batch?.takeIf { it.active }?.let { b ->
            item(key = "batch") {
                val name = library.value?.firstOrNull { it.id == b.roteiroId }?.title ?: "roteiro"
                Card(border = H3Palette.TealSecondary) {
                    Text("⏵ Lote no PC · $name", color = H3Palette.TealPrimary, fontWeight = FontWeight.SemiBold)
                    Muted(b.describe())
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        SecondaryButton("Abrir roteiro", { vm.push(Screen.Roteiro(b.roteiroId)) }, Modifier.weight(1f))
                        SecondaryButton("Parar…", { confirmStop = b }, Modifier.weight(1f), danger = true,
                            busy = vm.isBusy("stopbatch:${b.id}"), enabled = !b.stopRequested)
                    }
                }
            }
        }
        item(key = "new") { PrimaryButton("+ Novo roteiro", { vm.push(Screen.NewRoteiro) }) }
        item(key = "header") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Title("Roteiros")
                Spacer(Modifier.weight(1f))
                FilterChip(selected = onlyFavorites, onClick = { onlyFavorites = !onlyFavorites }, label = { Text("☆ favoritos") })
            }
        }
        when {
            library.value == null && library.error != null -> item(key = "error") {
                ErrorCard("PC inacessível", technical(library.error)) { vm.loadLibrary() }
            }
            library.value == null -> item(key = "loading") { Loading() }
            else -> {
                if (library.error != null) item(key = "stale") {
                    ErrorCard("PC inacessível agora · mostrando a última leitura", technical(library.error)) { vm.loadLibrary() }
                }
                if (items.isEmpty()) item(key = "empty") {
                    Muted(if (onlyFavorites) "Nenhum favorito." else "Nenhum roteiro no PC ainda.")
                }
                items(items, key = { it.id }) { item ->
                    RoteiroCard(
                        item = item,
                        favorite = item.id in vm.favorites,
                        uncertain = vm.pendingFor(item.id).isNotEmpty(),
                        onOpen = { vm.push(Screen.Roteiro(item.id)) },
                        onLongPress = { menuFor = item },
                    )
                }
            }
        }
    }

    menuFor?.let { item ->
        val favorite = item.id in vm.favorites
        AlertDialog(
            onDismissRequest = { menuFor = null },
            title = { Text(item.title) },
            text = {
                Column {
                    TextButton(onClick = { menuFor = null; vm.setFavorite(item.id, !favorite) }, modifier = Modifier.fillMaxWidth()) {
                        Text(if (favorite) "★ Tirar dos favoritos" else "☆ Favoritar", modifier = Modifier.fillMaxWidth())
                    }
                    TextButton(onClick = { menuFor = null; confirmDelete = item }, modifier = Modifier.fillMaxWidth()) {
                        Text("Apagar roteiro…", color = H3Palette.StateError, modifier = Modifier.fillMaxWidth())
                    }
                }
            },
            confirmButton = { TextButton(onClick = { menuFor = null }) { Text("Fechar") } },
            containerColor = H3Palette.SurfaceElevated,
        )
    }
    confirmDelete?.let { item ->
        ConfirmDialog(
            title = "Apagar “${item.title}”?",
            text = "Os vídeos e montagens deste roteiro vão para a lixeira do PC (/tmp). Registros de segurança e referências compartilhadas são preservados.",
            confirm = "Apagar", danger = true,
            onConfirm = { vm.deleteRoteiro(item) }, onDismiss = { confirmDelete = null },
        )
    }
    confirmStop?.let { b ->
        ConfirmDialog(
            title = "Parar o lote?",
            text = "O bloco em geração é interrompido e o lote não continua. Nada do que já foi aceito é perdido.",
            confirm = "Confirmar parada", danger = true,
            onConfirm = { vm.stopBatch(b) }, onDismiss = { confirmStop = null },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun RoteiroCard(item: SummaryItem, favorite: Boolean, uncertain: Boolean, onOpen: () -> Unit, onLongPress: () -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    Card(
        Modifier.appearOnce().pressScale(interaction).combinedClickable(
            interactionSource = interaction, indication = LocalIndication.current,
            onClick = onOpen, onLongClick = onLongPress, onLongClickLabel = "Favoritar ou apagar",
        ),
    ) {
        Text((if (favorite) "★ " else "") + item.title, color = H3Palette.TextPrimary, fontSize = 16.sp,
            fontWeight = FontWeight.SemiBold, maxLines = 2)
        Spacer(Modifier.height(8.dp))
        if (item.strip.isNotEmpty()) StateStrip(item.strip)
        Spacer(Modifier.height(6.dp))
        val accepted = item.count("accepted")
        Muted(
            when {
                !item.adopted -> "Proposta ainda não adotada"
                item.blockCount > 0 && accepted == item.blockCount -> "$accepted/${item.blockCount} ✓ todos aceitos"
                else -> "$accepted/${item.blockCount} aceitos"
            },
        )
        val review = item.count("ready_for_review")
        val active = item.count("active")
        val failed = item.count("failed")
        if (review > 0) Text("● $review para revisar", color = H3Palette.StateReady, fontSize = 14.sp)
        if (active > 0) Text("⟳ $active gerando", color = H3Palette.StateActive, fontSize = 14.sp)
        if (failed > 0) Text("✕ $failed recusado/interrompido", color = H3Palette.StateError, fontSize = 14.sp)
        if (uncertain) Text("⚠ pedido sem resposta confirmada", color = H3Palette.StateUncertain, fontSize = 14.sp)
    }
}

/** One mark per block, colored by its real state; scales down to a hairline for long films. */
@Composable
fun StateStrip(strip: List<String>) {
    val states = strip.map(BlockState::fromWire)
    Canvas(Modifier.fillMaxWidth().height(8.dp)) {
        val n = states.size
        val gap = if (n <= 60) 2f else 0f
        val w = (size.width - gap * (n - 1)) / n
        states.forEachIndexed { i, s ->
            drawRect(H3Palette.of(s), topLeft = Offset(i * (w + gap), 0f), size = Size(w.coerceAtLeast(0.5f), size.height))
        }
    }
}
