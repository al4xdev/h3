package com.al4xdev.h3.service

import android.app.PendingIntent
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.al4xdev.h3.H3App
import com.al4xdev.h3.data.isCanonicalUuid
import com.al4xdev.h3.ui.MainActivity
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Downloads a run clip into app storage (offline review after a push) or an assembly into the
 * phone gallery (Movies/H3 Studio). Bounded retries: a 4xx is final, never an endless loop.
 */
class VideoDownloadWorker(private val context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    companion object {
        const val KEY_ID = "run_id"
        const val KEY_URL = "download_url"
        const val KEY_GALLERY = "gallery"
        const val KEY_ROTEIRO = "roteiro_id"
        private const val MAX_ATTEMPTS = 3
        private const val TAG = "VideoDownloadWorker"

        fun videoDir(context: Context): File = File(context.filesDir, "h3_videos").apply { mkdirs() }

        fun localRunVideo(context: Context, runId: String): File? =
            File(videoDir(context), "$runId.mp4").takeIf { it.isFile && it.length() > 0 }

        /** Push download of a run: the URL is always derived from the run ID (`/runs/{id}/video`). */
        fun enqueueRun(context: Context, baseUrl: String, runId: String) {
            if (!isCanonicalUuid(runId)) return
            enqueue(context, runId, "${baseUrl.trimEnd('/')}/runs/$runId/video", gallery = false, roteiroId = null)
        }

        fun enqueueAssembly(context: Context, baseUrl: String, assemblyId: String, roteiroId: String?) {
            if (!isCanonicalUuid(assemblyId)) return
            enqueue(context, assemblyId, "${baseUrl.trimEnd('/')}/assemblies/$assemblyId/video", gallery = true, roteiroId = roteiroId)
        }

        private fun enqueue(context: Context, id: String, url: String, gallery: Boolean, roteiroId: String?) {
            val data = Data.Builder().putString(KEY_ID, id).putString(KEY_URL, url).putBoolean(KEY_GALLERY, gallery)
                .putString(KEY_ROTEIRO, roteiroId).build()
            val request = OneTimeWorkRequestBuilder<VideoDownloadWorker>().setInputData(data).build()
            WorkManager.getInstance(context).enqueueUniqueWork("download-$id", ExistingWorkPolicy.KEEP, request)
        }

        fun storedBytes(context: Context): Pair<Int, Long> {
            val files = videoDir(context).listFiles().orEmpty().filter { it.name.endsWith(".mp4") }
            return files.size to files.sumOf { it.length() }
        }

        fun clearStored(context: Context) {
            videoDir(context).listFiles()?.forEach { it.delete() }
        }
    }

    private val http = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS).build()

    override suspend fun doWork(): Result {
        val id = inputData.getString(KEY_ID) ?: return Result.failure()
        val url = inputData.getString(KEY_URL) ?: return Result.failure()
        val gallery = inputData.getBoolean(KEY_GALLERY, false)
        return try {
            http.newCall(Request.Builder().url(url).build()).execute().use { response ->
                if (response.code in 400..499) {
                    Log.w(TAG, "Download recusado ($url): HTTP ${response.code}")
                    return Result.failure()
                }
                if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
                val body = response.body ?: return Result.failure()
                if (gallery) saveToGallery(id, body.byteStream()) else saveRun(id, body.byteStream())
            }
            notifyDone(id, gallery)
            Result.success()
        } catch (e: IOException) {
            Log.w(TAG, "Download falhou ($url): ${e.message}")
            if (runAttemptCount + 1 >= MAX_ATTEMPTS) Result.failure() else Result.retry()
        }
    }

    private fun saveRun(runId: String, input: java.io.InputStream) {
        val out = File(videoDir(context), "$runId.mp4")
        val tmp = File(videoDir(context), "$runId.part")
        input.use { i -> tmp.outputStream().use { i.copyTo(it) } }
        if (!tmp.renameTo(out)) throw IOException("não foi possível publicar $out")
    }

    private fun saveToGallery(id: String, input: java.io.InputStream) {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, "montagem-${id.take(8)}.mp4")
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, Environment.DIRECTORY_MOVIES + "/H3 Studio")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values) ?: throw IOException("MediaStore recusou")
        try {
            input.use { i -> resolver.openOutputStream(uri)?.use { i.copyTo(it) } ?: throw IOException("sem saída") }
            resolver.update(uri, ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }, null, null)
        } catch (e: IOException) {
            resolver.delete(uri, null, null)
            throw e
        }
    }

    private fun notifyDone(id: String, gallery: Boolean) {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            if (gallery) inputData.getString(KEY_ROTEIRO)?.let { putExtra(MainActivity.EXTRA_ROTEIRO_ID, it) }
            else putExtra(MainActivity.EXTRA_RUN_ID, id)
        }
        val pending = PendingIntent.getActivity(context, id.hashCode() + 1, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, H3App.CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle(if (gallery) "H3 · Montagem salva" else "H3 · Vídeo no aparelho")
            .setContentText(if (gallery) "Em Filmes/H3 Studio." else "Bloco ${id.take(8)} disponível offline. Toque para revisar.")
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(id.hashCode() + 1, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "Sem permissão de notificação")
        }
    }
}
