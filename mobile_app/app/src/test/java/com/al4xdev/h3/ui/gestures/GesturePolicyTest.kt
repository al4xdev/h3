package com.al4xdev.h3.ui.gestures

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GesturePolicyTest {
    private val w = 1080f
    private val d = 2.625f // px per dp on a typical phone

    @Test
    fun lanesAreMirroredAndNeedSomewhereToGo() {
        assertEquals(SwipeKind.Back, WorkspaceGesturePolicy.lane(100f, w, blocked = false, canBack = true, canForward = true))
        assertEquals(SwipeKind.Forward, WorkspaceGesturePolicy.lane(1000f, w, blocked = false, canBack = true, canForward = true))
        assertNull(WorkspaceGesturePolicy.lane(540f, w, blocked = false, canBack = true, canForward = true)) // middle 10%
        assertNull(WorkspaceGesturePolicy.lane(100f, w, blocked = false, canBack = false, canForward = true))
        assertNull(WorkspaceGesturePolicy.lane(1000f, w, blocked = false, canBack = true, canForward = false)) // empty forward stack
        assertNull(WorkspaceGesturePolicy.lane(100f, w, blocked = true, canBack = true, canForward = true)) // slider/player/field
    }

    @Test
    fun axisWaitsForTouchSlopAndRejectsVerticalOrWrongWay() {
        val slop = 21f
        assertEquals(GestureAxis.Pending, WorkspaceGesturePolicy.axis(15f, 2f, slop))
        assertEquals(GestureAxis.Horizontal, WorkspaceGesturePolicy.axis(40f, 10f, slop))
        assertEquals(GestureAxis.Vertical, WorkspaceGesturePolicy.axis(10f, 40f, slop))
        assertEquals(GestureAxis.Vertical, WorkspaceGesturePolicy.axis(-40f, 0f, slop)) // dragging the wrong way
    }

    @Test
    fun releaseCompletesPastFortyPercentOrOnFling() {
        assertTrue(WorkspaceGesturePolicy.complete(0.45f * w, w, 0f, d))
        assertFalse(WorkspaceGesturePolicy.complete(0.30f * w, w, 0f, d))
        assertTrue(WorkspaceGesturePolicy.complete(60f * d, w, 900f * d, d)) // short fast fling
        assertFalse(WorkspaceGesturePolicy.complete(10f * d, w, 900f * d, d)) // fling too short to mean it
    }

    @Test
    fun flingBackCancelsEvenWhenFar() {
        assertFalse(WorkspaceGesturePolicy.complete(0.7f * w, w, -400f * d, d))
        assertFalse(WorkspaceGesturePolicy.complete(0f, w, 2000f * d, d))
        assertFalse(WorkspaceGesturePolicy.complete(-50f, w, 0f, d))
    }
}
