"""Operational duration policy: native graphs and fake publication, never GPU inference."""

import math
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_file_worker import admitted
from test_service import PROBE, make_service

from h3_backend.generation.dispatcher import verify_video
from h3_backend.generation.i2v import I2VPipe
from h3_backend.generation.models import ContinueRequest, RunRequest, Settings
from h3_backend.generation.v2v import V2VPipe
from h3_backend.generation.workflow import (
    WorkflowBuilder,
    duration_capabilities,
    frames_for_duration,
)

ROOT = Path(__file__).resolve().parents[1]


def probe(frames):
    return {"streams": [{**PROBE["streams"][0], "duration": str(frames / 24),
                         "nb_frames": str(frames)}]}


@pytest.mark.parametrize("seconds,frames", [(0.01, 5), (2.3, 56), (2.8, 73), (3, 73),
                                           (5, 124), (8, 192), (10, 243)])
def test_request_and_formula_domain(seconds, frames):
    for cls in (RunRequest, ContinueRequest):
        assert cls(seed=1, duration_seconds=seconds).duration_seconds == seconds
        assert cls(seed=1).duration_seconds == 8
    assert frames_for_duration(seconds) == frames


@pytest.mark.parametrize("seconds", [0, -1, math.nan, math.inf, -math.inf,
                                     math.nextafter(10, math.inf), 10.01])
def test_all_request_bounds(seconds):
    for cls in (RunRequest, ContinueRequest):
        with pytest.raises(ValueError):
            cls(seed=1, duration_seconds=seconds)
    with pytest.raises(ValueError):
        frames_for_duration(seconds)


@pytest.mark.parametrize("raw,frames", [(22.5, 22), (39.5, 56), (56.5, 56), (73.5, 90)])
def test_python_half_even_alignment_and_neighbor_boundary(raw, frames):
    assert frames_for_duration(raw / 24) == frames
    # Values on both sides are independently compared with the frozen expression.
    for value in (math.nextafter(raw / 24, 0), raw / 24, math.nextafter(raw / 24, math.inf)):
        r = max(5, round(value * 24))
        assert frames_for_duration(value) == r + (5 - r % 17) % 17


def test_capabilities_are_derived_and_return_fresh_values():
    caps = duration_capabilities()
    assert caps["default_requested_seconds"] == 8
    assert caps["max_frames"] == frames_for_duration(caps["max_requested_seconds"]) == 243
    assert caps["max_actual_seconds"] == 10.125
    caps["max_frames"] = 1
    assert duration_capabilities()["max_frames"] == 243
    settings = Settings()
    assert settings.inference_deadline == 1200
    assert settings.minimum_available_bytes == 1536 * 1024**2
    assert settings.memory_check_interval == 5


@pytest.mark.parametrize("seconds", [2.8, 3, 5, 10])
def test_aligned_output_not_capped_at_requested_seconds(seconds):
    frames = frames_for_duration(seconds)
    verify_video(probe(frames), frames)
    rounded = probe(frames)
    rounded["streams"][0]["duration"] = f"{frames / 24:.6f}"
    verify_video(rounded, frames)


@pytest.mark.parametrize("mutation", ["duration", "nan", "inf", "zero", "negative", "fps",
                                      "width", "height", "frames", "streams"])
def test_long_output_still_fails_closed(mutation):
    info = probe(243)
    video = info["streams"][0]
    if mutation in {"duration", "nan", "inf", "zero", "negative"}:
        video["duration"] = {"duration": "10", "nan": "nan", "inf": "inf",
                             "zero": "0", "negative": "-1"}[mutation]
    elif mutation == "fps":
        video["avg_frame_rate"] = "25/1"
    elif mutation in {"width", "height"}:
        video[mutation] = 512
    elif mutation == "frames":
        video["nb_frames"] = "242"
    else:
        info["streams"].append(deepcopy(video))
    with pytest.raises(ValueError):
        verify_video(info, 243)


@pytest.mark.parametrize("frames", [0, 4, 6, 242, 244, 260])
def test_output_expected_frames_bound_is_derived(frames):
    with pytest.raises(ValueError):
        verify_video(probe(frames), frames)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["i2v", "v2v"])
@pytest.mark.parametrize("seconds", [3, 5, 10])
async def test_long_hydration_is_pure_and_preserves_snapshot(tmp_path, monkeypatch, operation, seconds):
    service = make_service(tmp_path)
    request = ContinueRequest(seed=17, duration_seconds=seconds)
    run = admitted(service, operation=operation, seed=17, continuation=request,
                   parent_id=str(uuid4()) if operation == "v2v" else None)
    service.store.create(run, materialize_request=True)
    snapshot = service.store.request(run.id)

    def forbidden(*args, **kwargs):
        pytest.fail("hydration must not perform external I/O")

    monkeypatch.setattr(service.comfy, "ensure_idle", forbidden)
    monkeypatch.setattr(service.comfy, "execute", forbidden)
    monkeypatch.setattr(service.media, "verify_image", forbidden)
    cls = I2VPipe if operation == "i2v" else V2VPipe
    pipe = cls.from_run(service, snapshot)
    assert pipe.state.request.duration_seconds == seconds
    assert pipe.state.run == snapshot
    if operation == "v2v":
        assert pipe.state.request.reference_tail_seconds == 3
        assert pipe.state.request.include_audio is True
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["i2v", "v2v"])
@pytest.mark.parametrize("seconds", [0, -1, math.nan, math.inf, 10.01])
async def test_invalid_hydration_before_any_external_operation(tmp_path, monkeypatch, operation, seconds):
    service = make_service(tmp_path)
    run = admitted(service, operation=operation, parent_id=str(uuid4()) if operation == "v2v" else None)
    run.duration_seconds = seconds
    if operation == "v2v":
        run.input_info["continuation"]["duration_seconds"] = seconds

    def forbidden(*args, **kwargs):
        pytest.fail("invalid duration reached external operation")

    monkeypatch.setattr(service.comfy, "ensure_idle", forbidden)
    monkeypatch.setattr(service.media, "verify_image", forbidden)
    cls = I2VPipe if operation == "i2v" else V2VPipe
    with pytest.raises(ValueError):
        cls.from_run(service, run)
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_seconds,child_seconds", [(3, 5), (5, 10), (10, 3)])
async def test_long_root_continue_persist_and_publish_once(tmp_path, parent_seconds, child_seconds):
    service = make_service(tmp_path)
    service.builder = WorkflowBuilder(ROOT)
    baseline = service.builder.baseline_for("v2v")
    info = {node["class_type"]: {"input": {"required": {}}} for node in baseline.values()}
    for node_id, field in (("171:4", "unet_name"), ("171:3", "clip_name"), ("171:2", "vae_name"),
                           ("171:1", "vae_name"), ("22:6", "sampler_name"), ("22:7", "scheduler"),
                           ("18", "format"), ("34", "format")):
        node = baseline[node_id]
        choices = info[node["class_type"]]["input"]["required"].setdefault(field, [[]])[0]
        if node["inputs"][field] not in choices:
            choices.append(node["inputs"][field])

    async def object_info():
        return info

    service.comfy.object_info = object_info
    current_frames = [frames_for_duration(parent_seconds)]

    async def output_probe(path):
        return probe(current_frames[0])

    service.media.probe = output_probe
    parent = await service.create(RunRequest(seed=1, duration_seconds=parent_seconds))
    await service._task
    assert service.store.get(parent.id).state == "ready_for_review"
    await service.decide(parent.id, True)
    parent_manifest = service.store.get(parent.id).model_dump()
    parent_request = (service.store.directory(parent.id) / "request.json").read_bytes()
    current_frames[0] = frames_for_duration(child_seconds)
    child = await service.continue_run(parent.id, ContinueRequest(seed=2, duration_seconds=child_seconds))
    await service._task
    result = service.store.get(child.id)
    assert result.state == "ready_for_review"
    assert result.duration_seconds == child_seconds
    assert service.store.request(child.id).duration_seconds == child_seconds
    assert service.store.request(child.id).input_info["continuation"]["reference_tail_seconds"] == 3
    assert service.store.request(child.id).input_info["continuation"]["include_audio"] is True
    assert service.media.tails[0][1:] == (3, True)
    assert service.store.get(parent.id).model_dump() == parent_manifest
    assert (service.store.directory(parent.id) / "request.json").read_bytes() == parent_request
    assert len(service.comfy.submitted) == 2 and len(set(service.comfy.submitted)) == 2
    assert service.video_path(child.id).read_bytes() == b"fake-video"
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", [5, 10])
async def test_real_cpu_ffmpeg_aligned_publication_and_context_window(tmp_path, seconds):
    import asyncio

    from h3_backend.infrastructure import media

    frames = frames_for_duration(seconds)
    output = tmp_path / "synthetic.mp4"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i", "color=black:size=480x864:rate=24",
        "-f", "lavfi", "-i", "anullsrc=r=32000:cl=mono", "-frames:v", str(frames),
        "-t", str(frames / 24), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(output), stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    details = await media.probe(output)
    verify_video(details, frames)
    tail = await media.prepare_tail(output, tmp_path / "tail.mp4", 3, include_audio=True)
    assert tail["requested_seconds"] == 3
    assert tail["has_audio"] is True
    assert tail["actual_seconds"] == pytest.approx(3, abs=1 / 24)
    assert tail["loaded_reference_frames"] == 72
    assert tail["effective_reference_frames"] == 56


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/runs", "/runs/i2v", "/runs/not-a-uuid/continue"])
@pytest.mark.parametrize("seconds", [0, -1, 10.01])
async def test_http_invalid_duration_before_media_or_comfy(tmp_path, monkeypatch, route, seconds):
    import httpx

    from h3_backend.api import create_app

    service = make_service(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid HTTP duration reached external operation")

    monkeypatch.setattr(service.comfy, "ensure_idle", forbidden)
    monkeypatch.setattr(service.comfy, "object_info", forbidden)
    monkeypatch.setattr(service.media, "verify_image", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(service=service)),
                                base_url="http://fake") as client:
        response = await client.post(route, json={"seed": 1, "duration_seconds": seconds})
        assert response.status_code == 422
    assert not service.comfy.submitted and service._task is None
    assert not list(service.store.runs.iterdir())
    await service.shutdown()
