import asyncio
from uuid import uuid4

import httpx
from test_roteiro import fields, setup
from test_roteiro_batch import FakeEnhancer

from h3_backend.api import create_app
from h3_backend.roteiro import CreatePlan


async def test_http_batch_binds_editor_and_preserves_one_known_uuid(tmp_path):
    service, op = setup(tmp_path)
    doc = await op.create(CreatePlan(**fields()))
    app = create_app(service=service)
    app.state.grok = FakeEnhancer()
    batch_id = str(uuid4())
    path = f"/roteiros/{doc['id']}/batches/{batch_id}"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            incomplete = {"expected_revision": 1, "auto_accept_intermediate": True}
            assert (await client.post(path, json=incomplete)).status_code == 422
            assert not app.state.grok.calls
            body = {**incomplete, "enhance_with_grok": True}
            assert (await client.post(path, json=body, headers={"Origin": "http://other"})).status_code == 403
            result = await client.post(path, json=body)
            assert result.status_code == 202 and result.json()["id"] == batch_id
            await app.state.roteiro_batch.task
            stored = (await client.get(path)).json()
            assert stored["state"] == "ready_for_review"
            assert (await client.get("/roteiro-batches/current")).json()["batch"] == stored
            assert len(app.state.grok.calls) == 2
            assert (await client.post(path, json=body)).status_code == 409
            assert len(app.state.grok.calls) == 2
    finally:
        await app.state.roteiro_batch.shutdown()
        await service.shutdown()


async def test_http_batch_stop_while_detailing_never_submits_gpu(tmp_path):
    service, op = setup(tmp_path)
    doc = await op.create(CreatePlan(**fields()))
    entered = asyncio.Event()

    class GatedEnhancer:
        async def complete(self, request):
            entered.set()
            await asyncio.Event().wait()

    app = create_app(service=service)
    app.state.grok = GatedEnhancer()
    batch_id = str(uuid4())
    path = f"/roteiros/{doc['id']}/batches/{batch_id}"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            response = await client.post(path, json={"expected_revision": 1,
                                                     "auto_accept_intermediate": True,
                                                     "enhance_with_grok": True})
            assert response.status_code == 202
            await entered.wait()
            current = (await client.get("/roteiro-batches/current")).json()["batch"]
            assert current["phase"] == "improving" and current["current_run_id"] is None
            assert (await client.post(f"{path}/stop", json={"resume": True})).status_code == 400
            assert not app.state.roteiro_batch.task.done()
            stopped = await client.post(f"{path}/stop", json={})
            assert stopped.status_code == 200 and stopped.json()["state"] == "stopped"
            assert (await client.get(path)).json()["stop_requested"] is True
            assert (await client.post(f"{path}/stop", json={})).status_code == 409
            assert service.comfy.submitted == []
            assert op.get(doc["id"]).attempts == []
    finally:
        await app.state.roteiro_batch.shutdown()
        await service.shutdown()
