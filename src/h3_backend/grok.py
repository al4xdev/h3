"""Small, backend-only SuperGrok operation; no history or inference replay."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .infrastructure.grok_oauth import BASE_URL, OAuthError, OAuthManager


class PromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_prompt: str = Field(default="", max_length=100_000, strict=True)
    prompt: str = Field(min_length=1, max_length=100_000, strict=True)
    model: str | None = Field(default=None, min_length=1, max_length=256, strict=True)

    @field_validator("prompt", "model")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Must not be blank")
        return value


class FlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow_id: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def reply(value: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def extract_text(value: object) -> str:
    invalid = OAuthError("invalid_response", "Grok did not return a complete text response.", 502)
    if (not isinstance(value, dict) or value.get("status") != "completed"
            or value.get("error") or value.get("incomplete_details")):
        raise invalid
    output = value.get("output")
    if not isinstance(output, list):
        raise invalid
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise invalid
        if item.get("type") == "reasoning":
            continue
        if (item.get("type") != "message" or item.get("role") != "assistant"
                or item.get("status") != "completed" or not isinstance(item.get("content"), list)):
            raise invalid
        for part in item["content"]:
            if (not isinstance(part, dict) or part.get("type") != "output_text"
                    or not isinstance(part.get("text"), str)):
                raise invalid
            texts.append(part["text"])
    text = "".join(texts)
    if not text.strip():
        raise invalid
    return text


class Grok:
    def __init__(self, manager: OAuthManager, model: str = ""):
        self.manager = manager
        self.model = model

    async def complete(self, payload: PromptRequest) -> dict:
        model = payload.model or self.model
        if not model:
            raise OAuthError("model_required", "Set H3_GROK_MODEL or provide a catalog model.", 400)
        async with self.manager.client_factory() as client:
            tokens, models = await self.manager.authorized_models(client, recover=False)
            if not any(row["id"] == model for row in models):
                raise OAuthError("model_required", "Choose a model from /grok/auth/models.", 400)
            messages = []
            if payload.system_prompt:
                messages.append({"role": "system", "content": payload.system_prompt})
            messages.append({"role": "user", "content": payload.prompt})
            # A rejected or uncertain inference is never replayed automatically.
            try:
                async with (
                    asyncio.timeout(120),
                    client.stream(
                        "POST", f"{BASE_URL}/responses",
                        headers={"Authorization": f"Bearer {tokens.access}",
                                 "User-Agent": "H3-SuperGrok/0.1"},
                        json={"model": model, "input": messages, "max_output_tokens": 8192,
                              "stream": False, "store": False},
                        timeout=120, follow_redirects=False,
                    ) as response,
                ):
                    if response.status_code in (401, 403):
                        raise OAuthError("authorization_rejected", "Grok refused authorization.",
                                         response.status_code)
                    if response.status_code == 429:
                        raise OAuthError("rate_limited", "Grok quota or rate limit reached.", 429)
                    if response.status_code != 200:
                        raise OAuthError("provider_error", "Grok request failed; not retried.", 502)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise OAuthError("invalid_response", "Grok response exceeds limit.", 502)
                    value = json.loads(raw)
            except (httpx.HTTPError, TimeoutError):
                raise OAuthError("network_error", "Grok result is uncertain; not retried.", 502) from None
            except (ValueError, UnicodeError):
                raise OAuthError("invalid_response", "Grok returned invalid JSON.", 502) from None
        return {"text": extract_text(value), "model": model}


@asynccontextmanager
async def grok_lifespan(app: FastAPI):
    # No credential or network I/O at import. Storage is independent of video state.
    root = Path(os.getenv("H3_PROJECT_ROOT", str(Path(__file__).resolve().parents[2])))
    grok = Grok(OAuthManager(root / ".data" / "grok" / "oauth.json"),
                os.getenv("H3_GROK_MODEL", ""))
    app.state.grok = grok
    try:
        yield
    finally:
        await grok.manager.close()


router = APIRouter(prefix="/grok", tags=["grok"], lifespan=grok_lifespan)


async def invoke(operation, *args) -> JSONResponse:
    try:
        return reply(await operation(*args))
    except OAuthError as error:
        return reply({"error": error.code, "detail": str(error)}, error.status)
    except OSError:
        return reply({"error": "storage_error", "detail": "Could not store Grok credentials."}, 500)


@router.post("")
async def complete(payload: PromptRequest, request: Request):
    return await invoke(request.app.state.grok.complete, payload)


@router.post("/auth/start")
async def start(request: Request):
    return await invoke(request.app.state.grok.manager.start)


@router.post("/auth/flow")
async def flow(payload: FlowRequest, request: Request):
    return await invoke(request.app.state.grok.manager.flow_status, payload.flow_id)


@router.post("/auth/status")
async def status(request: Request):
    return await invoke(request.app.state.grok.manager.connection_status)


@router.post("/auth/cancel")
async def cancel(payload: FlowRequest, request: Request):
    async def operation():
        await request.app.state.grok.manager.cancel(payload.flow_id)
        return {"cancelled": True}
    return await invoke(operation)


@router.post("/auth/models")
async def models(request: Request):
    async def operation():
        manager = request.app.state.grok.manager
        async with manager.client_factory() as client:
            _, catalog = await manager.authorized_models(client, recover=False)
        return {"models": catalog}
    return await invoke(operation)
