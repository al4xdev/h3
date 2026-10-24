package com.al4xdev.h3.data

/** Visual state of a block; `wire` matches the strings of `/roteiros/summary` strip. */
enum class BlockState(val wire: String) {
    PLANNED("planned"),
    ACTIVE("active"),
    UNCERTAIN("uncertain"),
    REVIEW("ready_for_review"),
    ACCEPTED("accepted"),
    FAILED("failed");

    companion object {
        fun fromWire(value: String): BlockState = entries.firstOrNull { it.wire == value } ?: when (value) {
            RunStates.QUEUED, RunStates.RUNNING -> ACTIVE
            RunStates.REJECTED, RunStates.INTERRUPTED, RunStates.NOT_ADMITTED -> FAILED
            else -> PLANNED
        }
    }
}

data class RetryPlan(val prompt: String, val seed: Long, val durationSeconds: Double, val parentId: String?, val targetRunId: String? = null)

sealed interface NextAction {
    data object Adopt : NextAction
    data class Review(val index: Int) : NextAction
    data class Consult(val index: Int) : NextAction
    data class Generating(val index: Int) : NextAction
    data class Resolve(val index: Int) : NextAction
    data class GeneratePending(val count: Int) : NextAction
    data object Assemble : NextAction
    data object Empty : NextAction
}

/** Backend `MAX_BLOCKS` (local planning budget; films up to about one hour). */
const val MAX_BLOCKS = 1000

object RoteiroLogic {
    private val inFlight = setOf(RunStates.QUEUED, RunStates.RUNNING, RunStates.UNCERTAIN, RunStates.READY)
    private val retryable = setOf(RunStates.REJECTED, RunStates.INTERRUPTED, RunStates.NOT_ADMITTED)

    fun attemptsFor(doc: Roteiro, blockId: String): List<Attempt> = doc.attemptsByBlock[blockId].orEmpty()

    /** Same rule as the backend: `selected_runs[block]`, else the latest attempt. */
    fun selectedAttempt(doc: Roteiro, blockId: String): Attempt? {
        val attempts = attemptsFor(doc, blockId)
        val selected = doc.selectedRuns[blockId]
        return if (selected != null) attempts.firstOrNull { it.runId == selected } else attempts.lastOrNull()
    }

    /** What the block shows: work still in flight wins over an older selected version. */
    fun currentAttempt(doc: Roteiro, blockId: String): Attempt? {
        val latest = attemptsFor(doc, blockId).lastOrNull() ?: return null
        if (latest.state in inFlight) return latest
        return selectedAttempt(doc, blockId) ?: latest
    }

    fun stateOf(attempt: Attempt?): BlockState = stateOf(attempt?.state)

    fun stateOf(runState: String?): BlockState = when (runState) {
        null -> BlockState.PLANNED
        RunStates.ACCEPTED -> BlockState.ACCEPTED
        RunStates.READY -> BlockState.REVIEW
        RunStates.QUEUED, RunStates.RUNNING -> BlockState.ACTIVE
        RunStates.UNCERTAIN -> BlockState.UNCERTAIN
        else -> BlockState.FAILED
    }

    fun blockState(doc: Roteiro, blockId: String): BlockState = stateOf(currentAttempt(doc, blockId))

    fun states(doc: Roteiro): List<BlockState> = doc.blocks.map { blockState(doc, it.id) }

    /**
     * Indexes i where blocks i and i+1 are NOT parent/child. Connected iff the selected attempt
     * of i+1 continues the selected run of i, or the selected attempt of i is a bridge that
     * lands on the selected run of i+1. Blocks without attempts never show a cut.
     */
    fun cuts(doc: Roteiro): Set<Int> {
        val result = mutableSetOf<Int>()
        for (i in 0 until doc.blocks.size - 1) {
            val a = selectedAttempt(doc, doc.blocks[i].id) ?: continue
            val b = selectedAttempt(doc, doc.blocks[i + 1].id) ?: continue
            val connected = b.snapshot.parentId == a.runId || (a.isBridge && a.targetRunId == b.runId)
            if (!connected) result += i
        }
        return result
    }

    fun neverSent(doc: Roteiro): List<Block> = doc.blocks.filter { attemptsFor(doc, it.id).isEmpty() }

    /** Selected run of every block when all are accepted (editorial assembly input); else null. */
    fun selectedAcceptedRuns(doc: Roteiro): List<String>? {
        if (doc.blocks.isEmpty()) return null
        return doc.blocks.map { b ->
            val a = selectedAttempt(doc, b.id)
            if (a?.state != RunStates.ACCEPTED) return null
            a.runId
        }
    }

    /** Accepted selected run of a block, used as anchor/parent. */
    fun acceptedRun(doc: Roteiro, blockId: String?): String? {
        blockId ?: return null
        return selectedAttempt(doc, blockId)?.takeIf { it.state == RunStates.ACCEPTED }?.runId
    }

    /** Parent for the first attempt of a never-sent block; Result.failure explains the block. */
    fun parentForFirstAttempt(doc: Roteiro, index: Int): Result<String?> {
        if (index == 0) return Result.success(null)
        val previous = doc.blocks.getOrNull(index - 1) ?: return Result.failure(IllegalStateException("Nonexistent block"))
        val run = acceptedRun(doc, previous.id)
            ?: return Result.failure(IllegalStateException("Block $index must have an accepted version first."))
        return Result.success(run)
    }

    /**
     * New attempt for a rejected/interrupted/not-admitted block: literal prompt that was sent,
     * same seed, duration, ORIGINAL parent and, for a bridge, the same target. Failed is not retryable.
     */
    fun retryPlan(doc: Roteiro, blockId: String): RetryPlan? {
        val latest = attemptsFor(doc, blockId).lastOrNull() ?: return null
        if (latest.state !in retryable) return null
        return RetryPlan(latest.effectivePrompt, latest.snapshot.seed, latest.snapshot.durationSeconds, latest.snapshot.parentId,
            latest.targetRunId.takeIf { latest.isBridge })
    }

    fun nextAction(doc: Roteiro, uncertainBlockIds: Set<String> = emptySet()): NextAction {
        if (!doc.adopted) return NextAction.Adopt
        val states = states(doc)
        states.indexOfFirst { it == BlockState.REVIEW }.takeIf { it >= 0 }?.let { return NextAction.Review(it) }
        doc.blocks.indexOfFirst { it.id in uncertainBlockIds }.takeIf { it >= 0 }?.let { return NextAction.Consult(it) }
        states.indexOfFirst { it == BlockState.UNCERTAIN }.takeIf { it >= 0 }?.let { return NextAction.Consult(it) }
        states.indexOfFirst { it == BlockState.ACTIVE }.takeIf { it >= 0 }?.let { return NextAction.Generating(it) }
        states.indexOfFirst { it == BlockState.FAILED }.takeIf { it >= 0 }?.let { return NextAction.Resolve(it) }
        val pending = neverSent(doc).size
        if (pending > 0) return NextAction.GeneratePending(pending)
        if (doc.blocks.isNotEmpty() && states.all { it == BlockState.ACCEPTED }) return NextAction.Assemble
        return NextAction.Empty
    }

    /** Inserts planned blocks after `afterBlockId` (null = before the first). Null if the anchor vanished. */
    fun splice(blocks: List<Block>, afterBlockId: String?, inserted: List<Block>): List<Block>? {
        if (afterBlockId == null) return inserted + blocks
        val index = blocks.indexOfFirst { it.id == afterBlockId }
        if (index < 0) return null
        return blocks.subList(0, index + 1) + inserted + blocks.subList(index + 1, blocks.size)
    }

    /** Manual blocks: one per slot, action = prompt = the user's idea. */
    fun manualBlocks(count: Int, idea: String, durationSeconds: Double, seed: Long): List<Block> =
        List(count) { Block(newUuid(), idea.trim(), durationSeconds, seed, idea.trim()) }
}
