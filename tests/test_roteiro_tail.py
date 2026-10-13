"""Tail proposals and adoption use temporary CPU media and fake providers."""

import asyncio
import json
from uuid import uuid4

import pytest
from test_grok_continuation import command
from test_roteiro import FakeGrok, fields, setup, update
from test_roteiro_admission import request

from h3_backend.generation.dispatcher import Conflict
from h3_backend.roteiro import AdoptTail, Block, CreatePlan, TailRequest


async def accepted_root(tmp_path):
    service, op = setup(tmp_path)
    output = tmp_path / "comfy/output/safe/final.mp4"
    command("ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=32x32:rate=4:duration=1", "-c:v", "libx264", "-threads", "1",
            "-pix_fmt", "yuv420p", str(output))
    created = await op.create(CreatePlan(**fields(count=1)))
    doc = op.get(created["id"])
    parent_id = str(uuid4())
    await op.generate(doc.id, doc.blocks[0].id, parent_id, request(doc))
    await service._task
    await service.decide(parent_id, True)
    return service, op, op.get(doc.id), parent_id


def payload(doc, **changes):
    return TailRequest(expected_revision=doc.revision, idea="Then turn and wave", count=2,
                       seed=42, **changes)


def adoption(doc, candidate):
    return AdoptTail(expected_revision=doc.revision,
                     blocks=[Block(**b) for b in candidate["blocks"]])


@pytest.mark.asyncio
async def test_plan_actual_parent_and_explicit_atomic_adoption_preserve_prefix(tmp_path):
    service, op, doc, parent_id = await accepted_root(tmp_path)
    fake = FakeGrok()
    ident = str(uuid4())
    before_calls = len(service.comfy.submitted)
    candidate = await op.propose_tail(doc.id, ident, payload(doc), fake)
    assert candidate["state"] == "proposed" and not candidate["stale"]
    assert candidate["parent_id"] == parent_id
    assert candidate["prefix_block_ids"] == [doc.blocks[0].id]
    assert candidate["name"] == doc.name
    assert candidate["request"]["idea"] != candidate["source"]["idea"] == doc.idea
    assert fake.calls[0].continuation_parent_id == parent_id
    assert fake.calls[0].reference == doc.reference
    assert "Future frames are unknown" in fake.calls[0].prompt
    assert fake.schemas[0]["schema_name"] == "h3_roteiro"
    assert op.get(doc.id) == doc
    assert op.get_tail(doc.id, ident)["raw_text"] == fake.text
    result = await op.adopt_tail(doc.id, ident, adoption(doc, candidate))
    assert result["revision"] == doc.revision + 1
    updated = op.get(doc.id)
    assert updated.blocks[:1] == doc.blocks and updated.attempts == doc.attempts
    assert updated.idea == doc.idea and updated.name == doc.name
    assert op.get_tail(doc.id, ident)["state"] == "adopted"
    assert len(service.comfy.submitted) == before_calls
    with pytest.raises(Conflict):
        await op.propose_tail(doc.id, ident, payload(updated), fake)
    assert len(fake.calls) == 1
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "video", "reference", "decision", "foreign_id"])
async def test_adoption_rechecks_frozen_context(tmp_path, change):
    service, op, doc, parent_id = await accepted_root(tmp_path)
    ident = str(uuid4())
    candidate = await op.propose_tail(doc.id, ident, payload(doc), FakeGrok())
    chosen = adoption(doc, candidate)
    if change == "revision":
        await op.update(doc.id, update(doc, name="Edited concurrently"))
    elif change == "video":
        (service.store.directory(parent_id) / "chunk.mp4").write_bytes(b"changed video")
    elif change == "reference":
        (tmp_path / "assets/dance_reference.png").write_bytes(b"changed image")
    elif change == "decision":
        marker = service.store.directory(parent_id) / "manifest.json"
        data = json.loads(marker.read_text())
        data["decision"] = {"accepted": False}
        marker.write_text(json.dumps(data))
    else:
        chosen.blocks[0] = chosen.blocks[0].model_copy(update={"id": str(uuid4())})
    with pytest.raises((Conflict, ValueError, OSError)):
        await op.adopt_tail(doc.id, ident, chosen)
    assert op.get(doc.id).blocks == doc.blocks
    assert op.get(doc.id).attempts == doc.attempts
    await service.shutdown()


@pytest.mark.asyncio
async def test_pending_unattempted_prefix_blocks_rejected_before_provider(tmp_path):
    service, op = setup(tmp_path)
    doc = op.get((await op.create(CreatePlan(**fields(count=2))))["id"])
    fake = FakeGrok()
    with pytest.raises(Conflict):
        await op.propose_tail(doc.id, str(uuid4()), payload(doc), fake)
    assert not fake.calls and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_invalid_json_is_durable_and_never_adopted(tmp_path):
    service, op, doc, _ = await accepted_root(tmp_path)
    ident = str(uuid4())
    fake = FakeGrok(text='{"name":"bad","blocks":[]}')
    result = await op.propose_tail(doc.id, ident, payload(doc), fake)
    assert result["state"] == "invalid" and result["raw_text"] == fake.text
    assert op.get_tail(doc.id, ident)["state"] == "invalid"
    assert op.get(doc.id) == doc
    with pytest.raises(Conflict):
        await op.propose_tail(doc.id, ident, payload(doc), fake)
    assert len(fake.calls) == 1
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_provider_failure_or_cancel_fences_same_and_new_ids_without_replay(tmp_path, cancel):
    service, op, doc, _ = await accepted_root(tmp_path)
    ident = str(uuid4())
    gate = asyncio.Event()
    fake = FakeGrok(gate=gate)
    if cancel:
        task = asyncio.create_task(op.propose_tail(doc.id, ident, payload(doc), fake))
        await asyncio.wait_for(fake.entered.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        async def failure(request, **kwargs):
            fake.calls.append(request)
            raise OSError("lost provider response")
        fake.complete = failure
        with pytest.raises(OSError):
            await op.propose_tail(doc.id, ident, payload(doc), fake)
    assert op.get_tail(doc.id, ident)["state"] == "uncertain"
    for next_id in (ident, str(uuid4())):
        with pytest.raises(Conflict):
            await op.propose_tail(doc.id, next_id, payload(doc), fake)
    assert len(fake.calls) == 1 and op.get(doc.id) == doc
    await service.shutdown()


@pytest.mark.asyncio
async def test_partial_adoption_get_proves_committed_plan_no_replay(tmp_path, monkeypatch):
    import h3_backend.roteiro as module

    service, op, doc, _ = await accepted_root(tmp_path)
    ident = str(uuid4())
    fake = FakeGrok()
    candidate = await op.propose_tail(doc.id, ident, payload(doc), fake)
    original = module.write_file

    def crash(directory, name, value, **kwargs):
        if name == f"tail-{ident}.json" and value.get("state") == "adopted":
            raise OSError("lost after plan commit")
        return original(directory, name, value, **kwargs)

    monkeypatch.setattr(module, "write_file", crash)
    with pytest.raises(OSError):
        await op.adopt_tail(doc.id, ident, adoption(doc, candidate))
    monkeypatch.setattr(module, "write_file", original)
    assert op.get_tail(doc.id, ident)["state"] == "adopted"
    assert op.get(doc.id).revision == doc.revision + 1
    assert len(op.get(doc.id).blocks) == 3 and len(fake.calls) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_known_provider_refusal_is_terminal_not_uncertain(tmp_path):
    from h3_backend.infrastructure.grok_oauth import OAuthError

    service, op, doc, _ = await accepted_root(tmp_path)
    ident = str(uuid4())

    class Refused:
        async def complete(self, request, **kwargs):
            raise OAuthError("rate_limited", "Explicit quota refusal", 429)

    with pytest.raises(OAuthError):
        await op.propose_tail(doc.id, ident, payload(doc), Refused())
    assert op.get_tail(doc.id, ident)["state"] == "invalid"
    fake = FakeGrok()
    result = await op.propose_tail(doc.id, str(uuid4()), payload(doc), fake)
    assert result["state"] == "proposed" and len(fake.calls) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_late_proposal_is_stale_and_count_budget_precedes_provider(tmp_path):
    service, op, doc, _ = await accepted_root(tmp_path)
    fake = FakeGrok()
    with pytest.raises(Conflict, match="50-block"):
        await op.propose_tail(doc.id, str(uuid4()), TailRequest(
            expected_revision=doc.revision, idea="More", count=50, seed=42), fake)
    assert not fake.calls
    gate = asyncio.Event()
    fake = FakeGrok(gate=gate)
    ident = str(uuid4())
    task = asyncio.create_task(op.propose_tail(doc.id, ident, payload(doc), fake))
    await asyncio.wait_for(fake.entered.wait(), 10)
    await op.update(doc.id, update(doc, name="Concurrent name"))
    gate.set()
    candidate = await task
    assert candidate["stale"] and op.get_tail(doc.id, ident)["stale"]
    assert len(op.get(doc.id).blocks) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_get_never_finishes_unpublished_adoption(tmp_path, monkeypatch):
    import h3_backend.roteiro as module

    service, op, doc, _ = await accepted_root(tmp_path)
    ident = str(uuid4())
    candidate = await op.propose_tail(doc.id, ident, payload(doc), FakeGrok())
    original = module.write_file

    def crash(directory, name, value, **kwargs):
        if name == "plan.json":
            raise OSError("failed before plan publication")
        return original(directory, name, value, **kwargs)

    monkeypatch.setattr(module, "write_file", crash)
    with pytest.raises(OSError):
        await op.adopt_tail(doc.id, ident, adoption(doc, candidate))
    monkeypatch.setattr(module, "write_file", original)
    assert op.get_tail(doc.id, ident)["state"] == "proposed"
    assert op.get(doc.id) == doc
    await op.adopt_tail(doc.id, ident, adoption(doc, candidate))
    assert len(op.get(doc.id).blocks) == 3
    await service.shutdown()
