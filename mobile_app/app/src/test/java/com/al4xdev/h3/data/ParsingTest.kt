package com.al4xdev.h3.data

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ParsingTest {
    private val roteiroJson = """
    {
      "id": "aaaaaaaa-0000-4000-8000-000000000001", "revision": 7, "name": "Dança sob neon",
      "idea": "Ela dança", "reference": {"source_root": "inputs", "path": "abc/original.png"},
      "reference_sha256": "${"0".repeat(64)}", "adopted": true,
      "blocks": [
        {"id": "bbbbbbbb-0000-4000-8000-000000000001", "action": "abre", "duration_seconds": 8.0, "seed": 2026101205, "prompt": "opens"},
        {"id": "bbbbbbbb-0000-4000-8000-000000000002", "action": "vira", "duration_seconds": 7.25, "seed": 9007199254740991, "prompt": "turns"}
      ],
      "selected_runs": {"bbbbbbbb-0000-4000-8000-000000000001": "cccccccc-0000-4000-8000-000000000001"},
      "removed_blocks": [{"block": {}}],
      "attempts": [
        {"intent_id": "cccccccc-0000-4000-8000-000000000001", "run_id": "cccccccc-0000-4000-8000-000000000001",
         "roteiro_id": "aaaaaaaa-0000-4000-8000-000000000001", "block_id": "bbbbbbbb-0000-4000-8000-000000000001",
         "source_revision": 2,
         "snapshot": {"prompt": "opens", "seed": 2026101205, "duration_seconds": 8.0, "parent_id": null,
                      "reference": {"source_root": "inputs", "path": "abc/original.png", "sha256": "${"1".repeat(64)}"}},
         "origin": "native", "target_run_id": null, "source": null, "admission": "admitted", "error": null,
         "state": "accepted",
         "run": {"id": "cccccccc-0000-4000-8000-000000000001", "state": "accepted", "prompt": "Opens, improved by Grok",
                 "seed": 2026101205, "duration_seconds": 8.0, "parent_id": null, "error": null,
                 "output": {"path": ".data/runs/cccccccc-0000-4000-8000-000000000001/chunk.mp4"},
                 "input_info": {"operation": "i2v", "mode": "normal"}}},
        {"intent_id": "cccccccc-0000-4000-8000-000000000002", "run_id": "cccccccc-0000-4000-8000-000000000002",
         "roteiro_id": "aaaaaaaa-0000-4000-8000-000000000001", "block_id": "bbbbbbbb-0000-4000-8000-000000000002",
         "source_revision": 5,
         "snapshot": {"prompt": "turns", "seed": 1, "duration_seconds": 7.25, "parent_id": "cccccccc-0000-4000-8000-000000000001",
                      "reference": {"source_root": "inputs", "path": "abc/original.png", "sha256": "${"1".repeat(64)}"}},
         "origin": "bridge", "target_run_id": "cccccccc-0000-4000-8000-000000000009", "source": null,
         "admission": "rejected", "error": {"code": "busy"}, "state": "not_admitted", "run": null}
      ]
    }
    """.trimIndent()

    @Test
    fun parsesRoteiroView() {
        val doc = Roteiro.parse(parseJson(roteiroJson).jsonObject)
        assertEquals(7, doc.revision)
        assertEquals(Reference("inputs", "abc/original.png"), doc.reference)
        assertEquals(2, doc.blocks.size)
        assertEquals(9007199254740991L, doc.blocks[1].seed)
        assertEquals(7.25, doc.blocks[1].durationSeconds, 0.0)
        assertEquals(1, doc.removedBlockCount)
        val first = doc.attempts[0]
        assertEquals("Opens, improved by Grok", first.effectivePrompt)
        assertTrue(first.run!!.playable)
        assertEquals("i2v", first.run!!.operation)
        val second = doc.attempts[1]
        assertTrue(second.isBridge)
        assertEquals("cccccccc-0000-4000-8000-000000000009", second.targetRunId)
        assertNull(second.run)
        assertEquals("turns", second.effectivePrompt)
        assertEquals("{\"code\":\"busy\"}", second.error)
        assertEquals(BlockState.ACCEPTED, RoteiroLogic.blockState(doc, doc.blocks[0].id))
        assertEquals(BlockState.FAILED, RoteiroLogic.blockState(doc, doc.blocks[1].id))
    }

    @Test
    fun blockJsonKeepsStrictTypes() {
        val json = Block("bbbbbbbb-0000-4000-8000-000000000001", "a", 8.0, 2026101205L, "p").toJson()
        assertTrue((json["seed"] as JsonPrimitive).content == "2026101205")
        assertEquals("8.0", (json["duration_seconds"] as JsonPrimitive).content)
        assertFalse((json["seed"] as JsonPrimitive).isString)
        assertEquals(setOf("id", "action", "duration_seconds", "seed", "prompt"), json.keys)
    }

    @Test
    fun parsesSummaryAndSegmentWithPlan() {
        val summary = SummaryItem.parseList(parseJson("""
            {"items":[{"id":"aaaaaaaa-0000-4000-8000-000000000001","name":"","idea":"Praia\nao pôr do sol","adopted":true,"revision":3,
             "block_count":3,"states":{"accepted":2,"planned":1},"strip":["accepted","accepted","planned"],"updated_at":"2026-10-16T10:00:00Z"}],"total":1}
        """.trimIndent()).jsonObject)
        assertEquals("Praia", summary[0].title)
        assertEquals(2, summary[0].count("accepted"))
        assertEquals(0, summary[0].count("failed"))
        assertEquals(listOf(BlockState.ACCEPTED, BlockState.ACCEPTED, BlockState.PLANNED), summary[0].strip.map(BlockState::fromWire))

        val seg = SegmentRecord.parse(parseJson("""
            {"id":"dddddddd-0000-4000-8000-000000000001","roteiro_id":"aaaaaaaa-0000-4000-8000-000000000001","source_revision":3,
             "after_block_id":null,"before_block_id":"bbbbbbbb-0000-4000-8000-000000000001","state":"proposed","stale":false,
             "vision":{"style":"noir","camera":"","light_and_color":"neon","rhythm":"","notes":""},
             "scenes":[{"title":"Abertura","beats":[{"kind":"action","action":"gira","seconds":4.5,"dialogue":"Oi"},
                                                   {"kind":"hold","action":"pausa","seconds":3.5,"dialogue":null}]}],
             "draft_scenes":[],
             "blocks":[{"id":"eeeeeeee-0000-4000-8000-000000000001","action":"Abertura · gira — parte 1/1","duration_seconds":8.0,"seed":5,"prompt":"spins"}],
             "raw_texts":["{}"]}
        """.trimIndent()).jsonObject)
        assertEquals("proposed", seg.state)
        assertNull(seg.afterBlockId)
        assertEquals(8.0, seg.scenes[0].seconds, 0.0)
        assertEquals("Oi", seg.scenes[0].beats[0].dialogue)
        assertNull(seg.scenes[0].beats[1].dialogue)
        assertEquals("noir", seg.vision?.style)
        assertEquals(1, seg.blocks.size)
    }

    @Test
    fun errorDetailReadsFastApiShapes() {
        assertEquals("Revision mismatch", errorDetail(parseJson("""{"detail":"Revision mismatch"}""").jsonObject, "", 409))
        assertEquals("body.seed: Input should be a valid integer",
            errorDetail(parseJson("""{"detail":[{"loc":["body","seed"],"msg":"Input should be a valid integer"}]}""").jsonObject, "", 422))
        assertEquals("rate_limited · slow down", errorDetail(parseJson("""{"error":"rate_limited","detail":"slow down"}""").jsonObject, "", 429))
        assertEquals("HTTP 502", errorDetail(null, "", 502))
    }

    @Test
    fun referencePreviewPaths() {
        assertEquals("/inputs/image?path=a%20b/original.png", Reference("inputs", "a b/original.png").imagePath())
        assertEquals("/runs/cccccccc-0000-4000-8000-000000000001/image?name=last_frame.png",
            Reference("runs", ".data/runs/cccccccc-0000-4000-8000-000000000001/last_frame.png").imagePath())
        assertNull(Reference("runs", "../etc/passwd").imagePath())
    }

    @Test
    fun parsesNarratorEventWithoutBeats() {
        val scene = Scene.parse(parseJson("""
            {"title":"Sala","kind":"speech","intent":"ela fala e ri","dialogue":"Oi, guris",
             "anatomy":["corpo 1","corpo 2"],"expressions":["olhar 1"],"deltas":["peso 1"]}
        """.trimIndent()).jsonObject)
        assertTrue(scene.isEvent)
        assertEquals("ela fala e ri", scene.intent)
        assertEquals("Oi, guris", scene.dialogue)
        assertEquals(2, scene.anatomy.size)
        assertEquals(0.0, scene.seconds, 0.0)
    }

    @Test
    fun sseParserYieldsChangePaths() {
        val parser = SseParser()
        val lines = listOf(": hi", "event: change", "data: {\"path\":\"roteiros/x/plan.json\",\"invalidation\":true}", "")
        val events = lines.mapNotNull(parser::feed)
        assertEquals(1, events.size)
        val path = SseParser.changedPath(events[0].first, events[0].second)
        assertEquals("roteiros/x/plan.json", path)
        assertTrue(SseParser.relevant(path!!))
        assertNull(SseParser.changedPath("change", "{\"path\":\"runs/x/video.mp4.part\"}"))
        assertFalse(SseParser.relevant("inputs/abc/original.png"))
    }
}
