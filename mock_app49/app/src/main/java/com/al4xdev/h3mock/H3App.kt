package com.al4xdev.h3mock

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.util.Log
import com.google.firebase.messaging.FirebaseMessaging
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException

class H3App : Application() {

    companion object {
        const val CHANNEL_ID = "h3_video_renders"
        const val PREFS_NAME = "h3_mock_prefs"
        const val KEY_BACKEND_URL = "backend_url"
        const val KEY_FCM_TOKEN = "fcm_token"
        const val DEFAULT_BACKEND_URL = "http://192.168.0.100:8010"
        private const val TAG = "H3App"

        fun registerTokenWithBackend(context: Context, token: String, backendUrl: String? = null) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val url = backendUrl ?: prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL) ?: DEFAULT_BACKEND_URL
            val registerUrl = "$url/notifications/register"

            val json = JSONObject().apply {
                put("token", token)
                put("device_name", "${Build.MANUFACTURER} ${Build.MODEL} (Spike)")
                put("device_id", Build.ID)
            }

            val request = Request.Builder()
                .url(registerUrl)
                .post(json.toString().toRequestBody("application/json".toMediaType()))
                .build()

            OkHttpClient().newCall(request).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    Log.w(TAG, "Falha ao registrar token no backend H3 ($registerUrl): ${e.message}")
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        if (it.isSuccessful) {
                            Log.i(TAG, "Token FCM registrado com sucesso no backend H3!")
                        } else {
                            Log.w(TAG, "Backend H3 recusou registro de token: HTTP ${it.code}")
                        }
                    }
                }
            })
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()

        // Obter e salvar token do FCM
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (task.isSuccessful && task.result != null) {
                val token = task.result
                Log.i(TAG, "Token FCM gerado: $token")
                getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                    .edit()
                    .putString(KEY_FCM_TOKEN, token)
                    .apply()

                registerTokenWithBackend(this, token)
            } else {
                Log.w(TAG, "Falha ao obter token FCM", task.exception)
            }
        }
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Renderização de Vídeos H3",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Avisos quando os vídeos e chunks estiverem prontos no PC"
            enableVibration(true)
        }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)
    }
}
