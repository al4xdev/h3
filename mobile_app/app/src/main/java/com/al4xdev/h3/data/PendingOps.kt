package com.al4xdev.h3.data

import android.content.Context
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Minimal persistent map so the bookkeeping is testable on the JVM. */
interface KeyValueStore {
    fun get(key: String): String?
    fun put(key: String, value: String)
    fun remove(key: String)
    fun keys(): Set<String>

    /** Synchronous write for records that must exist before a request leaves the phone. */
    fun putDurable(key: String, value: String) = put(key, value)
}

/** `durable = true` writes synchronously: a pending ID must be on disk before the POST leaves. */
class SharedPrefsStore(context: Context, name: String, private val durable: Boolean) : KeyValueStore {
    private val prefs = context.getSharedPreferences(name, Context.MODE_PRIVATE)
    override fun get(key: String): String? = prefs.getString(key, null)

    override fun put(key: String, value: String) {
        val editor = prefs.edit().putString(key, value)
        if (durable) editor.commit() else editor.apply()
    }

    override fun putDurable(key: String, value: String) {
        prefs.edit().putString(key, value).commit()
    }

    override fun remove(key: String) {
        val editor = prefs.edit().remove(key)
        if (durable) editor.commit() else editor.apply()
    }
    override fun keys(): Set<String> = prefs.all.keys.toSet()
}

class MemoryStore : KeyValueStore {
    private val map = LinkedHashMap<String, String>()
    override fun get(key: String): String? = map[key]
    override fun put(key: String, value: String) { map[key] = value }
    override fun remove(key: String) { map.remove(key) }
    override fun keys(): Set<String> = map.keys.toSet()
}

enum class OpKind(val label: String) {
    BATCH("lote"),
    SEGMENT("planejamento de blocos"),
    ASSEMBLY("montagem"),
    ATTEMPT("envio de bloco"),
    EDIT("nova versão"),
    DECISION("decisão"),
}

/**
 * A request whose client-generated ID is recorded BEFORE the POST. While it exists, the
 * only legal follow-up is reading the same ID; a new POST needs a new ID and an explicit tap.
 */
data class PendingOp(
    val kind: OpKind,
    val id: String,
    val roteiroId: String?,
    val blockId: String? = null,
    val detail: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("kind", kind.name)
        put("id", id)
        roteiroId?.let { put("roteiro_id", it) }
        blockId?.let { put("block_id", it) }
        detail?.let { put("detail", it) }
        put("created_at", createdAt)
    }

    companion object {
        fun parse(text: String): PendingOp? = runCatching {
            val o = parseJson(text).obj() ?: return null
            PendingOp(
                kind = OpKind.valueOf(o.text("kind")),
                id = o.str("id") ?: return null,
                roteiroId = o.str("roteiro_id"),
                blockId = o.str("block_id"),
                detail = o.str("detail"),
                createdAt = o.long("created_at") ?: 0L,
            )
        }.getOrNull()
    }
}

/** What to do with a pending record after the POST answered. */
enum class Outcome { DONE, REFUSED, UNCERTAIN }

fun <T> ApiResult<T>.outcome(): Outcome = when (this) {
    is ApiResult.Ok -> Outcome.DONE
    is ApiResult.Network -> Outcome.UNCERTAIN
    is ApiResult.Http -> if (code >= 500) Outcome.UNCERTAIN else Outcome.REFUSED
}

class PendingOps(private val store: KeyValueStore) {
    private fun key(id: String) = "op:$id"

    fun begin(op: PendingOp): PendingOp {
        require(isCanonicalUuid(op.id)) { "Pending op requires a canonical UUID" }
        store.putDurable(key(op.id), op.toJson().toString())
        return op
    }

    fun get(id: String): PendingOp? = store.get(key(id))?.let(PendingOp::parse)

    fun note(id: String, detail: String) {
        val op = get(id) ?: return
        store.putDurable(key(id), op.copy(detail = detail).toJson().toString())
    }

    fun resolve(id: String) = store.remove(key(id))

    fun all(): List<PendingOp> =
        store.keys().filter { it.startsWith("op:") }.mapNotNull { k -> store.get(k)?.let(PendingOp::parse) }
            .sortedBy { it.createdAt }

    fun forRoteiro(roteiroId: String): List<PendingOp> = all().filter { it.roteiroId == roteiroId }

    fun find(kind: OpKind, roteiroId: String?, blockId: String? = null): PendingOp? =
        all().firstOrNull { it.kind == kind && it.roteiroId == roteiroId && (blockId == null || it.blockId == blockId) }

    /**
     * Applies the POST answer. Attempts stay recorded even on a plain 4xx because the intent
     * may already be durable on the PC (same rule as the web client): only a GET clears them.
     */
    fun settle(op: PendingOp, outcome: Outcome, detail: String? = null) {
        when {
            outcome == Outcome.DONE -> resolve(op.id)
            outcome == Outcome.REFUSED && op.kind != OpKind.ATTEMPT -> resolve(op.id)
            else -> note(op.id, detail ?: "Resposta incerta")
        }
    }
}
