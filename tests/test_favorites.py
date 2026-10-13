import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from test_library_cleanup import block
from test_roteiro import fields, setup
from test_service import make_service

from h3_backend.favorites import Favorites, router
from h3_backend.infrastructure.store import Store
from h3_backend.library import Library
from h3_backend.roteiro import CreatePlan, locked


def test_favorites_survive_restart_and_resolve_outside_page(tmp_path):
    service = make_service(tmp_path)
    oldest = block(service)
    for _ in range(13):
        block(service)
    op = Favorites(service)
    op.select("freestyle", oldest.id, True)
    assert oldest.id not in {item["id"] for item in op.freestyle(12, 0)["items"]}
    restarted = Favorites(SimpleNamespace(store=Store(tmp_path)))
    assert restarted.catalog()["items"][0]["item"]["id"] == oldest.id
    restarted.select("freestyle", oldest.id, True)
    assert restarted.catalog()["total"] == 1
    restarted.select("freestyle", oldest.id, False)
    assert op.catalog() == {"items": [], "total": 0}
    assert not service.comfy.submitted


@pytest.mark.asyncio
async def test_roteiro_favorite_and_standalone_filter_before_pagination(tmp_path):
    service, roteiro = setup(tmp_path)
    doc = await roteiro.create(CreatePlan(**fields()))
    run = block(service)
    op = Favorites(service)
    assert op.select("roteiro", doc["id"], True)["items"][0]["item"]["name"] == "Dança"
    op.roteiro.list = lambda: {"items": [{"attempts": [{"run_id": run.id}]}]}
    others = [block(service) for _ in range(13)]
    first, second = op.freestyle(12, 0), op.freestyle(12, 12)
    assert first["total"] == second["total"] == 13
    assert len(first["items"]) == 12 and len(second["items"]) == 1
    assert {item["id"] for item in first["items"] + second["items"]} == {run.id for run in others}
    assert not service.comfy.submitted


@pytest.mark.asyncio
async def test_long_roteiros_publish_small_favorite_summaries_without_native_observation(tmp_path):
    service, roteiro = setup(tmp_path)
    payload = fields(count=50)
    payload["name"] = "🎞" * 256
    for item in payload["blocks"]:
        item["prompt"] = "p" * 12000
    docs = [await roteiro.create(CreatePlan(**payload)) for _ in range(2)]
    before = [(tmp_path / f".data/roteiros/{doc['id']}/plan.json").read_bytes() for doc in docs]
    op = Favorites(service)
    op.roteiro.view = lambda _: pytest.fail("Favorite summary must not observe native children")
    app = FastAPI()
    app.state.service = service
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for doc in docs:
            result = await client.put(f"/favorites/roteiro/{doc['id']}", json={"favorite": True})
            assert result.status_code == 200
            assert len(result.content) < 2048
        result = await client.get("/favorites")
        assert result.status_code == 200 and result.json()["total"] == 2
        assert len(result.content) < 2048
    for item in op.catalog()["items"]:
        assert item["item"]["block_count"] == 50
        assert set(item["item"]) == {"id", "name", "block_count"}
        assert len(item["item"]["name"].encode()) <= 256
    assert before == [(tmp_path / f".data/roteiros/{doc['id']}/plan.json").read_bytes() for doc in docs]
    run = block(service)
    service.store.update(run.id, prompt="🎞" * 12000)
    summary = op.select("freestyle", run.id, True)["items"][-1]["item"]
    assert len(summary["prompt"]) <= 160 and len(summary["prompt"].encode()) <= 256
    assert set(summary) == {"id", "state", "prompt", "duration_seconds", "seed"}
    assert not service.comfy.submitted


def test_invalid_target_symlink_and_corruption_preserve_evidence(tmp_path):
    service = make_service(tmp_path)
    op = Favorites(service)
    run = block(service)
    with pytest.raises((ValueError, FileNotFoundError)):
        op.select("freestyle", "../outside", True)
    with pytest.raises(FileNotFoundError):
        op.select("freestyle", str(uuid4()), True)
    op.select("freestyle", run.id, True)
    path = tmp_path / ".data/library/favorites.json"
    original = path.read_bytes()
    path.rename(path.with_suffix(".bak"))
    path.symlink_to(path.with_suffix(".bak"))
    with pytest.raises(OSError):
        op.select("freestyle", run.id, False)
    assert path.with_suffix(".bak").read_bytes() == original


@pytest.mark.asyncio
async def test_routes_require_boolean_put_and_never_submit(tmp_path):
    service = make_service(tmp_path)
    run = block(service)
    app = FastAPI()
    app.state.service = service
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/favorites")).json() == {"items": [], "total": 0}
        path = f"/favorites/freestyle/{run.id}"
        assert (await client.put(path, json={"favorite": "true"})).status_code == 422
        result = await client.put(path, json={"favorite": True})
        assert result.status_code == 200 and result.json()["total"] == 1
        assert (await client.get("/library/freestyle?limit=12")).json()["total"] == 1
        assert (await client.get("/library/freestyle?limit=0")).status_code == 422
    assert json.loads((tmp_path / ".data/library/favorites.json").read_text())["items"] == [
        {"kind": "freestyle", "id": run.id}]
    assert not service.comfy.submitted


@pytest.mark.asyncio
async def test_removed_favorite_is_not_resolved_or_republished(tmp_path):
    service = make_service(tmp_path)
    run = block(service)
    op = Favorites(service)
    op.select("freestyle", run.id, True)
    before = (tmp_path / ".data/library/favorites.json").read_bytes()
    await Library(service).remove(run.id)
    assert op.catalog() == {"items": [], "total": 0}
    assert (tmp_path / ".data/library/favorites.json").read_bytes() == before
    with pytest.raises(FileNotFoundError):
        op.select("freestyle", run.id, True)
    assert op.select("freestyle", run.id, False) == {"items": [], "total": 0}
    with pytest.raises(FileNotFoundError):
        op.select("freestyle", str(uuid4()), False)
    assert not service.comfy.submitted


def test_hardlink_and_competing_writer_do_not_overwrite_catalog(tmp_path):
    import os

    from h3_backend.generation.dispatcher import Conflict
    from h3_backend.infrastructure.grok_image import _directory

    service = make_service(tmp_path)
    run = block(service)
    op = Favorites(service)
    op.select("freestyle", run.id, True)
    path = tmp_path / ".data/library/favorites.json"
    before = path.read_bytes()
    with (_directory(tmp_path, (".data", "library")) as directory,
          locked(directory), pytest.raises(Conflict)):
        Favorites(service).select("freestyle", run.id, False)
    assert path.read_bytes() == before
    os.link(path, path.with_suffix(".bak"))
    with pytest.raises(ValueError):
        op.select("freestyle", run.id, False)
    assert path.read_bytes() == before
