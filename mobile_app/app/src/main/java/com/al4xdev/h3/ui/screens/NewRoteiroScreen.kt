package com.al4xdev.h3.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.InputItem
import com.al4xdev.h3.data.MAX_BLOCKS
import com.al4xdev.h3.ui.AppViewModel
import com.al4xdev.h3.ui.components.Card
import com.al4xdev.h3.ui.components.CountSlider
import com.al4xdev.h3.ui.components.DurationSeedFields
import com.al4xdev.h3.ui.components.ErrorCard
import com.al4xdev.h3.ui.components.technical
import com.al4xdev.h3.ui.components.Loading
import com.al4xdev.h3.ui.components.Muted
import com.al4xdev.h3.ui.components.PlanningWait
import com.al4xdev.h3.ui.components.PrimaryButton
import com.al4xdev.h3.ui.components.RemoteImage
import com.al4xdev.h3.ui.components.SecondaryButton
import com.al4xdev.h3.ui.components.SectionTitle
import com.al4xdev.h3.ui.components.SingleField
import com.al4xdev.h3.ui.components.TextArea
import com.al4xdev.h3.ui.components.TopBar
import com.al4xdev.h3.ui.settingsAction
import com.al4xdev.h3.ui.theme.H3Palette

fun AppViewModel.inputImageUrl(item: InputItem): String? =
    (item.imageUrl ?: item.reference.imagePath())?.let { api.url(it) }

/** "≈ 12 min runtime" for N blocks of the given duration (seconds below one minute). */
fun filmLength(count: Int, durationText: String): String? {
    val seconds = Durations.parse(durationText) ?: return null
    val total = count * Durations.effectiveSeconds(Durations.frames(seconds))
    return if (total < 60) "≈ ${total.toInt()}s runtime" else "≈ ${Math.round(total / 60)} min runtime"
}

@Composable
fun NewRoteiroScreen(vm: AppViewModel) {
    val d = vm.newDraft
    var picking by rememberSaveable { mutableStateOf(false) }
    val creating = vm.isBusy("new:create")
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) vm.upload(uri)
    }

    TopBar("New script", vm.settingsAction())
    Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        SectionTitle("Identity reference")
        Row {
            val ratio = d.reference?.let { r -> if (r.width != null && r.height != null && r.height > 0) r.width.toFloat() / r.height else null } ?: 0.5625f
            RemoteImage(
                url = d.reference?.let { vm.inputImageUrl(it) }, maxPx = 720,
                modifier = Modifier.width(140.dp).aspectRatio(ratio).border(1.dp, H3Palette.Outline, RoundedCornerShape(10.dp)),
                contentScale = ContentScale.Fit, description = "Reference photo",
            )
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                if (d.reference == null) Muted("No photo selected.")
                else {
                    Text(d.reference.label, color = H3Palette.TextPrimary, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    if (d.reference.width != null) Muted("${d.reference.width} × ${d.reference.height}")
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SecondaryButton("Choose from PC", { picking = true; vm.loadInputs() }, Modifier.weight(1f), enabled = !creating)
            SecondaryButton("Upload photo", {
                photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            }, Modifier.weight(1f), busy = vm.isBusy("upload"), enabled = !creating)
        }
        Muted("PNG or JPEG up to 20 MiB (Grok rejects other formats).", Modifier.padding(top = 4.dp))

        SectionTitle("Title")
        SingleField(d.title, { vm.updateNewDraft(d.copy(title = it)) }, "Title (optional)")
        SectionTitle("Script idea")
        TextArea(d.idea, { vm.updateNewDraft(d.copy(idea = it)) }, "What happens in the video", minLines = 4)

        SectionTitle("Breakdown")
        CountSlider("Blocks", d.count, 1..MAX_BLOCKS, { vm.updateNewDraft(d.copy(count = it)) }, caption = filmLength(d.count, d.durationText))
        Spacer(Modifier.height(8.dp))
        DurationSeedFields(d.durationText, { vm.updateNewDraft(d.copy(durationText = it)) }, d.seedText, { vm.updateNewDraft(d.copy(seedText = it)) })

        Spacer(Modifier.height(16.dp))
        if (d.creationUncertain) {
            Card(border = H3Palette.StateUncertain) {
                Text("Script creation received no response.", color = H3Palette.StateUncertain)
                Muted("Before creating another, check if it already exists on the PC.")
                Spacer(Modifier.height(8.dp))
                SecondaryButton("Find on PC", vm::findCreatedRoteiro, busy = vm.isBusy("new:find"))
            }
            Spacer(Modifier.height(12.dp))
        } else if (d.roteiroId != null) {
            Muted("Script already created on PC (${d.roteiroId.take(8)}). Proposing again reuses it.")
            Spacer(Modifier.height(8.dp))
        }
        PrimaryButton("Propose with Grok", vm::proposeNew, enabled = !d.creationUncertain, busy = creating)
        PlanningWait(creating)
        Spacer(Modifier.height(10.dp))
        SecondaryButton("Write blocks manually", vm::writeNewByHand, enabled = !d.creationUncertain && !creating)
        Spacer(Modifier.height(32.dp))
    }

    if (picking) {
        ReferencePicker(vm, onPick = { vm.updateNewDraft(vm.newDraft.copy(reference = it)); picking = false }, onClose = { picking = false })
    }
}

@Composable
private fun ReferencePicker(vm: AppViewModel, onPick: (InputItem) -> Unit, onClose: () -> Unit) {
    LaunchedEffect(Unit) { if (vm.inputs.value == null) vm.loadInputs() }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.fillMaxSize().background(H3Palette.SurfaceDark).padding(12.dp)) {
            Row {
                Text("PC Images", color = H3Palette.TextPrimary, fontSize = 18.sp, modifier = Modifier.weight(1f).padding(top = 12.dp))
                TextButton(onClick = onClose) { Text("Close") }
            }
            val inputs = vm.inputs
            when {
                inputs.value == null && inputs.error != null -> ErrorCard("PC unreachable", technical(inputs.error)) { vm.loadInputs() }
                inputs.value == null -> Loading()
                else -> LazyVerticalGrid(
                    columns = GridCells.Fixed(3),
                    contentPadding = PaddingValues(4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    // Photos (assets + uploads) first, then frames taken from generated videos.
                    val (frames, photos) = inputs.value.partition { it.isRunFrame }
                    for ((title, group) in listOf("Photos" to photos, "Video frames" to frames)) {
                        if (group.isEmpty()) continue
                        item(key = "h:$title", span = { GridItemSpan(maxLineSpan) }) {
                            Text(title, color = H3Palette.TextSecondary, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp))
                        }
                        items(group, key = { it.sourceRoot + ":" + it.path }) { item ->
                            Column(Modifier.clickable { onPick(item) }) {
                                RemoteImage(vm.inputImageUrl(item), 256, Modifier.fillMaxWidth().aspectRatio(0.75f), ContentScale.Fit, item.label)
                                Text(item.label, color = H3Palette.TextSecondary, fontSize = 11.sp, maxLines = 1,
                                    overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                    if (inputs.value.size < vm.inputsTotal) {
                        item(span = { GridItemSpan(maxLineSpan) }) {
                            SecondaryButton("Load more", { vm.loadInputs(more = true) }, busy = vm.isBusy("inputs"))
                        }
                    }
                }
            }
        }
    }
}
