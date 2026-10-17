package com.al4xdev.h3.data

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * Duration/seed rules mirrored from the backend (`/app/config` duration_capabilities):
 * 24 fps, frames = 5 + 17k, half-even rounding, requested (0, 10] with at most 2 decimals,
 * aligned frames at most 243.
 */
object Durations {
    const val FPS = 24
    const val FRAME_BASE = 5
    const val FRAME_STRIDE = 17
    const val MAX_FRAMES = 243
    val MAX_SECONDS: BigDecimal = BigDecimal("10")
    const val DEFAULT_TEXT = "8"
    const val MAX_SEED = 9_007_199_254_740_991L
    const val DEFAULT_SEED = 2_026_101_205L

    private val pattern = Regex("""^\d{1,2}([.,]\d{1,2})?$""")

    /** Aligned frame count for a requested duration, exactly like app.js/backend. */
    fun frames(seconds: BigDecimal): Int {
        val requested = maxOf(FRAME_BASE, seconds.multiply(BigDecimal(FPS)).setScale(0, RoundingMode.HALF_EVEN).toInt())
        return requested + ((FRAME_BASE - requested % FRAME_STRIDE + FRAME_STRIDE) % FRAME_STRIDE)
    }

    fun frames(seconds: Double): Int = frames(BigDecimal(seconds.toString()))

    fun effectiveSeconds(frames: Int): Double = frames.toDouble() / FPS

    /** Parses user text ("8", "8,5", "7.25"); null when outside the backend contract. */
    fun parse(text: String): BigDecimal? {
        val t = text.trim()
        if (!pattern.matches(t)) return null
        val value = BigDecimal(t.replace(',', '.'))
        if (value.signum() <= 0 || value > MAX_SECONDS) return null
        if (frames(value) > MAX_FRAMES) return null
        return value
    }

    fun parseSeed(text: String): Long? {
        val t = text.trim()
        if (t.isEmpty() || t.length > 16 || !t.all { it in '0'..'9' }) return null
        val v = t.toLongOrNull() ?: return null
        return if (v in 0..MAX_SEED) v else null
    }

    /** Portuguese display with comma: 8.0 → "8,00". */
    fun label(seconds: Double): String = String.format(java.util.Locale.ROOT, "%.2f", seconds).replace('.', ',')

    /** Editable text for a stored duration (8.0 → "8", 7.25 → "7,25"). */
    fun text(seconds: Double): String =
        BigDecimal(seconds.toString()).stripTrailingZeros().toPlainString().replace('.', ',')

    /** "→ 192 frames · 8,00 s efetivos" or the validation message. */
    fun preview(text: String): String {
        val v = parse(text) ?: return "Use um valor maior que 0 e até 10 s, com no máximo 2 casas."
        val f = frames(v)
        return "→ $f frames · ${label(effectiveSeconds(f))} s efetivos a $FPS fps"
    }
}
