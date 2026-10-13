"""Independent Grok text editor and local config; no video coupling or replay."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from stat import S_ISREG
from uuid import uuid4

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


DEFAULT_EDITOR_SYSTEM = (
    "Transforme a ideia simples do usuário em uma instrução de cena clara, no idioma dele. "
    "Preserve a ação, roupa, pose e ordem das mudanças pedidas; descreva a continuidade de modo "
    "conciso. Não invente identidade, aparência, ações ou mudanças não solicitadas. "
    "Não inclua explicações, títulos, parâmetros técnicos, nodes, seed, duração, resolução, "
    "sampler ou ajustes do modelo. Responda somente com a instrução editável da cena, "
    "em até 12000 caracteres. Você edita texto: não edita imagens nem gera vídeos."
)
EDITOR_MAX_BYTES = 1024 * 1024


class EditorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_prompt: str = Field(min_length=1, max_length=100_000, strict=True)
    model: str = Field(default="", max_length=256, strict=True)

    @field_validator("system_prompt", "model")
    @classmethod
    def nonblank(cls, value: str, info) -> str:
        if not value.strip() and (info.field_name == "system_prompt" or value):
            raise ValueError("Must not be blank")
        return value


@contextmanager
def editor_directory(root: Path, *, create: bool = False):
    # Fixed relative names and no-follow directory descriptors keep editor I/O
    # separate from credentials, even when an on-disk entry is replaced by a link.
    descriptors = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        for name in (".data", "grok"):
            if create:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=directory)
                except FileExistsError:
                    pass
            try:
                directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=directory)
            except FileNotFoundError:
                if create:
                    raise
                yield None
                return
            descriptors.append(directory)
        yield directory
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_editor_file(directory: int | None) -> EditorConfig | None:
    if directory is None:
        return None
    try:
        descriptor = os.open("editor.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > EDITOR_MAX_BYTES:
            raise ValueError("Invalid editor configuration file")
        raw = stream.read(EDITOR_MAX_BYTES + 1)
    if len(raw) > EDITOR_MAX_BYTES:
        raise ValueError("Editor configuration exceeds limit")
    return EditorConfig.model_validate_json(raw)


def read_editor(root: Path) -> EditorConfig:
    with editor_directory(root) as directory:
        value = read_editor_file(directory)
    return value or EditorConfig(system_prompt=DEFAULT_EDITOR_SYSTEM,
                                 model=os.getenv("H3_GROK_MODEL", ""))


def save_editor(root: Path, payload: EditorConfig) -> EditorConfig:
    with editor_directory(root, create=True) as directory:
        # A corrupt existing configuration is evidence, not permission to erase it.
        read_editor_file(directory)
        temporary = f".editor-{uuid4()}.part"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload.model_dump_json().encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, "editor.json", src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            # Only this invocation's verified directory-local temporary is removed.
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    return payload


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
    app.state.grok_editor_root = root
    app.state.grok_editor_lock = asyncio.Lock()
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


@router.get("/editor")
async def editor_config(request: Request):
    try:
        value = await asyncio.to_thread(read_editor, request.app.state.grok_editor_root)
        return reply(value.model_dump())
    except (ValueError, OSError):
        return reply({"error": "editor_storage_error",
                      "detail": "Editor configuration is invalid or inaccessible; not replaced."}, 409)


@router.put("/editor")
async def update_editor_config(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > EDITOR_MAX_BYTES:
            return reply({"error": "editor_too_large", "detail": "Editor JSON exceeds limit."}, 413)
        raw.extend(chunk)
    try:
        payload = EditorConfig.model_validate_json(raw)
    except ValueError:
        return reply({"error": "invalid_editor", "detail": "Use only bounded system_prompt and model."}, 422)
    try:
        async with request.app.state.grok_editor_lock:
            value = await asyncio.to_thread(save_editor, request.app.state.grok_editor_root, payload)
        return reply(value.model_dump())
    except (ValueError, OSError):
        return reply({"error": "editor_storage_error",
                      "detail": "Editor configuration could not be saved; inspect local configuration."}, 409)


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
