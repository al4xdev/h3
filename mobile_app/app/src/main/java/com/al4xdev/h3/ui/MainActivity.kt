package com.al4xdev.h3.ui

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.al4xdev.h3.H3App
import com.al4xdev.h3.data.BatchStatus
import com.al4xdev.h3.data.BlockItem
import com.al4xdev.h3.data.H3ApiClient
import com.al4xdev.h3.data.RoteiroItem
import com.al4xdev.h3.service.VideoDownloadWorker
import com.al4xdev.h3.ui.gestures.FullscreenWorkspace
import com.al4xdev.h3.ui.screens.CreateStoryScreen
import com.al4xdev.h3.ui.screens.LibraryScreen
import com.al4xdev.h3.ui.screens.ProposalReviewScreen
import com.al4xdev.h3.ui.screens.SettingsScreen
import com.al4xdev.h3.ui.screens.StoryDetailScreen
import com.al4xdev.h3.ui.screens.VideoReviewScreen
import com.al4xdev.h3.ui.theme.H3Palette
import com.al4xdev.h3.ui.theme.H3Theme
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

sealed class Screen {
    data object Library : Screen()
    data class StoryDetail(val roteiroId: String) : Screen()
    data object CreateStory : Screen()
    data class ProposalReview(val roteiroId: String, val name: String, val blocks: List<BlockItem>, val revision: Int, val idea: String) : Screen()
    data class VideoReview(val runId: String, val videoFile: File?, val videoUrl: String, val prompt: String) : Screen()
    data object Settings : Screen()
}

class MainActivity : ComponentActivity() {

    private lateinit var apiClient: H3ApiClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        apiClient = H3ApiClient(this)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 101)
            }
        }

        setContent {
            H3Theme {
                H3AppNavigation(apiClient, this)
            }
        }
    }
}

@Composable
fun H3AppNavigation(apiClient: H3ApiClient, context: Context) {
    val coroutineScope = rememberCoroutineScope()
    val screenStack = remember { mutableStateListOf<Screen>(Screen.Library) }

    var roteiros by remember { mutableStateOf<List<RoteiroItem>>(emptyList()) }
    var activeBatch by remember { mutableStateOf<BatchStatus?>(null) }
    var isLoading by remember { mutableStateOf(false) }

    val prefs = context.getSharedPreferences(H3App.PREFS_NAME, Context.MODE_PRIVATE)
    var currentUrl by remember { mutableStateOf(prefs.getString(H3App.KEY_BACKEND_URL, H3App.DEFAULT_BACKEND_URL) ?: H3App.DEFAULT_BACKEND_URL) }
    val fcmToken = prefs.getString(H3App.KEY_FCM_TOKEN, null)

    fun refreshData() {
        coroutineScope.launch {
            roteiros = apiClient.getRoteiros()
            activeBatch = apiClient.getCurrentBatch()
        }
    }

    LaunchedEffect(Unit) {
        refreshData()
        while (true) {
            delay(5000)
            activeBatch = apiClient.getCurrentBatch()
        }
    }

    // Broadcast receiver para atualizar quando um vídeo termina de baixar
    DisposableEffect(Unit) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                refreshData()
            }
        }
        val filter = IntentFilter(VideoDownloadWorker.ACTION_VIDEO_DOWNLOADED)
        ContextCompat.registerReceiver(context, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
        onDispose {
            context.unregisterReceiver(receiver)
        }
    }

    val currentScreen = screenStack.lastOrNull() ?: Screen.Library

    Box(modifier = Modifier.fillMaxSize().background(H3Palette.Midnight)) {
        FullscreenWorkspace(
            canDismiss = screenStack.size > 1,
            onDismiss = {
                if (screenStack.size > 1) {
                    screenStack.removeAt(screenStack.size - 1)
                }
            }
        ) {
            when (currentScreen) {
                is Screen.Library -> {
                    LibraryScreen(
                        roteiros = roteiros,
                        activeBatch = activeBatch,
                        onSelectRoteiro = { roteiro ->
                            screenStack.add(Screen.StoryDetail(roteiro.id))
                        },
                        onCreateNew = {
                            screenStack.add(Screen.CreateStory)
                        },
                        onOpenSettings = {
                            screenStack.add(Screen.Settings)
                        }
                    )
                }

                is Screen.StoryDetail -> {
                    val roteiro = roteiros.find { it.id == currentScreen.roteiroId }
                    if (roteiro != null) {
                        StoryDetailScreen(
                            roteiro = roteiro,
                            onReviewBlock = { blockId, runId ->
                                val file = File(VideoDownloadWorker.getVideoDir(context), "$runId.mp4")
                                val videoUrl = "${currentUrl}/runs/$runId/video"
                                val block = roteiro.blocks.find { it.id == blockId }
                                screenStack.add(
                                    Screen.VideoReview(
                                        runId = runId,
                                        videoFile = if (file.exists()) file else null,
                                        videoUrl = videoUrl,
                                        prompt = block?.prompt ?: ""
                                    )
                                )
                            },
                            onStartBatch = {
                                coroutineScope.launch {
                                    val ok = apiClient.startBatch(roteiro.id, roteiro.revision)
                                    if (ok) {
                                        Toast.makeText(context, "Lote iniciado na GPU!", Toast.LENGTH_SHORT).show()
                                        refreshData()
                                    } else {
                                        Toast.makeText(context, "Falha ao iniciar lote", Toast.LENGTH_SHORT).show()
                                    }
                                }
                            }
                        )
                    } else {
                        screenStack.removeAt(screenStack.size - 1)
                    }
                }

                is Screen.CreateStory -> {
                    CreateStoryScreen(
                        isLoading = isLoading,
                        onCreateWithGrok = { name, idea, count ->
                            coroutineScope.launch {
                                isLoading = true
                                val newStory = apiClient.createRoteiro(name, idea)
                                if (newStory != null) {
                                    val proposed = apiClient.proposeWithGrok(newStory.id, newStory.revision, count)
                                    isLoading = false
                                    if (proposed.isNotEmpty()) {
                                        screenStack.add(
                                            Screen.ProposalReview(
                                                roteiroId = newStory.id,
                                                name = name,
                                                blocks = proposed,
                                                revision = newStory.revision,
                                                idea = idea
                                            )
                                        )
                                    } else {
                                        Toast.makeText(context, "Falha na proposta do Grok", Toast.LENGTH_SHORT).show()
                                    }
                                } else {
                                    isLoading = false
                                    Toast.makeText(context, "Erro ao criar roteiro", Toast.LENGTH_SHORT).show()
                                }
                            }
                        }
                    )
                }

                is Screen.ProposalReview -> {
                    ProposalReviewScreen(
                        storyName = currentScreen.name,
                        proposedBlocks = currentScreen.blocks,
                        onAdopt = {
                            coroutineScope.launch {
                                val ok = apiClient.adoptBlocks(
                                    roteiroId = currentScreen.roteiroId,
                                    revision = currentScreen.revision,
                                    name = currentScreen.name,
                                    idea = currentScreen.idea,
                                    blocks = currentScreen.blocks
                                )
                                if (ok) {
                                    Toast.makeText(context, "Roteiro adotado com sucesso!", Toast.LENGTH_SHORT).show()
                                    refreshData()
                                    // Voltar à biblioteca
                                    screenStack.clear()
                                    screenStack.add(Screen.Library)
                                    screenStack.add(Screen.StoryDetail(currentScreen.roteiroId))
                                } else {
                                    Toast.makeText(context, "Erro ao adotar roteiro", Toast.LENGTH_SHORT).show()
                                }
                            }
                        }
                    )
                }

                is Screen.VideoReview -> {
                    VideoReviewScreen(
                        runId = currentScreen.runId,
                        videoFile = currentScreen.videoFile,
                        videoUrl = currentScreen.videoUrl,
                        prompt = currentScreen.prompt,
                        onAccept = {
                            coroutineScope.launch {
                                val ok = apiClient.decideRun(currentScreen.runId, true)
                                if (ok) {
                                    Toast.makeText(context, "Bloco Aceito!", Toast.LENGTH_SHORT).show()
                                    refreshData()
                                    screenStack.removeAt(screenStack.size - 1)
                                }
                            }
                        },
                        onReject = {
                            coroutineScope.launch {
                                val ok = apiClient.decideRun(currentScreen.runId, false)
                                if (ok) {
                                    Toast.makeText(context, "Bloco Recusado", Toast.LENGTH_SHORT).show()
                                    refreshData()
                                    screenStack.removeAt(screenStack.size - 1)
                                }
                            }
                        }
                    )
                }

                is Screen.Settings -> {
                    SettingsScreen(
                        currentUrl = currentUrl,
                        fcmToken = fcmToken,
                        onSaveUrl = { newUrl ->
                            currentUrl = newUrl
                            prefs.edit().putString(H3App.KEY_BACKEND_URL, newUrl).apply()
                            if (fcmToken != null) {
                                H3App.registerTokenWithBackend(context, fcmToken, newUrl)
                            }
                            Toast.makeText(context, "Configuração salva!", Toast.LENGTH_SHORT).show()
                        }
                    )
                }
            }
        }
    }
}
