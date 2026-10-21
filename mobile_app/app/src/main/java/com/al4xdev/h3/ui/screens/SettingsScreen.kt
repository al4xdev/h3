package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.ApiClient
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.components.Card
import com.al4xdev.h3.ui.components.Expandable
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PrimaryButton
import com.al4xdev.h3.ui.components.SecondaryButton
import com.al4xdev.h3.ui.components.SectionTitle
import com.al4xdev.h3.ui.components.SingleField
import com.al4xdev.h3.ui.components.TextArea
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.theme.H3Palette

@Composable
fun SettingsScreen(vm: AppViewModel) {
    LaunchedEffect(Unit) { vm.loadEditors() }
    var url by rememberSaveable { mutableStateOf(vm.settings.baseUrl) }
    var autoDownload by remember { mutableStateOf(vm.settings.autoDownload) }
    var storageTick by remember { mutableIntStateOf(0) }
    val (count, bytes, cache) = remember(storageTick) { vm.storageInfo() }

    TopBar("Ajustes", null)
    Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        SectionTitle("Servidor do PC")
        SingleField(url, { url = it }, "Endereço (http://IP:porta)")
        Spacer(Modifier.height(8.dp))
        SecondaryButton("Testar e usar", { vm.testServer(url) }, busy = vm.isBusy("server"))
        Muted(if (vm.live) "Atualização ao vivo conectada." else "Atualização ao vivo desconectada.")

        SectionTitle("Notificações")
        Muted(vm.settings.fcmToken?.let { "Ativas · token …${it.takeLast(4)}" } ?: "Sem token ainda")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Baixar vídeo pronto para ver offline", color = H3Palette.TextPrimary, modifier = Modifier.weight(1f))
            Switch(checked = autoDownload, onCheckedChange = { autoDownload = it; vm.settings.autoDownload = it })
        }
        SecondaryButton("Registrar este aparelho no PC", vm::registerNotifications)

        SectionTitle("Armazenamento neste aparelho")
        Muted("Vídeos baixados: $count · ${bytes / (1024 * 1024)} MB · miniaturas ${cache / (1024 * 1024)} MB")
        Spacer(Modifier.height(6.dp))
        SecondaryButton("Limpar", { vm.clearStorage(); storageTick++ }, danger = true)

        SectionTitle("Grok")
        Muted("Duração e seed não ficam aqui: pertencem a cada bloco.")
        EditorCard(
            vm, ApiClient.ROTEIRO_EDITOR, "Roteiro completo",
            note = "A proposta nova usa o narrador: script, paleta e um cartão por bloco. " +
                "Tarefa e formato viajam no código, então este texto salvo é só registro e " +
                "não é enviado ao Grok.",
            editable = false,
        )
        Spacer(Modifier.height(10.dp))
        EditorCard(vm, ApiClient.GROK_EDITOR, "Melhoria por bloco")
        Spacer(Modifier.height(10.dp))
        EditorCard(vm, ApiClient.EDIT_EDITOR, "Edição entre vídeos")
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun EditorCard(vm: AppViewModel, path: String, title: String, note: String? = null,
                       editable: Boolean = true) {
    val remote = vm.editors[path]
    val config = remote?.value
    Card {
        Expandable(title) {
            when {
                config == null && remote?.error != null -> {
                    Muted(remote.error)
                    SecondaryButton("Tentar de novo", { vm.loadEditors() })
                }
                config == null -> Loading()
                else -> {
                    if (note != null) {
                        Muted(note)
                        Spacer(Modifier.height(6.dp))
                    }
                    Muted("Modelo fixo: ${config.model.ifBlank { "—" }}")
                    Spacer(Modifier.height(6.dp))
                    if (editable) {
                        var text by rememberSaveable(path, config.systemPrompt) { mutableStateOf(config.systemPrompt) }
                        TextArea(text, { text = it }, "System prompt", minLines = 6, maxChars = 100000)
                        Spacer(Modifier.height(8.dp))
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            PrimaryButton("Salvar", { vm.saveEditor(path, text) },
                                enabled = text != config.systemPrompt && text.isNotBlank(),
                                busy = vm.isBusy("editor:$path"))
                            if (text != config.systemPrompt) Muted("Alterado; ainda não salvo no PC.")
                        }
                    } else {
                        // Read-only keeps the stored writer prompt visible without implying an effect.
                        Text(config.systemPrompt, color = H3Palette.TextSecondary, fontSize = 13.sp)
                    }
                }
            }
        }
    }
}
