package com.al4xdev.h3.data

/** One clip of "Assistir em sequência": the selected playable version of a block. */
data class SeqItem(val blockIndex: Int, val blockId: String, val runId: String, val label: String, val placeholderMs: Long)

object Sequence {
    const val WINDOW = 20
    /** Append the next window when playback reaches the last LOOKAHEAD clips of the current one. */
    const val LOOKAHEAD = 5

    /** Planned actions look like "<cena> · <beat> — parte i/n"; the overlay shows the scene part. */
    fun label(index: Int, action: String): String {
        val scene = action.substringBefore(" — ").trim().take(60)
        return if (scene.isEmpty()) "Bloco ${index + 1}" else "Bloco ${index + 1} · $scene"
    }

    /**
     * Consecutive blocks from `from` whose selected version is accepted or ready for review with a
     * published video. Stops at the first block that has nothing to play (planned, failed, gerando).
     */
    fun playable(doc: Roteiro, from: Int): List<SeqItem> {
        val out = mutableListOf<SeqItem>()
        for (i in from until doc.blocks.size) {
            val block = doc.blocks[i]
            val attempt = RoteiroLogic.selectedAttempt(doc, block.id) ?: break
            val run = attempt.run ?: break
            if (attempt.state != RunStates.ACCEPTED && attempt.state != RunStates.READY) break
            if (!run.playable) break
            val ms = (Durations.effectiveSeconds(Durations.frames(attempt.snapshot.durationSeconds)) * 1000).toLong()
            out += SeqItem(i, block.id, attempt.runId, label(i, block.action), ms)
        }
        return out
    }

    /** First block index with something to play, used by the grid's main "Assistir" entry. */
    fun firstPlayable(doc: Roteiro): Int? =
        doc.blocks.indices.firstOrNull { playable(doc, it).isNotEmpty() }

    /** Index range (into the playable list) of the window starting at `start`. */
    fun window(total: Int, start: Int, size: Int = WINDOW): IntRange = start until minOf(start + size, total)

    /** True when the clip at `clipInWindow` of `window` is close enough to its end to append the next one. */
    fun shouldExtend(window: IntRange, clipInWindow: Int, total: Int): Boolean =
        window.last < total - 1 && clipInWindow >= (window.last - window.first + 1) - LOOKAHEAD
}
