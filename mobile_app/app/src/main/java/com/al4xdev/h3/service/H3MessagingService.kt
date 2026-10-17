package com.al4xdev.h3.service

import android.app.PendingIntent
import android.content.Intent
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.al4xdev.h3.H3App
import com.al4xdev.h3.data.RunStates
import com.al4xdev.h3.data.Settings
import com.al4xdev.h3.data.isCanonicalUuid
import com.al4xdev.h3.ui.MainActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class H3MessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Settings(this).saveToken(token)
        H3App.registerToken(this, token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        val data = message.data
        val runId = data["run_id"]?.takeIf(::isCanonicalUuid)
        val state = data["state"].orEmpty()
        val title = message.notification?.title ?: "H3 Studio"
        val body = message.notification?.body ?: RunStates.label(state)
        Log.i(TAG, "push run_terminal run=$runId state=$state")

        val settings = Settings(this)
        // data.video_url pointed at a non-existent route in older backends; the URL is derived
        // from the run ID instead (`/runs/{id}/video`).
        if (runId != null && state == RunStates.READY && settings.autoDownload) {
            VideoDownloadWorker.enqueueRun(this, settings.baseUrl, runId)
        }
        show(title, body, runId)
    }

    private fun show(title: String, body: String, runId: String?) {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            runId?.let { putExtra(MainActivity.EXTRA_RUN_ID, it) }
        }
        val code = runId?.hashCode() ?: 0
        val pending = PendingIntent.getActivity(this, code, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(this, H3App.CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        try {
            NotificationManagerCompat.from(this).notify(code, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "Sem permissão POST_NOTIFICATIONS")
        }
    }

    companion object {
        private const val TAG = "H3MessagingService"
    }
}
