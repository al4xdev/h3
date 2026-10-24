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

    TopBar("Settings", null)
    Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        SectionTitle("PC server")
        SingleField(url, { url = it }, "Address (http://IP:port)")
        Spacer(Modifier.height(8.dp))
        SecondaryButton("Test and connect", { vm.testServer(url) }, busy = vm.isBusy("server"))
        Muted(if (vm.live) "Live updates connected." else "Live updates disconnected.")

        SectionTitle("Notifications")
        Muted(vm.settings.fcmToken?.let { "Active · token …${it.takeLast(4)}" } ?: "No token yet")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Download ready videos for offline viewing", color = H3Palette.TextPrimary, modifier = Modifier.weight(1f))
            Switch(checked = autoDownload, onCheckedChange = { autoDownload = it; vm.settings.autoDownload = it })
        }
        SecondaryButton("Register this device on PC", vm::registerNotifications)

        SectionTitle("Storage on this device")
        Muted("Downloaded videos: $count · ${bytes / (1024 * 1024)} MB · thumbnails ${cache / (1024 * 1024)} MB")
        Spacer(Modifier.height(6.dp))
        SecondaryButton("Clear", { vm.clearStorage(); storageTick++ }, danger = true)

        SectionTitle("Grok")
        Muted("Duration and seed are not here: they belong to each block.")
        EditorCard(
            vm, ApiClient.ROTEIRO_EDITOR, "Full script",
            note = "The new proposal uses the narrator: script, palette, and one card per block. " +
                "Task and format travel in code, so this saved text is only a reference record and " +
                "is not sent to Grok.",
            editable = false,
        )
        Spacer(Modifier.height(10.dp))
        EditorCard(vm, ApiClient.GROK_EDITOR, "Per-block refinement")
        Spacer(Modifier.height(10.dp))
        EditorCard(vm, ApiClient.EDIT_EDITOR, "In-between video editing")
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
                    SecondaryButton("Try again", { vm.loadEditors() })
                }
                config == null -> Loading()
                else -> {
                    if (note != null) {
                        Muted(note)
                        Spacer(Modifier.height(6.dp))
                    }
                    Muted("Fixed model: ${config.model.ifBlank { "—" }}")
                    Spacer(Modifier.height(6.dp))
                    if (editable) {
                        var text by rememberSaveable(path, config.systemPrompt) { mutableStateOf(config.systemPrompt) }
                        TextArea(text, { text = it }, "System prompt", minLines = 6, maxChars = 100000)
                        Spacer(Modifier.height(8.dp))
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            PrimaryButton("Save", { vm.saveEditor(path, text) },
                                enabled = text != config.systemPrompt && text.isNotBlank(),
                                busy = vm.isBusy("editor:$path"))
                            if (text != config.systemPrompt) Muted("Changed; not yet saved on PC.")
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
