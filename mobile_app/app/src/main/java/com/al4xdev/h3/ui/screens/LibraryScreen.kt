package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.data.BatchStatus
import com.al4xdev.h3.data.RoteiroItem
import com.al4xdev.h3.ui.theme.H3Palette

@Composable
fun LibraryScreen(
    roteiros: List<RoteiroItem>,
    activeBatch: BatchStatus?,
    onSelectRoteiro: (RoteiroItem) -> Unit,
    onCreateNew: () -> Unit,
    onOpenSettings: () -> Unit
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
            // Top Header: Title & Settings (sem botão voltar, é a home)
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "H3 Studio",
                    color = H3Palette.TextPrimary,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold
                )
                Button(
                    onClick = onOpenSettings,
                    colors = ButtonDefaults.buttonColors(containerColor = H3Palette.SurfaceCard),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Text("⚙ Ajustes", color = H3Palette.TealPrimary, fontSize = 12.sp)
                }
            }

            // Card de Lote Ativo no PC (se houver)
            if (activeBatch != null && activeBatch.state == "active") {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp),
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
                                text = "⏵ LOTE EM EXECUÇÃO NO PC",
                                color = H3Palette.TealPrimary,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold
                            )
                            Text(
                                text = "Ativo",
                                color = H3Palette.StateAccepted,
                                fontSize = 11.sp
                            )
                        }
                        Spacer(modifier = Modifier.height(6.dp))
                        val phaseText = when (activeBatch.phase) {
                            "improving" -> "Grok melhorando o prompt..."
                            "generating" -> "ComfyUI gerando vídeo na GPU..."
                            "accepting" -> "Aceitação intermediária..."
                            else -> "Processando..."
                        }
                        Text(
                            text = phaseText,
                            color = H3Palette.TextSecondary,
                            fontSize = 13.sp
                        )
                        Spacer(modifier = Modifier.height(10.dp))
                        LinearProgressIndicator(
                            modifier = Modifier.fillMaxWidth(),
                            color = H3Palette.TealPrimary,
                            trackColor = H3Palette.Outline
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "MEUS ROTEIROS",
                color = H3Palette.TextTertiary,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp
            )
            Spacer(modifier = Modifier.height(8.dp))

            if (roteiros.isEmpty()) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "Nenhum roteiro encontrado no PC.\nToque abaixo para criar o primeiro!",
                        color = H3Palette.TextSecondary,
                        fontSize = 14.sp,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center
                    )
                }
            } else {
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    items(roteiros) { roteiro ->
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { onSelectRoteiro(roteiro) },
                            colors = CardDefaults.cardColors(containerColor = H3Palette.SurfaceCard),
                            shape = RoundedCornerShape(16.dp)
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = roteiro.name,
                                    color = H3Palette.TextPrimary,
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.SemiBold
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = roteiro.idea,
                                    color = H3Palette.TextSecondary,
                                    fontSize = 13.sp,
                                    maxLines = 2
                                )
                                Spacer(modifier = Modifier.height(10.dp))
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween
                                ) {
                                    val acceptedCount = roteiro.attempts.count { it.state == "accepted" }
                                    Text(
                                        text = "$acceptedCount de ${roteiro.blocks.size} blocos aceitos",
                                        color = H3Palette.TealSecondary,
                                        fontSize = 12.sp
                                    )
                                    val hasReview = roteiro.attempts.any { it.state == "ready_for_review" }
                                    if (hasReview) {
                                        Text(
                                            text = "● Revisão pendente",
                                            color = H3Palette.TealPrimary,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Bold
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // FAB + Novo Roteiro
        FloatingActionButton(
            onClick = onCreateNew,
            containerColor = H3Palette.TealPrimary,
            contentColor = H3Palette.Midnight,
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(bottom = 24.dp)
        ) {
            Text("+ NOVO ROTEIRO", fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 16.dp))
        }
    }
}
