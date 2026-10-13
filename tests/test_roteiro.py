"""Temporary-root/CPU contracts: no credentials, provider or production traversal."""

import asyncio
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from test_grok_multimodal import fixture_image
from test_service import make_service

from h3_backend.generation.dispatcher import Conflict
from h3_backend.grok import FIXED_EDITOR_MODEL, seed_editor
from h3_backend.roteiro import (
    MAX_METADATA_BYTES,
    Block,
    CreatePlan,
    ProposalRequest,
    Roteiro,
    ScriptConfig,
    UpdatePlan,
    router,
    strict_json,
)


def fields(*, count=2, adopted=True):
    return {"name": "Dança", "idea": "Preto, depois vermelho",
            "reference": {"source_root": "assets", "path": "dance_reference.png"},
            "adopted": adopted,
            "blocks": [{"id": str(uuid4()), "action": f"Ação {i}", "duration_seconds": 2.3,
                        "seed": 2026101205, "prompt": f"Prompt {i}"} for i in range(count)]}


def setup(tmp_path):
    service = make_service(tmp_path)
    # Generate at a fresh name: FFmpeg's -nostdin fixture does not overwrite fake-image.
    encoded = fixture_image(tmp_path / "reference-fixture.png")
    (tmp_path / "assets" / "dance_reference.png").write_bytes(encoded)
    seed_editor(tmp_path)
    return service, Roteiro(service)


def update(doc, **changes):
    return UpdatePlan(**{key: getattr(doc, key) for key in (
        "name", "idea", "reference", "adopted", "blocks")},
        expected_revision=doc.revision).model_copy(update=changes)


class FakeGrok:
    def __init__(self, *, text=None, gate=None):
        self.calls = []
        self.schemas = []
        self.gate = gate
        self.entered = asyncio.Event()
        self.text = text or json.dumps({"name": "Proposta", "blocks": [
            {"action": "Preto", "duration_seconds": 8, "prompt": "Dança de preto"},
            {"action": "Vermelho", "duration_seconds": 8, "prompt": "Muda para vermelho"},
        ]})

    async def complete(self, request, **kwargs):
        self.calls.append(request)
        self.schemas.append(kwargs)
        self.entered.set()
        if self.gate:
            await self.gate.wait()
        return {"text": self.text, "model": FIXED_EDITOR_MODEL}


@pytest.mark.asyncio
async def test_create_read_update_list_are_inert(tmp_path):
    service, op = setup(tmp_path)
    assert op.list() == {"items": [], "total": 0}
    assert not (tmp_path / ".data" / "roteiros").exists()
    result = await op.create(CreatePlan(**fields()))
    doc = op.get(result["id"])
    assert result["revision"] == 1 and result["attempts"] == []
    assert len(doc.reference_sha256) == 64
    assert op.list()["items"] == [result]
    changed = await op.update(doc.id, update(doc, name="Outra"))
    assert changed["revision"] == 2 and changed["name"] == "Outra"
    with pytest.raises(Conflict):
        await op.update(doc.id, update(doc))
    assert not service.comfy.submitted and service._active is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_editor_is_separate_absent_get_inert_and_put_explicit(tmp_path):
    service, op = setup(tmp_path)
    original = (tmp_path / ".data" / "grok" / "editor.json").read_bytes()
    config = op.script_config()
    assert config["model"] == FIXED_EDITOR_MODEL
    assert not (tmp_path / ".data" / "roteiros").exists()
    op.save_script(ScriptConfig(system_prompt="Meu sistema do macro"))
    assert op.script_config()["system_prompt"] == "Meu sistema do macro"
    assert (tmp_path / ".data" / "grok" / "editor.json").read_bytes() == original
    with pytest.raises(ValidationError):
        ScriptConfig(system_prompt="x", model="override")
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_candidate_separate_exact_count_seed_and_late_revision(tmp_path):
    service, op = setup(tmp_path)
    created = await op.create(CreatePlan(**fields(adopted=False)))
    doc = op.get(created["id"])
    gate = asyncio.Event()
    fake = FakeGrok(gate=gate)
    task = asyncio.create_task(op.propose(doc.id, ProposalRequest(
        expected_revision=1, count=2, seed=42), fake))
    await asyncio.wait_for(fake.entered.wait(), 5)
    edited = await op.update(doc.id, update(doc, name="Manual mudou"))
    gate.set()
    candidate = await task
    assert candidate["stale"] is True and candidate["source_revision"] == 1
    assert candidate["name"] == "Proposta"
    assert all(block["seed"] == 42 and block["duration_seconds"] == 8
               for block in candidate["blocks"])
    assert not {b["id"] for b in candidate["blocks"]} & {b.id for b in doc.blocks}
    assert op.get(doc.id).blocks == doc.blocks
    assert op.get(doc.id).name == edited["name"]
    assert len(fake.calls) == 1
    assert fake.schemas[0]["schema_name"] == "h3_roteiro"
    schema = fake.schemas[0]["output_schema"]
    assert schema["properties"]["blocks"]["minItems"] == 2
    assert schema["properties"]["blocks"]["maxItems"] == 2
    assert fake.calls[0].reference == doc.reference
    assert fake.calls[0].system_prompt == op.script_config()["system_prompt"]
    assert fake.calls[0].model == FIXED_EDITOR_MODEL
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    '```json\n{"name":"x","blocks":[]}\n```',
    '{"name":"x","name":"y","blocks":[]}',
    '{"name":"x","blocks":[{"action":"a","prompt":"b","duration_seconds":NaN}]}',
    '{"name":"x","blocks":[{"action":"a","duration_seconds":8}]}',
    '{"name":"x","blocks":[{"action":"a","prompt":"b","duration_seconds":11}]}',
    '{"name":"x","blocks":[{"action":"a","prompt":"b","duration_seconds":8,"seed":1}]}',
    '{"name":"x","blocks":[{"action":"a","prompt":"b","duration_seconds":8}]}',
])
async def test_invalid_provider_json_never_guesses_or_adopts(tmp_path, text):
    service, op = setup(tmp_path)
    created = await op.create(CreatePlan(**fields(adopted=False)))
    doc = op.get(created["id"])
    fake = FakeGrok(text=text)
    result = await op.propose(doc.id, ProposalRequest(expected_revision=1, count=2, seed=7), fake)
    assert result["error"] == "invalid_proposal" and result["raw_text"] == text
    assert op.get(doc.id) == doc
    assert len(fake.calls) == 1 and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.parametrize("change", [
    {"duration_seconds": 0}, {"duration_seconds": 10.01}, {"duration_seconds": 1.001},
    {"duration_seconds": True}, {"seed": True}, {"seed": "5"}, {"action": "  "},
    {"prompt": "x" * 12001}, {"id": "../escape"}, {"id": str(uuid4()).upper()},
    {"unexpected": "field"},
])
def test_strict_blocks_reject_without_clamping(change):
    block = fields(count=1)["blocks"][0]
    with pytest.raises(ValidationError):
        Block(**{**block, **change})


def test_plan_count_duplicate_keys_and_metadata_limits():
    with pytest.raises(ValidationError):
        CreatePlan(**fields(count=51))
    payload = fields()
    payload["blocks"][1]["id"] = payload["blocks"][0]["id"]
    with pytest.raises(ValidationError):
        CreatePlan(**payload)
    with pytest.raises(ValueError):
        strict_json(b" " * (MAX_METADATA_BYTES + 1))
    with pytest.raises(ValueError):
        strict_json('{"nested":{"a":1,"a":2}}')


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["file_symlink", "dir_symlink", "hardlink", "wrong_uuid", "json"])
async def test_owned_storage_rejects_links_corruption_and_file_identity(tmp_path, corruption):
    service, op = setup(tmp_path)
    created = await op.create(CreatePlan(**fields()))
    doc = op.get(created["id"])
    path = tmp_path / ".data" / "roteiros" / doc.id / "plan.json"
    if corruption == "file_symlink":
        saved = path.read_bytes()
        path.unlink()
        other = tmp_path / "other.json"
        other.write_bytes(saved)
        path.symlink_to(other)
    elif corruption == "dir_symlink":
        directory = path.parent
        moved = directory.with_name("moved")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    elif corruption == "hardlink":
        os.link(path, tmp_path / "alias.json")
    elif corruption == "wrong_uuid":
        value = json.loads(path.read_text())
        value["id"] = str(uuid4())
        path.write_text(json.dumps(value))
    else:
        path.write_text("{bad")
    with pytest.raises((ValueError, OSError)):
        op.get(doc.id)
    await service.shutdown()


@pytest.mark.asyncio
async def test_http_strict_body_no_server_owned_fields_and_no_provider_on_reads(tmp_path):
    service, _op = setup(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.service = service
    app.state.grok = FakeGrok()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/roteiros")
        assert listed.json() == {"items": [], "total": 0}
        response = await client.post("/roteiros", json={**fields(), "attempts": []})
        assert response.status_code == 422
        response = await client.post("/roteiros", content=b" " * (MAX_METADATA_BYTES + 1))
        assert response.status_code == 413
        response = await client.post("/roteiros", json=fields())
        assert response.status_code == 201
        doc = response.json()
        assert (await client.get(f"/roteiros/{doc['id']}")).json() == doc
        assert (await client.get("/roteiros/editor")).status_code == 200
        assert not app.state.grok.calls
        assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_aggregate_metadata_overflow_leaves_no_empty_document(tmp_path):
    service, op = setup(tmp_path)
    payload = fields(count=50)
    for block in payload["blocks"]:
        block["action"] = "a" * 12000
        block["prompt"] = "p" * 12000
    with pytest.raises(ValueError, match="1 MiB"):
        await op.create(CreatePlan(**payload))
    assert op.list() == {"items": [], "total": 0}
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_reference_requires_publication_sha_and_no_partial_marker(tmp_path, partial):
    from test_grok_multimodal import input_fixture

    service, op = setup(tmp_path)
    reference, _ = input_fixture(tmp_path, corrupt=not partial, partial=partial)
    payload = fields()
    payload["reference"] = reference.model_dump()
    with pytest.raises(ValueError):
        await op.create(CreatePlan(**payload))
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_provider_failure_leaves_durable_candidate_intent_not_adopted(tmp_path):
    service, op = setup(tmp_path)
    created = await op.create(CreatePlan(**fields(adopted=False)))
    doc = op.get(created["id"])

    class LostGrok:
        async def complete(self, payload, **kwargs):
            raise OSError("Lost explicit proposal response")

    with pytest.raises(OSError):
        await op.propose(doc.id, ProposalRequest(expected_revision=1, count=2, seed=8), LostGrok())
    candidates = list((tmp_path / ".data" / "roteiros" / doc.id).glob("proposal-*.json"))
    assert len(candidates) == 1
    reserved = json.loads(candidates[0].read_text())
    assert reserved["state"] == "uncertain" and reserved["source"]["idea"] == doc.idea
    assert op.get(doc.id) == doc and not service.comfy.submitted
    await service.shutdown()
