"""Offline HTTP contract: no calls to xAI or ComfyUI."""

import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from h3_backend.grok import Grok, PromptRequest, extract_text, router
from h3_backend.infrastructure.grok_oauth import BASE_URL, OAuthError, OAuthManager, Tokens


def finished(text="hello"):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "status": "completed", "content": [{"type": "output_text", "text": text}]}]}


def fake_grok(tmp_path, handler, model="grok-test"):
    manager = OAuthManager(tmp_path / "grok" / "oauth.json", client_factory=lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler)))
    manager._persist(Tokens("private-access", "private-refresh", time.time() + 3600,
                            time.time() + 3500))
    return Grok(manager, model)


async def test_payload_and_persistence(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer private-access"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "grok-test"}]})
        assert str(request.url) == f"{BASE_URL}/responses"
        assert json.loads(request.content) == {
            "model": "grok-test", "input": [{"role": "system", "content": "instruction"},
                                             {"role": "user", "content": "question"}],
            "max_output_tokens": 8192, "stream": False, "store": False,
        }
        return httpx.Response(200, json=finished())

    grok = fake_grok(tmp_path, handler)
    app = FastAPI()
    app.include_router(router)
    app.state.grok = grok
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        response = await client.post("/grok", json={"system_prompt": "instruction", "prompt": "question"})
        assert response.status_code == 200
        assert response.json() == {"text": "hello", "model": "grok-test"}
        assert response.headers["cache-control"] == "no-store"
        status = await client.post("/grok/auth/status")
        assert status.json()["connected"]
        assert "private-" not in status.text
    restored = OAuthManager(grok.manager.path)
    assert (await restored.connection_status())["connected"]
    assert grok.manager.path.stat().st_mode & 0o777 == 0o600
    assert grok.manager.path.parent.stat().st_mode & 0o777 == 0o700
    assert len(seen) == 2


@pytest.mark.parametrize("failure", [401, 403, 429, 500, 302, "timeout", "bad-json", "incomplete"])
async def test_failures_are_sanitized_never_replayed(tmp_path, failure):
    submissions = []

    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "grok-test"}]})
        submissions.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-access", request=request)
        if failure == "bad-json":
            return httpx.Response(200, text="private-access")
        if failure == "incomplete":
            return httpx.Response(200, json={"status": "incomplete", "error": "private-access"})
        return httpx.Response(failure, json={"error": "private-access"})

    grok = fake_grok(tmp_path, handler)
    with pytest.raises(OAuthError) as raised:
        await grok.complete(PromptRequest(prompt="question"))
    assert "private-access" not in str(raised.value)
    assert len(submissions) == 1


async def test_login_and_model_required(tmp_path):
    def never_network(request):
        pytest.fail("Unexpected network call")

    manager = OAuthManager(tmp_path / "oauth.json", client_factory=lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(never_network)))
    with pytest.raises(OAuthError, match="Set H3_GROK_MODEL"):
        await Grok(manager).complete(PromptRequest(prompt="hello"))
    with pytest.raises(OAuthError, match="Connect your SuperGrok"):
        await Grok(manager, "grok-test").complete(PromptRequest(prompt="hello"))


async def test_unknown_model_never_submits(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "grok-test"}]})

    grok = fake_grok(tmp_path, handler)
    with pytest.raises(OAuthError, match="Choose a model"):
        await grok.complete(PromptRequest(prompt="hello", model="unknown"))
    assert seen == ["/v1/models"]


@pytest.mark.parametrize("value", [None, {}, finished(""),
    {"status": "completed", "output": [{"type": "message", "role": "assistant",
     "status": "completed", "content": [{"type": "refusal", "refusal": "no"}]}]}])
def test_response_validation(value):
    with pytest.raises(OAuthError):
        extract_text(value)


def test_router_lifespan_is_inert_and_closes(tmp_path, monkeypatch):
    monkeypatch.setenv("H3_PROJECT_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post("/grok/auth/status").json()["connected"] is False
        assert client.post("/grok", json={"prompt": " "}).status_code == 422
        assert client.post("/grok", json={"prompt": "hello", "api_base": "http://evil"}).status_code == 422
        assert not (tmp_path / ".data").exists()
    assert app.state.grok.manager._closed


def test_main_api_mounts_router_and_blocks_cross_origin(tmp_path, monkeypatch):
    from h3_backend.api import create_app

    class FakeService:
        async def startup(self):
            pass

        async def shutdown(self):
            pass

    monkeypatch.setenv("H3_PROJECT_ROOT", str(tmp_path))
    app = create_app(service=FakeService())
    with TestClient(app) as client:
        assert client.post("/grok/auth/status").status_code == 200
        response = client.post("/grok/auth/start", headers={"Origin": "https://foreign.example"})
        assert response.status_code == 403
        assert not (tmp_path / ".data").exists()
    assert app.state.grok.manager._closed
