from uuid import uuid4

import httpx
import pytest

from h3_backend.api import create_app
from h3_backend.models import Run
from h3_backend.service import Conflict
from h3_backend.store import Store, timestamp


class Service:
    def __init__(self, root):
        self.store = Store(root)
        self.calls = []
        self.pipes = []

    async def submit(self, pipe):
        from h3_backend.routes.i2v import I2VPipe
        from h3_backend.routes.v2v import V2VPipe

        self.pipes.append(pipe)
        if isinstance(pipe, I2VPipe):
            return await self.create(pipe.state.request)
        assert isinstance(pipe, V2VPipe)
        return await self.continue_run(pipe.state.parent_id, pipe.state.request)

    async def create(self, request):
        self.calls.append(request)
        now = timestamp()
        return self.store.create(
            Run(
                id=str(uuid4()),
                created_at=now,
                updated_at=now,
                seed=request.seed,
                prompt=request.prompt,
                duration_seconds=request.duration_seconds,
                workflow_hash="fake",
            )
        )

    async def decide(self, run_id, accepted):
        if self.store.get(run_id).state != "ready_for_review":
            raise Conflict("Only ready clips can be decided")
        return self.store.update(
            run_id, state="accepted" if accepted else "rejected", decision={"accepted": accepted}
        )

    async def continue_run(self, run_id, request):
        if self.store.get(run_id).state != "accepted":
            raise Conflict("Parent is not accepted")
        self.calls.append(request)
        return self.store.get(run_id)

    def video_path(self, run_id):
        if self.store.get(run_id).state not in {"ready_for_review", "accepted", "rejected"}:
            raise Conflict("Video not ready")
        return self.store.directory(run_id) / "chunk.mp4"


@pytest.mark.asyncio
async def test_http_validation_gate_and_video(tmp_path):
    service = Service(tmp_path)
    app = create_app(service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fake"
    ) as client:
        for payload in (
            {},
            {"seed": "7"},
            {"seed": True},
            {"seed": 7, "duration_seconds": 4},
            {"seed": 7, "parent_id": "hidden"},
        ):
            assert (await client.post("/runs", json=payload)).status_code == 422
        response = await client.post("/runs", json={"seed": 7})
        assert response.status_code == 202
        run = response.json()
        run_id = run["id"]
        assert run["state"] == "queued" and run["duration_seconds"] == 2.3
        assert "<Picture 1>" in run["prompt"]
        assert (await client.get(f"/runs/{run_id}")).json()["seed"] == 7
        assert (await client.post(f"/runs/{run_id}/accept")).status_code == 409
        assert (await client.post(f"/runs/{run_id}/continue", json={"seed": 8})).status_code == 409
        assert (
            await client.post(
                f"/runs/{run_id}/continue", json={"seed": 8, "reference_tail_seconds": 1}
            )
        ).status_code == 422
        service.store.update(run_id, state="running")
        service.store.update(run_id, state="ready_for_review")
        (service.store.directory(run_id) / "chunk.mp4").write_bytes(b"fake-clip")
        assert (await client.get(f"/runs/{run_id}/video")).content == b"fake-clip"
        assert (await client.post(f"/runs/{run_id}/accept")).json()["state"] == "accepted"
        assert len(service.calls) == 1
        assert (await client.post(f"/runs/{run_id}/reject")).status_code == 409
        assert (await client.post(f"/runs/{run_id}/continue", json={"seed": 8})).status_code == 202
        assert len(service.calls) == 2
        assert (await client.get(f"/runs/{uuid4()}")).status_code == 404
        assert (await client.get("/runs/not-a-uuid")).status_code == 400
