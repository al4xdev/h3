package com.al4xdev.h3mock

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.IOException

class MainActivity : AppCompatActivity() {

    private lateinit var tvTitle: TextView
    private lateinit var etBackendUrl: EditText
    private lateinit var btnConnect: Button
    private lateinit var tvStatus: TextView
    private lateinit var playerView: PlayerView
    private lateinit var btnPlayLatest: Button
    private lateinit var btnConcatAll: Button
    private lateinit var tvDownloadedList: TextView

    private var player: ExoPlayer? = null

    private val videoReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val runId = intent?.getStringExtra("run_id") ?: return
            val filePath = intent.getStringExtra("file_path") ?: return
            runOnUiThread {
                Toast.makeText(this@MainActivity, "Vídeo $runId baixado no celular!", Toast.LENGTH_LONG).show()
                refreshDownloadedList()
                playSingleFile(File(filePath))
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvTitle = findViewById(R.id.tvTitle)
        etBackendUrl = findViewById(R.id.etBackendUrl)
        btnConnect = findViewById(R.id.btnConnect)
        tvStatus = findViewById(R.id.tvStatus)
        playerView = findViewById(R.id.playerView)
        btnPlayLatest = findViewById(R.id.btnPlayLatest)
        btnConcatAll = findViewById(R.id.btnConcatAll)
        tvDownloadedList = findViewById(R.id.tvDownloadedList)

        checkPermissions()
        initPlayer()

        val prefs = getSharedPreferences(H3App.PREFS_NAME, Context.MODE_PRIVATE)
        val savedBackend = prefs.getString(H3App.KEY_BACKEND_URL, H3App.DEFAULT_BACKEND_URL)
        etBackendUrl.setText(savedBackend)

        updateStatusText()

        btnConnect.setOnClickListener {
            val url = etBackendUrl.text.toString().trim()
            if (url.isNotBlank()) {
                prefs.edit().putString(H3App.KEY_BACKEND_URL, url).apply()
                testBackendConnection(url)
            }
        }

        btnPlayLatest.setOnClickListener {
            playLatestVideo()
        }

        btnConcatAll.setOnClickListener {
            playAllVideosSequentially()
        }

        refreshDownloadedList()

        // Tratar intent de notificação
        val playFile = intent?.getStringExtra("play_file")
        if (!playFile.isNullOrBlank()) {
            playSingleFile(File(playFile))
        }
    }

    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(VideoDownloadWorker.ACTION_VIDEO_DOWNLOADED)
        ContextCompat.registerReceiver(this, videoReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    override fun onStop() {
        super.onStop()
        unregisterReceiver(videoReceiver)
    }

    override fun onDestroy() {
        super.onDestroy()
        player?.release()
        player = null
    }

    private fun checkPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 101)
            }
        }
    }

    private fun initPlayer() {
        player = ExoPlayer.Builder(this).build()
        playerView.player = player
    }

    private fun updateStatusText() {
        val prefs = getSharedPreferences(H3App.PREFS_NAME, Context.MODE_PRIVATE)
        val token = prefs.getString(H3App.KEY_FCM_TOKEN, null)
        val tokenDisplay = if (token != null) "Ativo (${token.take(8)}...${token.takeLast(6)})" else "Aguardando geração..."
        tvStatus.text = "FCM Token: $tokenDisplay\nBackend: ${prefs.getString(H3App.KEY_BACKEND_URL, H3App.DEFAULT_BACKEND_URL)}"
    }

    private fun testBackendConnection(url: String) {
        tvStatus.text = "Testando conexão com $url/notifications/config..."
        val request = Request.Builder().url("$url/notifications/config").build()

        OkHttpClient().newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread {
                    tvStatus.text = "Erro ao conectar no H3: ${e.message}"
                    Toast.makeText(this@MainActivity, "Falha de rede: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onResponse(call: Call, response: Response) {
                val ok = response.isSuccessful
                val body = response.body?.string() ?: ""
                runOnUiThread {
                    if (ok) {
                        tvStatus.text = "Conectado ao H3 com sucesso! Config: $body"
                        val prefs = getSharedPreferences(H3App.PREFS_NAME, Context.MODE_PRIVATE)
                        val token = prefs.getString(H3App.KEY_FCM_TOKEN, null)
                        if (token != null) {
                            H3App.registerTokenWithBackend(this@MainActivity, token, url)
                        }
                    } else {
                        tvStatus.text = "H3 respondeu com erro HTTP ${response.code}"
                    }
                }
            }
        })
    }

    private fun refreshDownloadedList() {
        val dir = VideoDownloadWorker.getVideoDir(this)
        val files = dir.listFiles { f -> f.extension == "mp4" }?.sortedByDescending { it.lastModified() } ?: emptyList()

        if (files.isEmpty()) {
            tvDownloadedList.text = "Nenhum vídeo baixado ainda.\nEnvie uma geração de vídeo no PC para ver o download automático!"
        } else {
            val sb = StringBuilder()
            files.forEachIndexed { index, file ->
                val sizeKb = file.length() / 1024
                sb.append("${index + 1}. ${file.name} (${sizeKb} KB)\n")
            }
            tvDownloadedList.text = sb.toString()
        }
    }

    private fun playSingleFile(file: File) {
        if (!file.exists()) return
        player?.apply {
            stop()
            clearMediaItems()
            setMediaItem(MediaItem.fromUri(Uri.fromFile(file)))
            prepare()
            playWhenReady = true
        }
    }

    private fun playLatestVideo() {
        val dir = VideoDownloadWorker.getVideoDir(this)
        val files = dir.listFiles { f -> f.extension == "mp4" }?.sortedByDescending { it.lastModified() } ?: emptyList()
        val latest = files.firstOrNull()
        if (latest != null) {
            playSingleFile(latest)
            Toast.makeText(this, "Tocando ${latest.name}", Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(this, "Nenhum vídeo disponível no celular", Toast.LENGTH_SHORT).show()
        }
    }

    private fun playAllVideosSequentially() {
        val dir = VideoDownloadWorker.getVideoDir(this)
        val files = dir.listFiles { f -> f.extension == "mp4" }?.sortedBy { it.lastModified() } ?: emptyList()
        if (files.isEmpty()) {
            Toast.makeText(this, "Nenhum vídeo disponível para concatenar", Toast.LENGTH_SHORT).show()
            return
        }

        player?.apply {
            stop()
            clearMediaItems()
            files.forEach { file ->
                addMediaItem(MediaItem.fromUri(Uri.fromFile(file)))
            }
            prepare()
            playWhenReady = true
        }
        Toast.makeText(this, "Tocando sequência de ${files.size} chunks sem corte!", Toast.LENGTH_SHORT).show()
    }
}
