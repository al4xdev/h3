package com.al4xdev.h3.data

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

data class Reference(val sourceRoot: String, val path: String) {
    fun toJson(): JsonObject = buildJsonObject {
        put("source_root", sourceRoot)
        put("path", path)
    }

    /** Preview URL path for this reference (same forms the web client whitelists). */
    fun imagePath(): String? = when (sourceRoot) {
        "assets", "inputs" -> "/$sourceRoot/image?path=" + java.net.URLEncoder.encode(path, "UTF-8").replace("+", "%20").replace("%2F", "/")
        "runs" -> Regex("""^(?:\.data/)?runs/([0-9a-f-]{36})/(initial_frame|last_frame)\.png$""").find(path)
            ?.let { "/runs/${it.groupValues[1]}/image?name=${it.groupValues[2]}.png" }
        else -> null
    }

    companion object {
        fun parse(o: JsonObject?): Reference? {
            o ?: return null
            return Reference(o.str("source_root") ?: return null, o.str("path") ?: return null)
        }
    }
}

data class Block(
    val id: String,
    val action: String,
    val durationSeconds: Double,
    val seed: Long,
    val prompt: String,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("id", id)
        put("action", action)
        put("duration_seconds", durationSeconds)
        put("seed", seed)
        put("prompt", prompt)
    }

    companion object {
        fun parse(o: JsonObject): Block = Block(
            id = o.text("id"),
            action = o.text("action"),
            durationSeconds = o.double("duration_seconds") ?: 8.0,
            seed = o.long("seed") ?: Durations.DEFAULT_SEED,
            prompt = o.text("prompt"),
        )
    }
}

object RunStates {
    const val QUEUED = "queued"
    const val RUNNING = "running"
    const val READY = "ready_for_review"
    const val ACCEPTED = "accepted"
    const val REJECTED = "rejected"
    const val FAILED = "failed"
    const val INTERRUPTED = "interrupted"
    const val NOT_ADMITTED = "not_admitted"
    const val UNCERTAIN = "uncertain"

    val playable = setOf(READY, ACCEPTED, REJECTED)

    fun label(state: String?): String = when (state) {
        QUEUED -> "Queued"
        RUNNING -> "Generating"
        READY -> "Ready for review"
        ACCEPTED -> "Accepted"
        REJECTED -> "Rejected"
        FAILED -> "Failed"
        INTERRUPTED -> "Interrupted"
        NOT_ADMITTED -> "Not admitted"
        UNCERTAIN -> "Uncertain"
        null -> "No attempt"
        else -> "Unknown state"
    }
}

data class RunInfo(
    val id: String,
    val state: String,
    val prompt: String,
    val seed: Long?,
    val durationSeconds: Double?,
    val parentId: String?,
    val error: String?,
    val hasOutput: Boolean,
    val operation: String?,
    val createdAt: String?,
) {
    val playable: Boolean get() = state in RunStates.playable && hasOutput
    val videoPath: String get() = "/runs/$id/video"

    companion object {
        fun parse(o: JsonObject?): RunInfo? {
            o ?: return null
            return RunInfo(
                id = o.text("id"),
                state = o.text("state"),
                prompt = o.text("prompt"),
                seed = o.long("seed"),
                durationSeconds = o.double("duration_seconds"),
                parentId = o.str("parent_id"),
                error = o.errorText("error"),
                hasOutput = !o.objAt("output")?.str("path").isNullOrEmpty(),
                operation = o.objAt("input_info")?.str("operation"),
                createdAt = o.str("created_at"),
            )
        }
    }
}

data class Snapshot(val prompt: String, val seed: Long, val durationSeconds: Double, val parentId: String?)

data class Attempt(
    val intentId: String,
    val runId: String,
    val blockId: String,
    val snapshot: Snapshot,
    val origin: String,
    val targetRunId: String?,
    val admission: String,
    val state: String,
    val error: String?,
    val run: RunInfo?,
) {
    /** The prompt actually sent to the native engine (Grok-improved when the batch used it). */
    val effectivePrompt: String get() = run?.prompt?.takeIf { it.isNotBlank() } ?: snapshot.prompt
    val isBridge: Boolean get() = origin == "bridge"

    companion object {
        fun parse(o: JsonObject): Attempt {
            val snap = o.objAt("snapshot") ?: JsonObject(emptyMap())
            return Attempt(
                intentId = o.text("intent_id"),
                runId = o.text("run_id"),
                blockId = o.text("block_id"),
                snapshot = Snapshot(
                    prompt = snap.text("prompt"),
                    seed = snap.long("seed") ?: 0L,
                    durationSeconds = snap.double("duration_seconds") ?: 8.0,
                    parentId = snap.str("parent_id"),
                ),
                origin = o.str("origin") ?: "native",
                targetRunId = o.str("target_run_id"),
                admission = o.text("admission"),
                state = o.text("state"),
                error = o.errorText("error"),
                run = RunInfo.parse(o.objAt("run")),
            )
        }
    }
}

data class Roteiro(
    val id: String,
    val revision: Int,
    val name: String,
    val idea: String,
    val reference: Reference?,
    val adopted: Boolean,
    val blocks: List<Block>,
    val selectedRuns: Map<String, String>,
    val attempts: List<Attempt>,
    val removedBlockCount: Int,
) {
    /** Grouped once per parsed document: grids of 1000 blocks must not rescan every attempt per tile. */
    val attemptsByBlock: Map<String, List<Attempt>> by lazy { attempts.groupBy { it.blockId } }
    private val indexById: Map<String, Int> by lazy { blocks.withIndex().associate { it.value.id to it.index } }

    fun index(blockId: String): Int = indexById[blockId] ?: -1
    val title: String get() = name.ifBlank { idea.lineSequence().firstOrNull()?.take(60) ?: "Script" }

    companion object {
        fun parse(o: JsonObject): Roteiro = Roteiro(
            id = o.text("id"),
            revision = o.int("revision") ?: 1,
            name = o.text("name"),
            idea = o.text("idea"),
            reference = Reference.parse(o.objAt("reference")),
            adopted = o.bool("adopted") ?: false,
            blocks = o.arrAt("blocks").mapNotNull { it.obj()?.let(Block::parse) },
            selectedRuns = o.objAt("selected_runs")?.mapNotNull { (k, v) ->
                (v as? kotlinx.serialization.json.JsonPrimitive)?.takeIf { it.isString }?.let { k to it.content }
            }?.toMap() ?: emptyMap(),
            attempts = o.arrAt("attempts").mapNotNull { it.obj()?.let(Attempt::parse) },
            removedBlockCount = o.arrAt("removed_blocks").size,
        )
    }
}

data class SummaryItem(
    val id: String,
    val name: String,
    val idea: String,
    val adopted: Boolean,
    val revision: Int,
    val blockCount: Int,
    val states: Map<String, Int>,
    val strip: List<String>,
    val updatedAt: String?,
) {
    val title: String get() = name.ifBlank { idea.lineSequence().firstOrNull()?.take(60) ?: "Script" }
    fun count(state: String): Int = states[state] ?: 0

    companion object {
        fun parse(o: JsonObject): SummaryItem = SummaryItem(
            id = o.text("id"),
            name = o.text("name"),
            idea = o.text("idea"),
            adopted = o.bool("adopted") ?: false,
            revision = o.int("revision") ?: 1,
            blockCount = o.int("block_count") ?: 0,
            states = o.objAt("states")?.let { s -> s.keys.mapNotNull { k -> s.int(k)?.let { k to it } }.toMap() }
                ?: emptyMap(),
            strip = o.strings("strip"),
            updatedAt = o.str("updated_at"),
        )

        fun parseList(o: JsonObject): List<SummaryItem> = o.arrAt("items").mapNotNull { it.obj()?.let(::parse) }
    }
}

data class BatchRecord(
    val id: String,
    val roteiroId: String,
    val state: String,
    val phase: String?,
    val blockIds: List<String>,
    val currentBlockId: String?,
    val currentRunId: String?,
    val completedBlockIds: List<String>,
    val stopRequested: Boolean,
    val error: String?,
) {
    val active: Boolean get() = state == "active"

    fun describe(): String {
        val position = (blockIds.indexOf(currentBlockId).takeIf { it >= 0 } ?: completedBlockIds.size) + 1
        val phaseText = when (phase) {
            "improving" -> "Grok improving prompt"
            "generating" -> "generating video"
            "accepting" -> "intermediate technical acceptance"
            else -> null
        }
        return when (state) {
            "active" -> "Block $position of ${blockIds.size}" + (phaseText?.let { " · $it" } ?: "") +
                (if (stopRequested) " · stop requested" else "")
            "ready_for_review" -> "Last block ready for review"
            "interrupted" -> "Batch interrupted" + (error?.let { ": $it" } ?: "")
            "stopped" -> "Batch stopped"
            else -> state
        }
    }

    companion object {
        fun parse(o: JsonObject?): BatchRecord? {
            o ?: return null
            return BatchRecord(
                id = o.text("id"),
                roteiroId = o.text("roteiro_id"),
                state = o.text("state"),
                phase = o.str("phase"),
                blockIds = o.arrAt("blocks").mapNotNull { it.obj()?.str("id") },
                currentBlockId = o.str("current_block_id"),
                currentRunId = o.str("current_run_id"),
                completedBlockIds = o.strings("completed_block_ids"),
                stopRequested = o.bool("stop_requested") ?: false,
                error = o.errorText("error"),
            )
        }
    }
}

data class SegmentRecord(
    val id: String,
    val roteiroId: String,
    val sourceRevision: Int,
    val afterBlockId: String?,
    val state: String,
    val stale: Boolean,
    val blocks: List<Block>,
    val scenes: List<Scene>,
    val vision: Vision?,
    val rawTexts: List<String>,
    val error: String?,
    val detail: String?,
) {
    companion object {
        fun parse(o: JsonObject): SegmentRecord = SegmentRecord(
            id = o.text("id"),
            roteiroId = o.text("roteiro_id"),
            sourceRevision = o.int("source_revision") ?: 0,
            afterBlockId = o.str("after_block_id"),
            state = o.text("state"),
            stale = o.bool("stale") ?: false,
            blocks = o.arrAt("blocks").mapNotNull { it.obj()?.let(Block::parse) },
            scenes = Scene.parseList(o),
            vision = Vision.parse(o.objAt("vision")),
            rawTexts = o.strings("raw_texts"),
            error = o.errorText("error"),
            detail = o.errorText("detail"),
        )
    }
}

data class Beat(val kind: String, val action: String, val seconds: Double, val dialogue: String? = null)

/** Cinematographic intent of a planning answer (all fields optional free text). */
data class Vision(val style: String, val camera: String, val lightAndColor: String, val rhythm: String, val notes: String) {
    val isEmpty: Boolean get() = listOf(style, camera, lightAndColor, rhythm, notes).all { it.isBlank() }

    fun toJson(): JsonObject = buildJsonObject {
        put("style", style); put("camera", camera); put("light_and_color", lightAndColor); put("rhythm", rhythm); put("notes", notes)
    }

    companion object {
        fun parse(o: JsonObject?): Vision? {
            o ?: return null
            return Vision(o.text("style"), o.text("camera"), o.text("light_and_color"), o.text("rhythm"), o.text("notes"))
                .takeIf { !it.isEmpty }
        }
    }
}

/** Planning outline returned with proposals/segments; blocks remain the editable unit. */
data class Scene(
    val title: String,
    val beats: List<Beat>,
    val kind: String? = null,
    val intent: String? = null,
    val dialogue: String? = null,
    val anatomy: List<String> = emptyList(),
    val expressions: List<String> = emptyList(),
    val deltas: List<String> = emptyList(),
    val camera_focus: String? = null,
    val keeps: List<String> = emptyList(),
) {
    val seconds: Double get() = beats.sumOf { it.seconds }
    val isEvent: Boolean get() = beats.isEmpty() && intent != null

    fun toJson(): JsonObject = buildJsonObject {
        put("title", title)
        put("beats", buildJsonArray {
            beats.forEach { b ->
                add(buildJsonObject {
                    put("kind", b.kind); put("action", b.action); put("seconds", b.seconds)
                    b.dialogue?.let { put("dialogue", it) }
                })
            }
        })
        kind?.let { put("kind", it) }
        intent?.let { put("intent", it) }
        dialogue?.let { put("dialogue", it) }
        if (anatomy.isNotEmpty()) put("anatomy", stringsJson(anatomy))
        if (expressions.isNotEmpty()) put("expressions", stringsJson(expressions))
        if (deltas.isNotEmpty()) put("deltas", stringsJson(deltas))
        camera_focus?.let { put("camera_focus", it) }
        if (keeps.isNotEmpty()) put("keeps", stringsJson(keeps))
    }

    companion object {
        fun parse(o: JsonObject): Scene = Scene(
            title = o.text("title"),
            beats = o.arrAt("beats").mapNotNull { it.obj() }.map { b ->
                Beat(b.str("kind") ?: "action", b.text("action"), b.double("seconds") ?: 0.0, b.str("dialogue")?.takeIf { it.isNotBlank() })
            },
            kind = o.str("kind")?.takeIf { it.isNotBlank() },
            intent = o.str("intent")?.takeIf { it.isNotBlank() },
            dialogue = o.str("dialogue")?.takeIf { it.isNotBlank() },
            anatomy = o.strings("anatomy"),
            expressions = o.strings("expressions"),
            deltas = o.strings("deltas"),
            camera_focus = o.str("camera_focus")?.takeIf { it.isNotBlank() },
            keeps = o.strings("keeps"),
        )

        fun parseList(o: JsonObject): List<Scene> = o.arrAt("scenes").mapNotNull { it.obj()?.let(::parse) }
    }
}

internal fun stringsJson(values: List<String>): JsonElement = buildJsonArray { values.forEach { add(it) } }

internal fun scenesJson(scenes: List<Scene>): JsonElement = buildJsonArray { scenes.forEach { add(it.toJson()) } }

data class Proposal(
    val name: String,
    val blocks: List<Block>,
    val scenes: List<Scene>,
    val vision: Vision?,
    val rawText: String?,
    val stale: Boolean,
) {
    companion object {
        fun parse(o: JsonObject): Proposal = Proposal(
            name = o.text("name"),
            blocks = o.arrAt("blocks").mapNotNull { it.obj()?.let(Block::parse) },
            scenes = Scene.parseList(o),
            vision = Vision.parse(o.objAt("vision")),
            rawText = o.str("raw_text") ?: o.strings("raw_texts").takeIf { it.isNotEmpty() }?.joinToString("\n\n"),
            stale = o.bool("stale") ?: false,
        )
    }
}

data class EditRecord(
    val id: String,
    val roteiroId: String,
    val sourceRevision: Int,
    val mode: String,
    val blockId: String,
    val idea: String,
    val seed: Long,
    val durationSeconds: Double,
    val previousRunId: String?,
    val nextRunId: String?,
    val prompt: String?,
    val state: String,
    val runId: String?,
    val error: String?,
    val run: RunInfo?,
) {
    val open: Boolean get() = state !in setOf("applied", "discarded")

    companion object {
        fun parse(o: JsonObject): EditRecord = EditRecord(
            id = o.text("id"),
            roteiroId = o.text("roteiro_id"),
            sourceRevision = o.int("source_revision") ?: 0,
            mode = o.text("mode"),
            blockId = o.text("block_id"),
            idea = o.text("idea"),
            seed = o.long("seed") ?: Durations.DEFAULT_SEED,
            durationSeconds = o.double("duration_seconds") ?: 8.0,
            previousRunId = o.str("previous_run_id"),
            nextRunId = o.str("next_run_id"),
            prompt = o.str("prompt"),
            state = o.text("state"),
            runId = o.str("run_id"),
            error = o.errorText("error"),
            run = RunInfo.parse(o.objAt("run")),
        )
    }
}

data class Assembly(
    val id: String,
    val state: String,
    val mode: String?,
    val frames: Int?,
    val fps: Int?,
    val videoUrl: String?,
    val inputIds: List<String>,
    val roteiroId: String?,
    val roteiroRevision: Int?,
    val createdAt: String?,
    val error: String?,
) {
    val completed: Boolean get() = state == "completed" && videoUrl == "/assemblies/$id/video"

    companion object {
        fun parse(o: JsonObject): Assembly = Assembly(
            id = o.text("id"),
            state = o.text("state"),
            mode = o.str("mode"),
            frames = o.int("frames"),
            fps = o.int("fps"),
            videoUrl = o.str("video_url"),
            inputIds = o.strings("input_ids"),
            roteiroId = o.str("roteiro_id"),
            roteiroRevision = o.int("roteiro_revision"),
            createdAt = o.str("created_at"),
            error = o.errorText("error"),
        )
    }
}

data class InputItem(
    val sourceRoot: String,
    val path: String,
    val name: String,
    val imageUrl: String?,
    val width: Int?,
    val height: Int?,
) {
    val reference: Reference get() = Reference(sourceRoot, path)
    val isRunFrame: Boolean get() = sourceRoot == "runs"

    /** Readable name: run frames become "initial frame · 1a2b3c4d" instead of "initial_frame.png". */
    val label: String
        get() {
            if (isRunFrame) {
                Regex("""runs/([0-9a-f-]{36})/(initial_frame|last_frame)\.png$""").find(path)?.let { m ->
                    val which = if (m.groupValues[2] == "initial_frame") "initial frame" else "last frame"
                    return "$which · ${m.groupValues[1].take(8)}"
                }
            }
            return name.ifBlank { path.substringAfterLast('/') }
        }

    companion object {
        fun parse(o: JsonObject): InputItem? {
            val root = o.str("source_root") ?: return null
            val path = o.str("path") ?: return null
            return InputItem(root, path, o.text("name"), o.str("image_url"), o.int("width"), o.int("height"))
        }
    }
}

data class EditorConfig(val systemPrompt: String, val model: String) {
    companion object {
        fun parse(o: JsonObject): EditorConfig = EditorConfig(o.text("system_prompt"), o.text("model"))
    }
}

internal fun blocksJson(blocks: List<Block>): JsonElement = buildJsonArray { blocks.forEach { add(it.toJson()) } }

internal fun nullableString(value: String?): JsonElement =
    value?.let { kotlinx.serialization.json.JsonPrimitive(it) } ?: JsonNull
