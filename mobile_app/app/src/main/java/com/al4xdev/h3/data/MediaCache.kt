package com.al4xdev.h3.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaMetadataRetriever
import android.util.Log
import android.util.LruCache
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Images and video thumbnails without any backend thumbnail route. Every source used here is
 * immutable on the PC (run media, uploaded inputs, anchor frames of a run), so the disk cache
 * never needs invalidation.
 */
object MediaCache {
    private val memory = object : LruCache<String, Bitmap>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    private val gate = Semaphore(3)
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()

    private fun sha1(text: String) = MessageDigest.getInstance("SHA-1").digest(text.toByteArray())
        .joinToString("") { "%02x".format(it) }

    private const val MAX_DISK_BYTES = 150L * 1024 * 1024
    private var writes = 0

    /** Oldest-first eviction keeps the disk cache bounded (a 1000-block grid fills it fast). */
    @Synchronized
    private fun noteWrite(context: Context) {
        if (++writes % 40 != 0) return
        val files = (thumbDir(context).listFiles().orEmpty().toList() + imageDir(context).listFiles().orEmpty().toList()).sortedBy { it.lastModified() }
        var total = files.sumOf { it.length() }
        for (f in files) {
            if (total <= MAX_DISK_BYTES) break
            total -= f.length()
            f.delete()
        }
    }

    fun thumbDir(context: Context) = File(context.cacheDir, "thumbs").apply { mkdirs() }
    fun imageDir(context: Context) = File(context.cacheDir, "images").apply { mkdirs() }

    fun cachedThumb(runId: String): Bitmap? = memory.get("run:$runId")
    fun cachedImage(url: String, maxPx: Int): Bitmap? = memory.get("img:$maxPx:$url")

    /** First frame of a run's video, extracted on the phone (Range reads, not a full download). */
    suspend fun runThumbnail(context: Context, runId: String, videoUrl: String, localFile: File?): Bitmap? {
        val key = "run:$runId"
        memory.get(key)?.let { return it }
        return withContext(Dispatchers.IO) {
            val file = File(thumbDir(context), "$runId.jpg")
            if (file.isFile) {
                BitmapFactory.decodeFile(file.path)?.let { memory.put(key, it); return@withContext it }
            }
            gate.withPermit {
                // The tile may have scrolled away while waiting for a slot.
                coroutineContext.ensureActive()
                val retriever = MediaMetadataRetriever()
                try {
                    if (localFile != null && localFile.isFile) retriever.setDataSource(localFile.path)
                    else retriever.setDataSource(videoUrl, emptyMap())
                    val frame = retriever.getScaledFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 256, 256)
                        ?: return@withPermit null.also { Log.w("H3Thumb", "no frame for $runId") }
                    val tmp = File(file.path + ".part")
                    tmp.outputStream().use { frame.compress(Bitmap.CompressFormat.JPEG, 82, it) }
                    tmp.renameTo(file)
                    noteWrite(context)
                    memory.put(key, frame)
                    frame
                } catch (e: Exception) {
                    Log.w("H3Thumb", "thumbnail failed for $runId", e)
                    null
                } finally {
                    runCatching { retriever.release() }
                }
            }
        }
    }

    /** Remote image (reference or anchor frame), decoded down to about `maxPx`. */
    suspend fun image(context: Context, url: String, maxPx: Int): Bitmap? {
        val key = "img:$maxPx:$url"
        memory.get(key)?.let { return it }
        return withContext(Dispatchers.IO) {
            val file = File(imageDir(context), sha1(url))
            if (!file.isFile) {
                val ok = gate.withPermit {
                    runCatching {
                        http.newCall(Request.Builder().url(url).build()).execute().use { r ->
                            if (!r.isSuccessful) return@use false
                            val tmp = File(file.path + ".part")
                            r.body?.byteStream()?.use { input -> tmp.outputStream().use { input.copyTo(it) } } ?: return@use false
                            tmp.renameTo(file).also { noteWrite(context) }
                        }
                    }.getOrDefault(false)
                }
                if (!ok) return@withContext null
            }
            decodeSampled(file, maxPx)?.also { memory.put(key, it) }
        }
    }

    private fun decodeSampled(file: File, maxPx: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        if (bounds.outWidth <= 0) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxPx) sample *= 2
        return BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
    }

    fun clear(context: Context) {
        memory.evictAll()
        thumbDir(context).listFiles()?.forEach { it.delete() }
        imageDir(context).listFiles()?.forEach { it.delete() }
    }

    fun cacheBytes(context: Context): Long =
        (thumbDir(context).listFiles().orEmpty().toList() + imageDir(context).listFiles().orEmpty().toList()).sumOf { it.length() }
}
