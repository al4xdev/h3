"""Long roteiros: summary, removal, relaxed PUT, segments, timeline planning and middle batches.

CPU fixtures only: fake ComfyUI/media/builders and fake Grok clients, never a real provider.
"""

import asyncio
import sys
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_bridge import BridgeBuilder
from test_grok_continuation import command
from test_roteiro import FakeGrok, fields, setup, update
from test_roteiro_batch import FakeEnhancer, consent

from h3_backend.api import create_app
from h3_backend.generation.dispatcher import Conflict
from h3_backend.roteiro import (
    MAX_BLOCKS,
    Block,
    CreatePlan,
    Generate,
    ProposalRequest,
    RemovePlan,
    SegmentRequest,
    Timeline,
    slice_timeline,
)
from h3_backend.roteiro_batch import RoteiroBatch


def blocks(count, *, prefix="ACT"):
    return [{"id": str(uuid4()), "action": f"{prefix}-{i:03d}", "duration_seconds": 2.3,
             "seed": 7, "prompt": f"PROMPT-{prefix}-{i:03d}"} for i in range(count)]


async def chain(tmp_path, count, *, planned=0, video=True):
    """A roteiro whose first `count` blocks are accepted and genealogically chained."""
    service, op = setup(tmp_path)
    service.builder = BridgeBuilder()

    async def first_frame(source, destination):
        destination.write_bytes(b"exact-first-frame")
        return {"path": str(destination), "source_frame_index": 0, "format": "PNG"}

    service.media.prepare_first_frame = first_frame
    if video:
        # A real tiny MP4 lets continuation_frame decode an actual final frame for Grok context.
        command("ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                "testsrc2=size=32x32:rate=4:duration=1", "-c:v", "libx264", "-threads", "1",
                "-pix_fmt", "yuv420p", str(tmp_path / "comfy/output/safe/final.mp4"))
    payload = fields(count=1)
    payload["blocks"] = blocks(count + planned)
    created = await op.create(CreatePlan(**payload))
    doc = op.get(created["id"])
    parent = None
    for block in doc.blocks[:count]:
        run_id = str(uuid4())
        await op.generate(doc.id, block.id, run_id, Generate(
            expected_revision=doc.revision, prompt=block.prompt, seed=block.seed,
            duration_seconds=block.duration_seconds, parent_id=parent))
        await service.wait_run(run_id)
        await service.decide(run_id, True)
        parent = run_id
    return service, op, op.get(doc.id)


def client_for(service, grok=None):
    app = create_app(service=service)
    app.state.grok = grok
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                             base_url="http://local.test")


@pytest.mark.asyncio
async def test_summary_route_reports_block_states_without_colliding_with_ids(tmp_path):
    service, _, doc = await chain(tmp_path, 2, planned=2, video=False)
    async with client_for(service) as client:
        result = await client.get("/roteiros/summary")
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["id"] == doc.id and item["block_count"] == 4 and item["adopted"] is True
        assert item["strip"] == ["accepted", "accepted", "planned", "planned"]
        assert item["states"] == {"accepted": 2, "ready_for_review": 0, "active": 0,
                                  "failed": 0, "planned": 2}
        assert item["revision"] == doc.revision and item["updated_at"]
        assert set(item) == {"id", "name", "idea", "adopted", "revision", "block_count",
                             "states", "strip", "updated_at"}
        assert (await client.get(f"/roteiros/{doc.id}")).status_code == 200
    await service.shutdown()


@pytest.mark.asyncio
async def test_remove_planned_and_accepted_middle_preserves_history_and_cut(tmp_path):
    service, op, doc = await chain(tmp_path, 3, planned=1, video=False)
    first, middle, last, planned = doc.blocks
    removed = op.remove_block(doc.id, planned.id, RemovePlan(expected_revision=doc.revision))
    assert [b["id"] for b in removed["blocks"]] == [first.id, middle.id, last.id]
    assert removed["removed_blocks"] == []
    doc = op.get(doc.id)
    middle_run = next(a.run_id for a in doc.attempts if a.block_id == middle.id)
    async with client_for(service) as client:
        result = await client.post(f"/roteiros/{doc.id}/blocks/{middle.id}/remove",
                                   json={"expected_revision": doc.revision})
        assert result.status_code == 200, result.text
        view = result.json()
    assert [b["id"] for b in view["blocks"]] == [first.id, last.id]
    assert [b["id"] for b in view["removed_blocks"]] == [middle.id]
    assert len(view["attempts"]) == 3 and all(a["state"] == "accepted" for a in view["attempts"])
    after = op.get(doc.id)
    assert set(after.selected_runs) == {first.id, last.id}
    # The cut is visible: the last block's parent is the removed middle video, kept intact.
    last_attempt = op.selected_attempt(after, last.id)
    assert last_attempt.snapshot.parent_id == middle_run
    assert service.store.get(middle_run).state == "accepted" and service.video_path(middle_run).is_file()
    assert op.selected_run_ids(after) == [op.selected_attempt(after, first.id).run_id,
                                          last_attempt.run_id]
    # A removed block cannot come back through PUT.
    with pytest.raises((Conflict, ValueError)):
        await op.update(doc.id, update(after, blocks=[*after.blocks, middle]))
    with pytest.raises(Conflict):
        op.remove_block(doc.id, first.id, RemovePlan(expected_revision=doc.revision))
    await service.shutdown()


@pytest.mark.asyncio
async def test_remove_refuses_review_pending_block(tmp_path):
    service, op, doc = await chain(tmp_path, 1, planned=1, video=False)
    block = doc.blocks[1]
    run_id = str(uuid4())
    await op.generate(doc.id, block.id, run_id, Generate(
        expected_revision=doc.revision, prompt=block.prompt, seed=block.seed,
        duration_seconds=block.duration_seconds, parent_id=doc.attempts[0].run_id))
    await service.wait_run(run_id)
    with pytest.raises(Conflict, match="Aceite ou recuse"):
        op.remove_block(doc.id, block.id, RemovePlan(expected_revision=doc.revision))
    assert op.get(doc.id).blocks == doc.blocks
    await service.shutdown()


@pytest.mark.asyncio
async def test_relaxed_put_edits_only_never_sent_blocks_anywhere(tmp_path):
    service, op, doc = await chain(tmp_path, 2, planned=2, video=False)
    a, b, p1, p2 = doc.blocks
    new = Block(**blocks(1, prefix="NEW")[0])
    edited = p2.model_copy(update={"prompt": "edited"})
    result = await op.update(doc.id, update(doc, blocks=[new, a, edited, b]))
    assert [x["id"] for x in result["blocks"]] == [new.id, a.id, p2.id, b.id]
    doc = op.get(doc.id)
    for invalid in ([b, a, new, edited],  # reordered attempted blocks
                    [a, b.model_copy(update={"prompt": "changed"}), new],  # edited attempted
                    [a, new]):  # deleted attempted block
        with pytest.raises(Conflict, match="Blocks with attempts"):
            await op.update(doc.id, update(doc, blocks=invalid))
    assert p1.id not in {x.id for x in op.get(doc.id).blocks}
    await service.shutdown()


class SegmentGrok(FakeGrok):
    def __init__(self, *, fail_chunk=None, **kwargs):
        super().__init__(**kwargs)
        self.active = 0
        self.peak = 0
        self.fail_chunk = fail_chunk

    async def complete(self, request, **kwargs):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.01)
            if kwargs.get("schema_name") == "h3_roteiro_card" and self.fail_chunk is not None:
                from test_roteiro import payload_of
                slot = payload_of(request.prompt)
                if slot["index"] == self.fail_chunk:
                    self.calls.append(request)
                    self.schemas.append(kwargs)
                    return {"text": '{"blocks":[]}'}
            return await super().complete(request, **kwargs)
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_segment_single_plan_uses_neighbours_and_never_writes_plan(tmp_path):
    service, op, doc = await chain(tmp_path, 2)
    a, b = doc.blocks
    run_a = op.selected_attempt(doc, a.id).run_id
    fake = SegmentGrok()
    ident = str(uuid4())
    async with client_for(service, fake) as client:
        url = f"/roteiros/{doc.id}/segments/{ident}"
        assert (await client.get(url)).status_code == 404
        result = await client.post(url, json={
            "expected_revision": doc.revision, "after_block_id": a.id, "idea": "Gira devagar",
            "count": 3, "duration_seconds": 8, "seed": 5})
        assert result.status_code == 200, result.text
        record = result.json()
        assert record["state"] == "proposed" and record["stale"] is False
        assert record["after_block_id"] == a.id and record["before_block_id"] == b.id
        assert len(record["blocks"]) == 3 and len(record["raw_texts"]) == 4
        assert all(x["duration_seconds"] == 8 and x["seed"] == 5 for x in record["blocks"])
        assert record["vision"] is None and record["scenes"] and record["draft_scenes"]
        assert (await client.get(url)).json() == record
        again = await client.post(url, json={
            "expected_revision": doc.revision, "after_block_id": a.id, "idea": "x",
            "count": 1, "duration_seconds": 8, "seed": 5})
        assert again.status_code == 409
    from test_roteiro import payload_of
    context = payload_of(fake.calls[0].prompt)["context"]
    assert context["idea"] == "Gira devagar" and context["original_idea"] == doc.idea
    assert context["previous_block"]["historical_prompt_actually_submitted"] == a.prompt
    assert context["following_block"]["editorial_intention"] == b.action
    assert all(call.continuation_parent_id == run_a for call in fake.calls)
    assert op.get(doc.id) == doc and len(fake.calls) == 4
    # Adoption is an explicit PUT inserting the planned blocks between the two accepted ones.
    planned = [Block(**x) for x in record["blocks"]]
    adopted = await op.update(doc.id, update(doc, blocks=[a, *planned, b]))
    assert len(adopted["blocks"]) == 5
    assert await op.propose_segment(doc.id, str(uuid4()), SegmentRequest(
        expected_revision=adopted["revision"], after_block_id=None, idea="Abertura", count=1,
        duration_seconds=8, seed=1), SegmentGrok()) is not None
    await service.shutdown()


@pytest.mark.asyncio
async def test_segment_chunks_run_in_parallel_and_invalid_chunk_keeps_raw_texts(tmp_path):
    service, op = setup(tmp_path)
    doc = op.get((await op.create(CreatePlan(**fields(count=1))))["id"])
    fake = SegmentGrok()
    record = await op.propose_segment(doc.id, str(uuid4()), SegmentRequest(
        expected_revision=doc.revision, after_block_id=doc.blocks[0].id, idea="Muito tempo",
        count=45, duration_seconds=8, seed=3), fake)
    assert record["state"] == "proposed" and len(record["blocks"]) == 45
    card_calls = [s for s in fake.schemas if s["schema_name"] == "h3_roteiro_card"]
    assert len(card_calls) == 45 and 1 < fake.peak <= 4
    assert len(record["raw_texts"]) == 1 + 45
    failing = SegmentGrok(fail_chunk=11)
    ident = str(uuid4())
    invalid = await op.propose_segment(doc.id, ident, SegmentRequest(
        expected_revision=doc.revision, after_block_id=None, idea="Muito tempo",
        count=25, duration_seconds=8, seed=3), failing)
    assert invalid["state"] == "invalid" and invalid["error"] == "prompt_failed"
    assert invalid["blocks"] == [] and '{"blocks":[]}' in invalid["raw_texts"]
    assert op.get_segment(doc.id, ident)["state"] == "invalid"
    assert op.get(doc.id) == doc and not service.comfy.submitted
    await service.shutdown()


def test_single_sustained_beat_is_sliced_into_parts_with_requested_duration():
    timeline = Timeline.model_validate({"name": "Um", "scenes": [{"title": "Palco", "beats": [
        {"kind": "action", "action": "Dança contínua", "seconds": 80, "dialogue": None}]}]})
    scenes, slices = slice_timeline(timeline.scenes, 10, 8.0)
    assert [s["part"] for s in slices] == list(range(1, 11))
    assert {s["parts"] for s in slices} == {10} and scenes[0]["end_seconds"] == 80


@pytest.mark.asyncio
async def test_ten_blocks_one_eighty_second_beat_yield_parts_and_fixed_duration(tmp_path):
    service, op = setup(tmp_path)
    doc = op.get((await op.create(CreatePlan(**fields(adopted=False))))["id"])
    fake = FakeGrok(scenes=[{"title": "Palco", "beats": [
        {"kind": "action", "action": "Dança contínua", "seconds": 13, "dialogue": None}]}])
    candidate = await op.propose(doc.id, ProposalRequest(
        expected_revision=doc.revision, count=10, duration_seconds=8, seed=4), fake)
    assert [b["action"] for b in candidate["blocks"]] == [
        f"Palco · do — parte {i}/10" for i in range(1, 11)]
    assert all(b["duration_seconds"] == 8.0 for b in candidate["blocks"])
    assert len([s for s in fake.schemas if s["schema_name"] == "h3_roteiro_card"]) == 10
    await service.shutdown()


@pytest.mark.asyncio
async def test_critic_replaces_draft_kinds_and_single_dialogue_reach_writers(tmp_path):
    service, op = setup(tmp_path)
    doc = op.get((await op.create(CreatePlan(**fields(adopted=False))))["id"])
    critic = [{"title": "Quarto", "beats": [
        {"kind": "action", "action": "Salta", "seconds": 16, "dialogue": "Olá, mundo!"},
        {"kind": "hold", "action": "Respira", "seconds": 16, "dialogue": None},
        {"kind": "transition", "action": "Vira de costas", "seconds": 16, "dialogue": None}]}]
    fake = FakeGrok(scenes=critic, dialogue="Olá, mundo!")
    candidate = await op.propose(doc.id, ProposalRequest(
        expected_revision=doc.revision, count=6, duration_seconds=8, seed=4), fake)
    assert [event["title"] for event in candidate["scenes"]] == ["Quarto"]
    spoken = [b["prompt"] for b in candidate["blocks"] if "Olá, mundo!" in b["prompt"]]
    assert len(spoken) == 1
    assert "fala em português do Brasil com sotaque do sul: 'Olá, mundo!'" in spoken[0]
    silent = [b["prompt"] for b in candidate["blocks"] if "Olá, mundo!" not in b["prompt"]]
    assert silent and all("Sem fala." in prompt for prompt in silent)
    await service.shutdown()


@pytest.mark.asyncio
async def test_long_plan_of_450_blocks_slices_and_bounds_parallel_writers(tmp_path):
    service, op = setup(tmp_path)
    doc = op.get((await op.create(CreatePlan(**fields(adopted=False))))["id"])
    scenes = [{"title": f"Cena {i}", "beats": [
        {"kind": "action", "action": f"Ação longa {i}", "seconds": 40, "dialogue": None},
        {"kind": "hold", "action": f"Pausa {i}", "seconds": 10, "dialogue": None},
        {"kind": "transition", "action": f"Transição {i}", "seconds": 10, "dialogue": None}]}
        for i in range(60)]
    fake = SegmentGrok(scenes=scenes)
    candidate = await op.propose(doc.id, ProposalRequest(
        expected_revision=doc.revision, count=450, duration_seconds=8, seed=4), fake)
    assert len(candidate["blocks"]) == 450 and MAX_BLOCKS == 1000
    assert 1 < fake.peak <= 4
    assert all(b["duration_seconds"] == 8 for b in candidate["blocks"])
    cards = [s for s in fake.schemas if s["schema_name"] == "h3_roteiro_card"]
    assert len(cards) == 450
    await service.shutdown()


@pytest.mark.asyncio
async def test_long_chain_view_is_linear_and_shallow(tmp_path, monkeypatch):
    import os

    from h3_backend.roteiro import Roteiro

    # Durability is not under test here; 300 fixture generations would otherwise be fsync-bound.
    monkeypatch.setattr(os, "fsync", lambda fd: None)
    service, op = setup(tmp_path)
    payload = fields(count=1)
    payload["blocks"] = blocks(300)
    doc = op.get((await op.create(CreatePlan(**payload)))["id"])
    real = Roteiro.observed
    # Building the fixture only: cheap fences while generating; the view below is real.
    monkeypatch.setattr(Roteiro, "observed", lambda self, intent: {"state": "accepted", "run": {}})
    parent = None
    for block in doc.blocks:
        run_id = str(uuid4())
        await op.generate(doc.id, block.id, run_id, Generate(
            expected_revision=doc.revision, prompt=block.prompt, seed=block.seed,
            duration_seconds=block.duration_seconds, parent_id=parent))
        await service.wait_run(run_id)
        await service.decide(run_id, True)
        parent = run_id
    monkeypatch.setattr(Roteiro, "observed", real)
    doc = op.get(doc.id)
    reads = {"get": 0}
    original_get = service.store.get

    def counted(run_id):
        reads["get"] += 1
        return original_get(run_id)

    monkeypatch.setattr(service.store, "get", counted)
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(400)  # Far below one frame per historical continuation.
    try:
        fresh = Roteiro(service)
        last = fresh.observed(doc.attempts[-1])
        view = fresh.view(doc)
    finally:
        sys.setrecursionlimit(limit)
    assert last["state"] == "accepted"
    assert len(view["attempts"]) == 300 and all(a["state"] == "accepted" for a in view["attempts"])
    assert reads["get"] < 300 * 12  # Linear: a bounded number of manifest reads per attempt.
    summary = fresh.summary()["items"][0]
    assert summary["states"]["accepted"] == 300
    await service.shutdown()


@pytest.mark.asyncio
async def test_batch_generates_middle_segment_ending_in_bridge_and_tail(tmp_path):
    service, op, doc = await chain(tmp_path, 2, video=False)
    a, b = doc.blocks
    p1, p2, p3 = (Block(**x) for x in blocks(3, prefix="NEW"))
    doc = op.get((await op.update(doc.id, update(doc, blocks=[a, p1, b, p2, p3])))["id"])
    run_a, run_b = (op.selected_attempt(doc, x.id).run_id for x in (a, b))
    enhancer = FakeEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    initial = await batch.start(doc.id, ident, consent(doc.revision))
    assert [x["id"] for x in initial["blocks"]] == [p1.id, p2.id, p3.id]
    assert initial["initial_parent_id"] == run_a and initial["targets"] == {p1.id: run_b}
    await asyncio.wait_for(batch.task, 300)
    result = batch.get(doc.id, ident)
    assert result["state"] == "ready_for_review", result["error"]
    final = op.get(doc.id)
    runs = {x.id: service.store.get(op.selected_attempt(final, x.id).run_id) for x in (p1, p2, p3)}
    assert runs[p1.id].input_info["operation"] == "bridge" and runs[p1.id].parent_id == run_a
    assert runs[p1.id].input_info["continuation"]["target_run_id"] == run_b
    assert op.selected_attempt(final, p1.id).origin == "bridge"
    assert runs[p2.id].parent_id == run_b and runs[p3.id].parent_id == runs[p2.id].id
    assert [runs[x.id].state for x in (p1, p2, p3)] == ["accepted", "accepted", "ready_for_review"]
    assert result["accepted_run_ids"] == [runs[p1.id].id, runs[p2.id].id]
    assert enhancer.calls[0].target_run_id == run_b
    assert enhancer.calls[0].continuation_parent_id == run_a
    assert "DESTINATION — FOLLOWING EXISTING ACCEPTED VIDEO" in enhancer.calls[0].prompt
    assert b.prompt in enhancer.calls[0].prompt
    assert not hasattr(enhancer.calls[1], "target_run_id")
    view = op.view(final)
    assert all(x["state"] in {"accepted", "ready_for_review"} for x in view["attempts"])
    # Tail must keep working after a bridged middle insertion (order is now editorial).
    await service.decide(runs[p3.id].id, True)
    assert op.tail_parent(op.get(doc.id)) == runs[p3.id].id
    await service.shutdown()


@pytest.mark.asyncio
async def test_batch_refuses_pending_block_after_unaccepted_block(tmp_path):
    service, op, doc = await chain(tmp_path, 1, planned=1, video=False)
    run_id = op.selected_attempt(doc, doc.blocks[0].id).run_id
    payload = fields(count=1)
    payload["blocks"] = blocks(2)
    other = op.get((await op.create(CreatePlan(**payload)))["id"])
    first = other.blocks[0]
    rejected = str(uuid4())
    await op.generate(other.id, first.id, rejected, Generate(
        expected_revision=other.revision, prompt=first.prompt, seed=first.seed,
        duration_seconds=first.duration_seconds, parent_id=None))
    await service.wait_run(rejected)
    await service.decide(rejected, False)
    batch = RoteiroBatch(service, FakeEnhancer())
    with pytest.raises(Conflict, match="needs an accepted version"):
        await batch.start(other.id, str(uuid4()), consent(other.revision))
    assert run_id and batch.lock_fd is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_batch_context_is_bounded_and_idea_is_background(tmp_path, monkeypatch):
    service, op = setup(tmp_path)
    payload = fields(count=1)
    payload["blocks"] = blocks(30)
    payload["idea"] = 'Ela diz "Olá, mundo!" no começo'
    doc = op.get((await op.create(CreatePlan(**payload)))["id"])
    batch = RoteiroBatch(service, FakeEnhancer())
    monkeypatch.setattr(batch.roteiro, "selected_attempt", lambda doc, key: SimpleNamespace(
        run_id=key, snapshot=SimpleNamespace(prompt=f"SENT-{key}")))
    monkeypatch.setattr(batch.roteiro, "observed", lambda attempt: {"state": "accepted"})
    text = batch.context(doc, 29)
    assert "(9 earlier blocks omitted.)" in text
    assert all(f"ACT-{i:03d}" in text for i in range(9, 30))
    assert all(f"ACT-{i:03d}" not in text for i in range(9))
    assert text.count("BEGIN HISTORICAL PROMPT") == 3
    assert all(f"SENT-{doc.blocks[i].id}" in text for i in (26, 27, 28))
    assert f"SENT-{doc.blocks[25].id}" not in text
    assert "BACKGROUND ONLY" in text
    assert "Do not speak any dialogue that appears in the overall idea" in text
    await service.shutdown()


@pytest.mark.asyncio
async def test_push_video_url_points_at_the_streaming_route(tmp_path, monkeypatch):
    from h3_backend.notifications import NotificationManager

    manager = NotificationManager(tmp_path)
    monkeypatch.setattr(manager, "load_config",
                        lambda: manager.__class__.load_config(manager).model_copy(update={"enabled": True}))
    sent = []

    async def broadcast(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(manager, "broadcast_event", broadcast)
    run_id = str(uuid4())
    manager.notify_run_terminal_sync(SimpleNamespace(id=run_id, state="ready_for_review"))
    await asyncio.sleep(0)
    assert sent[0]["data"]["video_url"] == f"/runs/{run_id}/video"
