import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_bridge import anchors, bridge_service, request
from test_library_cleanup import block
from test_roteiro_edit import EditGrok, edit_request, prepared
from test_service import make_service

from h3_backend.generation.bridge import BridgePipe
from h3_backend.generation.dispatcher import Conflict
from h3_backend.library import Library
from h3_backend.roteiro_edit import EditGenerate, Revision, RoteiroEdit


@pytest.mark.parametrize("anchor", ["parent", "target"])
async def test_native_bridge_protects_both_external_anchors(tmp_path, anchor):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    bridge = await BridgePipe(service).have(request(target)).from_parent(parent.id).admit()
    await service._task
    selected = parent if anchor == "parent" else target
    try:
        with pytest.raises(Conflict, match="depends"):
            await Library(service).remove(selected.id)
        assert service.video_path(selected.id).is_file()
        assert service.store.get(bridge.id).state == "ready_for_review"
        assert not service.store.removed(selected.id)
    finally:
        await service.shutdown()


async def test_own_generated_bridge_artifacts_do_not_block_unrelated_removal(tmp_path):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    bridge = await BridgePipe(service).have(request(target)).from_parent(parent.id).admit()
    await service._task
    unrelated = block(service)
    try:
        result = await Library(service).remove(unrelated.id)
        assert result["run_ids"] == [unrelated.id]
        assert service.store.get(bridge.id).state == "ready_for_review"
        for ident in (parent.id, target.id, bridge.id):
            assert service.video_path(ident).is_file()
        assert (service.store.directory(bridge.id) / "target_frame.png").is_file()
        assert (Path(result["trash_path"]) / "runs" / unrelated.id / "chunk.mp4").is_file()
    finally:
        await service.shutdown()


@pytest.mark.parametrize("state", ["improving", "proposed", "uncertain"])
async def test_unapplied_proposal_protects_owner_and_anchors(tmp_path, state):
    service, roteiro, doc = await prepared(tmp_path)
    edits = RoteiroEdit(service)
    edit_id = str(uuid4())
    try:
        proposal = await edits.propose(doc.id, edit_id, edit_request(doc), EditGrok())
        proposal.pop("run")
        proposal["state"] = state
        edits.save(proposal)
        for identifier, options in [(doc.id, {"revision": doc.revision}),
                                    (proposal["previous_run_id"], {}),
                                    (proposal["next_run_id"], {})]:
            with pytest.raises(Conflict, match="unapplied or uncertain edit"):
                await Library(service).remove(identifier, **options)
        assert not roteiro.removed(doc.id)
        assert edits.read(doc.id, edit_id)["state"] == state
        assert len(service.comfy.submitted) == 3
    finally:
        await service.shutdown()


@pytest.mark.parametrize("decision", [None, True, False])
async def test_generated_unapplied_edit_cannot_be_orphaned(tmp_path, decision):
    service, roteiro, doc = await prepared(tmp_path)
    edits = RoteiroEdit(service)
    edit_id = str(uuid4())
    try:
        await edits.propose(doc.id, edit_id, edit_request(doc), EditGrok())
        await edits.generate(doc.id, edit_id, EditGenerate(prompt="Literal improved bridge"))
        await service._task
        if decision is not None:
            await service.decide(edit_id, decision)
        preserved = (service.store.directory(edit_id) / "manifest.json").read_bytes()
        for identifier, options in [(doc.id, {"revision": doc.revision}), (edit_id, {})]:
            with pytest.raises(Conflict, match="unapplied or uncertain edit"):
                await Library(service).remove(identifier, **options)
        assert not roteiro.removed(doc.id)
        assert (service.store.directory(edit_id) / "manifest.json").read_bytes() == preserved
        assert service.video_path(edit_id).is_file()
        assert len(service.comfy.submitted) == 4
    finally:
        await service.shutdown()


async def test_applied_edit_and_all_own_versions_move_recoverably_with_owner(tmp_path):
    service, roteiro, doc = await prepared(tmp_path)
    edits = RoteiroEdit(service)
    edit_id = str(uuid4())
    try:
        await edits.propose(doc.id, edit_id, edit_request(doc), EditGrok())
        await edits.generate(doc.id, edit_id, EditGenerate(prompt="Literal improved bridge"))
        await service._task
        await service.decide(edit_id, True)
        await edits.apply(doc.id, edit_id, Revision(expected_revision=doc.revision))
        current = roteiro.get(doc.id)
        record_path = tmp_path / ".data" / "roteiros" / doc.id / f"edit-{edit_id}.json"
        record = record_path.read_bytes()
        selected = {a.run_id for a in current.attempts}
        before = {ident: (service.store.directory(ident) / "manifest.json").read_bytes()
                  for ident in selected}
        result = await Library(service).remove(doc.id, revision=current.revision)
        assert set(result["run_ids"]) == selected
        assert record_path.read_bytes() == record
        assert roteiro.removed(doc.id)
        trash = Path(result["trash_path"])
        for ident in selected:
            assert (trash / "runs" / ident / "chunk.mp4").is_file()
            assert (service.store.directory(ident) / "manifest.json").read_bytes() == before[ident]
        for name in ("target_frame.png", "reference_tail.mp4", "bridge_parent.mp4", "bridge_target.mp4"):
            assert (trash / "runs" / edit_id / name).is_file()
    finally:
        await service.shutdown()


async def test_confirmed_failed_admission_without_run_allows_owner_removal(tmp_path):
    service, roteiro, doc = await prepared(tmp_path)
    edits = RoteiroEdit(service)
    edit_id = str(uuid4())
    try:
        proposal = await edits.propose(doc.id, edit_id, edit_request(doc), EditGrok())
        proposal.pop("run")
        proposal.update(state="failed", run_id=edit_id, error="Explicit refusal before admission")
        edits.save(proposal)
        assert not service.store.directory(edit_id).exists()
        result = await Library(service).remove(doc.id, revision=doc.revision)
        assert set(result["run_ids"]) == {a.run_id for a in doc.attempts}
        assert roteiro.removed(doc.id)
        assert edits.read(doc.id, edit_id)["state"] == "failed"
    finally:
        await service.shutdown()


async def test_invalid_edit_metadata_blocks_removal_without_touching_media(tmp_path):
    service, roteiro, doc = await prepared(tmp_path)
    edit_id = str(uuid4())
    path = tmp_path / ".data" / "roteiros" / doc.id / f"edit-{edit_id}.json"
    path.write_text(json.dumps({"state": "failed", "run_id": None}))
    try:
        with pytest.raises(Conflict, match="dependencies cannot be verified"):
            await Library(service).remove(doc.id, revision=doc.revision)
        assert not roteiro.removed(doc.id)
        assert all(service.video_path(a.run_id).is_file() for a in doc.attempts)
    finally:
        await service.shutdown()


async def test_unknown_bridge_target_dependency_blocks_removal(tmp_path):
    service = make_service(tmp_path)
    unrelated = block(service)
    malformed = block(service)
    path = service.store.directory(malformed.id) / "manifest.json"
    data = json.loads(path.read_text())
    data["input_info"] = {"operation": "bridge", "bridge_anchors": {"target": {}}}
    path.write_text(json.dumps(data))
    with pytest.raises(Conflict, match="Bridge dependencies cannot be verified"):
        await Library(service).remove(unrelated.id)
    assert not service.store.removed(unrelated.id)


async def test_explicitly_discarded_proposal_allows_recoverable_owner_removal(tmp_path):
    service, roteiro, doc = await prepared(tmp_path)
    edits, edit_id = RoteiroEdit(service), str(uuid4())
    try:
        await edits.propose(doc.id, edit_id, edit_request(doc), EditGrok())
        assert edits.discard(doc.id, edit_id)["state"] == "discarded"
        result = await Library(service).remove(doc.id, revision=doc.revision)
        assert set(result["run_ids"]) == {a.run_id for a in doc.attempts}
        assert roteiro.removed(doc.id)
        assert edits.read(doc.id, edit_id)["state"] == "discarded"
    finally:
        await service.shutdown()


@pytest.mark.parametrize("decision", [True, False])
async def test_discarded_terminal_edit_joins_confirmed_owner_cleanup(tmp_path, decision):
    service, roteiro, doc = await prepared(tmp_path)
    edits, edit_id = RoteiroEdit(service), str(uuid4())
    try:
        await edits.propose(doc.id, edit_id, edit_request(doc), EditGrok())
        await edits.generate(doc.id, edit_id, EditGenerate(prompt="Literal improved bridge"))
        await service._task
        await service.decide(edit_id, decision)
        assert edits.discard(doc.id, edit_id)["state"] == "discarded"
        result = await Library(service).remove(doc.id, revision=doc.revision)
        assert set(result["run_ids"]) == {edit_id, *(a.run_id for a in doc.attempts)}
        assert roteiro.removed(doc.id)
        assert (Path(result["trash_path"]) / "runs" / edit_id / "target_frame.png").is_file()
        assert edits.read(doc.id, edit_id)["state"] == "discarded"
    finally:
        await service.shutdown()


async def test_discarded_terminal_run_can_be_removed_before_owner(tmp_path):
    service, roteiro, doc = await prepared(tmp_path)
    edits, edit_id = RoteiroEdit(service), str(uuid4())
    try:
        await edits.propose(doc.id, edit_id, edit_request(doc), EditGrok())
        await edits.generate(doc.id, edit_id, EditGenerate(prompt="Literal improved bridge"))
        await service._task
        await service.decide(edit_id, False)
        edits.discard(doc.id, edit_id)
        first = await Library(service).remove(edit_id)
        assert first["run_ids"] == [edit_id]
        result = await Library(service).remove(doc.id, revision=doc.revision)
        assert set(result["run_ids"]) == {a.run_id for a in doc.attempts}
        assert roteiro.removed(doc.id)
    finally:
        await service.shutdown()
