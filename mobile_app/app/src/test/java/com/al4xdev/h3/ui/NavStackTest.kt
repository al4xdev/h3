package com.al4xdev.h3.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test

class NavStackTest {
    private val r = "aaaaaaaa-0000-4000-8000-000000000001"
    private val b1 = "bbbbbbbb-0000-4000-8000-000000000001"
    private val b2 = "bbbbbbbb-0000-4000-8000-000000000002"
    private val rot = Screen.Roteiro(r)
    private val blk = Screen.Block(r, b1)

    @Test
    fun popFeedsForwardAndForwardReenters() {
        val s = NavStack().push(rot).push(blk).pop().pop()
        assertEquals(listOf(Screen.Library), s.back)
        assertEquals(listOf(blk, rot), s.forward) // most recent pop is last
        val f = s.goForward()
        assertEquals(listOf(Screen.Library, rot), f.back)
        assertEquals(blk, f.nextForward)
        assertEquals(listOf(Screen.Library, rot, blk), f.goForward().back)
        assertNull(f.goForward().nextForward)
    }

    @Test
    fun newNavigationClearsForwardButReenteringKeepsTheRest() {
        val s = NavStack().push(rot).push(blk).pop().pop()
        assertEquals(listOf(blk), s.push(rot).forward) // tapping into the same screen = forward
        assertEquals(emptyList<Screen>(), s.push(Screen.Settings).forward)
        val onRot = s.goForward()
        assertEquals(emptyList<Screen>(), onRot.replaceTop(Screen.Roteiro("aaaaaaaa-0000-4000-8000-000000000002")).forward)
        assertEquals(emptyList<Screen>(), onRot.reset(Screen.Block(r, b2)).forward)
    }

    @Test
    fun rootAndEmptyForwardAreNoOps() {
        val root = NavStack()
        assertSame(root, root.pop())
        assertSame(root, root.goForward())
        assertSame(root, root.push(Screen.Library))
    }

    @Test
    fun forwardStackRoundTripsAndKeepsSavedState() {
        val s = NavStack().push(rot).push(blk).pop()
        assertEquals(s.forward, Nav.decodeList(Nav.encode(s.forward)))
        assertEquals(setOf("lib", "rot:$r", "blk:$r:$b1"), s.liveKeys())
    }
}
