package com.al4xdev.h3.service

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.al4xdev.h3.H3App
import com.al4xdev.h3.ui.MainActivity
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream

class VideoDownloadWorker(
    private val context: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(context, workerParams) {

    companion object {
        const val KEY_RUN_ID = "run_id"
        const val KEY_DOWNLOAD_URL = "download_url"
        const val ACTION_VIDEO_DOWNLOADED = "com.al4xdev.h3.VIDEO_DOWNLOADED"
        private const val TAG = "VideoDownloadWorker"

        fun getVideoDir(context: Context): File {
            val dir = File(context.filesDir, "h3_videos")
            if (!dir.exists()) dir.mkdirs()
            return dir
        }
    }

    override suspend fun doWork(): Result {
        val runId = inputData.getString(KEY_RUN_ID) ?: return Result.failure()
        val downloadUrl = inputData.getString(KEY_DOWNLOAD_URL) ?: return Result.failure()

        Log.i(TAG, "Baixando vídeo $runId de $downloadUrl")

        val client = OkHttpClient()
        val request = Request.Builder().url(downloadUrl).build()

        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) return Result.retry()

            val body = response.body ?: return Result.failure()
            val outputFile = File(getVideoDir(context), "$runId.mp4")
            val tempFile = File(getVideoDir(context), "$runId.tmp")

            body.byteStream().use { input ->
                FileOutputStream(tempFile).use { output ->
                    input.copyTo(output)
                }
            }
            tempFile.renameTo(outputFile)

            Log.i(TAG, "Salvo: ${outputFile.absolutePath} (${outputFile.length()} bytes)")
            showDownloadedNotification(runId, outputFile.absolutePath)

            val broadcast = Intent(ACTION_VIDEO_DOWNLOADED).apply {
                putExtra("run_id", runId)
                putExtra("file_path", outputFile.absolutePath)
                setPackage(context.packageName)
            }
            context.sendBroadcast(broadcast)

            return Result.success()
        } catch (e: Exception) {
            Log.e(TAG, "Erro download: ${e.message}")
            return Result.retry()
        }
    }

    private fun showDownloadedNotification(runId: String, filePath: String) {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("play_file", filePath)
            putExtra("run_id", runId)
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            runId.hashCode() + 1,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(context, H3App.CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("H3 · Vídeo Baixado")
            .setContentText("Chunk ${runId.take(8)} pronto no aparelho. Toque para assistir.")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        try {
            NotificationManagerCompat.from(context).notify(runId.hashCode() + 1, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "Sem permissão POST_NOTIFICATIONS")
        }
    }
}
