"""Real ASGI lifecycle with pytest-owned paths and inert provider boundaries."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from test_roteiro import fields, setup
from test_roteiro_batch import FakeEnhancer, consent
from test_service import Builder, Comfy, Media, frames, telemetry

from h3_backend.api import create_app
from h3_backend.generation.dispatcher import RunService
from h3_backend.generation.models import Settings
from h3_backend.roteiro import CreatePlan
from h3_backend.roteiro_batch import RoteiroBatch


def create_fixture():
    root = Path(os.environ["H3_SHUTDOWN_TEST_ROOT"])
    service, roteiro = setup(root)
    service.comfy.gate = asyncio.Event()
    service.comfy.submitted_event = asyncio.Event()
    app = create_app(service=service)
    original_batch_startup = RoteiroBatch.startup
    original_batch_shutdown = RoteiroBatch.shutdown
    original_shutdown = service.shutdown
    batch_id = str(uuid4())
    plan_id = None

    async def startup(batch):
        nonlocal plan_id
        await original_batch_startup(batch)
        if batch.service is not service:
            return
        batch.grok = FakeEnhancer()
        document = await roteiro.create(CreatePlan(**fields()))
        plan_id = document["id"]
        await batch.start(plan_id, batch_id, consent())
        await asyncio.wait_for(service.comfy.submitted_event.wait(), 3)

    async def batch_shutdown(batch):
        await original_batch_shutdown(batch)
        if os.environ.get("H3_SHUTDOWN_TEST_BATCH_ERROR") == "1":
            raise RuntimeError("injected batch cleanup failure")

    async def shutdown():
        await original_shutdown()
        batch = app.state.roteiro_batch
        result = {
            "watcher_closed": service.watcher.fd is None,
            "runtime_released": service.store._runtime_lock is None,
            "observer_done": service._observer_task.done(),
            "generation_done": service._task.done(),
            "run_state": service.store.get(batch.get(plan_id, batch_id)["current_run_id"]).state,
            "batch_state": batch.get(plan_id, batch_id)["state"],
            "submissions": len(service.comfy.submitted),
            "enhancements": len(batch.grok.calls),
        }
        restart = RunService(
            Settings(project_root=root, comfy_root=root / "comfy"),
            media=Media(), comfy=Comfy(service.comfy.output), builder=Builder(),
            frames_for_duration=frames, telemetry=telemetry,
        )
        await restart.startup()
        recovered = RoteiroBatch(restart, FakeEnhancer())
        await original_batch_startup(recovered)
        await asyncio.sleep(0)
        result.update(
            restart_submissions=len(restart.comfy.submitted),
            restart_enhancements=len(recovered.grok.calls),
            restart_batch_task=recovered.task is not None,
            restart_run_state=restart.store.get(batch.get(plan_id, batch_id)["current_run_id"]).state,
            restart_batch_state=recovered.get(plan_id, batch_id)["state"],
        )
        await original_batch_shutdown(recovered)
        await restart.shutdown()
        (root / "cleanup.json").write_text(json.dumps(result))

    RoteiroBatch.startup = startup
    RoteiroBatch.shutdown = batch_shutdown
    service.shutdown = shutdown

    @app.get("/shutdown-test-ready")
    def ready():
        return {"active": service._active is not None,
                "subscribers": len(service.watcher._subscribers)}

    return app
