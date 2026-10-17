"""ASGI Tail contracts use temporary accepted CPU fixtures and fake Grok."""

import json
from uuid import uuid4

import httpx
import pytest
from test_roteiro import FakeGrok
from test_roteiro_tail import accepted_root, payload

from h3_backend.api import create_app


def client_for(service, fake):
    app = create_app(service=service)
    app.state.grok = fake
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                             base_url="http://local.test")


@pytest.mark.asyncio
async def test_http_explicit_uuid_propose_get_adopt_preserves_prefix_and_no_generation(tmp_path):
    service, op, doc, parent_id = await accepted_root(tmp_path)
    fake = FakeGrok()
    ident = str(uuid4())
    url = f"/roteiros/{doc.id}/tail/{ident}"
    calls = len(service.comfy.submitted)
    async with client_for(service, fake) as client:
        missing = await client.get(url)
        assert missing.status_code == 404 and not fake.calls
        result = await client.post(url, json=payload(doc).model_dump())
        assert result.status_code == 200
        candidate = result.json()
        assert candidate["parent_id"] == parent_id and candidate["name"] == doc.name
        assert result.headers["cache-control"] == "no-store"
        assert (await client.get(url)).json() == candidate
        duplicate = await client.post(url, json=payload(doc).model_dump())
        assert duplicate.status_code == 409
        assert not duplicate.json().get("tail_not_submitted")
        assert len(fake.calls) == 3
        edited = candidate["blocks"][::-1]
        edited[0]["prompt"] = "Explicit user edited instruction"
        adopted = await client.put(url, json={"expected_revision": doc.revision, "blocks": edited})
        assert adopted.status_code == 200
        updated = adopted.json()
        assert updated["blocks"][:1] == [b.model_dump() for b in doc.blocks]
        assert updated["blocks"][1:] == edited
        assert updated["revision"] == doc.revision + 1
        assert updated["idea"] == doc.idea and updated["attempts"][0]["run_id"] == parent_id
        assert (await client.get(url)).json()["state"] == "adopted"
        assert (await client.put(url, json={"expected_revision": doc.revision,
                                          "blocks": edited})).status_code == 409
    assert op.get(doc.id).attempts == doc.attempts
    assert len(service.comfy.submitted) == calls and len(fake.calls) == 3
    await service.shutdown()


@pytest.mark.asyncio
async def test_http_strict_dto_same_origin_and_definitive_preflight_marker(tmp_path):
    service, op, doc, _ = await accepted_root(tmp_path)
    fake = FakeGrok()
    ident = str(uuid4())
    url = f"/roteiros/{doc.id}/tail/{ident}"
    async with client_for(service, fake) as client:
        blocked = await client.post(url, headers={"Origin": "https://external.test"},
                                    json=payload(doc).model_dump())
        assert blocked.status_code == 403 and not fake.calls
        invalid = await client.post(url, headers={"Origin": "http://local.test"},
                                    json={**payload(doc).model_dump(), "parent_id": str(uuid4())})
        assert invalid.status_code == 422
        proof = invalid.json()
        assert proof["tail_not_submitted"] is True
        assert proof["id"] == ident and proof["roteiro_id"] == doc.id
        stale = await client.post(url, json={**payload(doc).model_dump(), "expected_revision": 9})
        assert stale.status_code == 409 and stale.json()["tail_not_submitted"] is True
        assert (await client.get(url)).status_code == 404
        assert not fake.calls
        result = await client.post(url, json=payload(doc).model_dump())
        assert result.status_code == 200
        known = await client.post(url, json={**payload(doc).model_dump(), "seed": True})
        assert known.status_code == 422 and not known.json().get("tail_not_submitted")
        foreign = result.json()["blocks"]
        foreign[0]["id"] = doc.blocks[0].id
        rejected = await client.put(url, json={"expected_revision": doc.revision, "blocks": foreign})
        assert rejected.status_code == 409
        assert op.get(doc.id) == doc
    assert len(fake.calls) == 3
    await service.shutdown()


@pytest.mark.asyncio
async def test_http_invalid_json_retains_raw_and_unknown_provider_result_is_fenced(tmp_path):
    service, op, doc, _ = await accepted_root(tmp_path)
    fake = FakeGrok(text='{"name":"bad","blocks":[]}')
    url = f"/roteiros/{doc.id}/tail/{uuid4()}"
    async with client_for(service, fake) as client:
        result = await client.post(url, json=payload(doc).model_dump())
        assert result.status_code == 422
        assert result.json()["state"] == "invalid" and result.json()["raw_text"] == fake.text
        assert (await client.get(url)).json()["raw_text"] == fake.text
        assert (await client.post(url, json=payload(doc).model_dump())).status_code == 409
    class Lost:
        calls = 0

        async def complete(self, request, **kwargs):
            self.calls += 1
            raise OSError("Response lost")

    lost = Lost()
    uncertain_url = f"/roteiros/{doc.id}/tail/{uuid4()}"
    async with client_for(service, lost) as client:
        failed = await client.post(uncertain_url, json=payload(doc).model_dump())
        assert failed.status_code == 500
        assert "tail_not_submitted" not in failed.text
        recovered = await client.get(uncertain_url)
        assert recovered.status_code == 200 and recovered.json()["state"] == "uncertain"
        assert recovered.json()["raw_text"] == ""
        duplicate = await client.post(uncertain_url, json=payload(doc).model_dump())
        assert duplicate.status_code == 409 and not duplicate.json().get("tail_not_submitted")
        another = await client.post(f"/roteiros/{doc.id}/tail/{uuid4()}",
                                    json=payload(doc).model_dump())
        assert another.status_code == 409 and another.json()["tail_not_submitted"] is True
    assert lost.calls == 1 and op.get(doc.id) == doc
    ledger = list((tmp_path / ".data/roteiros" / doc.id).glob("tail-*.json"))
    assert sorted(json.loads(p.read_text())["state"] for p in ledger) == ["invalid", "uncertain"]
    await service.shutdown()
