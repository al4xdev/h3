import asyncio

import pytest

from h3_backend.models import CONTINUATION_PROMPT, ContinueRequest, RunRequest, Settings
from h3_backend.service import Conflict, RunService, output_source, verify_video

PROBE = {
    "streams": [
        {
            "codec_type": "video",
            "width": 480,
            "height": 864,
            "avg_frame_rate": "24/1",
            "duration": "2.333333",
            "nb_frames": "56",
        }
    ],
    "format": {"duration": "2.333333"},
}


class Media:
    def __init__(self):
        self.tails = []

    def verify_image(self, path):
        return {"width": 1024, "height": 1024, "format": "PNG"}

    async def probe(self, path):
        return PROBE

    async def prepare_last_frame(self, parent, destination):
        destination.write_bytes(b"exact-last-frame")
        return {"path": str(destination), "format": "PNG", "frame_index": 55}

    async def prepare_tail(
        self, parent, destination, seconds, include_audio=True, *, reference_frame_limit=None
    ):
        self.tails.append((parent, seconds, include_audio))
        destination.write_bytes(b"fake-tail")
        return {
            "path": str(destination),
            "actual_seconds": min(seconds, 56 / 24),
            "requested_seconds": seconds,
            "has_audio": include_audio,
            "width": 480,
            "height": 864,
        }


class Builder:
    hash = "baseline-sha"

    def __init__(self):
        self.calls = []

    def validate_object_info(self, info):
        assert info == {"fake": True}

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {"baseline": True}


class Comfy:
    def __init__(self, output):
        self.output = output
        self.submitted = []
        self.uploads = []
        self.gate = None

    async def ensure_idle(self):
        pass

    async def object_info(self):
        return {"fake": True}

    async def upload(self, path, name):
        self.uploads.append((path, name))
        return {
            "name": name,
            "subfolder": "unique",
            "filename": f"unique/{name} [input]",
            "type": "input",
        }

    async def execute(self, workflow, *, prompt_id, on_submitted, on_progress, **kwargs):
        self.submitted.append(prompt_id)
        await on_submitted(prompt_id)
        await on_progress({"value": 1, "max": 2, "prompt_id": prompt_id})
        if self.gate:
            await self.gate.wait()
        return {
            "outputs": {
                "18": {"gifs": [{"filename": "ignored.mp4", "type": "temp"}]},
                "34": {
                    "gifs": [
                        {
                            "filename": self.output.name,
                            "subfolder": "safe",
                            "type": "output",
                            "fullpath": "/untrusted/ignored",
                        }
                    ]
                },
            }
        }

    async def close(self):
        pass


async def telemetry(comfy, path, stop, **kwargs):
    await stop.wait()


def frames(seconds):
    if seconds > 2.9:
        raise ValueError("Aligned duration exceeds 3 seconds")
    return 56


def make_service(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "dance_reference.png").write_bytes(b"fake-image")
    output = tmp_path / "comfy" / "output" / "safe" / "final.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"fake-video")
    return RunService(
        Settings(project_root=tmp_path, comfy_root=tmp_path / "comfy"),
        media=Media(),
        comfy=Comfy(output),
        builder=Builder(),
        frames_for_duration=frames,
        telemetry=telemetry,
        memory_available=lambda: 8 * 1024**3,
    )


@pytest.mark.asyncio
async def test_publish_acceptance_gate_and_explicit_continuation(tmp_path):
    service = make_service(tmp_path)
    await service.startup()
    run = await service.create(RunRequest(seed=7))
    await service._task
    ready = service.store.get(run.id)
    assert ready.state == "ready_for_review"
    assert ready.prompt_id == service.comfy.submitted[0]
    assert ready.publication_mode == "atomic_copy_from_comfy_output"
    assert (service.store.directory(run.id) / "workflow_api.json").is_file()
    assert service.video_path(run.id).read_bytes() == b"fake-video"
    with pytest.raises(Conflict):
        await service.continue_run(run.id, ContinueRequest(seed=8))
    await service.decide(run.id, True)
    assert len(service.comfy.submitted) == 1  # acceptance itself never submits
    with pytest.raises(Conflict):
        await service.decide(run.id, False)
    child = await service.continue_run(run.id, ContinueRequest(seed=8, reference_tail_seconds=3))
    await service._task
    final = service.store.get(child.id)
    assert final.state == "ready_for_review" and final.parent_id == run.id
    assert final.prompt == CONTINUATION_PROMPT and final.seed == 8
    assert final.references[0]["role"] == "initial_frame"
    assert final.references[0]["sha256"] != ready.references[0]["sha256"]
    assert final.references[1]["sha256"] == ready.references[0]["sha256"]
    assert final.input_info["mode"] == "continuation"
    assert [slot["tag"] for slot in final.input_info["slot_map"]] == [
        "<Picture 1>", "<Picture 2>", "<Video 1>"
    ]
    assert (service.store.directory(child.id) / "prompt.md").read_text() == CONTINUATION_PROMPT
    tail = final.references[-1]
    assert tail["type"] == "video" and tail["has_audio"]
    assert tail["input_info"]["actual_seconds"] == 56 / 24
    assert tail["input_info"]["requested_seconds"] == 3
    assert tail["filename"].startswith("unique/") and tail["filename"].endswith(" [input]")
    assert len(service.builder.calls[1]["references"]) == 3
    await service.decide(child.id, True)
    grandchild = await service.continue_run(child.id, ContinueRequest(seed=9))
    await service._task
    descendant = service.store.get(grandchild.id)
    assert descendant.state == "ready_for_review"
    assert [r["role"] for r in descendant.references] == [
        "initial_frame", "identity", "motion_video"
    ]
    assert descendant.references[1]["source"] == "dance_reference.png"
    assert descendant.references[0]["parent_id"] == child.id
    await service.shutdown()


@pytest.mark.asyncio
async def test_rejected_parent_and_single_job(tmp_path):
    service = make_service(tmp_path)
    service.comfy.gate = asyncio.Event()
    run = await service.create(RunRequest(seed=1))
    with pytest.raises(Conflict):
        await service.create(RunRequest(seed=2))
    service.comfy.gate.set()
    await service._task
    await service.decide(run.id, False)
    with pytest.raises(Conflict):
        await service.continue_run(run.id, ContinueRequest(seed=3))
    await service.shutdown()


@pytest.mark.asyncio
async def test_paths_and_duration_rejected_before_job(tmp_path):
    service = make_service(tmp_path)
    (tmp_path / "assets" / "escape.png").symlink_to(tmp_path / "outside.png")
    (tmp_path / "outside.png").write_bytes(b"outside")
    for name in ("../outside.png", str(tmp_path / "outside.png"), "escape.png"):
        with pytest.raises(ValueError):
            await service.create(RunRequest(seed=1, image=name))
    with pytest.raises(ValueError):
        await service.create(RunRequest(seed=1, duration_seconds=3))
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_and_failure_cannot_be_accepted(tmp_path):
    service = make_service(tmp_path)
    service.comfy.gate = asyncio.Event()
    run = await service.create(RunRequest(seed=1))
    # Ensure execution started, then shut down without leaving pending work.
    await asyncio.sleep(0)
    await service.shutdown()
    assert service.store.get(run.id).state == "interrupted"
    with pytest.raises(Conflict):
        await service.decide(run.id, True)


def test_output_source_and_ffprobe_constraints(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "good.mp4").write_bytes(b"clip")
    history = {
        "outputs": {
            "34": {
                "gifs": [
                    {
                        "filename": "good.mp4",
                        "subfolder": "",
                        "type": "output",
                        "fullpath": "/wrong",
                    }
                ]
            }
        }
    }
    assert output_source(history, tmp_path) == output / "good.mp4"
    history["outputs"]["34"]["gifs"][0]["subfolder"] = "../"
    with pytest.raises(ValueError):
        output_source(history, tmp_path)
    (output / "symlink.mp4").symlink_to(tmp_path / "secret.mp4")
    (tmp_path / "secret.mp4").write_bytes(b"secret")
    history["outputs"]["34"]["gifs"][0].update(filename="symlink.mp4", subfolder="")
    with pytest.raises(ValueError):
        output_source(history, tmp_path)
    verify_video(PROBE, 56)
    with pytest.raises(ValueError):
        verify_video(PROBE, 73)
    wrong = {"streams": [{**PROBE["streams"][0], "duration": "3.041667"}]}
    with pytest.raises(ValueError):
        verify_video(wrong, 56)


@pytest.mark.asyncio
async def test_low_memory_preflight_and_running_guard(tmp_path):
    service = make_service(tmp_path)
    available = [0]
    service.memory_available = lambda: available[0]
    with pytest.raises(Conflict, match="RAM"):
        await service.create(RunRequest(seed=1))
    assert not service.comfy.submitted
    available[0] = 8 * 1024**3
    service.comfy.gate = asyncio.Event()
    run = await service.create(RunRequest(seed=1))
    available[0] = 0
    with pytest.raises(asyncio.CancelledError):
        await service._task
    final = service.store.get(run.id)
    assert final.state == "interrupted" and final.prompt_id is not None
    assert "RAM dropped" in final.error
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_telemetry_failure_is_recorded_not_silent(tmp_path):
    service = make_service(tmp_path)

    async def broken_telemetry(*args, **kwargs):
        raise RuntimeError("fake recording failure")

    service.telemetry = broken_telemetry
    run = await service.create(RunRequest(seed=1))
    await service._task
    assert (service.store.directory(run.id) / "telemetry_error.json").is_file()
    assert "fake recording failure" in service.store.get(run.id).input_info["telemetry_error"]
    await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_before_background_task_started(tmp_path):
    service = make_service(tmp_path)
    run = await service.create(RunRequest(seed=1))
    await service.shutdown()
    assert service.store.get(run.id).state == "interrupted"
    assert not service.comfy.submitted


@pytest.mark.asyncio
async def test_canceled_http_wait_preserves_execution_task(tmp_path):
    service = make_service(tmp_path)
    service.comfy.gate = asyncio.Event()
    run = await service.create(RunRequest(seed=1))
    waiter = asyncio.create_task(service.wait_run(run.id))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not service._task.cancelled() and not service._task.done()
    service.comfy.gate.set()
    final = await service.wait_run(run.id)
    assert final.state == "ready_for_review"
    await service.shutdown()
