package com.al4xdev.h3.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RoteiroLogicTest {
    private fun id(n: Int) = "00000000-0000-4000-8000-%012d".format(n)
    private fun block(n: Int) = Block(id(n), "ação $n", 8.0, 1L, "prompt $n")

    private fun attempt(run: Int, block: Int, state: String, parent: Int? = null, origin: String = "native", target: Int? = null) =
        Attempt(
            intentId = id(run), runId = id(run), blockId = id(block),
            snapshot = Snapshot("prompt $block", 1L, 8.0, parent?.let(::id)),
            origin = origin, targetRunId = target?.let(::id), admission = "admitted", state = state, error = null,
            run = RunInfo(id(run), state, "sent $run", 1L, 8.0, parent?.let(::id), null, state in RunStates.playable, "v2v", null),
        )

    private fun doc(blocks: List<Block>, attempts: List<Attempt>, selected: Map<String, String> = emptyMap(), adopted: Boolean = true) =
        Roteiro(id(999), 3, "n", "idea", Reference("assets", "dance_reference.png"), adopted, blocks, selected, attempts, 0)

    @Test
    fun blockStateDerivation() {
        val d = doc(
            (1..6).map(::block),
            listOf(
                attempt(101, 1, RunStates.ACCEPTED),
                attempt(102, 2, RunStates.READY, parent = 101),
                attempt(103, 3, RunStates.RUNNING),
                attempt(104, 4, RunStates.REJECTED),
                attempt(105, 5, RunStates.UNCERTAIN),
            ),
        )
        assertEquals(
            listOf(BlockState.ACCEPTED, BlockState.REVIEW, BlockState.ACTIVE, BlockState.FAILED, BlockState.UNCERTAIN, BlockState.PLANNED),
            RoteiroLogic.states(d),
        )
        assertEquals(NextAction.Review(1), RoteiroLogic.nextAction(d))
    }

    @Test
    fun inFlightRetryWinsOverOlderSelectedVersion() {
        val d = doc(listOf(block(1)), listOf(attempt(101, 1, RunStates.ACCEPTED), attempt(102, 1, RunStates.QUEUED)),
            selected = mapOf(id(1) to id(101)))
        assertEquals(BlockState.ACTIVE, RoteiroLogic.blockState(d, id(1)))
        assertEquals(id(101), RoteiroLogic.selectedAttempt(d, id(1))?.runId)
    }

    @Test
    fun cutsAppearOnlyBetweenNonParentNeighbours() {
        val d = doc(
            (1..5).map(::block),
            listOf(
                attempt(101, 1, RunStates.ACCEPTED),
                attempt(102, 2, RunStates.ACCEPTED, parent = 101), // child of 1: connected
                attempt(103, 3, RunStates.ACCEPTED, parent = 999), // parent elsewhere (block removed): cut 2|3
                attempt(104, 4, RunStates.ACCEPTED, parent = 103, origin = "bridge", target = 105), // bridge into 5
                attempt(105, 5, RunStates.ACCEPTED, parent = 777), // reached by bridge: connected
            ),
        )
        assertEquals(setOf(1), RoteiroLogic.cuts(d))
    }

    @Test
    fun plannedNeighboursNeverShowCut() {
        val d = doc((1..3).map(::block), listOf(attempt(101, 1, RunStates.ACCEPTED)))
        assertTrue(RoteiroLogic.cuts(d).isEmpty())
        assertEquals(NextAction.GeneratePending(2), RoteiroLogic.nextAction(d))
    }

    @Test
    fun retryKeepsSentPromptAndOriginalParent() {
        val d = doc((1..2).map(::block), listOf(attempt(101, 1, RunStates.ACCEPTED), attempt(102, 2, RunStates.INTERRUPTED, parent = 101)))
        val plan = RoteiroLogic.retryPlan(d, id(2))!!
        assertEquals("sent 102", plan.prompt)
        assertEquals(id(101), plan.parentId)
        assertNull(RoteiroLogic.retryPlan(d, id(1)))
        // A bridge retry keeps both anchors: same parent and same target run.
        val bridge = doc(listOf(block(1)), listOf(attempt(103, 1, RunStates.REJECTED, parent = 101, origin = "bridge", target = 5)))
        val bridgePlan = RoteiroLogic.retryPlan(bridge, id(1))!!
        assertEquals(id(101), bridgePlan.parentId)
        assertEquals(id(5), bridgePlan.targetRunId)
        assertNull(plan.targetRunId)
        val failed = doc(listOf(block(1)), listOf(attempt(104, 1, RunStates.FAILED)))
        assertNull(RoteiroLogic.retryPlan(failed, id(1)))
    }

    @Test
    fun firstAttemptParentRequiresAcceptedPredecessor() {
        val d = doc((1..3).map(::block), listOf(attempt(101, 1, RunStates.ACCEPTED), attempt(102, 2, RunStates.REJECTED, parent = 101)))
        assertNull(RoteiroLogic.parentForFirstAttempt(d, 0).getOrThrow())
        assertTrue(RoteiroLogic.parentForFirstAttempt(d, 2).isFailure)
        val ok = doc((1..2).map(::block), listOf(attempt(101, 1, RunStates.ACCEPTED)))
        assertEquals(id(101), RoteiroLogic.parentForFirstAttempt(ok, 1).getOrThrow())
    }

    @Test
    fun assemblyNeedsEverySelectedAccepted() {
        val all = doc((1..2).map(::block), listOf(attempt(101, 1, RunStates.ACCEPTED), attempt(102, 2, RunStates.ACCEPTED, parent = 101)))
        assertEquals(listOf(id(101), id(102)), RoteiroLogic.selectedAcceptedRuns(all))
        assertEquals(NextAction.Assemble, RoteiroLogic.nextAction(all))
        val partial = doc((1..2).map(::block), listOf(attempt(101, 1, RunStates.ACCEPTED)))
        assertNull(RoteiroLogic.selectedAcceptedRuns(partial))
    }

    @Test
    fun spliceInsertsAtAnchor() {
        val blocks = (1..3).map(::block)
        val new = listOf(block(10), block(11))
        assertEquals(listOf(1, 10, 11, 2, 3).map(::id), RoteiroLogic.splice(blocks, id(1), new)!!.map { it.id })
        assertEquals(listOf(10, 11, 1, 2, 3).map(::id), RoteiroLogic.splice(blocks, null, new)!!.map { it.id })
        assertEquals(listOf(1, 2, 3, 10, 11).map(::id), RoteiroLogic.splice(blocks, id(3), new)!!.map { it.id })
        assertNull(RoteiroLogic.splice(blocks, id(42), new))
    }

    @Test
    fun manualBlocksGetCanonicalIds() {
        val blocks = RoteiroLogic.manualBlocks(3, "  dança  ", 8.0, 7L)
        assertEquals(3, blocks.map { it.id }.toSet().size)
        assertTrue(blocks.all { isCanonicalUuid(it.id) && it.action == "dança" && it.prompt == "dança" && it.seed == 7L })
    }

    @Test
    fun unadoptedPlanAsksForAdoption() {
        assertEquals(NextAction.Adopt, RoteiroLogic.nextAction(doc(emptyList(), emptyList(), adopted = false)))
    }

    @Test
    fun uncertainLocalAttemptRequiresConsult() {
        val d = doc((1..2).map(::block), listOf(attempt(101, 1, RunStates.ACCEPTED)))
        assertEquals(NextAction.Consult(1), RoteiroLogic.nextAction(d, setOf(id(2))))
    }
}
