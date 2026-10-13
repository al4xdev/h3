import asyncio
import threading
from uuid import uuid4

import httpx
import pytest
from test_service import make_service

from h3_backend.api import create_app
from h3_backend.generation.dispatcher import Conflict
from h3_backend.generation.models import RunRequest


async def running(service):
    service.comfy.gate = asyncio.Event()
    service.comfy.submitted_event = asyncio.Event()
    run = await service.create(RunRequest(seed=42, duration_seconds=2.3))
    await service.comfy.submitted_event.wait()
    return run


async def test_stop_preserves_request_and_cancels_only_owned_task(tmp_path):
    service = make_service(tmp_path)
    try:
        run = await running(service)
        request = (service.store.directory(run.id) / "request.json").read_bytes()
        with pytest.raises(FileNotFoundError):
            await service.stop_run(str(uuid4()))
        assert not service._task.done()
        stopped = await service.stop_run(run.id)
        assert stopped.state == "interrupted" and "User requested stop" in stopped.error
        assert service.comfy.submitted == [stopped.prompt_id]
        assert (service.store.directory(run.id) / "request.json").read_bytes() == request
        assert service._active is None
        with pytest.raises(Conflict):
            await service.stop_run(run.id)
    finally:
        await service.shutdown()


async def test_stop_before_worker_starts_never_submits_gpu(tmp_path):
    service = make_service(tmp_path)
    try:
        run = await service.create(RunRequest(seed=42, duration_seconds=2.3))
        stopped = await service.stop_run(run.id)
        assert stopped.state == "interrupted"
        assert service.comfy.submitted == [] and service._active is None
    finally:
        await service.shutdown()


async def test_stop_finishes_after_http_waiter_disconnects(tmp_path):
    service = make_service(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    execute = service.comfy.execute

    async def delayed_cleanup(*args, **kwargs):
        try:
            return await execute(*args, **kwargs)
        finally:
            entered.set()
            await release.wait()

    service.comfy.execute = delayed_cleanup
    try:
        run = await running(service)
        waiter = asyncio.create_task(service.stop_run(run.id))
        await entered.wait()
        with pytest.raises(Conflict, match="already requested"):
            await service.stop_run(run.id)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert service._stop_tasks
        release.set()
        await asyncio.gather(*service._stop_tasks)
        assert service.store.get(run.id).state == "interrupted"
        assert service._active is None and not service._stop_requested
    finally:
        release.set()
        await service.shutdown()


async def test_http_stop_body_origin_and_target_validation(tmp_path):
    service = make_service(tmp_path)
    app = create_app(service=service)
    try:
        run = await running(service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            path = f"/runs/{run.id}/stop"
            assert (await client.post(path, json={"run_id": run.id})).status_code == 400
            assert (await client.post(path, json={}, headers={"Origin": "http://other"})).status_code == 403
            assert (await client.post(f"/runs/{uuid4()}/stop", json={})).status_code == 404
            result = await client.post(path, json={})
            assert result.status_code == 200
            assert result.json()["id"] == run.id and result.json()["state"] == "interrupted"
            assert (await client.post(path, json={})).status_code == 409
            assert (await client.get("/roteiro-batches/current")).json() == {"batch": None}
    finally:
        await service.shutdown()


@pytest.mark.parametrize("operation", ["i2v", "v2v"])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_stop_joins_publication_before_releasing_own_slot(tmp_path, monkeypatch, operation, shutdown):
    from h3_backend.generation import i2v, v2v
    from h3_backend.generation.models import ContinueRequest

    service = make_service(tmp_path)
    parent = None
    if operation == "v2v":
        root = await service.create(RunRequest(seed=1, duration_seconds=2.3))
        await service.wait_run(root.id)
        parent = await service.decide(root.id, True)
    module = i2v if operation == "i2v" else v2v
    publish = module.publish
    entered, release = threading.Event(), threading.Event()
    stopping = asyncio.Event()
    finish = service._finish_stop

    def delayed_publish(source, destination):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Publication fixture was not released")
        publish(source, destination)

    async def finish_stop(run_id, task):
        stopping.set()
        return await finish(run_id, task)

    monkeypatch.setattr(module, "publish", delayed_publish)
    monkeypatch.setattr(service, "_finish_stop", finish_stop)
    try:
        request = (ContinueRequest(seed=42, duration_seconds=2.3) if parent else
                   RunRequest(seed=42, duration_seconds=2.3))
        run = (await service.continue_run(parent.id, request) if parent else
               await service.create(request))
        assert await asyncio.to_thread(entered.wait, 5)
        if shutdown:
            waiter = asyncio.create_task(service.shutdown())
            while not service._closing:
                await asyncio.sleep(0)
            with pytest.raises(Conflict, match="shutting down"):
                await service.stop_run(run.id)
        else:
            waiter = asyncio.create_task(service.stop_run(run.id))
            await stopping.wait()
        assert service._active == run.id and not service._task.done()
        assert not waiter.done()
        release.set()
        result = await waiter
        assert service.store.get(run.id).state == "interrupted" and service._active is None
        if not shutdown:
            assert result.state == "interrupted"
        assert service._task.done()
        assert (service.store.directory(run.id) / "chunk.mp4").read_bytes() == b"fake-video"
        if parent:
            assert service.store.get(parent.id).state == "accepted"
    finally:
        release.set()
        await service.shutdown()
