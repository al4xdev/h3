import json

import httpx
import pytest
from fastapi import FastAPI

from h3_backend.pwa import WEB_ROOT, router


@pytest.mark.asyncio
async def test_pwa_assets_are_explicit_and_worker_is_versioned():
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://h3.test") as client:
        response = await client.get("/manifest.webmanifest")
        manifest = response.json()
        assert manifest["display"] == "fullscreen"
        assert manifest["scope"] == manifest["start_url"] == manifest["id"] == "/"
        assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}
        assert response.headers["content-type"].startswith("application/manifest+json")
        worker = await client.get("/service-worker.js")
        assert worker.headers["service-worker-allowed"] == "/"
        assert worker.headers["cache-control"] == "no-cache"
        assert "__CACHE_VERSION__" not in worker.text
        assert worker.text == (await client.get("/service-worker.js")).text
        offline = await client.get("/ui/offline.html")
        assert "Sem conexão com o PC" in offline.text
        assert "app.js" not in offline.text
        for path in ("/ui/pwa.js",):
            assert (await client.get(path)).status_code == 200
        for path in ("/ui/oauth.json", "/ui/icon-source.png", "/ui/app.js", "/.data/runs"):
            assert (await client.get(path)).status_code == 404
        assert "setupPwa" in (await client.get("/ui/pwa.js?filename=oauth.json")).text


def test_offline_page_never_opens_generation_or_mutates_data():
    offline = (WEB_ROOT / "offline.html").read_text()
    assert 'href=""' in offline
    assert "<script" not in offline
    manifest = json.loads((WEB_ROOT / "manifest.webmanifest").read_text())
    assert all(icon["src"].startswith("/ui/icon-") for icon in manifest["icons"])
