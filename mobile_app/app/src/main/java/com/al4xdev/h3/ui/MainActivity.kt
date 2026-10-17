package com.al4xdev.h3.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.al4xdev.h3.data.isCanonicalUuid
import com.al4xdev.h3.ui.gestures.FullscreenWorkspace
import com.al4xdev.h3.ui.screens.AssemblyScreen
import com.al4xdev.h3.ui.screens.BlockScreen
import com.al4xdev.h3.ui.screens.InsertScreen
import com.al4xdev.h3.ui.screens.LibraryScreen
import com.al4xdev.h3.ui.screens.NewRoteiroScreen
import com.al4xdev.h3.ui.screens.RedoScreen
import com.al4xdev.h3.ui.screens.ReviewScreen
import com.al4xdev.h3.ui.screens.RoteiroScreen
import com.al4xdev.h3.ui.screens.SettingsScreen
import com.al4xdev.h3.ui.screens.WatchScreen
import com.al4xdev.h3.ui.theme.H3Palette
import com.al4xdev.h3.ui.theme.H3Theme

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 101)
        }
        // A restored activity already has its back stack; only a fresh launch reads the extras.
        if (savedInstanceState == null) handleIntent(intent)
        setContent { H3Theme { H3Root(vm) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    override fun onStart() {
        super.onStart()
        vm.onForeground()
    }

    override fun onStop() {
        vm.onBackground()
        super.onStop()
    }

    private fun handleIntent(intent: Intent?) {
        intent ?: return
        val runId = intent.getStringExtra(EXTRA_RUN_ID)?.takeIf(::isCanonicalUuid)
        val roteiroId = intent.getStringExtra(EXTRA_ROTEIRO_ID)?.takeIf(::isCanonicalUuid)
        if (runId != null || roteiroId != null) vm.openFromNotification(runId, roteiroId)
        intent.removeExtra(EXTRA_RUN_ID)
        intent.removeExtra(EXTRA_ROTEIRO_ID)
    }

    companion object {
        const val EXTRA_RUN_ID = "run_id"
        const val EXTRA_ROTEIRO_ID = "roteiro_id"
    }
}

@Composable
fun H3Root(vm: AppViewModel) {
    val snackbar = remember { SnackbarHostState() }
    val notice = vm.notice
    LaunchedEffect(notice) {
        if (notice != null) {
            snackbar.showSnackbar(notice, withDismissAction = true)
            vm.clearNotice()
        }
    }

    // Keeps rememberSaveable state (fields, scroll) of every screen in the back AND forward stacks.
    val holder = rememberSaveableStateHolder()
    val seen = remember { mutableSetOf<String>() }
    val live = vm.nav.liveKeys()
    LaunchedEffect(live) {
        (seen - live).forEach { holder.removeState(it); seen.remove(it) }
    }

    Box(Modifier.fillMaxSize().background(H3Palette.Midnight)) {
        FullscreenWorkspace(
            stack = vm.stack,
            nextForward = vm.nav.nextForward,
            keyOf = Nav::key,
            onBack = { vm.back() },
            onForward = vm::forward,
        ) { screen ->
            val key = Nav.key(screen)
            seen += key
            holder.SaveableStateProvider(key) {
                Column(Modifier.fillMaxSize().background(H3Palette.Midnight).navigationBarsPadding().imePadding()) {
                    ScreenContent(vm, screen)
                }
            }
        }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding())
    }

    vm.invalidAnswer?.let { raw ->
        AlertDialog(
            onDismissRequest = vm::dismissInvalid,
            title = { Text("Resposta inválida do Grok") },
            text = {
                SelectionContainer {
                    Text(raw, modifier = Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()))
                }
            },
            confirmButton = { TextButton(onClick = vm::dismissInvalid) { Text("Fechar") } },
            containerColor = H3Palette.SurfaceElevated,
        )
    }
}

@Composable
private fun ScreenContent(vm: AppViewModel, screen: Screen) {
    when (screen) {
        Screen.Library -> LibraryScreen(vm)
        Screen.NewRoteiro -> NewRoteiroScreen(vm)
        Screen.Settings -> SettingsScreen(vm)
        is Screen.Roteiro -> RoteiroScreen(vm, screen.roteiroId)
        is Screen.Block -> BlockScreen(vm, screen.roteiroId, screen.blockId)
        is Screen.Insert -> InsertScreen(vm, screen.roteiroId, screen.afterBlockId)
        is Screen.Redo -> RedoScreen(vm, screen.roteiroId, screen.blockId)
        is Screen.Review -> ReviewScreen(vm, screen.roteiroId, screen.blockId, screen.runId)
        is Screen.Assembly -> AssemblyScreen(vm, screen.roteiroId)
        is Screen.Watch -> WatchScreen(vm, screen.roteiroId, screen.fromBlockId)
    }
}

/** ⚙ from any screen except Ajustes itself. */
fun AppViewModel.settingsAction(): (() -> Unit)? = if (top == Screen.Settings) null else ({ push(Screen.Settings) })
