package com.al4xdev.h3.ui.screens

import android.content.Context
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.al4xdev.h3.H3App
import com.al4xdev.h3.service.VideoDownloadWorker
import com.al4xdev.h3.ui.theme.H3Palette

@Composable
fun SettingsScreen(
    currentUrl: String,
    fcmToken: String?,
    onSaveUrl: (String) -> Unit
) {
    val context = LocalContext.current
    var url by remember { mutableStateOf(currentUrl) }
    var cacheCount by remember {
        val files = VideoDownloadWorker.getVideoDir(context).listFiles { f -> f.extension == "mp4" }
        mutableStateOf(files?.size ?: 0)
    }

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
                text = "Ajustes do Estúdio",
                color = H3Palette.TextPrimary,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "Deslize da borda esquerda para voltar a qualquer momento.",
                color = H3Palette.TextSecondary,
                fontSize = 12.sp
            )
            Spacer(modifier = Modifier.height(20.dp))

            Text(
                text = "SERVIDOR DO PC (Rede Local)",
                color = H3Palette.TextTertiary,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(6.dp))

            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text("Endereço do PC") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = H3Palette.TealPrimary,
                    unfocusedBorderColor = H3Palette.Outline,
                    focusedTextColor = H3Palette.TextPrimary,
                    unfocusedTextColor = H3Palette.TextPrimary
                ),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(modifier = Modifier.height(8.dp))
            Button(
                onClick = { onSaveUrl(url.trim()) },
                colors = ButtonDefaults.buttonColors(containerColor = H3Palette.SurfaceCard),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Salvar e Conectar ao PC", color = H3Palette.TealPrimary)
            }

            Spacer(modifier = Modifier.height(24.dp))

            Text(
                text = "NOTIFICAÇÕES PUSH (Firebase FCM)",
                color = H3Palette.TextTertiary,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = if (fcmToken != null) "Status: Ativo (${fcmToken.take(8)}...${fcmToken.takeLast(6)})" else "Aguardando geração do token...",
                color = H3Palette.TextSecondary,
                fontSize = 13.sp
            )

            Spacer(modifier = Modifier.height(24.dp))

            Text(
                text = "ARMAZENAMENTO LOCAL DE VÍDEOS",
                color = H3Palette.TextTertiary,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "$cacheCount vídeos baixados no celular",
                color = H3Palette.TextSecondary,
                fontSize = 13.sp
            )
            Spacer(modifier = Modifier.height(8.dp))
            Button(
                onClick = {
                    val dir = VideoDownloadWorker.getVideoDir(context)
                    dir.listFiles()?.forEach { it.delete() }
                    cacheCount = 0
                },
                colors = ButtonDefaults.buttonColors(containerColor = H3Palette.SurfaceCard),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Limpar Cache Local", color = H3Palette.StateError)
            }
        }
    }
}
