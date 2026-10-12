"""Minimal HTTP interface. Starting the server never submits a Comfy job."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .generation.dispatcher import Conflict, RunService
from .generation.i2v import router as i2v_router
from .generation.models import Run, Settings
from .generation.v2v import router as v2v_router
from .infrastructure.comfy import QueueBusy


def create_app(*, settings: Settings | None = None, service: RunService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or RunService(settings or Settings.from_env())
        await app.state.service.startup()
        try:
            yield
        finally:
            await app.state.service.shutdown()

    app = FastAPI(title="H3 backend", lifespan=lifespan)
    if service is not None:
        app.state.service = service

    def backend() -> RunService:
        return app.state.service

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(QueueBusy)
    async def queue_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def missing_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Run or reference not found"})

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(i2v_router)
    app.include_router(v2v_router)

    @app.get("/runs/{run_id}", response_model=Run)
    async def get_run(run_id: str, wait: bool = False):
        return await backend().wait_run(run_id) if wait else backend().store.get(run_id)

    @app.get("/runs/{run_id}/video")
    async def get_video(run_id: str):
        return FileResponse(
            backend().video_path(run_id), media_type="video/mp4", filename="chunk.mp4"
        )

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
