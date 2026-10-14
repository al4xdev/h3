import asyncio
from uuid import uuid4

import httpx
import pytest
from test_bridge import BridgeBuilder
from test_roteiro import fields, setup
from test_roteiro_batch import FakeEnhancer, consent

from h3_backend.api import create_app
from h3_backend.generation.dispatcher import Conflict
from h3_backend.roteiro import CreatePlan
from h3_backend.roteiro_batch import RoteiroBatch
from h3_backend.roteiro_edit import EditGenerate, EditRequest, Revision, RoteiroEdit


async def prepared(tmp_path):
    service, roteiro = setup(tmp_path)
    service.builder = BridgeBuilder()

    async def first_frame(source, destination):
        destination.write_bytes(b"first-frame")
        return {"path": str(destination), "source_frame_index": 0, "format": "PNG"}

    service.media.prepare_first_frame = first_frame
    doc = await roteiro.create(CreatePlan(**fields(count=3)))
    batch = RoteiroBatch(service, FakeEnhancer())
    await batch.start(doc["id"], str(uuid4()), consent())
    await batch.task
    assert batch.value["state"] == "ready_for_review", batch.value["error"]
    await service.decide(batch.value["current_run_id"], True)
    return service, roteiro, roteiro.get(doc["id"])


class EditGrok:
    def __init__(self, error=False):
        self.calls = []
        self.error = error

    async def complete(self, request):
        self.calls.append(request)
        if self.error:
            raise OSError("Provider result unknown")
        return {"text": "Move naturally from the initial pose toward the destination pose."}


def edit_request(doc, mode="replace", index=1):
    return EditRequest(expected_revision=doc.revision, mode=mode, block_id=doc.blocks[index].id,
                       idea="Add a small turn", duration_seconds=2.3, seed=42)


@pytest.mark.parametrize("mode", ["replace", "insert_before", "insert_after"])
async def test_edit_lifecycle_preserves_originals_and_selects_new_version(tmp_path, mode):
    service, roteiro, original = await prepared(tmp_path)
    op, grok = RoteiroEdit(service), EditGrok()
    edit_id = str(uuid4())
    old_ids = [a.run_id for a in original.attempts]
    frozen = {ident: (service.store.directory(ident) / "manifest.json").read_bytes() for ident in old_ids}
    try:
        proposal = await op.propose(original.id, edit_id, edit_request(original, mode), grok)
        before = mode != "insert_after"
        previous = original.attempts[0 if before else 1]
        following = original.attempts[1 if mode == "insert_before" else 2]
        assert proposal["previous_run_id"] == previous.run_id
        assert proposal["next_run_id"] == following.run_id
        assert grok.calls[0].continuation_parent_id == previous.run_id
        assert grok.calls[0].target_run_id == following.run_id
        assert previous.snapshot.prompt in grok.calls[0].prompt
        assert following.snapshot.prompt in grok.calls[0].prompt
        assert "HISTORICAL PROMPT ACTUALLY SUBMITTED" in grok.calls[0].prompt
        assert roteiro.get(original.id) == original
        with pytest.raises(Conflict, match="already exists"):
            await op.propose(original.id, edit_id, edit_request(original, mode), grok)
        assert len(grok.calls) == 1
        await op.generate(original.id, edit_id, EditGenerate(prompt=proposal["prompt"] + " Keep identity."))
        await service._task
        run = service.store.get(edit_id)
        assert run.state == "ready_for_review", run.error
        assert len(service.comfy.submitted) == 4
        with pytest.raises(Conflict, match="consulte"):
            await op.generate(original.id, edit_id, EditGenerate(prompt=proposal["prompt"]))
        with pytest.raises(Conflict, match="Aceite"):
            await op.apply(original.id, edit_id, Revision(expected_revision=original.revision))
        await service.decide(edit_id, True)
        result = await op.apply(original.id, edit_id, Revision(expected_revision=original.revision))
        assert result["revision"] == original.revision + 1
        assert result["selected_runs"][proposal["new_block_id"]] == edit_id
        assert all(a["state"] == "accepted" for a in result["attempts"])
        assert len(result["blocks"]) == (3 if mode == "replace" else 4)
        expected_order = old_ids.copy()
        if mode == "replace":
            expected_order[1] = edit_id
        else:
            expected_order.insert(1 if mode == "insert_before" else 2, edit_id)
        current = roteiro.get(original.id)
        assert roteiro.selected_run_ids(current) == expected_order
        assert roteiro.tail_parent(current) == old_ids[-1]
        assert op.view(original.id, edit_id)["state"] == "applied"
        assert await op.apply(original.id, edit_id, Revision(expected_revision=original.revision)) == result
        for ident, data in frozen.items():
            assert (service.store.directory(ident) / "manifest.json").read_bytes() == data
        if mode == "replace":
            restored = op.select(original.id, original.blocks[1].id, old_ids[1],
                                 Revision(expected_revision=current.revision))
            assert restored["selected_runs"][original.blocks[1].id] == old_ids[1]
            assert restored["blocks"][1]["prompt"] == original.attempts[1].snapshot.prompt
            assert restored["blocks"][1]["seed"] == original.attempts[1].snapshot.seed
            assert restored["blocks"][1]["duration_seconds"] == original.attempts[1].snapshot.duration_seconds
            assert roteiro.selected_run_ids(roteiro.get(original.id)) == old_ids
            assert len(restored["attempts"]) == 4
        assert len(service.comfy.submitted) == 4
    finally:
        await service.shutdown()


async def test_uncertain_editor_stays_durable_and_never_falls_back(tmp_path):
    service, roteiro, doc = await prepared(tmp_path)
    op, grok = RoteiroEdit(service), EditGrok(error=True)
    ident = str(uuid4())
    try:
        with pytest.raises(OSError):
            await op.propose(doc.id, ident, edit_request(doc), grok)
        assert op.view(doc.id, ident)["state"] == "uncertain"
        with pytest.raises(Conflict, match="edição anterior"):
            await op.propose(doc.id, str(uuid4()), edit_request(doc), grok)
        with pytest.raises(Conflict):
            await op.generate(doc.id, ident, EditGenerate(prompt="Raw fallback"))
        assert len(grok.calls) == 1 and len(service.comfy.submitted) == 3
        assert roteiro.get(doc.id) == doc
    finally:
        await service.shutdown()


async def test_stale_proposal_and_boundaries_block_before_generation(tmp_path):
    service, _, doc = await prepared(tmp_path)
    op, grok = RoteiroEdit(service), EditGrok()
    try:
        for mode, index in [("replace", 0), ("insert_before", 0), ("insert_after", 2)]:
            with pytest.raises(Conflict):
                await op.propose(doc.id, str(uuid4()), edit_request(doc, mode, index), grok)
        assert not grok.calls
        ident = str(uuid4())
        await op.propose(doc.id, ident, edit_request(doc), grok)
        op.select(doc.id, doc.blocks[0].id, doc.attempts[0].run_id, Revision(expected_revision=doc.revision))
        with pytest.raises(Conflict, match="revision"):
            await op.generate(doc.id, ident, EditGenerate(prompt="Chosen proposal"))
        assert len(service.comfy.submitted) == 3
        assert op.view(doc.id, ident)["state"] == "proposed"
    finally:
        await service.shutdown()


async def test_edit_http_contract_and_same_id_reads_are_inert(tmp_path):
    service, _, doc = await prepared(tmp_path)
    app = create_app(service=service)
    app.state.grok = EditGrok()
    ident = str(uuid4())
    path = f"/roteiros/{doc.id}/edits/{ident}"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            config = await client.get("/roteiro-edits/editor")
            assert config.status_code == 200 and "historical" in config.json()["system_prompt"].lower()
            assert (await client.put("/roteiro-edits/editor", json={"system_prompt": "Custom bridge editor"})).status_code == 200
            assert (await client.post(path, json=edit_request(doc).model_dump(), headers={"Origin": "http://other"})).status_code == 403
            response = await client.post(path, json=edit_request(doc).model_dump())
            assert response.status_code == 200, response.text
            assert app.state.grok.calls[0].system_prompt == "Custom bridge editor"
            assert (await client.get(path)).json()["state"] == "proposed"
            assert len((await client.get(f"/roteiros/{doc.id}/edits")).json()["items"]) == 1
            assert len(service.comfy.submitted) == 3
            response = await client.post(path + "/generate", json={"prompt": "Improved bridge prompt"})
            assert response.status_code == 200, response.text
            await service._task
            assert (await client.get(path)).json()["run"]["state"] == "ready_for_review"
            assert (await client.post(path + "/generate", json={"prompt": "Replay"})).status_code == 409
            await service.decide(ident, True)
            response = await client.post(path + "/apply", json={"expected_revision": doc.revision})
            assert response.status_code == 200, response.text
            assert response.json()["selected_runs"][doc.blocks[1].id] == ident
            assert (await client.get(path)).json()["state"] == "applied"
            assert len(app.state.grok.calls) == 1 and len(service.comfy.submitted) == 4
    finally:
        await service.shutdown()


async def test_concurrent_generate_reserves_once(tmp_path):
    service, _, doc = await prepared(tmp_path)
    op, grok, ident = RoteiroEdit(service), EditGrok(), str(uuid4())
    try:
        await op.propose(doc.id, ident, edit_request(doc), grok)
        values = await asyncio.gather(*[op.generate(doc.id, ident, EditGenerate(prompt="Bridge"))
                                        for _ in range(2)], return_exceptions=True)
        assert sum(isinstance(value, Conflict) for value in values) == 1
        await service._task
        assert len(service.comfy.submitted) == 4
    finally:
        await service.shutdown()


async def test_sibling_proposal_cannot_generate_until_prior_edit_resolved(tmp_path):
    service, _, doc = await prepared(tmp_path)
    op, grok = RoteiroEdit(service), EditGrok()
    first, second = str(uuid4()), str(uuid4())
    try:
        await op.propose(doc.id, first, edit_request(doc), grok)
        await op.propose(doc.id, second, edit_request(doc), grok)
        await op.generate(doc.id, first, EditGenerate(prompt="First improved instruction"))
        await service._task
        with pytest.raises(Conflict, match="edição anterior"):
            await op.generate(doc.id, second, EditGenerate(prompt="Second instruction"))
        with pytest.raises(Conflict):
            op.discard(doc.id, first)
        await service.decide(first, True)
        with pytest.raises(Conflict, match="edição anterior"):
            op.select(doc.id, doc.blocks[0].id, doc.attempts[0].run_id, Revision(expected_revision=doc.revision))
        op.discard(doc.id, first)
        await op.generate(doc.id, second, EditGenerate(prompt="Second instruction"))
        await service._task
        assert len(service.comfy.submitted) == 5
        assert service.store.get(first).state == "accepted"
    finally:
        await service.shutdown()


async def test_explicit_retry_copies_actual_prompt_without_calling_grok(tmp_path):
    service, _, doc = await prepared(tmp_path)
    op, grok, ident = RoteiroEdit(service), EditGrok(), str(uuid4())
    try:
        await op.propose(doc.id, ident, edit_request(doc), grok)
        await op.generate(doc.id, ident, EditGenerate(prompt="Actually submitted enhanced prompt"))
        await service._task
        await service.decide(ident, False)
        old = service.store.get(ident).model_dump()
        new_id = str(uuid4())
        retry = op.retry(doc.id, ident, new_id, Revision(expected_revision=doc.revision))
        assert retry["prompt"] == old["prompt"]
        assert retry["previous_run_id"] == old["parent_id"]
        assert retry["next_run_id"] == old["input_info"]["continuation"]["target_run_id"]
        assert retry["run_id"] is None and retry["state"] == "proposed"
        assert len(grok.calls) == 1 and len(service.comfy.submitted) == 4
        assert service.store.get(ident).model_dump() == old
    finally:
        await service.shutdown()


async def test_restart_only_marks_pending_grok_uncertain(tmp_path):
    service, _, doc = await prepared(tmp_path)
    op, grok, ident = RoteiroEdit(service), EditGrok(), str(uuid4())
    try:
        await op.propose(doc.id, ident, edit_request(doc), grok)
        record = op.read(doc.id, ident)
        record.update(state="improving", prompt=None)
        op.save(record)
        op.recover()
        assert op.view(doc.id, ident)["state"] == "uncertain"
        assert len(grok.calls) == 1 and len(service.comfy.submitted) == 3
        with pytest.raises(Conflict):
            op.discard(doc.id, ident)
    finally:
        await service.shutdown()
