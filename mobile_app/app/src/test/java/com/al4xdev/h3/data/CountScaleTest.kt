package com.al4xdev.h3.data

import com.al4xdev.h3.ui.components.fastScrollIndex
import org.junit.Assert.assertEquals
import org.junit.Test

class CountScaleTest {
    @Test
    fun fineAtTheStartCoarseForLongFilms() {
        val v = CountScale.values(1000)
        assertEquals((1..30).toList(), v.take(30))
        assertEquals(listOf(35, 40), v.subList(30, 32))
        assertEquals(100, v[v.indexOf(100)])
        assertEquals(125, v[v.indexOf(100) + 1])
        assertEquals(1000, v.last())
        assertEquals(30 + 14 + 36, v.size)
    }

    @Test
    fun capIsAlwaysReachable() {
        assertEquals(listOf(1, 2, 3), CountScale.values(3))
        assertEquals(37, CountScale.values(37).last())
        assertEquals(35, CountScale.values(37)[30])
        assertEquals(emptyList<Int>(), CountScale.values(0))
    }

    @Test
    fun positionsRoundTripAndPlusMinusValuesLandBetween() {
        val v = CountScale.values(1000)
        assertEquals(12, CountScale.valueAt(CountScale.positionOf(12, v).toFloat(), v))
        assertEquals(CountScale.positionOf(35, v), CountScale.positionOf(37, v)) // 37 (set by +) sits on 35's notch
        assertEquals(1000, CountScale.valueAt(999f, v))
        assertEquals(1, CountScale.valueAt(-3f, v))
    }

    @Test
    fun runFramesGetReadableLabels() {
        val run = "cccccccc-0000-4000-8000-000000000001"
        assertEquals("initial frame · cccccccc", InputItem("runs", ".data/runs/$run/initial_frame.png", "initial_frame.png", null, 480, 864).label)
        assertEquals("last frame · cccccccc", InputItem("runs", "runs/$run/last_frame.png", "", null, null, null).label)
        assertEquals("foto.png", InputItem("inputs", "x/original.png", "foto.png", null, null, null).label)
        assertEquals("dance_reference.png", InputItem("assets", "dance_reference.png", "", null, null, null).label)
    }

    @Test
    fun fastScrollMapsTrackToBlocks() {
        assertEquals(0, fastScrollIndex(-10f, 1000f, 1000))
        assertEquals(999, fastScrollIndex(2000f, 1000f, 1000))
        assertEquals(500, fastScrollIndex(500f, 1000f, 1000))
        assertEquals(0, fastScrollIndex(300f, 0f, 1000))
    }
}
