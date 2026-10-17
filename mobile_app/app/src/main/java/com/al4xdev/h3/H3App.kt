package com.al4xdev.h3

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.util.Log
import com.al4xdev.h3.data.ApiClient
import com.al4xdev.h3.data.ApiResult
import com.al4xdev.h3.data.Settings
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class H3App : Application() {

    companion object {
        const val CHANNEL_ID = "h3_video_renders"
        private const val TAG = "H3App"
        private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

        /** Registers this phone for push on the configured PC. Returns nothing; failures are logged. */
        fun registerToken(context: Context, token: String, onResult: ((String) -> Unit)? = null) {
            val settings = Settings(context.applicationContext)
            val api = ApiClient { settings.baseUrl }
            scope.launch {
                val result = api.registerToken(token, "${Build.MANUFACTURER} ${Build.MODEL} (H3 Studio)", Build.ID)
                val text = if (result is ApiResult.Ok) "Notificações registradas no PC" else "Registro de notificações falhou: ${result.message()}"
                Log.i(TAG, text)
                onResult?.invoke(text)
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        val channel = NotificationChannel(CHANNEL_ID, "Renderização de Vídeos H3", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Avisos quando os vídeos estiverem prontos no PC"
            enableVibration(true)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)

        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            val token = if (task.isSuccessful) task.result else null
            if (token == null) {
                Log.w(TAG, "Falha ao obter token FCM", task.exception)
                return@addOnCompleteListener
            }
            Settings(this).saveToken(token)
            registerToken(this, token)
        }
    }
}
