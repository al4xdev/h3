package com.al4xdev.h3.data

data class BlockItem(
    val id: String,
    val action: String,
    val prompt: String,
    val duration_seconds: Double,
    val seed: Long
)

data class AttemptItem(
    val intent_id: String,
    val run_id: String,
    val block_id: String,
    val state: String,
    val video_path: String? = null
)

data class RoteiroItem(
    val id: String,
    val name: String,
    val idea: String,
    val revision: Int,
    val adopted: Boolean,
    val blocks: List<BlockItem>,
    val attempts: List<AttemptItem> = emptyList(),
    val selected_runs: Map<String, String> = emptyMap()
)

data class BatchStatus(
    val id: String,
    val roteiro_id: String,
    val state: String,
    val phase: String?,
    val current_block_id: String?,
    val completed_block_ids: List<String>
)
