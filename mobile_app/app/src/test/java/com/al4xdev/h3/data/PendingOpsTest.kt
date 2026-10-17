package com.al4xdev.h3.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PendingOpsTest {
    private val rid = "11111111-1111-4111-8111-111111111111"
    private val bid = "22222222-2222-4222-8222-222222222222"

    @Test
    fun recordSurvivesProcessDeathUntilResolved() {
        val disk = MemoryStore()
        val op = PendingOps(disk).begin(PendingOp(OpKind.BATCH, newUuid(), rid))
        // A new instance over the same storage = app restarted mid-POST: the ID is still there.
        val restarted = PendingOps(disk)
        assertEquals(op.id, restarted.find(OpKind.BATCH, rid)?.id)
        restarted.resolve(op.id)
        assertNull(PendingOps(disk).get(op.id))
    }

    @Test
    fun outcomeClassification() {
        assertEquals(Outcome.DONE, ApiResult.Ok(Unit, 202).outcome())
        assertEquals(Outcome.UNCERTAIN, ApiResult.Network("timeout").outcome())
        assertEquals(Outcome.UNCERTAIN, ApiResult.Http(502, "bad gateway", null).outcome())
        assertEquals(Outcome.REFUSED, ApiResult.Http(409, "conflict", null).outcome())
        assertTrue(ApiResult.Http(500, "", null).uncertain)
    }

    @Test
    fun unreadableSuccessIsUncertainNotRefused() {
        val r: ApiResult<Int> = ApiResult.Ok<String?>(null, 202).map { error("corpo ausente") }
        assertTrue(r.uncertain)
        assertEquals(Outcome.UNCERTAIN, r.outcome())
    }

    @Test
    fun settleKeepsUncertainAndAttemptRefusals() {
        val ops = PendingOps(MemoryStore())
        val batch = ops.begin(PendingOp(OpKind.BATCH, newUuid(), rid))
        ops.settle(batch, Outcome.REFUSED)
        assertNull(ops.get(batch.id))

        val assembly = ops.begin(PendingOp(OpKind.ASSEMBLY, newUuid(), rid))
        ops.settle(assembly, Outcome.UNCERTAIN, "timeout")
        assertEquals("timeout", ops.get(assembly.id)?.detail)

        // An intent may be durable on the PC even when the POST answered 4xx: only a GET clears it.
        val attempt = ops.begin(PendingOp(OpKind.ATTEMPT, newUuid(), rid, bid))
        ops.settle(attempt, Outcome.REFUSED, "409")
        assertNotNull(ops.get(attempt.id))
        ops.settle(attempt, Outcome.DONE)
        assertNull(ops.get(attempt.id))
    }

    @Test
    fun scopedLookup() {
        val ops = PendingOps(MemoryStore())
        ops.begin(PendingOp(OpKind.ATTEMPT, newUuid(), rid, bid))
        ops.begin(PendingOp(OpKind.SEGMENT, newUuid(), "33333333-3333-4333-8333-333333333333"))
        assertEquals(1, ops.forRoteiro(rid).size)
        assertNotNull(ops.find(OpKind.ATTEMPT, rid, bid))
        assertNull(ops.find(OpKind.BATCH, rid))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonCanonicalIds() {
        PendingOps(MemoryStore()).begin(PendingOp(OpKind.BATCH, "ABC", rid))
    }

    @Test
    fun uuidsAreCanonicalLowercase() {
        repeat(20) { assertTrue(isCanonicalUuid(newUuid())) }
        assertTrue(!isCanonicalUuid("11111111-1111-4111-8111-11111111111A"))
    }

    @Test
    fun draftsRoundTrip() {
        val drafts = Drafts(MemoryStore())
        val d = NewRoteiroDraft(title = "Dança", idea = "ideia", count = 750, durationText = "7,5", roteiroId = rid, creationUncertain = true,
            reference = InputItem("inputs", "x/original.png", "foto", "/inputs/image?path=x/original.png", 480, 864))
        drafts.saveNewRoteiro(d)
        assertEquals(d, drafts.newRoteiro())
        val c = Candidate("n", listOf(Block(bid, "a", 8.0, 1L, "p")), fromGrok = true,
            scenes = listOf(Scene("Abertura", listOf(Beat("action", "gira", 4.0, "olá")))),
            vision = Vision("noir", "steadicam", "neon", "lento", ""))
        drafts.saveCandidate(rid, c)
        assertEquals(c, drafts.candidate(rid))
        val ins = InsertDraft(idea = "x", count = 4, segmentId = newUuid())
        drafts.saveInsert(rid, null, ins)
        assertEquals(ins, drafts.insert(rid, null))
        assertNull(drafts.insert(rid, bid))
    }
}
