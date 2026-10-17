package com.al4xdev.h3.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.math.BigDecimal

class DurationsTest {
    @Test
    fun alignedFramesFollowFivePlusSeventeenK() {
        assertEquals(192, Durations.frames(8.0))
        assertEquals(56, Durations.frames(2.3)) // frozen benchmark: 2.3 s → 56 frames
        assertEquals(243, Durations.frames(10.0)) // max aligned frames
        assertEquals(5, Durations.frames(0.01)) // floor of 5 frames
        assertEquals(124, Durations.frames(5.0))
        for (s in listOf(0.5, 1.0, 3.33, 7.25, 9.99)) assertEquals(5, Durations.frames(s) % 17)
    }

    @Test
    fun parseAcceptsBackendContractOnly() {
        assertEquals(BigDecimal("8.5"), Durations.parse("8,5"))
        assertEquals(BigDecimal("7.25"), Durations.parse(" 7.25 "))
        assertEquals(BigDecimal("10"), Durations.parse("10"))
        assertNull(Durations.parse("0"))
        assertNull(Durations.parse("10.01"))
        assertNull(Durations.parse("8.123"))
        assertNull(Durations.parse("-1"))
        assertNull(Durations.parse("abc"))
        assertNull(Durations.parse(""))
    }

    @Test
    fun seedsAreIntegersWithinJsSafeRange() {
        assertEquals(2026101205L, Durations.parseSeed("2026101205"))
        assertEquals(9007199254740991L, Durations.parseSeed("9007199254740991"))
        assertNull(Durations.parseSeed("9007199254740992"))
        assertNull(Durations.parseSeed("12.5"))
        assertNull(Durations.parseSeed("-3"))
        assertNull(Durations.parseSeed(""))
    }

    @Test
    fun labelsAndPreview() {
        assertEquals("8,00", Durations.label(8.0))
        assertEquals("8", Durations.text(8.0))
        assertEquals("7,25", Durations.text(7.25))
        assertEquals("→ 192 frames · 8,00 s efetivos a 24 fps", Durations.preview("8"))
        assertEquals("→ 243 frames · 10,13 s efetivos a 24 fps", Durations.preview("10"))
    }
}
