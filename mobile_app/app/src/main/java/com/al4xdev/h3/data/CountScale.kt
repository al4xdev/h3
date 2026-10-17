package com.al4xdev.h3.data

/**
 * Slider positions for block counts: fine where counts are small, coarse for long films
 * (1–30 by 1, 30–100 by 5, 100–1000 by 25). The −/+ buttons still step by 1.
 */
object CountScale {
    private val all: List<Int> = (1..30).toList() + (35..100 step 5) + (125..MAX_BLOCKS step 25)

    /** Positions available up to `max` (the room left in the roteiro); `max` itself is always reachable. */
    fun values(max: Int): List<Int> {
        val capped = all.filter { it <= max }
        return if (max >= 1 && capped.lastOrNull() != max) capped + max else capped
    }

    /** Slider position for a value that may sit between positions (set by −/+). */
    fun positionOf(value: Int, values: List<Int>): Int = values.indexOfLast { it <= value }.coerceAtLeast(0)

    fun valueAt(position: Float, values: List<Int>): Int = values[Math.round(position).coerceIn(0, values.lastIndex)]
}
