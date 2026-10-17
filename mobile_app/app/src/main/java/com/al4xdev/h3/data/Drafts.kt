package com.al4xdev.h3.data

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** T1 draft. `roteiroId` makes "Propor de novo" reuse the same roteiro instead of creating another. */
data class NewRoteiroDraft(
    val title: String = "",
    val idea: String = "",
    val reference: InputItem? = null,
    val count: Int = 3,
    val durationText: String = Durations.DEFAULT_TEXT,
    val seedText: String = Durations.DEFAULT_SEED.toString(),
    val roteiroId: String? = null,
    /** Set before POST /roteiros (no client ID exists for it); cleared only by proof. */
    val creationUncertain: Boolean = false,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("title", title)
        put("idea", idea)
        reference?.let {
            put("reference", buildJsonObject {
                put("source_root", it.sourceRoot); put("path", it.path); put("name", it.name)
                it.imageUrl?.let { u -> put("image_url", u) }
                it.width?.let { w -> put("width", w) }
                it.height?.let { h -> put("height", h) }
            })
        }
        put("count", count)
        put("duration", durationText)
        put("seed", seedText)
        roteiroId?.let { put("roteiro_id", it) }
        put("creation_uncertain", creationUncertain)
    }

    companion object {
        fun parse(text: String?): NewRoteiroDraft = runCatching {
            val o = parseJson(text ?: return NewRoteiroDraft()).obj() ?: return NewRoteiroDraft()
            NewRoteiroDraft(
                title = o.text("title"),
                idea = o.text("idea"),
                reference = o.objAt("reference")?.let(InputItem::parse),
                count = (o.int("count") ?: 3).coerceIn(1, MAX_BLOCKS),
                durationText = o.str("duration") ?: Durations.DEFAULT_TEXT,
                seedText = o.str("seed") ?: Durations.DEFAULT_SEED.toString(),
                roteiroId = o.str("roteiro_id"),
                creationUncertain = o.bool("creation_uncertain") ?: false,
            )
        }.getOrDefault(NewRoteiroDraft())
    }
}

/** Not-yet-adopted plan of a roteiro (Grok proposal or manual), kept only on the phone. */
data class Candidate(
    val name: String,
    val blocks: List<Block>,
    val fromGrok: Boolean,
    val stale: Boolean = false,
    val scenes: List<Scene> = emptyList(),
    val vision: Vision? = null,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("name", name)
        put("blocks", blocksJson(blocks))
        put("scenes", scenesJson(scenes))
        vision?.let { put("vision", it.toJson()) }
        put("from_grok", fromGrok)
        put("stale", stale)
    }

    companion object {
        fun parse(text: String?): Candidate? = runCatching {
            val o = parseJson(text ?: return null).obj() ?: return null
            Candidate(
                name = o.text("name"),
                blocks = o.arrAt("blocks").mapNotNull { it.obj()?.let(Block::parse) },
                fromGrok = o.bool("from_grok") ?: false,
                stale = o.bool("stale") ?: false,
                scenes = Scene.parseList(o),
                vision = Vision.parse(o.objAt("vision")),
            )
        }.getOrNull()
    }
}

/** T4/T7 draft for inserting N blocks after `afterBlockId` (null = before the first block). */
data class InsertDraft(
    val idea: String = "",
    val count: Int = 1,
    val durationText: String = Durations.DEFAULT_TEXT,
    val seedText: String = Durations.DEFAULT_SEED.toString(),
    val segmentId: String? = null,
    val blocks: List<Block> = emptyList(),
    val scenes: List<Scene> = emptyList(),
    val vision: Vision? = null,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("idea", idea)
        put("count", count)
        put("duration", durationText)
        put("seed", seedText)
        segmentId?.let { put("segment_id", it) }
        put("blocks", blocksJson(blocks))
        put("scenes", scenesJson(scenes))
        vision?.let { put("vision", it.toJson()) }
    }

    companion object {
        fun parse(text: String?): InsertDraft? = runCatching {
            val o = parseJson(text ?: return null).obj() ?: return null
            InsertDraft(
                idea = o.text("idea"),
                count = (o.int("count") ?: 1).coerceIn(1, MAX_BLOCKS),
                durationText = o.str("duration") ?: Durations.DEFAULT_TEXT,
                seedText = o.str("seed") ?: Durations.DEFAULT_SEED.toString(),
                segmentId = o.str("segment_id"),
                blocks = o.arrAt("blocks").mapNotNull { it.obj()?.let(Block::parse) },
                scenes = Scene.parseList(o),
                vision = Vision.parse(o.objAt("vision")),
            )
        }.getOrNull()
    }
}

class Drafts(private val store: KeyValueStore) {
    fun newRoteiro(): NewRoteiroDraft = NewRoteiroDraft.parse(store.get("new"))
    fun saveNewRoteiro(d: NewRoteiroDraft, durable: Boolean = false) =
        if (durable) store.putDurable("new", d.toJson().toString()) else store.put("new", d.toJson().toString())
    fun clearNewRoteiro() = store.remove("new")

    fun candidate(roteiroId: String): Candidate? = Candidate.parse(store.get("cand:$roteiroId"))
    fun saveCandidate(roteiroId: String, c: Candidate) = store.put("cand:$roteiroId", c.toJson().toString())
    fun clearCandidate(roteiroId: String) = store.remove("cand:$roteiroId")

    private fun insertKey(roteiroId: String, after: String?) = "ins:$roteiroId:${after ?: "start"}"
    fun insert(roteiroId: String, after: String?): InsertDraft? = InsertDraft.parse(store.get(insertKey(roteiroId, after)))
    fun saveInsert(roteiroId: String, after: String?, d: InsertDraft) = store.put(insertKey(roteiroId, after), d.toJson().toString())
    fun clearInsert(roteiroId: String, after: String?) = store.remove(insertKey(roteiroId, after))

    /** Open anchored edit (replace) per block, so the screen resumes the same edit ID. */
    fun editId(roteiroId: String, blockId: String): String? = store.get("edit:$roteiroId:$blockId")
    fun saveEditId(roteiroId: String, blockId: String, editId: String) = store.put("edit:$roteiroId:$blockId", editId)
    fun clearEditId(roteiroId: String, blockId: String) = store.remove("edit:$roteiroId:$blockId")
}
