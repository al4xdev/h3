package com.al4xdev.h3.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SequenceTest {
    private fun id(n: Int) = "00000000-0000-4000-8000-%012d".format(n)

    private fun attempt(run: Int, block: Int, state: String, published: Boolean = true) = Attempt(
        id(run), id(run), id(block), Snapshot("p", 1L, 8.0, null), "native", null, "admitted", state, null,
        RunInfo(id(run), state, "p", 1L, 8.0, null, null, published && state in RunStates.playable, "v2v", null),
    )

    private fun doc(attempts: List<Attempt>, n: Int = 5) = Roteiro(
        id(999), 1, "n", "i", null, true,
        (1..n).map { Block(id(it), "Abertura · gira — parte $it/$n", 8.0, 1L, "p") }, emptyMap(), attempts, 0,
    )

    @Test
    fun playableStopsAtFirstBlockWithNothingToPlay() {
        val d = doc(listOf(
            attempt(101, 1, RunStates.ACCEPTED), attempt(102, 2, RunStates.READY),
            attempt(104, 4, RunStates.ACCEPTED), attempt(105, 5, RunStates.REJECTED),
        ))
        assertEquals(listOf(0, 1), Sequence.playable(d, 0).map { it.blockIndex })
        assertEquals(listOf(3), Sequence.playable(d, 3).map { it.blockIndex })
        assertTrue(Sequence.playable(d, 2).isEmpty())
        assertTrue(Sequence.playable(d, 4).isEmpty())
        assertEquals(0, Sequence.firstPlayable(d))
        assertEquals(8000L, Sequence.playable(d, 0)[0].placeholderMs)
        assertEquals("Bloco 1 · Abertura · gira", Sequence.playable(d, 0)[0].label)
    }

    @Test
    fun unpublishedOrRunningIsNotPlayable() {
        val d = doc(listOf(attempt(101, 1, RunStates.ACCEPTED, published = false), attempt(102, 2, RunStates.RUNNING)))
        assertNull(Sequence.firstPlayable(d))
    }

    @Test
    fun slidingWindowBounds() {
        assertEquals(0 until 20, Sequence.window(300, 0))
        assertEquals(280 until 300, Sequence.window(300, 280))
        assertEquals(290 until 300, Sequence.window(300, 290))
        val w = 20 until 40
        assertFalse(Sequence.shouldExtend(w, 14, 300))
        assertTrue(Sequence.shouldExtend(w, 15, 300))
        assertFalse(Sequence.shouldExtend(280 until 300, 19, 300)) // nothing left to append
    }
}
