package com.al4xdev.h3.ui

import com.al4xdev.h3.data.isCanonicalUuid

/** App screens. Encoded as short strings so the back stack survives process death. */
sealed interface Screen {
    data object Library : Screen
    data object NewRoteiro : Screen
    data class Roteiro(val roteiroId: String) : Screen
    data class Block(val roteiroId: String, val blockId: String) : Screen
    /** Insert N planned blocks after `afterBlockId`; null = before the first block. */
    data class Insert(val roteiroId: String, val afterBlockId: String?) : Screen
    data class Redo(val roteiroId: String, val blockId: String) : Screen
    data class Review(val roteiroId: String, val blockId: String, val runId: String) : Screen
    data class Assembly(val roteiroId: String) : Screen
    /** "Assistir em sequência" starting at `fromBlockId`. */
    data class Watch(val roteiroId: String, val fromBlockId: String) : Screen
    data object Settings : Screen
}

/** Roteiro a screen belongs to (for SSE refreshes of what is visible). */
val Screen.ownerId: String?
    get() = when (this) {
        is Screen.Roteiro -> roteiroId
        is Screen.Block -> roteiroId
        is Screen.Insert -> roteiroId
        is Screen.Redo -> roteiroId
        is Screen.Review -> roteiroId
        is Screen.Assembly -> roteiroId
        is Screen.Watch -> roteiroId
        else -> null
    }

/**
 * Back stack plus forward stack (screens popped by back, re-pushable by the forward swipe).
 * Any navigation other than re-entering the most recently popped screen clears `forward`.
 */
data class NavStack(val back: List<Screen> = listOf(Screen.Library), val forward: List<Screen> = emptyList()) {
    val top: Screen get() = back.last()
    val canPop: Boolean get() = back.size > 1
    val nextForward: Screen? get() = forward.lastOrNull()

    fun push(screen: Screen): NavStack = when {
        screen == top -> this
        screen == nextForward -> NavStack(back + screen, forward.dropLast(1))
        else -> NavStack(back + screen, emptyList())
    }

    fun pop(): NavStack = if (!canPop) this else NavStack(back.dropLast(1), forward + top)

    fun goForward(): NavStack = nextForward?.let { NavStack(back + it, forward.dropLast(1)) } ?: this

    fun replaceTop(screen: Screen): NavStack = if (screen == top) this else NavStack(back.dropLast(1) + screen, emptyList())

    fun reset(vararg screens: Screen): NavStack = NavStack(listOf(Screen.Library) + screens, emptyList())

    /** Keys whose saved UI state must be kept (both stacks). */
    fun liveKeys(): Set<String> = (back + forward).map { Nav.key(it) }.toSet()
}

object Nav {
    fun key(screen: Screen): String = encode(listOf(screen))

    /** Forward stack: plain list, no implicit library root. */
    fun decodeList(text: String?): List<Screen> = text.orEmpty().split("|").filter { it.isNotEmpty() }.mapNotNull(::decodeOne)

    fun encode(stack: List<Screen>): String = stack.joinToString("|") { s ->
        when (s) {
            Screen.Library -> "lib"
            Screen.NewRoteiro -> "new"
            Screen.Settings -> "set"
        is Screen.Roteiro -> "rot:${s.roteiroId}"
        is Screen.Block -> "blk:${s.roteiroId}:${s.blockId}"
        is Screen.Insert -> "ins:${s.roteiroId}:${s.afterBlockId ?: "-"}"
        is Screen.Redo -> "redo:${s.roteiroId}:${s.blockId}"
        is Screen.Review -> "rev:${s.roteiroId}:${s.blockId}:${s.runId}"
        is Screen.Assembly -> "asm:${s.roteiroId}"
        is Screen.Watch -> "watch:${s.roteiroId}:${s.fromBlockId}"
        }
    }

    fun decode(text: String?): List<Screen> {
        val parsed = text.orEmpty().split("|").filter { it.isNotEmpty() }.mapNotNull(::decodeOne)
        // The library is always the root, so back from anything ends there.
        return if (parsed.firstOrNull() == Screen.Library) parsed else listOf(Screen.Library) + parsed
    }

    private fun decodeOne(item: String): Screen? {
        val p = item.split(":")
        fun id(i: Int) = p.getOrNull(i)?.takeIf(::isCanonicalUuid)
        return when (p[0]) {
            "lib" -> Screen.Library
            "new" -> Screen.NewRoteiro
            "set" -> Screen.Settings
            "rot" -> Screen.Roteiro(id(1) ?: return null)
            "blk" -> Screen.Block(id(1) ?: return null, id(2) ?: return null)
            "ins" -> Screen.Insert(id(1) ?: return null, if (p.getOrNull(2) == "-") null else id(2) ?: return null)
            "redo" -> Screen.Redo(id(1) ?: return null, id(2) ?: return null)
            "rev" -> Screen.Review(id(1) ?: return null, id(2) ?: return null, id(3) ?: return null)
            "asm" -> Screen.Assembly(id(1) ?: return null)
            "watch" -> Screen.Watch(id(1) ?: return null, id(2) ?: return null)
        else -> null
    }
    }
}
