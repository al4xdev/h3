package com.al4xdev.h3.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.ui.theme.H3Palette
import kotlin.math.roundToInt

@Composable
fun CreateStoryScreen(
    isLoading: Boolean,
    onCreateWithGrok: (name: String, idea: String, count: Int) -> Unit
) {
    var name by remember { mutableStateOf("") }
    var idea by remember { mutableStateOf("") }
    var blockCount by remember { mutableFloatStateOf(3f) }

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
                text = "Novo Roteiro",
                color = H3Palette.TextPrimary,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "Descreva sua ideia em linguagem natural. O Grok vai dividir as cenas em blocos ordenados para você.",
                color = H3Palette.TextSecondary,
                fontSize = 13.sp
            )
            Spacer(modifier = Modifier.height(16.dp))

            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text("Título da história") },
                placeholder = { Text("Ex: Dança sob a chuva de neon") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = H3Palette.TealPrimary,
                    unfocusedBorderColor = H3Palette.Outline,
                    focusedTextColor = H3Palette.TextPrimary,
                    unfocusedTextColor = H3Palette.TextPrimary
                ),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(modifier = Modifier.height(12.dp))

            OutlinedTextField(
                value = idea,
                onValueChange = { idea = it },
                label = { Text("Descreva sua ideia") },
                placeholder = { Text("Ex: Uma mulher de vestido preto começa a dançar, dá um salto e seu vestido muda para vermelho...") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = H3Palette.TealPrimary,
                    unfocusedBorderColor = H3Palette.Outline,
                    focusedTextColor = H3Palette.TextPrimary,
                    unfocusedTextColor = H3Palette.TextPrimary
                ),
                shape = RoundedCornerShape(12.dp),
                minLines = 4,
                maxLines = 6,
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(modifier = Modifier.height(16.dp))

            Text(
                text = "Quantidade de blocos: ${blockCount.roundToInt()}",
                color = H3Palette.TextPrimary,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold
            )
            Slider(
                value = blockCount,
                onValueChange = { blockCount = it },
                valueRange = 1f..10f,
                steps = 8,
                colors = SliderDefaults.colors(
                    thumbColor = H3Palette.TealPrimary,
                    activeTrackColor = H3Palette.TealPrimary,
                    inactiveTrackColor = H3Palette.Outline
                )
            )

            Spacer(modifier = Modifier.weight(1f))

            Button(
                onClick = {
                    if (name.isNotBlank() && idea.isNotBlank()) {
                        onCreateWithGrok(name, idea, blockCount.roundToInt())
                    }
                },
                enabled = !isLoading && name.isNotBlank() && idea.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = H3Palette.TealPrimary),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 24.dp)
            ) {
                Text(
                    text = if (isLoading) "Grok planejando cenas..." else "DIVIDIR E PLANEJAR COM GROK",
                    color = H3Palette.Midnight,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp
                )
            }
        }
    }
}
