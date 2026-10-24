package com.al4xdev.h3.ui.components

import android.provider.Settings
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.BlockState
import com.al4xdev.h3.ui.theme.H3Palette
import java.io.File

@Composable
fun reducedMotion(): Boolean {
    val context = LocalContext.current
    return remember {
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
}

private fun badge(state: BlockState): String = when (state) {
    BlockState.ACCEPTED -> "✓"
    BlockState.REVIEW -> "●"
    BlockState.ACTIVE -> "⟳"
    BlockState.UNCERTAIN -> "?"
    BlockState.FAILED -> "✕"
    BlockState.PLANNED -> "··"
}

fun stateLabel(state: BlockState): String = when (state) {
    BlockState.ACCEPTED -> "accepted"
    BlockState.REVIEW -> "ready for review"
    BlockState.ACTIVE -> "queued or generating"
    BlockState.UNCERTAIN -> "uncertain submission"
    BlockState.FAILED -> "rejected, interrupted or failed"
    BlockState.PLANNED -> "planned"
}

/**
 * Square block tile. Planned tiles are dashed with no fake thumbnail. A cut marker (⚡) sits on
 * the left edge when this block does not continue the previous one.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BlockTile(
    number: Int,
    state: BlockState,
    thumbRunId: String?,
    videoUrl: (String) -> String,
    localFile: (String) -> File?,
    caption: String?,
    cutBefore: Boolean,
    onClick: () -> Unit,
    onCut: () -> Unit,
    onLongClick: (() -> Unit)? = null,
) {
    val color = H3Palette.of(state)
    val shape = RoundedCornerShape(10.dp)
    val interaction = remember { MutableInteractionSource() }
    Box(Modifier.fillMaxWidth().aspectRatio(1f).appearOnce().pressScale(interaction)) {
        Box(
            Modifier.fillMaxSize().clip(shape).background(H3Palette.SurfaceCard)
                .then(
                    if (state == BlockState.PLANNED) Modifier.drawBehind {
                        drawRoundRect(color, style = Stroke(2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))),
                            cornerRadius = CornerRadius(10.dp.toPx()))
                    } else Modifier.border(1.5.dp, color, shape),
                )
                .combinedClickable(interactionSource = interaction, indication = LocalIndication.current,
                    onClick = onClick, onLongClick = onLongClick)
                .semantics { contentDescription = "Block $number, ${stateLabel(state)}" },
        ) {
            if (thumbRunId != null) {
                val local = remember(thumbRunId) { localFile(thumbRunId) }
                RunThumbnail(thumbRunId, videoUrl(thumbRunId), local, Modifier.fillMaxSize())
            }
            // Badge and caption share one column, so the text always starts below the number.
            Column(Modifier.fillMaxSize().padding(4.dp)) {
                Text("$number", color = H3Palette.TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(H3Palette.Midnight.copy(alpha = 0.6f), RoundedCornerShape(4.dp))
                        .padding(horizontal = 4.dp))
                if (thumbRunId == null && caption != null) {
                    Text(caption, color = H3Palette.TextSecondary, fontSize = 9.sp, lineHeight = 11.sp, maxLines = 4,
                        overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(start = 2.dp, end = 2.dp, top = 2.dp, bottom = 16.dp))
                }
            }
            val pulse = if (state == BlockState.REVIEW && !reducedMotion()) {
                val t = rememberInfiniteTransition(label = "pulse")
                val a by t.animateFloat(0.35f, 1f, infiniteRepeatable(tween(900), RepeatMode.Reverse), label = "a")
                a
            } else 1f
            Text(badge(state), color = color, fontSize = 13.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.align(Alignment.BottomEnd).padding(4.dp).alpha(pulse)
                    .background(H3Palette.Midnight.copy(alpha = 0.6f), RoundedCornerShape(4.dp)).padding(horizontal = 4.dp))
        }
        if (cutBefore) {
            Box(
                Modifier.align(Alignment.CenterStart).offset(x = (-13).dp).size(22.dp).clip(CircleShape)
                    .background(H3Palette.Cut).clickable(onClick = onCut)
                    .semantics { contentDescription = "Cut before block $number" },
                contentAlignment = Alignment.Center,
            ) { Text("⚡", fontSize = 12.sp) }
        }
    }
}
