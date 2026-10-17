package com.al4xdev.h3.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T, val code: Int) : ApiResult<T>
    data class Http(val code: Int, val detail: String, val body: JsonObject?) : ApiResult<Nothing>
    data class Network(val message: String) : ApiResult<Nothing>

    /** Network failure or 5xx: the PC may or may not have applied it. */
    val uncertain: Boolean get() = this is Network || (this is Http && code >= 500)

    fun valueOrNull(): T? = (this as? Ok<T>)?.value

    fun message(): String = when (this) {
        is Ok -> ""
        is Network -> "PC inacessível: $message"
        is Http -> detail.ifBlank { "HTTP $code" }
    }

    fun <R> map(transform: (T) -> R): ApiResult<R> = when (this) {
        // A 2xx we cannot read means the PC did act: report it as uncertain, never as a refusal.
        is Ok -> runCatching { Ok(transform(value), code) as ApiResult<R> }
            .getOrElse { Network("resposta ilegível do PC (HTTP $code): ${it.message}") }
        is Http -> this
        is Network -> this
    }
}

/** Turns FastAPI/Pydantic/Grok error bodies into a readable line. */
internal fun errorDetail(body: JsonObject?, raw: String, code: Int): String {
    if (body == null) return raw.take(400).ifBlank { "HTTP $code" }
    val detail = body["detail"]
    val text = when {
        detail is JsonPrimitive && detail.isString -> detail.content
        detail is JsonArray -> detail.joinToString("; ") { item ->
            val o = item.obj()
            val loc = o?.arrAt("loc")?.joinToString(".") { (it as? JsonPrimitive)?.content ?: "?" }
            listOfNotNull(loc, o?.str("msg")).joinToString(": ").ifBlank { item.toString() }
        }
        detail != null -> detail.toString()
        else -> null
    }
    val error = body.str("error")
    return listOfNotNull(error, text).joinToString(" · ").ifBlank { raw.take(400) }
}

class ApiClient(private val baseUrl: () -> String) {
    private val jsonType = "application/json".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        // Grok planning waits up to 120 s on the PC (parallel chunks may add more).
        .readTimeout(200, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    // Assembly is synchronous until the file is published, and planning chains several Grok calls
    // (director, critic, writers): both get a long read timeout.
    private val slowClient = client.newBuilder().readTimeout(900, TimeUnit.SECONDS).build()

    /** SSE has no heartbeat: an idle stream must not time out. */
    val streamClient: OkHttpClient = client.newBuilder().readTimeout(0, TimeUnit.SECONDS).build()

    fun base(): String = baseUrl().trim().trimEnd('/')

    fun url(path: String): String = base() + path

    private fun httpUrl(path: String, query: Map<String, String> = emptyMap()): HttpUrl? {
        val parsed = (base() + path).toHttpUrlOrNull() ?: return null
        if (query.isEmpty()) return parsed
        return parsed.newBuilder().apply { query.forEach { (k, v) -> addQueryParameter(k, v) } }.build()
    }

    private suspend fun call(
        method: String,
        path: String,
        body: JsonElement? = null,
        query: Map<String, String> = emptyMap(),
        raw: RequestBody? = null,
        slow: Boolean = false,
    ): ApiResult<JsonElement?> = withContext(Dispatchers.IO) {
        val url = httpUrl(path, query) ?: return@withContext ApiResult.Network("endereço do servidor inválido")
        // accept/reject take no body, but OkHttp requires one for POST/PUT: send zero bytes.
        val requestBody = raw ?: body?.toString()?.toRequestBody(jsonType)
            ?: if (method == "POST" || method == "PUT") ByteArray(0).toRequestBody(null) else null
        val request = Request.Builder().url(url).method(method, requestBody).build()
        try {
            (if (slow) slowClient else client).newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                val parsed = runCatching { if (text.isBlank()) null else parseJson(text) }.getOrNull()
                if (response.isSuccessful) ApiResult.Ok(parsed, response.code)
                else ApiResult.Http(response.code, errorDetail(parsed.obj(), text, response.code), parsed.obj())
            }
        } catch (e: IOException) {
            ApiResult.Network(e.message ?: e.javaClass.simpleName)
        }
    }

    private fun JsonElement?.req(): JsonObject = this.obj() ?: error("corpo JSON ausente")

    private val empty = buildJsonObject { }

    // ---- config / library ----

    suspend fun config() = call("GET", "/app/config").map { it.req() }

    suspend fun summary() = call("GET", "/roteiros/summary").map { SummaryItem.parseList(it.req()) }

    suspend fun roteiros() = call("GET", "/roteiros").map { e -> e.req().arrAt("items").mapNotNull { it.obj()?.let(Roteiro::parse) } }

    suspend fun roteiro(id: String) = call("GET", "/roteiros/$id").map { Roteiro.parse(it.req()) }

    suspend fun favorites() = call("GET", "/favorites").map { e ->
        e.req().arrAt("items").mapNotNull { it.obj() }.filter { it.str("kind") == "roteiro" }.mapNotNull { it.str("id") }.toSet()
    }

    suspend fun setFavorite(id: String, favorite: Boolean) =
        call("PUT", "/favorites/roteiro/$id", buildJsonObject { put("favorite", favorite) }).map { }

    suspend fun currentBatch() = call("GET", "/roteiro-batches/current").map { BatchRecord.parse(it.req().objAt("batch")) }

    // ---- roteiro document ----

    suspend fun createRoteiro(name: String, idea: String, reference: Reference) = call("POST", "/roteiros", buildJsonObject {
        put("name", name)
        put("idea", idea)
        put("reference", reference.toJson())
        put("adopted", false)
        put("blocks", JsonArray(emptyList()))
    }).map { Roteiro.parse(it.req()) }

    /** Whole-document PUT; reference/idea always come from the document itself. */
    suspend fun putRoteiro(doc: Roteiro, blocks: List<Block>, adopted: Boolean = doc.adopted, name: String = doc.name,
                           idea: String = doc.idea, reference: Reference? = doc.reference): ApiResult<Roteiro> {
        val ref = reference ?: return ApiResult.Http(400, "Roteiro sem referência registrada", null)
        return call("PUT", "/roteiros/${doc.id}", buildJsonObject {
            put("expected_revision", doc.revision)
            put("name", name)
            put("idea", idea)
            put("reference", ref.toJson())
            put("adopted", adopted)
            put("blocks", blocksJson(blocks))
        }).map { Roteiro.parse(it.req()) }
    }

    suspend fun deleteRoteiro(id: String, revision: Int) =
        call("DELETE", "/roteiros/$id", buildJsonObject { put("expected_revision", revision) }).map { }

    suspend fun proposal(id: String, revision: Int, count: Int, duration: Double, seed: Long) =
        call("POST", "/roteiros/$id/proposal", buildJsonObject {
            put("expected_revision", revision)
            put("count", count)
            put("duration_seconds", duration)
            put("seed", seed)
        }, slow = true).map { Proposal.parse(it.req()) }

    suspend fun removeBlock(id: String, blockId: String, revision: Int) =
        call("POST", "/roteiros/$id/blocks/$blockId/remove", buildJsonObject { put("expected_revision", revision) })
            .map { Roteiro.parse(it.req()) }

    suspend fun selectVersion(id: String, blockId: String, runId: String, revision: Int) =
        call("POST", "/roteiros/$id/blocks/$blockId/versions/$runId", buildJsonObject { put("expected_revision", revision) })
            .map { Roteiro.parse(it.req()) }

    // ---- attempts / runs ----

    suspend fun postAttempt(id: String, blockId: String, intentId: String, revision: Int, prompt: String, seed: Long,
                            duration: Double, parentId: String?, targetRunId: String? = null) =
        call("POST", "/roteiros/$id/blocks/$blockId/attempts/$intentId", buildJsonObject {
            put("expected_revision", revision)
            put("prompt", prompt)
            put("seed", seed)
            put("duration_seconds", duration)
            put("parent_id", nullableString(parentId))
            // Only bridge retries carry a target; native attempts keep the original strict body.
            if (targetRunId != null) put("target_run_id", targetRunId)
        }).map { Attempt.parse(it.req()) }

    suspend fun getAttempt(id: String, blockId: String, intentId: String) =
        call("GET", "/roteiros/$id/blocks/$blockId/attempts/$intentId").map { Attempt.parse(it.req()) }

    suspend fun run(runId: String) = call("GET", "/runs/$runId").map { RunInfo.parse(it.req())!! }

    suspend fun decide(runId: String, accept: Boolean) =
        call("POST", "/runs/$runId/${if (accept) "accept" else "reject"}").map { RunInfo.parse(it.req())!! }

    suspend fun stopRun(runId: String) = call("POST", "/runs/$runId/stop", empty).map { RunInfo.parse(it.req())!! }

    // ---- batch ----

    suspend fun startBatch(id: String, batchId: String, revision: Int) =
        call("POST", "/roteiros/$id/batches/$batchId", buildJsonObject {
            put("expected_revision", revision)
            put("auto_accept_intermediate", true)
            put("enhance_with_grok", true)
        }).map { BatchRecord.parse(it.req())!! }

    suspend fun batch(id: String, batchId: String) =
        call("GET", "/roteiros/$id/batches/$batchId").map { BatchRecord.parse(it.req())!! }

    suspend fun stopBatch(id: String, batchId: String) =
        call("POST", "/roteiros/$id/batches/$batchId/stop", empty).map { BatchRecord.parse(it.req())!! }

    // ---- segments (insert N planned blocks) ----

    suspend fun planSegment(id: String, segmentId: String, revision: Int, afterBlockId: String?, idea: String,
                            count: Int, duration: Double, seed: Long) =
        call("POST", "/roteiros/$id/segments/$segmentId", buildJsonObject {
            put("expected_revision", revision)
            put("after_block_id", nullableString(afterBlockId))
            put("idea", idea)
            put("count", count)
            put("duration_seconds", duration)
            put("seed", seed)
        }, slow = true).map { SegmentRecord.parse(it.req()) }

    suspend fun segment(id: String, segmentId: String) =
        call("GET", "/roteiros/$id/segments/$segmentId").map { SegmentRecord.parse(it.req()) }

    // ---- anchored edit (replace) ----

    suspend fun edits(id: String) = call("GET", "/roteiros/$id/edits").map { e ->
        e.req().arrAt("items").mapNotNull { it.obj()?.let(EditRecord::parse) }
    }

    suspend fun proposeEdit(id: String, editId: String, revision: Int, blockId: String, idea: String, seed: Long, duration: Double) =
        call("POST", "/roteiros/$id/edits/$editId", buildJsonObject {
            put("expected_revision", revision)
            put("mode", "replace")
            put("block_id", blockId)
            put("idea", idea)
            put("seed", seed)
            put("duration_seconds", duration)
        }).map { EditRecord.parse(it.req()) }

    suspend fun edit(id: String, editId: String) = call("GET", "/roteiros/$id/edits/$editId").map { EditRecord.parse(it.req()) }

    suspend fun generateEdit(id: String, editId: String, prompt: String) =
        call("POST", "/roteiros/$id/edits/$editId/generate", buildJsonObject { put("prompt", prompt) }).map { EditRecord.parse(it.req()) }

    suspend fun applyEdit(id: String, editId: String, sourceRevision: Int) =
        call("POST", "/roteiros/$id/edits/$editId/apply", buildJsonObject { put("expected_revision", sourceRevision) })
            .map { Roteiro.parse(it.req()) }

    suspend fun discardEdit(id: String, editId: String) =
        call("POST", "/roteiros/$id/edits/$editId/discard", empty).map { EditRecord.parse(it.req()) }

    suspend fun retryEdit(id: String, editId: String, newId: String, revision: Int) =
        call("POST", "/roteiros/$id/edits/$editId/retry/$newId", buildJsonObject { put("expected_revision", revision) })
            .map { EditRecord.parse(it.req()) }

    // ---- assembly ----

    /** Every assembly (paged); the list is global, the caller filters by roteiro. */
    suspend fun assemblies(): ApiResult<List<Assembly>> {
        val all = mutableListOf<Assembly>()
        var offset = 0
        while (offset <= 10_000) {
            val page = call("GET", "/assemblies", query = mapOf("limit" to "100", "offset" to offset.toString())).map { e ->
                val o = e.req()
                o.arrAt("items").mapNotNull { it.obj()?.let(Assembly::parse) } to (o.int("total") ?: 0)
            }
            val (items, total) = (page as? ApiResult.Ok)?.value ?: return page.map { emptyList() }
            all += items
            offset += items.size
            if (items.isEmpty() || offset >= total) break
        }
        return ApiResult.Ok(all, 200)
    }

    suspend fun assemble(id: String, assemblyId: String, revision: Int) =
        call("POST", "/roteiros/$id/assemblies/$assemblyId", buildJsonObject { put("expected_revision", revision) }, slow = true)
            .map { Assembly.parse(it.req()) }

    suspend fun assembly(assemblyId: String) = call("GET", "/assemblies/$assemblyId").map { Assembly.parse(it.req()) }

    // ---- inputs ----

    suspend fun inputs(offset: Int) = call("GET", "/inputs", query = mapOf("limit" to "100", "offset" to offset.toString())).map { e ->
        val o = e.req()
        o.arrAt("items").mapNotNull { it.obj()?.let(InputItem::parse) } to (o.int("total") ?: 0)
    }

    suspend fun upload(name: String, bytes: ByteArray, mime: String) =
        call("POST", "/inputs", query = mapOf("name" to name), raw = bytes.toRequestBody(mime.toMediaType()))
            .map { InputItem.parse(it.req()) ?: error("item inválido") }

    // ---- Grok editors (three system prompts) ----

    suspend fun editor(path: String) = call("GET", path).map { EditorConfig.parse(it.req()) }

    /** `/grok/editor` takes the (fixed) model too; the roteiro editors take only the prompt. */
    suspend fun saveEditor(path: String, systemPrompt: String, model: String?) = call("PUT", path, buildJsonObject {
        put("system_prompt", systemPrompt)
        if (model != null) put("model", model)
    }).map { EditorConfig.parse(it.req()) }

    // ---- notifications ----

    suspend fun registerToken(token: String, deviceName: String, deviceId: String) =
        call("POST", "/notifications/register", buildJsonObject {
            put("token", token)
            put("device_name", deviceName.take(128))
            put("device_id", deviceId.take(128))
        }).map { }

    companion object {
        const val GROK_EDITOR = "/grok/editor"
        const val ROTEIRO_EDITOR = "/roteiros/editor"
        const val EDIT_EDITOR = "/roteiro-edits/editor"
    }
}
