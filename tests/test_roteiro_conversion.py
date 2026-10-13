"""Explicit CPU-only branch adoption preserves native files and admission history."""

import asyncio
import json
from uuid import uuid4

import pytest
from test_roteiro import setup, update

from h3_backend.generation.dispatcher import Conflict
from h3_backend.generation.models import ContinueRequest, RunRequest
from h3_backend.roteiro import Block, Generate
from h3_backend.roteiro_conversion import convert


async def branch(service):
    root = await service.create(RunRequest(seed=41, prompt="Literal root", duration_seconds=2.3))
    await service._task
    await service.decide(root.id, True)
    child = await service.continue_run(root.id, ContinueRequest(
        seed=42, prompt="Literal child", duration_seconds=2.3))
    await service._task
    return root.id, child.id


@pytest.mark.asyncio
async def test_conversion_exact_full_branch_and_review_then_continue(tmp_path):
    service, op = setup(tmp_path)
    root, child = await branch(service)
    original = {path: path.read_bytes() for ident in (root, child)
                for path in service.store.directory(ident).rglob("*") if path.is_file()}
    submitted = len(service.comfy.submitted)
    view = await convert(op, child, str(uuid4()))
    assert [a["run_id"] for a in view["attempts"]] == [root, child]
    assert [b["action"] for b in view["blocks"]] == ["Literal root", "Literal child"]
    assert [a["state"] for a in view["attempts"]] == ["accepted", "ready_for_review"]
    assert all(a["origin"] == "freestyle" for a in view["attempts"])
    assert all(path.read_bytes() == data for path, data in original.items())
    assert not (tmp_path / ".data" / "roteiros" / ".locks").exists()
    assert len(service.comfy.submitted) == submitted
    with pytest.raises(Conflict):
        await convert(op, child, str(uuid4()))
    await service.decide(child, True)
    doc = op.get(view["id"])
    new = Block(id=str(uuid4()), action="Next", prompt="Exact next", seed=44, duration_seconds=2.3)
    changed = await op.update(doc.id, update(doc, blocks=[*doc.blocks, new]))
    doc = op.get(doc.id)
    result = await op.generate(doc.id, new.id, str(uuid4()), Generate(
        expected_revision=changed["revision"], prompt=new.prompt, seed=new.seed,
        duration_seconds=new.duration_seconds, parent_id=child))
    assert result["admission"] == "admitted"
    await service._task
    await service.shutdown()


@pytest.mark.asyncio
async def test_conversion_rejected_is_preserved_and_busy_refused(tmp_path):
    service, op = setup(tmp_path)
    root, child = await branch(service)
    await service.decide(child, False)
    async with service.cpu_slot("existing-operation"):
        with pytest.raises(Conflict):
            await convert(op, child, str(uuid4()))
    view = await convert(op, child, str(uuid4()))
    assert view["attempts"][-1]["state"] == "rejected"
    assert service.store.get(child).decision["accepted"] is False
    assert view["attempts"][-1]["snapshot"]["parent_id"] == root
    await service.shutdown()


@pytest.mark.asyncio
async def test_explicit_known_conversion_uuid_recovery_without_replay(tmp_path):
    service, op = setup(tmp_path)
    _, child = await branch(service)
    ident = str(uuid4())
    result = await convert(op, child, ident)
    assert result["id"] == ident
    assert op.view(op.get(ident)) == result
    with pytest.raises(Conflict):
        await convert(op, child, ident)
    await service.shutdown()


@pytest.mark.asyncio
async def test_interrupted_source_and_missing_proof_are_not_defaulted(tmp_path):
    service, op = setup(tmp_path)
    root = await service.create(RunRequest(seed=41, prompt="Literal root", duration_seconds=2.3))
    await service._task
    await service.decide(root.id, True)
    service.comfy.gate = asyncio.Event()
    run = await service.continue_run(root.id, ContinueRequest(
        seed=42, prompt="Literal child", duration_seconds=2.3))
    child = run.id
    await asyncio.sleep(0.02)
    service._task.cancel()
    await asyncio.gather(service._task, return_exceptions=True)
    result = await convert(op, child, str(uuid4()))
    assert result["attempts"][-1]["state"] == "interrupted"
    assert result["attempts"][-1]["snapshot"]["prompt"] == "Literal child"
    manifest = service.store.directory(child) / "manifest.json"
    original = manifest.read_bytes()
    corrupted = json.loads(original)
    corrupted["prompt"] = "Changed immutable input"
    manifest.write_text(json.dumps(corrupted))
    assert op.observed(op.get(result["id"]).attempts[-1])["state"] == "uncertain"
    manifest.write_bytes(original)
    assert op.observed(op.get(result["id"]).attempts[-1])["state"] == "interrupted"
    await service.shutdown()


@pytest.mark.asyncio
async def test_missing_native_request_refuses_conversion_without_claiming_runs(tmp_path):
    service, op = setup(tmp_path)
    _, child = await branch(service)
    request = service.store.directory(child) / "request.json"
    request.rename(request.with_suffix(".bak"))
    ident = str(uuid4())
    with pytest.raises(FileNotFoundError):
        await convert(op, child, ident)
    assert not (tmp_path / ".data" / "roteiros" / ident).exists()
    await service.shutdown()


@pytest.mark.asyncio
async def test_imported_publication_metadata_and_media_replacement_are_uncertain(tmp_path):
    service, op = setup(tmp_path)
    _, child = await branch(service)
    result = await convert(op, child, str(uuid4()))
    intent = op.get(result["id"]).attempts[-1]
    assert intent.source.media.size > 0
    assert len(intent.source.media.sha256) == 64
    manifest = service.store.directory(child) / "manifest.json"
    original = manifest.read_bytes()
    corrupted = json.loads(original)
    corrupted["output"]["conversion_tamper"] = True
    manifest.write_text(json.dumps(corrupted))
    assert op.observed(intent)["state"] == "uncertain"
    manifest.write_bytes(original)
    assert op.observed(intent)["state"] == "ready_for_review"
    await service.decide(child, True)
    assert op.observed(intent)["state"] == "accepted"
    video = service.video_path(child)
    unchanged = video.read_bytes()
    replacement = video.with_suffix(".replacement")
    replacement.write_bytes(unchanged)
    replacement.replace(video)
    assert op.observed(intent)["state"] == "uncertain"
    assert service.store.get(child).state == "accepted"
    await service.shutdown()


@pytest.mark.asyncio
async def test_media_hash_snapshot_and_same_inode_mutation_are_guarded(tmp_path):
    import hashlib

    service, op = setup(tmp_path)
    _, child = await branch(service)
    video = service.video_path(child)
    original = video.read_bytes()
    view = await convert(op, child, str(uuid4()))
    intent = op.get(view["id"]).attempts[-1]
    assert intent.source.media.sha256 == hashlib.sha256(original).hexdigest()
    assert intent.source.media.size == len(original)
    assert video.read_bytes() == original
    with video.open("r+b") as stream:
        stream.write(b"changed!")
    assert op.observed(intent)["state"] == "uncertain"
    await service.shutdown()
