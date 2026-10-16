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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.BlockItem
import com.al4xdev.h3.data.RoteiroItem
import com.al4xdev.h3.ui.theme.H3Palette

@Composable
fun StoryDetailScreen(
    roteiro: RoteiroItem,
    onReviewBlock: (blockId: String, runId: String, isAccepted: Boolean) -> Unit,
    onSaveBlock: (BlockItem) -> Unit,
    onStartBatch: () -> Unit
) {
    var editingBlock by remember { mutableStateOf<BlockItem?>(null) }

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
                                maxLines = 3
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
                                    onClick = { onReviewBlock(block.id, attempt.run_id, false) },
                                    colors = ButtonDefaults.buttonColors(containerColor = H3Palette.TealPrimary),
                                    shape = RoundedCornerShape(12.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("REVISAR VÍDEO AGORA", color = H3Palette.Midnight, fontWeight = FontWeight.Bold)
                                }
                            } else if (state == "accepted" && attempt != null) {
                                Spacer(modifier = Modifier.height(10.dp))
                                Button(
                                    onClick = { onReviewBlock(block.id, attempt.run_id, true) },
                                    colors = ButtonDefaults.buttonColors(containerColor = H3Palette.SurfaceElevated),
                                    shape = RoundedCornerShape(12.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("Assistir Bloco", color = H3Palette.TealPrimary)
                                }
                            } else {
                                Spacer(modifier = Modifier.height(10.dp))
                                Button(
                                    onClick = { editingBlock = block },
                                    colors = ButtonDefaults.buttonColors(containerColor = H3Palette.SurfaceElevated),
                                    shape = RoundedCornerShape(12.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("✏ Editar Bloco", color = H3Palette.TealPrimary)
                                }
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Button(
                onClick = onStartBatch,
                colors = ButtonDefaults.buttonColors(containerColor = H3Palette.TealPrimary),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 12.dp)
            ) {
                Text("⚡ GERAR LOTE NA GPU", color = H3Palette.Midnight, fontWeight = FontWeight.Bold)
            }
        }

        val currentEdit = editingBlock
        if (currentEdit != null) {
            var actionText by remember(currentEdit) { mutableStateOf(currentEdit.action) }
            var promptText by remember(currentEdit) { mutableStateOf(currentEdit.prompt) }
            var durationText by remember(currentEdit) { mutableStateOf(currentEdit.duration_seconds.toString()) }
            var seedText by remember(currentEdit) { mutableStateOf(currentEdit.seed.toString()) }

            AlertDialog(
                onDismissRequest = { editingBlock = null },
                title = { Text("Editar Bloco", color = H3Palette.TextPrimary) },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = actionText,
                            onValueChange = { actionText = it },
                            label = { Text("Ação") },
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedTextColor = H3Palette.TextPrimary,
                                unfocusedTextColor = H3Palette.TextPrimary,
                                focusedBorderColor = H3Palette.TealPrimary,
                                unfocusedBorderColor = H3Palette.Outline
                            )
                        )
                        OutlinedTextField(
                            value = promptText,
                            onValueChange = { promptText = it },
                            label = { Text("Prompt em Inglês") },
                            minLines = 3,
                            maxLines = 5,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedTextColor = H3Palette.TextPrimary,
                                unfocusedTextColor = H3Palette.TextPrimary,
                                focusedBorderColor = H3Palette.TealPrimary,
                                unfocusedBorderColor = H3Palette.Outline
                            )
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = durationText,
                                onValueChange = { durationText = it },
                                label = { Text("Duração (s)") },
                                modifier = Modifier.weight(1f),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedTextColor = H3Palette.TextPrimary,
                                    unfocusedTextColor = H3Palette.TextPrimary,
                                    focusedBorderColor = H3Palette.TealPrimary,
                                    unfocusedBorderColor = H3Palette.Outline
                                )
                            )
                            OutlinedTextField(
                                value = seedText,
                                onValueChange = { seedText = it },
                                label = { Text("Seed") },
                                modifier = Modifier.weight(1f),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedTextColor = H3Palette.TextPrimary,
                                    unfocusedTextColor = H3Palette.TextPrimary,
                                    focusedBorderColor = H3Palette.TealPrimary,
                                    unfocusedBorderColor = H3Palette.Outline
                                )
                            )
                        }
                    }
                },
                confirmButton = {
                    Button(
                        onClick = {
                            val dur = durationText.toDoubleOrNull() ?: currentEdit.duration_seconds
                            val sd = seedText.toLongOrNull() ?: currentEdit.seed
                            val updated = currentEdit.copy(
                                action = actionText,
                                prompt = promptText,
                                duration_seconds = dur,
                                seed = sd
                            )
                            onSaveBlock(updated)
                            editingBlock = null
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = H3Palette.TealPrimary)
                    ) {
                        Text("Salvar", color = H3Palette.Midnight)
                    }
                },
                dismissButton = {
                    TextButton(onClick = { editingBlock = null }) {
                        Text("Cancelar", color = H3Palette.TextSecondary)
                    }
                },
                containerColor = H3Palette.SurfaceCard
            )
        }
    }
}
