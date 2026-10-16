package com.al4xdev.h3.service

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.Data
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.al4xdev.h3.H3App
import com.al4xdev.h3.ui.MainActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class H3MessagingService : FirebaseMessagingService() {

    companion object {
        private const val TAG = "H3MessagingService"
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.i(TAG, "Novo token FCM: $token")
        getSharedPreferences(H3App.PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(H3App.KEY_FCM_TOKEN, token)
            .apply()

        H3App.registerTokenWithBackend(this, token)
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)
        Log.i(TAG, "Push FCM recebido: ${remoteMessage.data}")

        val data = remoteMessage.data
        val runId = data["run_id"] ?: "run-${System.currentTimeMillis()}"
        val state = data["state"] ?: ""
        val videoUrl = data["video_url"] ?: ""

        val title = remoteMessage.notification?.title ?: "H3 Studio · Vídeo Pronto"
        val body = remoteMessage.notification?.body ?: "Chunk concluído."

        if (state == "ready_for_review" && videoUrl.isNotBlank()) {
            val prefs = getSharedPreferences(H3App.PREFS_NAME, Context.MODE_PRIVATE)
            val backendUrl = prefs.getString(H3App.KEY_BACKEND_URL, H3App.DEFAULT_BACKEND_URL) ?: H3App.DEFAULT_BACKEND_URL
            val fullDownloadUrl = if (videoUrl.startsWith("http")) videoUrl else "$backendUrl$videoUrl"

            val workData = Data.Builder()
                .putString(VideoDownloadWorker.KEY_RUN_ID, runId)
                .putString(VideoDownloadWorker.KEY_DOWNLOAD_URL, fullDownloadUrl)
                .build()

            val downloadWork = OneTimeWorkRequestBuilder<VideoDownloadWorker>()
                .setInputData(workData)
                .build()

            WorkManager.getInstance(applicationContext).enqueue(downloadWork)

            showNotification(title = title, body = "$body Baixando no celular...", runId = runId)
        } else {
            showNotification(title = title, body = body, runId = runId)
        }
    }

    private fun showNotification(title: String, body: String, runId: String) {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("run_id", runId)
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            runId.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, H3App.CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        try {
            NotificationManagerCompat.from(this).notify(runId.hashCode(), notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "Sem permissão POST_NOTIFICATIONS: ${e.message}")
        }
    }
}
