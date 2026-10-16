package com.al4xdev.h3.data

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

class H3ApiClient(private val context: Context) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    companion object {
        private const val TAG = "H3ApiClient"
    }

    private fun baseUrl(): String {
        val prefs = context.getSharedPreferences("h3_mock_prefs", Context.MODE_PRIVATE)
        return prefs.getString("backend_url", "http://192.168.0.100:8888") ?: "http://192.168.0.100:8888"
    }

    suspend fun getRoteiros(): List<RoteiroItem> = withContext(Dispatchers.IO) {
        val url = "${baseUrl()}/roteiros"
        val request = Request.Builder().url(url).build()
        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) return@withContext emptyList()
            val text = response.body?.string() ?: return@withContext emptyList()
            val json = JSONObject(text)
            val items = json.optJSONArray("items") ?: return@withContext emptyList()

            val result = mutableListOf<RoteiroItem>()
            for (i in 0 until items.length()) {
                val obj = items.getJSONObject(i)
                result.add(parseRoteiro(obj))
            }
            result
        } catch (e: Exception) {
            Log.w(TAG, "Falha ao buscar roteiros: ${e.message}")
            emptyList()
        }
    }

    suspend fun getRoteiro(id: String): RoteiroItem? = withContext(Dispatchers.IO) {
        val url = "${baseUrl()}/roteiros/$id"
        val request = Request.Builder().url(url).build()
        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) return@withContext null
            val text = response.body?.string() ?: return@withContext null
            parseRoteiro(JSONObject(text))
        } catch (e: Exception) {
            Log.w(TAG, "Falha ao buscar roteiro $id: ${e.message}")
            null
        }
    }

    suspend fun createRoteiro(name: String, idea: String): RoteiroItem? = withContext(Dispatchers.IO) {
        val url = "${baseUrl()}/roteiros"
        val json = JSONObject().apply {
            put("name", name)
            put("idea", idea)
            put("reference", JSONObject().apply {
                put("source_root", "assets")
                put("path", "dance_reference.png")
            })
            put("adopted", false)
            put("blocks", JSONArray())
        }
        val request = Request.Builder()
            .url(url)
            .post(json.toString().toRequestBody("application/json".toMediaType()))
            .build()
        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) return@withContext null
            parseRoteiro(JSONObject(response.body?.string() ?: return@withContext null))
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao criar roteiro: ${e.message}")
            null
        }
    }

    suspend fun proposeWithGrok(roteiroId: String, revision: Int, count: Int = 3): Pair<List<BlockItem>, String> = withContext(Dispatchers.IO) {
        val url = "${baseUrl()}/roteiros/$roteiroId/proposal"
        val json = JSONObject().apply {
            put("expected_revision", revision)
            put("count", count)
            put("duration_seconds", 8.0)
            put("seed", 2026101205L)
        }
        val request = Request.Builder()
            .url(url)
            .post(json.toString().toRequestBody("application/json".toMediaType()))
            .build()
        try {
            val response = client.newCall(request).execute()
            val text = response.body?.string() ?: ""
            if (!response.isSuccessful) {
                val detail = try { JSONObject(text).optString("detail", text) } catch (e: Exception) { text }
                return@withContext Pair(emptyList(), detail)
            }
            val candidate = JSONObject(text)
            val blocksArray = candidate.optJSONArray("blocks") ?: return@withContext Pair(emptyList(), "Nenhum bloco retornado")

            val result = mutableListOf<BlockItem>()
            for (i in 0 until blocksArray.length()) {
                val b = blocksArray.getJSONObject(i)
                result.add(
                    BlockItem(
                        id = b.optString("id", UUID.randomUUID().toString()),
                        action = b.optString("action", ""),
                        prompt = b.optString("prompt", ""),
                        duration_seconds = b.optDouble("duration_seconds", 8.0),
                        seed = b.optLong("seed", 2026101205L)
                    )
                )
            }
            Pair(result, "")
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao propor com Grok: ${e.message}")
            Pair(emptyList(), "Erro de rede: ${e.message}")
        }
    }

    suspend fun updateBlock(
        roteiroId: String,
        revision: Int,
        name: String,
        idea: String,
        updatedBlock: BlockItem,
        allBlocks: List<BlockItem>
    ): Boolean = withContext(Dispatchers.IO) {
        val newBlocks = allBlocks.map { if (it.id == updatedBlock.id) updatedBlock else it }
        adoptBlocks(roteiroId, revision, name, idea, newBlocks)
    }

    suspend fun adoptBlocks(roteiroId: String, revision: Int, name: String, idea: String, blocks: List<BlockItem>): Boolean = withContext(Dispatchers.IO) {
        val url = "${baseUrl()}/roteiros/$roteiroId"
        val blocksArray = JSONArray()
        for (b in blocks) {
            blocksArray.put(JSONObject().apply {
                put("id", b.id)
                put("action", b.action)
                put("prompt", b.prompt)
                put("duration_seconds", b.duration_seconds)
                put("seed", b.seed)
            })
        }
        val json = JSONObject().apply {
            put("expected_revision", revision)
            put("name", name)
            put("idea", idea)
            put("adopted", true)
            put("reference", JSONObject().apply {
                put("source_root", "assets")
                put("path", "dance_reference.png")
            })
            put("blocks", blocksArray)
        }
        val request = Request.Builder()
            .url(url)
            .put(json.toString().toRequestBody("application/json".toMediaType()))
            .build()
        try {
            val response = client.newCall(request).execute()
            response.isSuccessful
        } catch (e: Exception) {
            false
        }
    }

    suspend fun startBatch(roteiroId: String, revision: Int): Pair<Boolean, String> = withContext(Dispatchers.IO) {
        val batchId = UUID.randomUUID().toString()
        val url = "${baseUrl()}/roteiros/$roteiroId/batches/$batchId"
        val json = JSONObject().apply {
            put("expected_revision", revision)
            put("auto_accept_intermediate", true)
            put("enhance_with_grok", true)
        }
        val request = Request.Builder()
            .url(url)
            .post(json.toString().toRequestBody("application/json".toMediaType()))
            .build()
        try {
            val response = client.newCall(request).execute()
            val text = response.body?.string() ?: ""
            if (response.code in 200..202) {
                Pair(true, "Lote iniciado na GPU com sucesso!")
            } else {
                val detail = try {
                    JSONObject(text).optString("detail", text)
                } catch (e: Exception) {
                    text
                }
                val msg = if (detail.contains("No never-submitted blocks")) {
                    "Todos os blocos deste roteiro já foram gerados!"
                } else {
                    detail.ifBlank { "Erro HTTP ${response.code}" }
                }
                Pair(false, msg)
            }
        } catch (e: Exception) {
            Pair(false, "Erro de rede: ${e.message}")
        }
    }

    suspend fun decideRun(runId: String, accept: Boolean): Boolean = withContext(Dispatchers.IO) {
        val action = if (accept) "accept" else "reject"
        val url = "${baseUrl()}/runs/$runId/$action"
        val request = Request.Builder()
            .url(url)
            .post("{}".toRequestBody("application/json".toMediaType()))
            .build()
        try {
            val response = client.newCall(request).execute()
            response.isSuccessful
        } catch (e: Exception) {
            false
        }
    }

    suspend fun getCurrentBatch(): BatchStatus? = withContext(Dispatchers.IO) {
        val url = "${baseUrl()}/roteiro-batches/current"
        val request = Request.Builder().url(url).build()
        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) return@withContext null
            val text = response.body?.string() ?: return@withContext null
            val json = JSONObject(text)
            val batchObj = json.optJSONObject("batch") ?: return@withContext null

            val completedList = mutableListOf<String>()
            val compArr = batchObj.optJSONArray("completed_block_ids")
            if (compArr != null) {
                for (i in 0 until compArr.length()) completedList.add(compArr.getString(i))
            }

            BatchStatus(
                id = batchObj.optString("id", ""),
                roteiro_id = batchObj.optString("roteiro_id", ""),
                state = batchObj.optString("state", ""),
                phase = batchObj.optString("phase", null),
                current_block_id = batchObj.optString("current_block_id", null),
                completed_block_ids = completedList
            )
        } catch (e: Exception) {
            null
        }
    }

    private fun parseRoteiro(obj: JSONObject): RoteiroItem {
        val blocksArr = obj.optJSONArray("blocks") ?: JSONArray()
        val blocks = mutableListOf<BlockItem>()
        for (j in 0 until blocksArr.length()) {
            val b = blocksArr.getJSONObject(j)
            blocks.add(
                BlockItem(
                    id = b.optString("id", ""),
                    action = b.optString("action", ""),
                    prompt = b.optString("prompt", ""),
                    duration_seconds = b.optDouble("duration_seconds", 8.0),
                    seed = b.optLong("seed", 0L)
                )
            )
        }

        val attemptsArr = obj.optJSONArray("attempts") ?: JSONArray()
        val attempts = mutableListOf<AttemptItem>()
        for (k in 0 until attemptsArr.length()) {
            val a = attemptsArr.getJSONObject(k)
            attempts.add(
                AttemptItem(
                    intent_id = a.optString("intent_id", ""),
                    run_id = a.optString("run_id", ""),
                    block_id = a.optString("block_id", ""),
                    state = a.optString("state", "")
                )
            )
        }

        val selectedObj = obj.optJSONObject("selected_runs") ?: JSONObject()
        val selectedMap = mutableMapOf<String, String>()
        val keys = selectedObj.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            selectedMap[key] = selectedObj.getString(key)
        }

        return RoteiroItem(
            id = obj.optString("id", ""),
            name = obj.optString("name", "Sem título"),
            idea = obj.optString("idea", ""),
            revision = obj.optInt("revision", 1),
            adopted = obj.optBoolean("adopted", false),
            blocks = blocks,
            attempts = attempts,
            selected_runs = selectedMap
        )
    }
}
