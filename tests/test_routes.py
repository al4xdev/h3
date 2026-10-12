import httpx
import pytest
from test_api import Service

from h3_backend.api import create_app
from h3_backend.models import RunRequest
from h3_backend.routes.i2v import router as i2v_router
from h3_backend.routes.v2v import router as v2v_router


@pytest.mark.asyncio
async def test_explicit_routes_and_aliases_are_isolated(tmp_path):
    service = Service(tmp_path)
    operations = []
    original_i2v = service.create
    original_v2v = service.continue_run

    async def i2v(request):
        operations.append("i2v")
        return await original_i2v(request)

    async def v2v(parent_id, request):
        operations.append("v2v")
        return await original_v2v(parent_id, request)

    parent = await original_i2v(RunRequest(seed=1))
    service.store.update(parent.id, state="running")
    service.store.update(parent.id, state="ready_for_review")
    await service.decide(parent.id, True)
    service.create = i2v
    service.continue_run = v2v
    app = create_app(service=service)
    endpoints = {route.path: route.endpoint for route in [*i2v_router.routes, *v2v_router.routes]}
    assert endpoints["/runs"] is endpoints["/runs/i2v"]
    assert endpoints["/runs/{parent_id}/continue"] is endpoints["/runs/{parent_id}/v2v"]
    assert endpoints["/runs/i2v"].__module__ == "h3_backend.routes.i2v"
    assert endpoints["/runs/{parent_id}/v2v"].__module__ == "h3_backend.routes.v2v"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://fake") as client:
        for url in ("/runs/i2v", "/runs"):
            response = await client.post(url, json={"seed": 7, "prompt": "# Initial\n"})
            assert response.status_code == 202
            assert response.json()["prompt"] == "# Initial\n"
            assert operations[-1] == "i2v"
            assert (await client.post(url, json={"seed": 7, "include_audio": True})).status_code == 422
        for url in (f"/runs/{parent.id}/v2v", f"/runs/{parent.id}/continue"):
            assert (await client.post(url, json={"seed": 8})).status_code == 202
            assert operations[-1] == "v2v"
            assert (await client.post(url, json={"seed": 8, "image": "oops.png"})).status_code == 422
    assert operations == ["i2v", "i2v", "v2v", "v2v"]
