package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.BlockItem
import com.al4xdev.h3.data.RoteiroItem
import com.al4xdev.h3.ui.theme.H3Palette

@Composable
fun StoryDetailScreen(
    roteiro: RoteiroItem,
    onReviewBlock: (blockId: String, runId: String) -> Unit,
    onStartBatch: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(H3Palette.Midnight)
            .padding(horizontal = 16.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = 28.dp)
        ) {
            // Título Fullscreen (sem botão Voltar: o gesto de swipe lateral volta)
            Text(
                text = roteiro.name,
                color = H3Palette.TextPrimary,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = roteiro.idea,
                color = H3Palette.TextSecondary,
                fontSize = 13.sp,
                maxLines = 3
            )
            Spacer(modifier = Modifier.height(14.dp))

            Text(
                text = "LINHA DO TEMPO DOS BLOCOS",
                color = H3Palette.TextTertiary,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp
            )
            Spacer(modifier = Modifier.height(8.dp))

            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                itemsIndexed(roteiro.blocks) { index, block ->
                    val attempt = roteiro.attempts.lastOrNull { it.block_id == block.id }
                    val state = attempt?.state ?: "planejado"

                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(containerColor = H3Palette.SurfaceCard),
                        shape = RoundedCornerShape(16.dp)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = "${index + 1}. ${block.action}",
                                    color = H3Palette.TextPrimary,
                                    fontSize = 15.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    modifier = Modifier.weight(1f)
                                )
                                val (badgeText, badgeColor) = when (state) {
                                    "accepted" -> "ACEITO" to H3Palette.StateAccepted
                                    "ready_for_review" -> "REVISÃO" to H3Palette.TealPrimary
                                    "failed" -> "FALHOU" to H3Palette.StateError
                                    "interrupted" -> "PARADO" to H3Palette.StateError
                                    else -> "PLANEJADO" to H3Palette.StatePlanned
                                }
                                Text(
                                    text = badgeText,
                                    color = badgeColor,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }

                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = block.prompt,
                                color = H3Palette.TextSecondary,
                                fontSize = 12.sp,
                                maxLines = 2
                            )
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = "${block.duration_seconds} s · Seed: ${block.seed}",
                                color = H3Palette.TextTertiary,
                                fontSize = 11.sp
                            )

                            if (state == "ready_for_review" && attempt != null) {
                                Spacer(modifier = Modifier.height(10.dp))
                                Button(
                                    onClick = { onReviewBlock(block.id, attempt.run_id) },
                                    colors = ButtonDefaults.buttonColors(containerColor = H3Palette.TealPrimary),
                                    shape = RoundedCornerShape(12.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("REVISAR VÍDEO AGORA", color = H3Palette.Midnight, fontWeight = FontWeight.Bold)
                                }
                            } else if (state == "accepted" && attempt != null) {
                                Spacer(modifier = Modifier.height(10.dp))
                                Button(
                                    onClick = { onReviewBlock(block.id, attempt.run_id) },
                                    colors = ButtonDefaults.buttonColors(containerColor = H3Palette.SurfaceElevated),
                                    shape = RoundedCornerShape(12.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("Assistir Bloco", color = H3Palette.TealPrimary)
                                }
                            }
                        }
                    }
                }
            }

            // Ações no Rodapé
            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    onClick = onStartBatch,
                    colors = ButtonDefaults.buttonColors(containerColor = H3Palette.TealPrimary),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("⚡ GERAR LOTE NA GPU", color = H3Palette.Midnight, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}
