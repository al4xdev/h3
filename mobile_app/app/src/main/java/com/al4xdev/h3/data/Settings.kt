package com.al4xdev.h3.data

import android.content.Context

/** Device settings. Keeps the original prefs file/keys so an upgraded install keeps its server URL. */
class Settings(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var baseUrl: String
        get() = prefs.getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL) ?: DEFAULT_BACKEND_URL
        set(value) { prefs.edit().putString(KEY_BACKEND_URL, value.trim().trimEnd('/')).apply() }

    val fcmToken: String? get() = prefs.getString(KEY_FCM_TOKEN, null)

    fun saveToken(token: String) { prefs.edit().putString(KEY_FCM_TOKEN, token).apply() }

    /** Push "pronto para revisão" also downloads the clip to the phone for offline viewing. */
    var autoDownload: Boolean
        get() = prefs.getBoolean(KEY_AUTO_DOWNLOAD, true)
        set(value) { prefs.edit().putBoolean(KEY_AUTO_DOWNLOAD, value).apply() }

    companion object {
        const val PREFS_NAME = "h3_mock_prefs"
        const val KEY_BACKEND_URL = "backend_url"
        const val KEY_FCM_TOKEN = "fcm_token"
        const val KEY_AUTO_DOWNLOAD = "auto_download"
        const val DEFAULT_BACKEND_URL = "http://192.168.0.100:8888"
    }
}
