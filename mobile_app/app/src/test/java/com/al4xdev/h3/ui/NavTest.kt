package com.al4xdev.h3.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class NavTest {
    private val r = "aaaaaaaa-0000-4000-8000-000000000001"
    private val b = "bbbbbbbb-0000-4000-8000-000000000001"
    private val run = "cccccccc-0000-4000-8000-000000000001"

    @Test
    fun backStackRoundTrips() {
        val stack = listOf(
            Screen.Library, Screen.Roteiro(r), Screen.Block(r, b), Screen.Insert(r, null), Screen.Insert(r, b),
            Screen.Redo(r, b), Screen.Review(r, b, run), Screen.Assembly(r), Screen.Settings, Screen.NewRoteiro,
        )
        assertEquals(stack, Nav.decode(Nav.encode(stack)))
    }

    @Test
    fun libraryIsAlwaysRootAndGarbageIsDropped() {
        assertEquals(listOf(Screen.Library), Nav.decode(null))
        assertEquals(listOf(Screen.Library, Screen.Roteiro(r)), Nav.decode("rot:$r|rot:NOT-A-UUID|zzz"))
    }
}
