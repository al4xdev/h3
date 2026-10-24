package com.al4xdev.h3.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.BlockState
import com.al4xdev.h3.data.CountScale
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.PendingOp
import com.al4xdev.h3.ui.gestures.noSwipeBack
import com.al4xdev.h3.ui.theme.H3Palette

/** Top of every screen: title + ⚙ only (navigation back is by gesture). */
@Composable
fun TopBar(title: String, onSettings: (() -> Unit)?) {
    Row(
        modifier = Modifier.fillMaxWidth().background(H3Palette.Midnight).statusBarsPadding()
            .padding(start = 20.dp, end = 4.dp).height(56.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            title, modifier = Modifier.weight(1f), color = H3Palette.TextPrimary, fontSize = 20.sp,
            fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
        )
        if (onSettings != null) {
            IconButton(onClick = onSettings, modifier = Modifier.size(48.dp)) {
                Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = H3Palette.TextSecondary)
            }
        }
    }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, modifier = modifier.padding(top = 16.dp, bottom = 6.dp), color = H3Palette.TextSecondary,
        fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
}

@Composable
fun Card(modifier: Modifier = Modifier, border: Color = H3Palette.Outline, content: @Composable () -> Unit) {
    Column(
        modifier = modifier.fillMaxWidth().background(H3Palette.SurfaceCard, RoundedCornerShape(14.dp))
            .border(1.dp, border, RoundedCornerShape(14.dp)).padding(14.dp),
    ) { content() }
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, busy: Boolean = false) {
    Button(
        onClick = onClick, enabled = enabled && !busy, modifier = modifier.fillMaxWidth().heightIn(min = 48.dp),
        colors = ButtonDefaults.buttonColors(containerColor = H3Palette.TealPrimary, contentColor = H3Palette.Midnight),
    ) {
        if (busy) { CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = H3Palette.Midnight); Spacer(Modifier.width(10.dp)) }
        Text(text, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
fun SecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                    busy: Boolean = false, danger: Boolean = false) {
    OutlinedButton(
        onClick = onClick, enabled = enabled && !busy, modifier = modifier.fillMaxWidth().heightIn(min = 48.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = if (danger) H3Palette.StateError else H3Palette.TealPrimary),
    ) {
        if (busy) { CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp); Spacer(Modifier.width(10.dp)) }
        Text(text)
    }
}

/** Disabled actions say why, instead of silently greying out. */
@Composable
fun BlockedReason(text: String?) {
    if (text != null) Text(text, color = H3Palette.StateUncertain, fontSize = 13.sp, modifier = Modifier.padding(vertical = 4.dp))
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier) {
    Text(text, color = H3Palette.TextSecondary, fontSize = 14.sp, modifier = modifier)
}

@Composable
fun StateDot(state: BlockState, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(10.dp).background(H3Palette.of(state), RoundedCornerShape(5.dp)))
        Spacer(Modifier.width(8.dp))
        Text(label, color = H3Palette.TextPrimary, fontSize = 15.sp)
    }
}

/** Network messages already start with "Unreachable PC: " (or legacy "PC inacessível: "); the card shows that once as its title. */
fun technical(error: String?): String? =
    error?.removePrefix("Unreachable PC: ")?.removePrefix("PC inacessível: ")?.takeIf { it.isNotBlank() }

@Composable
fun ErrorCard(message: String, detail: String? = null, retryLabel: String = "Try again", onRetry: (() -> Unit)?) {
    Card(border = H3Palette.StateError) {
        Text(message, color = H3Palette.TextPrimary, fontWeight = FontWeight.SemiBold)
        if (detail != null) Text(detail, color = H3Palette.TextTertiary, fontSize = 12.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
        if (onRetry != null) {
            Spacer(Modifier.height(10.dp))
            SecondaryButton(retryLabel, onRetry)
        }
    }
}

@Composable
fun Loading(text: String = "Reading from PC…") {
    Row(Modifier.fillMaxWidth().padding(24.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
        Spacer(Modifier.width(12.dp))
        Muted(text)
    }
}

@Composable
fun ConfirmDialog(title: String, text: String, confirm: String, danger: Boolean = false, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(onClick = { onDismiss(); onConfirm() }) {
                Text(confirm, color = if (danger) H3Palette.StateError else H3Palette.TealPrimary)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
        containerColor = H3Palette.SurfaceElevated,
    )
}

/** Uncertain requests: the only offered action is reading the same ID again. */
@Composable
fun PendingCard(ops: List<PendingOp>, busy: (PendingOp) -> Boolean, inFlight: (PendingOp) -> Boolean, onConsult: (PendingOp) -> Unit) {
    if (ops.isEmpty()) return
    Card(border = H3Palette.StateUncertain) {
        Text("Request without confirmed response", color = H3Palette.StateUncertain, fontWeight = FontWeight.SemiBold)
        Muted("Will not retry the request. Check the same ID on the PC.")
        ops.forEach { op ->
            Spacer(Modifier.height(8.dp))
            Text("${op.kind.label} · ${op.id.take(8)}", color = H3Palette.TextPrimary, fontSize = 14.sp)
            op.detail?.let { Muted(it.take(300)) }
            if (inFlight(op)) Muted("Sending…")
            else SecondaryButton("Check ${op.kind.label}", { onConsult(op) }, busy = busy(op))
        }
    }
}

@Composable
fun TextArea(value: String, onChange: (String) -> Unit, label: String, modifier: Modifier = Modifier, minLines: Int = 3,
             enabled: Boolean = true, maxChars: Int = 12000) {
    // Only a focused field blocks the swipe (cursor drags/selection); an idle one lets it through.
    var focused by remember { mutableStateOf(false) }
    OutlinedTextField(
        value = value, onValueChange = { if (it.length <= maxChars) onChange(it) }, label = { Text(label) },
        modifier = modifier.fillMaxWidth().onFocusChanged { focused = it.isFocused }.noSwipeBack { focused },
        minLines = minLines, enabled = enabled,
    )
}

@Composable
fun SingleField(value: String, onChange: (String) -> Unit, label: String, modifier: Modifier = Modifier,
                numeric: Boolean = false, decimal: Boolean = false, enabled: Boolean = true, maxChars: Int = 256) {
    var focused by remember { mutableStateOf(false) }
    OutlinedTextField(
        value = value, onValueChange = { if (it.length <= maxChars) onChange(it) }, label = { Text(label) },
        singleLine = true, enabled = enabled,
        modifier = modifier.fillMaxWidth().onFocusChanged { focused = it.isFocused }.noSwipeBack { focused },
        keyboardOptions = KeyboardOptions(keyboardType = when {
            decimal -> KeyboardType.Decimal
            numeric -> KeyboardType.Number
            else -> KeyboardType.Text
        }),
    )
}

/** Duration (per block) with the aligned-frames preview, plus seed. */
@Composable
fun DurationSeedFields(durationText: String, onDuration: (String) -> Unit, seedText: String, onSeed: (String) -> Unit, enabled: Boolean = true) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        SingleField(durationText, onDuration, "Duration (s)", Modifier.weight(1f), decimal = true, enabled = enabled, maxChars = 5)
        SingleField(seedText, onSeed, "Seed", Modifier.weight(1.4f), numeric = true, enabled = enabled, maxChars = 16)
    }
    val seedOk = Durations.parseSeed(seedText) != null
    Text(
        Durations.preview(durationText) + if (seedOk) "" else " · invalid seed",
        color = if (Durations.parse(durationText) != null && seedOk) H3Palette.TextSecondary else H3Palette.StateError,
        fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp),
    )
}

/** Count slider with fine −/+ buttons (owner likes the slider; big ranges need the buttons). */
@Composable
fun CountSlider(label: String, value: Int, range: IntRange, onChange: (Int) -> Unit, enabled: Boolean = true, caption: String? = null) {
    val max = range.last.coerceAtLeast(range.first)
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = H3Palette.TextPrimary, modifier = Modifier.weight(1f))
            OutlinedButton(onClick = { onChange((value - 1).coerceIn(range.first, max)) }, enabled = enabled && value > range.first,
                modifier = Modifier.size(48.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) { Text("−", fontSize = 20.sp) }
            Text("$value", color = H3Palette.TealPrimary, fontSize = 20.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.width(64.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            OutlinedButton(onClick = { onChange((value + 1).coerceIn(range.first, max)) }, enabled = enabled && value < max,
                modifier = Modifier.size(48.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) { Text("+", fontSize = 20.sp) }
        }
        val values = remember(max) { CountScale.values(max) }
        if (values.size > 1) {
            Slider(
                value = CountScale.positionOf(value, values).toFloat(),
                onValueChange = { onChange(CountScale.valueAt(it, values).coerceIn(range.first, max)) },
                valueRange = 0f..values.lastIndex.toFloat(), enabled = enabled,
                modifier = Modifier.fillMaxWidth().noSwipeBack(),
            )
        }
        Muted("(${range.first}–$max)" + (caption?.let { " · $it" } ?: ""))
    }
}

@Composable
fun Expandable(title: String, initiallyOpen: Boolean = false, content: @Composable () -> Unit) {
    var open by rememberSaveable { mutableStateOf(initiallyOpen) }
    TextButton(onClick = { open = !open }, modifier = Modifier.fillMaxWidth()) {
        Text((if (open) "▾ " else "▸ ") + title, color = H3Palette.TextSecondary, modifier = Modifier.fillMaxWidth())
    }
    if (open) content()
}

val screenPadding = Modifier.padding(horizontal = 16.dp)

@Composable
fun BodyText(text: String) {
    Text(text, color = H3Palette.TextPrimary, fontSize = 15.sp, lineHeight = 21.sp)
}

@Composable
fun Title(text: String) {
    Text(text, color = H3Palette.TextPrimary, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
}
