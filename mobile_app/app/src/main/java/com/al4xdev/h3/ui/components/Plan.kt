package com.al4xdev.h3.ui.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import kotlinx.coroutines.delay
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.Scene
import com.al4xdev.h3.data.Vision
import com.al4xdev.h3.ui.theme.H3Palette

/**
 * Honest wait for Grok planning: the PC chains director, critic and writers in one request.
 * Shows only the elapsed time (no invented percentage) while `active`.
 */
@Composable
fun PlanningWait(active: Boolean) {
    if (!active) return
    var elapsed by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        while (true) { delay(1000); elapsed++ } // local clock for the label, not a request
    }
    Muted("Grok em etapas no PC (diretor · crítico · roteiristas). Pode levar alguns minutos · ${elapsed}s")
}

fun minutesLabel(seconds: Double): String {
    val total = seconds.toInt()
    return if (total >= 60) "${total / 60} min ${total % 60} s" else "${Durations.label(seconds)} s"
}

@Composable
fun VisionCard(vision: Vision?) {
    if (vision == null) return
    Card {
        Expandable("Visão cinematográfica") {
            listOf(
                "Estilo" to vision.style, "Câmera" to vision.camera, "Luz e cor" to vision.lightAndColor,
                "Ritmo" to vision.rhythm, "Notas" to vision.notes,
            ).filter { it.second.isNotBlank() }.forEach { (label, text) ->
                Text(label, color = H3Palette.TextSecondary, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                Text(text, color = H3Palette.TextPrimary, fontSize = 14.sp, modifier = Modifier.padding(bottom = 8.dp))
            }
        }
    }
}

/** Compact outline of the plan: scene title + beats with seconds; blocks stay the editable unit. */
@Composable
fun SceneTimeline(scenes: List<Scene>) {
    if (scenes.isEmpty()) return
    val total = scenes.sumOf { it.seconds }
    Card {
        Text("${scenes.size} cenas · ${minutesLabel(total)}", color = H3Palette.TextPrimary, fontWeight = FontWeight.SemiBold)
        Expandable("Linha do tempo", initiallyOpen = scenes.size <= 8) {
            scenes.forEachIndexed { i, scene ->
                Text("${i + 1}. ${scene.title} · ${minutesLabel(scene.seconds)}", color = H3Palette.TealPrimary, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 6.dp))
                scene.beats.forEach { beat ->
                    Row(Modifier.padding(start = 10.dp, top = 2.dp)) {
                        Text(
                            when (beat.kind) { "transition" -> "⇢"; "hold" -> "■"; else -> "▸" },
                            color = H3Palette.TextSecondary, fontSize = 13.sp,
                        )
                        Spacer(Modifier.width(6.dp))
                        androidx.compose.foundation.layout.Column(Modifier.weight(1f)) {
                            Text(beat.action, color = H3Palette.TextPrimary, fontSize = 13.sp)
                            beat.dialogue?.let {
                                Text("💬 “$it”", color = H3Palette.TextSecondary, fontSize = 13.sp, fontStyle = FontStyle.Italic)
                            }
                        }
                        Text("${Durations.label(beat.seconds)} s", color = H3Palette.TextTertiary, fontSize = 12.sp)
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
        }
    }
}
