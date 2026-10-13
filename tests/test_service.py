import asyncio
import hashlib
from dataclasses import replace

import pytest

from h3_backend.generation.dispatcher import Conflict, RunService, output_source, verify_video
from h3_backend.generation.models import CONTINUATION_PROMPT, ContinueRequest, RunRequest, Settings

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
    def __init__(self):
        self.calls = []
        self.validations = []

    def hash_for(self, operation):
        return {"i2v": "baseline-sha", "v2v": "anchored-sha"}[operation]

    def provenance(self, operation):
        return {
            "canonical_template_sha256": "canonical-sha",
            "operation": operation,
            "config": {"operation": operation, "guide_frame_zero": operation == "v2v"},
        }

    def validate_object_info(self, info, *, operation):
        assert info == {"fake": True}
        self.validations.append(operation)

    def build(self, **kwargs):
        assert kwargs["operation"] in {"i2v", "v2v"}
        self.calls.append(kwargs)
        return {"operation": kwargs["operation"], "seed": kwargs["seed"]}


class Comfy:
    def __init__(self, output):
        self.output = output
        self.submitted = []
        self.uploads = []
        self.gate = None
        self.submitted_event = None

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
        if self.submitted_event is not None:
            self.submitted_event.set()
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
    from h3_backend.generation.workflow import frames_for_duration

    return frames_for_duration(seconds)


def make_service(tmp_path, *, memory_available=None):
    if memory_available is None:
        def memory_available():
            pytest.fail("Dispatcher must not consult a host RAM policy sensor")

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
        memory_available=memory_available,
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
    assert ready.workflow_hash == "baseline-sha"
    assert ready.input_info["operation"] == "i2v"
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
    assert final.workflow_hash == "anchored-sha"
    assert final.input_info["operation"] == "v2v"
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
    assert service.builder.validations == ["i2v", "v2v", "v2v"]
    assert [call["operation"] for call in service.builder.calls] == ["i2v", "v2v", "v2v"]
    for generated in (ready, final, descendant):
        artifact = service.store.directory(generated.id) / "workflow_api.json"
        assert generated.input_info["workflow_api_sha256"] == hashlib.sha256(
            artifact.read_bytes()
        ).hexdigest()
        assert generated.input_info["workflow_api_sha256"] != generated.workflow_hash
        assert generated.input_info["workflow_provenance"] == service.builder.provenance(
            generated.input_info["operation"]
        )
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
        await service.create(RunRequest(seed=1, duration_seconds=10.01))
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
@pytest.mark.parametrize("operation", ["i2v", "v2v"])
@pytest.mark.parametrize("sensor_raises", [False, True])
async def test_ram_sensor_ignored_at_admission_and_during_owned_job(tmp_path, operation, sensor_raises):
    available = [0]
    consulted = []

    def sensor():
        consulted.append(True)
        if sensor_raises:
            raise RuntimeError("Host RAM sensor unavailable")
        return available[0]

    service = make_service(tmp_path, memory_available=sensor)
    parent = None
    if operation == "v2v":
        parent = await service.create(RunRequest(seed=1))
        await service._task
        await service.decide(parent.id, True)

    async def create():
        if operation == "v2v":
            return await service.continue_run(parent.id, ContinueRequest(seed=2))
        return await service.create(RunRequest(seed=2))

    submitted = len(service.comfy.submitted)
    service.settings = replace(service.settings, memory_check_interval=0.001)
    service.comfy.gate = asyncio.Event()
    service.comfy.submitted_event = asyncio.Event()
    run = await create()
    await asyncio.wait_for(service.comfy.submitted_event.wait(), timeout=2)
    available[0] = 8 * 1024**3
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(service.comfy.gate.wait(), timeout=0.02)
    available[0] = 0
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(service.comfy.gate.wait(), timeout=0.02)
    assert not service._task.done() and service._active == run.id
    assert consulted == []
    service.comfy.gate.set()
    await service._task
    final = service.store.get(run.id)
    assert final.state == "ready_for_review" and final.prompt_id is not None
    assert final.error is None and consulted == []
    assert len(service.comfy.submitted) == submitted + 1
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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["i2v", "v2v"])
async def test_operations_share_global_slot(tmp_path, operation):
    service = make_service(tmp_path)
    parent = await service.create(RunRequest(seed=1))
    await service._task
    await service.decide(parent.id, True)
    service.comfy.gate = asyncio.Event()
    if operation == "i2v":
        active = await service.create(RunRequest(seed=2))
        with pytest.raises(Conflict, match="one backend job"):
            await service.continue_run(parent.id, ContinueRequest(seed=3))
    else:
        active = await service.continue_run(parent.id, ContinueRequest(seed=2))
        with pytest.raises(Conflict, match="one backend job"):
            await service.create(RunRequest(seed=3))
    assert service._active == active.id
    service.comfy.gate.set()
    await service._task
    assert len(service.comfy.submitted) == 2
    await service.shutdown()


@pytest.mark.asyncio
async def test_i2v_never_prepares_parent_media(tmp_path, monkeypatch):
    service = make_service(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("i2v must not access a parent or prepare continuation media")

    monkeypatch.setattr(service, "video_path", forbidden)
    monkeypatch.setattr(service.media, "prepare_last_frame", forbidden)
    monkeypatch.setattr(service.media, "prepare_tail", forbidden)
    run = await service.create(RunRequest(seed=1))
    await service._task
    assert service.store.get(run.id).state == "ready_for_review"
    assert service.builder.calls[0]["operation"] == "i2v"
    assert [ref["role"] for ref in service.builder.calls[0]["references"]] == ["identity"]
    await service.shutdown()


@pytest.mark.asyncio
async def test_v2v_ignores_low_memory_but_preserves_shutdown_guard(tmp_path):
    service = make_service(tmp_path)
    parent = await service.create(RunRequest(seed=1))
    await service._task
    await service.decide(parent.id, True)
    service.memory_available = lambda: 0
    child = await service.continue_run(parent.id, ContinueRequest(seed=2))
    await service.shutdown()
    assert service.store.get(child.id).state == "interrupted"
    assert len(service.comfy.submitted) == 1
    with pytest.raises(Conflict):
        await service.create(RunRequest(seed=3))
    with pytest.raises(Conflict):
        await service.continue_run(parent.id, ContinueRequest(seed=3))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["i2v", "v2v"])
async def test_identity_mutation_after_admission_fails_without_submission(tmp_path, operation):
    service = make_service(tmp_path)
    if operation == "v2v":
        parent = await service.create(RunRequest(seed=1))
        await service._task
        await service.decide(parent.id, True)
        run = await service.continue_run(parent.id, ContinueRequest(seed=2))
    else:
        run = await service.create(RunRequest(seed=1))
    submitted = len(service.comfy.submitted)
    (tmp_path / "assets" / "dance_reference.png").write_bytes(b"changed-image")
    await service._task
    result = service.store.get(run.id)
    assert result.state == "failed" and "changed after admission" in result.error
    assert len(service.comfy.submitted) == submitted
    assert service._active is None
    await service.shutdown()
