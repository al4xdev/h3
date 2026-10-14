"""Independent Grok text editor and local config; no video coupling or replay."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from stat import S_ISREG
from uuid import uuid4

import anyio
import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .infrastructure.grok_image import (
    EditorReference,
    _thread,
    _uuid,
    continuation_frame,
    encoded_chunks,
    image_json_body,
    images_json_body,
    owned_image,
    snapshot_digest,
)
from .infrastructure.grok_oauth import BASE_URL, OAuthError, OAuthManager


class PromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_prompt: str = Field(default="", max_length=100_000, strict=True)
    prompt: str = Field(min_length=1, max_length=100_000, strict=True)
    model: str | None = Field(default=None, min_length=1, max_length=256, strict=True)
    reference: EditorReference | None = None
    continuation_parent_id: str | None = Field(default=None, strict=True, max_length=36)

    @field_validator("continuation_parent_id")
    @classmethod
    def canonical_parent(cls, value: str | None) -> str | None:
        return _uuid(value) if value is not None else None

    @model_validator(mode="after")
    def continuation_requires_identity(self):
        if self.continuation_parent_id is not None and self.reference is None:
            raise ValueError("Continuation requires the original identity reference")
        return self

    @field_validator("prompt", "model")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Must not be blank")
        return value


DEFAULT_EDITOR_SYSTEM = (
    "Turn the user's simple idea into a clear scene instruction in English. "
    "Preserve exact dialogue quotations in their requested language. "
    "Preserve the requested action, clothing, pose and order of changes; describe continuity "
    "concisely. Do not invent identity, appearance, actions or unrequested changes. "
    "Do not include explanations, titles, technical parameters, nodes, seed, duration, "
    "resolution, sampler or model settings. Respond only with the editable scene instruction, "
    "using at most 12000 characters. You edit text: you do not edit images or generate videos."
)
EDITOR_MAX_BYTES = 1024 * 1024
EDITOR_OUTPUT_TOKENS = 12_000
SCRIPT_OUTPUT_TOKENS = 20_000
FIXED_EDITOR_MODEL = "grok-4.20-0309-non-reasoning"


class EditPromptRequest(PromptRequest):
    target_run_id: str = Field(strict=True, max_length=36)

    @field_validator("target_run_id")
    @classmethod
    def canonical_target(cls, value: str) -> str:
        return _uuid(value)

    @model_validator(mode="after")
    def editing_requires_distinct_anchors(self):
        if self.reference is None or self.continuation_parent_id is None:
            raise ValueError("Editing requires identity and both accepted video anchors")
        if self.target_run_id == self.continuation_parent_id:
            raise ValueError("Editing anchors must be distinct accepted videos")
        return self


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
        absolute = root.absolute()
        if ".." in absolute.parts:
            raise ValueError("Project root must not contain traversal")
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        descriptors.append(directory)
        for name in absolute.parts[1:]:
            directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=directory)
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
        if (not S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_size > EDITOR_MAX_BYTES):
            raise ValueError("Invalid editor configuration file")
        raw = stream.read(EDITOR_MAX_BYTES + 1)
    if len(raw) > EDITOR_MAX_BYTES:
        raise ValueError("Editor configuration exceeds limit")
    return EditorConfig.model_validate_json(raw)


def persisted_editor(root: Path) -> EditorConfig | None:
    with editor_directory(root) as directory:
        return read_editor_file(directory)


def read_editor(root: Path) -> EditorConfig:
    return persisted_editor(root) or EditorConfig(system_prompt=DEFAULT_EDITOR_SYSTEM,
                                                  model=os.getenv("H3_GROK_MODEL", ""))


class EditorModelConflict(ValueError):
    """The public editor can change instructions, not a persisted model pin."""


def save_editor(root: Path, payload: EditorConfig) -> EditorConfig:
    with editor_directory(root, create=True) as directory:
        # A corrupt existing configuration is evidence, not permission to erase it.
        existing = read_editor_file(directory)
        if existing and existing.model:
            if "model" in payload.model_fields_set and payload.model != existing.model:
                raise EditorModelConflict("The persisted editor model is fixed")
            payload = payload.model_copy(update={"model": existing.model})
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


def seed_editor(root: Path) -> EditorConfig:
    """Explicit administrative action only: publish the approved pin without clobbering."""
    payload = EditorConfig(system_prompt=DEFAULT_EDITOR_SYSTEM, model=FIXED_EDITOR_MODEL)
    with editor_directory(root, create=True) as directory:
        existing = read_editor_file(directory)
        if existing is not None:
            return existing
        temporary = f".editor-{uuid4()}.part"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload.model_dump_json().encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, "editor.json", src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False)
            except FileExistsError:
                # Another explicit writer won; preserve and validate their exact config.
                os.unlink(temporary, dir_fd=directory)
                value = read_editor_file(directory)
                if value is None:
                    raise ValueError("Editor configuration disappeared during publication")
                return value
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
        finally:
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
    def __init__(self, manager: OAuthManager, model: str = "", *, root: Path | None = None):
        self.manager = manager
        self.model = model
        self.root = root

    async def complete(self, payload: PromptRequest, *, output_schema: dict | None = None,
                       schema_name: str = "h3_roteiro") -> dict:
        output_tokens = SCRIPT_OUTPUT_TOKENS if output_schema is not None else EDITOR_OUTPUT_TOKENS
        output_text = ({"format": {"type": "json_schema", "name": schema_name,
                                  "strict": True, "schema": output_schema}}
                       if output_schema is not None else None)
        model = payload.model or self.model
        try:
            config = await asyncio.to_thread(persisted_editor, self.root) if self.root else None
        except (ValueError, OSError):
            raise OAuthError("editor_storage_error", "Editor configuration is invalid or inaccessible.",
                             409) from None
        if config and config.model:
            if payload.model is not None and payload.model != config.model:
                raise OAuthError("model_fixed", "The persisted editor model cannot be overridden.",
                                 409)
            model = config.model
        if not model:
            raise OAuthError("model_required", "Set H3_GROK_MODEL or provide a catalog model.", 400)
        if payload.reference is not None:
            if self.root is None:
                raise OAuthError("invalid_reference", "No owned image root is configured.", 400)
            async with AsyncExitStack() as stack:
                try:
                    snapshot, mime = await stack.enter_async_context(
                        owned_image(self.root, payload.reference))
                except (ValueError, OSError, TimeoutError):
                    raise OAuthError("invalid_reference", "Reference is unowned, changed, corrupt or "
                                     "unsupported; use a published JPEG/PNG up to 20 MiB.", 400) from None
                if payload.continuation_parent_id is not None:
                    try:
                        frame, recheck, digest = await stack.enter_async_context(continuation_frame(
                            self.root, payload.continuation_parent_id, payload.reference))
                        if await _thread(snapshot_digest, snapshot) != digest:
                            raise ValueError("Frozen identity disagrees with parent")
                        images = [(snapshot, mime), (frame, "image/png")]
                        if isinstance(payload, EditPromptRequest):
                            target, target_recheck, target_digest = await stack.enter_async_context(
                                continuation_frame(self.root, payload.target_run_id,
                                                   payload.reference, edge="first"))
                            if target_digest != digest:
                                raise ValueError("Editing anchors disagree on original identity")
                            images.append((target, "image/png"))
                            await _thread(target_recheck)
                        await _thread(recheck)
                        if isinstance(payload, EditPromptRequest):
                            await _thread(target_recheck)
                    except (ValueError, OSError, TimeoutError, KeyError, TypeError):
                        raise OAuthError("invalid_continuation", "Parent is unaccepted, changed, "
                                         "unsafe or unsupported, or identity does not match.", 400) from None
                    body, length = images_json_body(model, payload.system_prompt, payload.prompt,
                                                    images,
                                                    output_text=output_text,
                                                    max_output_tokens=output_tokens)
                else:
                    body, length = image_json_body(model, payload.system_prompt, payload.prompt,
                                                   snapshot, mime, output_text=output_text,
                                                   max_output_tokens=output_tokens)
                # Provider/auth failures are not image-validation errors.
                return await self._submit(model, {"content": body}, length=length)
        messages = []
        if payload.system_prompt:
            messages.append({"role": "system", "content": payload.system_prompt})
        messages.append({"role": "user", "content": payload.prompt})
        body = {
            "model": model, "input": messages, "max_output_tokens": output_tokens,
            "stream": False, "store": False,
        }
        if output_text is not None:
            body["text"] = output_text
        return await self._submit(model, {"json": body})

    async def _submit(self, model: str, body: dict, *, length: int | None = None) -> dict:
        async with self.manager.client_factory() as client:
            tokens, models = await self.manager.authorized_models(client, recover=False)
            if not any(row["id"] == model for row in models):
                raise OAuthError("model_required", "Choose a model from /grok/auth/models.", 400)
            headers = {"Authorization": f"Bearer {tokens.access}",
                       "User-Agent": "H3-SuperGrok/0.1"}
            if length is not None:
                headers.update({"Content-Type": "application/json", "Content-Length": str(length)})
            # A rejected or uncertain inference is never replayed automatically.
            try:
                async with (
                    asyncio.timeout(120),
                    client.stream(
                        "POST", f"{BASE_URL}/responses",
                        headers=headers, **body,
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
                os.getenv("H3_GROK_MODEL", ""), root=root)
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


class ContinuationPreview(StreamingResponse):
    def __init__(self, snapshot, stack):
        self.snapshot_stack = stack
        super().__init__(encoded_chunks(snapshot), media_type="image/png", headers={
            "Cache-Control": "no-store", "Content-Length": str(os.fstat(snapshot.fileno()).st_size),
            "X-Content-Type-Options": "nosniff",
        })

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.snapshot_stack.aclose()


@router.get("/continuation/{parent_id}/last-frame")
async def last_frame_preview(parent_id: str, request: Request):
    # Preparation/validation completes before response headers; no OAuth or business API.
    stack = AsyncExitStack()
    try:
        frame, _, _ = await stack.enter_async_context(continuation_frame(
            request.app.state.grok_editor_root, parent_id))
        return ContinuationPreview(frame, stack)
    except (ValueError, OSError, TimeoutError, KeyError, TypeError):
        await stack.aclose()
        return reply({"error": "invalid_continuation", "detail":
                      "Parent is unaccepted, changed, unsafe or exceeds the editor budget."}, 400)
    except BaseException:
        await stack.aclose()
        raise


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
    except EditorModelConflict:
        return reply({"error": "model_fixed", "detail": "The persisted editor model is fixed."}, 409)
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
