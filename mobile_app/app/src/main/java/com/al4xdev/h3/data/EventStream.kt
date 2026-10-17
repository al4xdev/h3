package com.al4xdev.h3.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.withContext
import okhttp3.Request
import java.io.IOException
import kotlin.coroutines.coroutineContext

/** Incremental `text/event-stream` parser: feed lines, get (event, data) on blank lines. */
class SseParser {
    private var event = "message"
    private val data = StringBuilder()

    fun feed(line: String): Pair<String, String>? {
        when {
            line.isEmpty() -> {
                if (data.isEmpty()) { event = "message"; return null }
                val out = event to data.toString()
                event = "message"; data.clear()
                return out
            }
            line.startsWith(":") -> Unit
            line.startsWith("event:") -> event = line.removePrefix("event:").trim()
            line.startsWith("data:") -> {
                if (data.isNotEmpty()) data.append('\n')
                data.append(line.removePrefix("data:").removePrefix(" "))
            }
        }
        return null
    }

    companion object {
        /** `.data`-relative path of a `change` event, or null if it is noise (tmp/partial files). */
        fun changedPath(event: String, data: String): String? {
            if (event != "change") return null
            val path = runCatching { parseJson(data).obj()?.str("path") }.getOrNull() ?: return null
            if (path.endsWith(".part") || path.contains("/tmp") || path.contains(".tmp")) return null
            return path
        }

        /** Paths that can change what the app shows (roteiros, batches, runs, assemblies, favorites). */
        fun relevant(path: String): Boolean =
            path == ".data" || path.startsWith("roteiros") || path.startsWith("roteiro-batches") ||
                path.startsWith("runs/") || path.startsWith("assemblies/") || path.startsWith("library")
    }
}

class EventStream(private val api: ApiClient) {
    /** Blocks until the stream ends or the coroutine is cancelled (which cancels the HTTP call). */
    suspend fun listen(onOpen: () -> Unit, onPath: (String) -> Unit) = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(api.url("/events")).header("Accept", "text/event-stream").build()
        val call = api.streamClient.newCall(request)
        val handle = coroutineContext[Job]?.invokeOnCompletion { call.cancel() }
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
                onOpen()
                val source = response.body?.source() ?: throw IOException("sem corpo")
                val parser = SseParser()
                while (true) {
                    val line = source.readUtf8Line() ?: break
                    val (event, data) = parser.feed(line) ?: continue
                    SseParser.changedPath(event, data)?.takeIf(SseParser::relevant)?.let(onPath)
                }
            }
        } finally {
            handle?.dispose()
        }
    }
}
