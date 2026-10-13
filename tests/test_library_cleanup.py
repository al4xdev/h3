import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_service import make_service

from h3_backend.generation.dispatcher import Conflict
from h3_backend.generation.models import Run
from h3_backend.infrastructure.store import Store, timestamp
from h3_backend.library import Library


def block(service, *, state="ready_for_review", parent=None, references=None):
    run = Run(id=str(uuid4()), state=state, created_at=timestamp(), updated_at=timestamp(),
              seed=42, prompt="literal sent prompt", duration_seconds=8, workflow_hash="fixed",
              parent_id=parent, references=references or [], decision=None)
    service.store.create(run)
    directory = service.store.directory(run.id)
    (directory / "chunk.mp4").write_bytes(b"encoded-media")
    (directory / "proof.json").write_text('{"preserve":true}')
    return run


@pytest.mark.asyncio
async def test_media_moves_history_and_restart_tombstone_survive(tmp_path):
    service = make_service(tmp_path)
    run = block(service)
    result = await Library(service).remove(run.id)
    directory = service.store.directory(run.id)
    assert not (directory / "chunk.mp4").exists()
    assert (directory / "manifest.json").exists()
    assert (directory / "proof.json").exists()
    trash = Path(result["trash_path"])
    assert trash.stat().st_mode & 0o777 == 0o700
    assert (trash / "runs" / run.id / "chunk.mp4").read_bytes() == b"encoded-media"
    journal = json.loads((trash / "journal.json").read_text())
    assert journal["state"] == "completed" and journal["runs"][0]["decision"] is None
    restarted = Store(tmp_path)
    with pytest.raises(FileNotFoundError):
        restarted.get(run.id)
    assert restarted.list_runs() == ([], 0)
    assert restarted.restore() == []
    with pytest.raises(ValueError):
        restarted.create(run)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["queued", "running"])
async def test_active_block_is_preserved(tmp_path, state):
    service = make_service(tmp_path)
    run = block(service, state=state)
    with pytest.raises(Conflict):
        await Library(service).remove(run.id)
    assert (service.store.directory(run.id) / "chunk.mp4").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [False, True])
async def test_dependents_block_removal(tmp_path, identity):
    service = make_service(tmp_path)
    parent = block(service)
    block(service, parent=None if identity else parent.id, references=[{
        "source_root": "runs", "source": f".data/runs/{parent.id}/last_frame.png"
    }] if identity else [])
    with pytest.raises(Conflict):
        await Library(service).remove(parent.id)
    assert not service.store.removed(parent.id)


@pytest.mark.asyncio
async def test_move_failure_rolls_back(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    run = block(service)
    directory = service.store.directory(run.id)
    (directory / "last_frame.png").write_bytes(b"frame")
    from h3_backend import library
    original = library.Library.transfer
    calls = []

    def move(source, destination):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("fixture failure")
        return original(source, destination)

    monkeypatch.setattr(library.Library, "transfer", staticmethod(move))
    with pytest.raises(Conflict, match="evidence retained"):
        await Library(service).remove(run.id)
    assert (directory / "chunk.mp4").read_bytes() == b"encoded-media"
    assert (directory / "last_frame.png").read_bytes() == b"frame"
    assert not service.store.removed(run.id)


@pytest.mark.asyncio
async def test_symlink_never_removes_external_media(tmp_path):
    service = make_service(tmp_path)
    run = block(service)
    outside = tmp_path / "external.png"
    outside.write_bytes(b"shared")
    (service.store.directory(run.id) / "last_frame.png").symlink_to(outside)
    with pytest.raises(Conflict):
        await Library(service).remove(run.id)
    assert outside.read_bytes() == b"shared"
    assert (service.store.directory(run.id) / "chunk.mp4").exists()


@pytest.mark.asyncio
async def test_roteiro_removal_hides_document_preserves_proposals(tmp_path):
    from test_roteiro import fields, setup

    from h3_backend.roteiro import CreatePlan

    service, op = setup(tmp_path)
    created = await op.create(CreatePlan(**fields()))
    directory = tmp_path / ".data" / "roteiros" / created["id"]
    (directory / "proposal-evidence.json").write_text('{"raw_text":"retained"}')
    result = await Library(service).remove(created["id"], revision=1)
    assert result["removed"] and result["run_ids"] == []
    assert (directory / "plan.json").exists()
    assert (directory / "proposal-evidence.json").exists()
    assert op.list() == {"items": [], "total": 0}
    with pytest.raises(FileNotFoundError):
        op.get(created["id"])


@pytest.mark.asyncio
async def test_admitted_ledger_without_native_proof_is_not_deletion_permission(tmp_path):
    from test_roteiro import fields, setup
    from test_roteiro_admission import request

    from h3_backend.roteiro import CreatePlan

    service, op = setup(tmp_path)
    created = await op.create(CreatePlan(**fields()))
    doc = op.get(created["id"])
    intent = op.reserve(doc, doc.blocks[0].id, str(uuid4()), request(doc))
    op.finish(intent, "admitted")
    with pytest.raises(Conflict, match="Uncertain"):
        await Library(service).remove(doc.id, revision=op.get(doc.id).revision)
    assert not op.removed(doc.id)


@pytest.mark.asyncio
async def test_root_lock_fences_new_document_during_transfer(tmp_path, monkeypatch):
    import asyncio
    import threading

    from test_roteiro import fields, setup

    from h3_backend.roteiro import CreatePlan

    service, op = setup(tmp_path)
    run = block(service)
    entered, release = threading.Event(), threading.Event()
    original = Library.transfer

    def transfer(source, destination):
        entered.set()
        release.wait(5)
        return original(source, destination)

    monkeypatch.setattr(Library, "transfer", staticmethod(transfer))
    task = asyncio.create_task(Library(service).remove(run.id))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        with pytest.raises(Conflict, match="writer"):
            await op.create(CreatePlan(**fields()))
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_failed_copy_destination_is_retained_separately_and_source_restored(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    run = block(service)
    original = Library.transfer
    calls = []

    def transfer(source, destination):
        calls.append(source)
        if len(calls) == 1:
            destination.write_bytes(b"partial")
            raise OSError("cross-device copy failed")
        return original(source, destination)

    monkeypatch.setattr(Library, "transfer", staticmethod(transfer))
    with pytest.raises(Conflict, match="evidence retained"):
        await Library(service).remove(run.id)
    assert (service.store.directory(run.id) / "chunk.mp4").read_bytes() == b"encoded-media"
    assert not service.store.removed(run.id)


async def confirmed_roteiro(tmp_path):
    from test_roteiro import fields, setup
    from test_roteiro_admission import request

    from h3_backend.roteiro import CreatePlan

    service, op = setup(tmp_path)
    created = await op.create(CreatePlan(**fields(count=1)))
    doc = op.get(created["id"])
    ident = str(uuid4())
    await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    await service._task
    assert op.observed(op.get(doc.id).attempts[0])["state"] == "ready_for_review"
    return service, op, op.get(doc.id), ident


@pytest.mark.asyncio
async def test_confirmed_roteiro_and_own_completed_assembly_removed_restart_safe(tmp_path):
    from h3_backend.generation.assembly import (
        MECHANISM,
        AssemblyPipe,
        get_assembly,
        list_assemblies,
        restore_interrupted,
    )

    service, op, doc, ident = await confirmed_roteiro(tmp_path)
    assembly_id = str(uuid4())

    async def concatenate(sources, destination):
        destination.write_bytes(b"fixture-assembled-media")
        return {"assembly": MECHANISM}

    service.media.concatenate = concatenate
    assembled = await AssemblyPipe(service).have(assembly_id).from_end(ident).save_video().arun()
    assert assembled["state"] == "completed"
    run_dir = service.store.directory(ident)
    assembly_dir = tmp_path / ".data" / "assemblies" / assembly_id
    preserved = {path: path.read_bytes() for directory in (run_dir, assembly_dir)
                 for path in directory.iterdir() if path.suffix in {".json", ".md", ".jsonl"}}
    original_image = tmp_path / "assets" / "dance_reference.png"
    comfy_source = tmp_path / "comfy" / "output" / "safe" / "final.mp4"
    external = {path: path.read_bytes() for path in (original_image, comfy_source)}
    intent = op.get(doc.id).attempts[0].model_dump()
    result = await Library(service).remove(doc.id, revision=doc.revision)
    assert result["run_ids"] == [ident]
    assert not (run_dir / "chunk.mp4").exists()
    assert not (assembly_dir / "video.mp4").exists()
    assert all(path.read_bytes() == contents for path, contents in preserved.items())
    assert all(path.read_bytes() == contents for path, contents in external.items())
    persisted = json.loads((tmp_path / ".data" / "roteiros" / doc.id / "plan.json").read_text())
    assert persisted["attempts"][0] == intent
    trash = Path(result["trash_path"])
    assert (trash / "assemblies" / assembly_id / "video.mp4").read_bytes() == b"fixture-assembled-media"
    assert (trash / "runs" / ident / "chunk.mp4").read_bytes() == external[comfy_source]
    restarted = Store(tmp_path)
    assert restarted.restore() == [] and restarted.list_runs() == ([], 0)
    restore_interrupted(tmp_path)
    assert list_assemblies(tmp_path)["total"] == 0
    with pytest.raises(FileNotFoundError):
        get_assembly(tmp_path, assembly_id)
    with pytest.raises(ValueError, match="already exists"):
        restarted.create(Run.model_validate_json(preserved[run_dir / "manifest.json"]))
    await service.shutdown()


@pytest.mark.asyncio
async def test_shared_assembly_is_refused_without_moving_selected_child(tmp_path):
    import hashlib

    from h3_backend.generation.assembly import (
        AssemblyInput,
        AssemblyIntent,
        AssemblyMetadata,
        _write,
    )

    service = make_service(tmp_path)
    parent = block(service, state="accepted")
    child = block(service, parent=parent.id)
    assembly_id = str(uuid4())
    directory = tmp_path / ".data" / "assemblies" / assembly_id
    directory.mkdir(parents=True)
    intent = AssemblyIntent(id=assembly_id, end_run_id=child.id, created_at=timestamp(), mode="preview",
                            inputs=[AssemblyInput(
                                run_id=run.id, parent_id=run.parent_id,
                                path=f".data/runs/{run.id}/chunk.mp4", sha256="a" * 64, bytes=13,
                                state=run.state, frames=56, width=480, height=864, fps="24/1",
                                codec="h264", pixel_format="yuv420p", has_audio=False)
                                for run in (parent, child)])
    _write(directory / "request.json", intent.model_dump())
    meta = AssemblyMetadata(id=assembly_id, end_run_id=child.id, state="failed", mode="preview",
                            created_at=intent.created_at, updated_at=intent.created_at,
                            request_sha256=hashlib.sha256((directory / "request.json").read_bytes()).hexdigest())
    _write(directory / "metadata.json", meta.model_dump())
    (directory / "video.mp4").write_bytes(b"preserved-attempt")
    with pytest.raises(Conflict, match="shared assembly"):
        await Library(service).remove(child.id)
    assert service.store.get(child.id).state == "ready_for_review"
    assert (directory / "video.mp4").read_bytes() == b"preserved-attempt"


@pytest.mark.asyncio
async def test_dependent_roteiro_reference_blocks_owner_cleanup(tmp_path, monkeypatch):
    from test_roteiro import fields

    from h3_backend.roteiro import CreatePlan

    service, op, doc, ident = await confirmed_roteiro(tmp_path)
    image = service.store.directory(ident) / "last_frame.png"
    image.write_bytes((tmp_path / "assets" / "dance_reference.png").read_bytes())
    payload = fields(count=1)
    payload["reference"] = {"source_root": "runs", "path": f".data/runs/{ident}/last_frame.png"}
    async def fixture_reference_digest(reference):
        import hashlib

        return hashlib.sha256(image.read_bytes()).hexdigest()

    monkeypatch.setattr(op, "reference_digest", fixture_reference_digest)
    dependent = await op.create(CreatePlan(**payload))
    with pytest.raises(Conflict, match="identity"):
        await Library(service).remove(doc.id, revision=doc.revision)
    assert op.get(dependent["id"]).reference.path == payload["reference"]["path"]
    assert service.store.get(ident).state == "ready_for_review"
    await service.shutdown()


@pytest.mark.asyncio
async def test_delete_asgi_contracts_origin_body_revision_and_uuid_fences(tmp_path):
    import httpx
    from test_roteiro import fields, setup

    from h3_backend.api import create_app
    from h3_backend.roteiro import CreatePlan

    service, op = setup(tmp_path)
    run = block(service)
    created = await op.create(CreatePlan(**fields(count=1)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(service=service)),
                                 base_url="http://local") as http:
        run_url = f"/runs/{run.id}"
        doc_url = f"/roteiros/{created['id']}"
        denied = await http.delete(run_url, headers={"Origin": "https://external.invalid"})
        assert denied.status_code == 403 and not service.store.removed(run.id)
        nonempty = await http.request("DELETE", run_url, content=b"{}")
        assert nonempty.status_code == 400 and not service.store.removed(run.id)
        missing = await http.request("DELETE", doc_url, json={})
        assert missing.status_code == 422
        extra = await http.request("DELETE", doc_url, json={"expected_revision": 1, "force": True})
        assert extra.status_code == 422
        stale = await http.request("DELETE", doc_url, json={"expected_revision": 2})
        assert stale.status_code == 409 and op.get(created["id"]).revision == 1
        deleted = await http.delete(run_url, headers={"Origin": "http://local"})
        assert deleted.status_code == 200 and deleted.json()["run_ids"] == [run.id]
        assert (await http.get(run_url)).status_code == 404
        assert (await http.delete(run_url)).status_code == 404
        removed = await http.request("DELETE", doc_url, json={"expected_revision": 1})
        assert removed.status_code == 200 and removed.json()["removed"] is True
        assert (await http.get(doc_url)).status_code == 404
        assert (await http.get("/roteiros")).json()["total"] == 0
        assert (await http.get("/runs")).json()["total"] == 0
    assert not service.comfy.submitted and service._cpu_active is None
