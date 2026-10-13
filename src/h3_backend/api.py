"""Local path bridge. Reads, uploads, subscriptions and startup never submit inference."""

import asyncio
import json
import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .generation.assembly import router as assembly_router
from .generation.dispatcher import Conflict, RunService
from .generation.i2v import router as i2v_router
from .generation.models import CONTINUATION_PROMPT, DEFAULT_PROMPT, Run, Settings
from .generation.v2v import router as v2v_router
from .generation.workflow import DEFAULT_DURATION_SECONDS, duration_capabilities
from .grok import router as grok_router
from .infrastructure.comfy import QueueBusy
from .infrastructure.media import sha256_file, verify_image
from .infrastructure.store import IMAGE_NAMES, IMAGE_TYPES, safe_path, storage_guard
from .library import router as library_router
from .roteiro import router as roteiro_router

WEB_ROOT = Path(__file__).with_name("web")
MAX_INPUT_BYTES = 32 * 1024**2
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
    "media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


def same_origin(origin: str, request: Request) -> bool:
    try:
        value, expected = urlsplit(origin), urlsplit(str(request.url))
        return (
            value.scheme in {"http", "https"} and value.username is None and value.password is None
            and value.path in {"", "/"} and not value.query and not value.fragment
            and (value.scheme, value.hostname, value.port if value.port is not None else (443 if value.scheme == "https" else 80))
            == (expected.scheme, expected.hostname,
                expected.port if expected.port is not None else (443 if expected.scheme == "https" else 80))
        )
    except ValueError:
        return False


def create_app(*, settings: Settings | None = None, service: RunService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or RunService(settings or Settings.from_env())
        await app.state.service.startup()
        try:
            yield
        finally:
            await app.state.service.shutdown()

    app = FastAPI(title="H3 local", lifespan=lifespan)
    app.include_router(grok_router)
    app.include_router(roteiro_router)
    app.include_router(library_router)
    app.include_router(assembly_router)
    if service is not None:
        app.state.service = service

    def backend() -> RunService:
        return app.state.service

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin is not None and not same_origin(origin, request):
            response = JSONResponse(status_code=403, content={"detail": "Mutation requires same origin"})
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(Conflict)
    @app.exception_handler(QueueBusy)
    @app.exception_handler(FileExistsError)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def missing_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Run or reference not found"})

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/")
    @app.get("/index")
    @app.get("/roteiro")
    def index():
        return FileResponse(safe_path(WEB_ROOT, "index.html"), media_type="text/html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    @app.get("/ui/{filename}")
    def ui_asset(filename: str):
        types = {"app.css": "text/css", "app.js": "text/javascript"}
        if filename not in types:
            raise FileNotFoundError(filename)
        return FileResponse(safe_path(WEB_ROOT, filename), media_type=types[filename])

    @app.get("/app/config")
    def app_config():
        current = getattr(backend(), "settings", settings or Settings())
        return {
            "default_prompt": DEFAULT_PROMPT, "continuation_prompt": CONTINUATION_PROMPT,
            "reference_image": "dance_reference.png", "duration_seconds": DEFAULT_DURATION_SECONDS,
            "workflow_output_profile": current.workflow_output_profile,
            "duration_capabilities": duration_capabilities(),
            "filesystem_events": getattr(backend(), "watcher", None) is not None,
            "reference_library": True, "assembly_enabled": True,
            "roteiro_enabled": True,
        }

    @app.get("/runs")
    def list_runs(limit: str = Query(default="50", max_length=5), offset: str = Query(default="0", max_length=5)):
        if not all(value.isascii() and value.isdecimal() for value in (limit, offset)):
            raise ValueError("Metadata pagination requires unsigned integers")
        limit, offset = int(limit), int(offset)
        runs, total = backend().store.list_runs(limit=limit, offset=offset)
        items = []
        for run in runs:
            url = None
            if run.state in {"ready_for_review", "accepted", "rejected"}:
                path = backend().store.own_artifact(
                    run.id, run.output.get("path", backend().store.relative_artifact(run.id, "chunk.mp4")),
                    "chunk.mp4",
                )
                if path.is_file():
                    url = f"/runs/{run.id}/video"
            items.append({
                **{key: getattr(run, key) for key in (
                    "id", "state", "prompt", "seed", "duration_seconds", "created_at", "updated_at", "parent_id",
                )}, "video_url": url,
            })
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.get("/inputs")
    def list_inputs(limit: str = Query(default="50", max_length=5), offset: str = Query(default="0", max_length=5)):
        if not all(value.isascii() and value.isdecimal() for value in (limit, offset)):
            raise ValueError("Metadata pagination requires unsigned integers")
        limit, offset = int(limit), int(offset)
        items, total = backend().store.list_inputs(limit=limit, offset=offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.post("/inputs", status_code=201)
    async def upload_input(request: Request, name: str = Query(default="uploaded image", max_length=512)):
        store = backend().store
        # Keep the shared storage lease through streaming and validation, including fixture clients
        # that omit application lifespan. This does not create an inference admission/slot.
        with storage_guard(store.root):
            input_id, part = await asyncio.to_thread(store.reserve_input)
            fd = os.open(part, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                os.close(fd)
                raise ValueError("Upload sink must be an own regular file")
            total = 0
            with os.fdopen(fd, "wb") as stream:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_INPUT_BYTES:
                        raise HTTPException(status_code=413, detail="Image exceeds 32 MiB upload limit")
                    # ASGI may deliver a large network chunk; writes remain fixed-size without copying it.
                    view = memoryview(chunk)
                    for offset in range(0, len(view), 65536):
                        await asyncio.to_thread(stream.write, view[offset:offset + 65536])
                await asyncio.to_thread(stream.flush)
                await asyncio.to_thread(os.fsync, stream.fileno())
            if total == 0:
                raise ValueError("Image upload cannot be empty")
            info = await asyncio.to_thread(verify_image, part)
            digest = await asyncio.to_thread(sha256_file, part)
            return await asyncio.to_thread(store.publish_input, input_id, name, info, digest)

    @app.get("/inputs/image")
    def input_image(path: str = Query(min_length=1, max_length=1024)):
        image = backend().store.reference_path("inputs", path)
        return FileResponse(image, media_type=IMAGE_TYPES[image.suffix.lower()], content_disposition_type="inline")

    @app.get("/assets/image")
    def asset_image(path: str = Query(min_length=1, max_length=1024)):
        image = backend().store.reference_path("assets", path)
        return FileResponse(image, media_type=IMAGE_TYPES[image.suffix.lower()], content_disposition_type="inline")

    @app.get("/events")
    async def events():
        watcher = getattr(backend(), "watcher", None)
        if watcher is None:
            raise HTTPException(status_code=503, detail="Filesystem observer is not running")

        async def hints():
            source = watcher.events()
            try:
                async for path in source:
                    data = json.dumps({"path": path, "invalidation": True}, ensure_ascii=True)
                    yield f"event: change\ndata: {data}\n\n"
            finally:
                close = getattr(source, "aclose", None)
                if close is not None:
                    await close()

        return StreamingResponse(hints(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })

    app.include_router(i2v_router)
    app.include_router(v2v_router)

    @app.get("/runs/{run_id}", response_model=Run)
    async def get_run(run_id: str, wait: bool = False):
        return await backend().wait_run(run_id) if wait else backend().store.get(run_id)

    @app.get("/runs/{run_id}/video")
    async def get_video(run_id: str):
        return FileResponse(backend().video_path(run_id), media_type="video/mp4", filename="chunk.mp4")

    @app.get("/runs/{run_id}/image")
    def run_image(run_id: str, name: str = Query()):
        if name not in IMAGE_NAMES:
            raise ValueError("Only own initial_frame.png or last_frame.png can be served")
        source = backend().store.relative_artifact(run_id, name)
        image = backend().store.reference_path("runs", source)
        return FileResponse(image, media_type="image/png", content_disposition_type="inline")

    @app.post("/runs/{run_id}/accept", response_model=Run)
    async def accept_run(run_id: str):
        return await backend().decide(run_id, True)

    @app.post("/runs/{run_id}/reject", response_model=Run)
    async def reject_run(run_id: str):
        return await backend().decide(run_id, False)

    @app.get("/runs/{run_id}/sequence")
    def get_sequence(run_id: str):
        return backend().store.sequence(run_id)

    return app


app = create_app()
