"""CPU-only native execution from immutable admission files and real Linux inode events."""

import asyncio
import hashlib
import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from test_service import make_service

from h3_backend.api import create_app
from h3_backend.generation.i2v import I2VPipe
from h3_backend.generation.models import ContinueRequest, Run, RunRequest
from h3_backend.generation.v2v import V2VPipe
from h3_backend.generation.workflow import I2V_CONFIG, WorkflowBuilder
from h3_backend.infrastructure.store import Store, timestamp


def admitted(service, *, operation="i2v", parent_id=None, seed=2026101205, continuation=None):
    now = timestamp()
    request = continuation or ContinueRequest(seed=seed, duration_seconds=2.3)
    from h3_backend.generation.models import CONTINUATION_PROMPT, DEFAULT_PROMPT

    return Run(
        id=str(uuid4()), created_at=now, updated_at=now, seed=seed,
        prompt=DEFAULT_PROMPT if operation == "i2v" else request.prompt or CONTINUATION_PROMPT,
        duration_seconds=request.duration_seconds, parent_id=parent_id,
        workflow_hash=service.builder.hash_for(operation),
        references=[{
            "type": "image", "role": "identity", "source": "dance_reference.png",
            "source_root": "assets", "sha256": hashlib.sha256(b"fake-image").hexdigest(),
            "input_info": {"width": 1024, "height": 1024, "format": "PNG"},
        }],
        input_info={
            "mode": "normal" if operation == "i2v" else "continuation", "operation": operation,
            "continuation": None if operation == "i2v" else request.model_dump(),
            "workflow_provenance": service.builder.provenance(operation),
            "comfy_extra_pnginfo": getattr(service.builder, "extra_pnginfo", {}),
        },
    )


async def inode_barrier(service, stream, run_id):
    async with asyncio.timeout(3):
        async for path in stream:
            if path in {f".data/runs/{run_id}", f".data/runs/{run_id}/request.json"}:
                break
        await service._candidates.join()


@pytest.mark.asyncio
async def test_commit_default_opt_out_and_request_bytes_never_rewritten(tmp_path):
    service = make_service(tmp_path)
    run = admitted(service)
    service.store.create(run)
    assert not (service.store.directory(run.id) / "request.json").exists()
    explicit = admitted(service)
    service.store.create(explicit, materialize_request=True)
    path = service.store.directory(explicit.id) / "request.json"
    original = path.read_bytes()
    assert service.store.request(explicit.id) == explicit
    with pytest.raises(ValueError, match="already exists"):
        service.store.create(explicit, materialize_request=True)
    with pytest.raises(FileExistsError):
        service.store._artifact(explicit.id, "request.json", "{}", ".request-")
    service.store.update(explicit.id, state="running")
    enriched = [{**r, "upload": {"filename": "uploaded"}, "filename": "uploaded [input]"}
                for r in explicit.references]
    service.store.update(explicit.id, references=enriched, input_info={
        **explicit.input_info, "effective_markdown": explicit.prompt, "telemetry_error": "diagnostic",
    })
    assert service.store.request(explicit.id) == explicit
    for state in ("ready_for_review", "accepted"):
        service.store.update(explicit.id, state=state)
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="immutable"):
        service.store.update(explicit.id, seed=99)
    await service.shutdown()


@pytest.mark.asyncio
async def test_request_commit_is_last_and_fsyncs_directory(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    run = admitted(service)
    link, fsync = os.link, os.fsync
    observed = []

    def checked_link(source, destination):
        if destination.name == "request.json":
            assert service.store.get(run.id) == run
            observed.append("marker")
        link(source, destination)

    def checked_fsync(fd):
        import stat

        observed.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        fsync(fd)

    monkeypatch.setattr(os, "link", checked_link)
    monkeypatch.setattr(os, "fsync", checked_fsync)
    service.store.create(run, materialize_request=True)
    assert observed.index("marker") > observed.index("file")
    assert "directory" in observed[observed.index("marker") + 1:]
    await service.shutdown()


@pytest.mark.asyncio
async def test_crash_before_commit_never_replays_or_synthesizes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    run = admitted(service)
    link = os.link

    def crash(source, destination):
        if destination.name == "request.json":
            raise OSError("fake publication crash")
        link(source, destination)

    monkeypatch.setattr(os, "link", crash)
    with pytest.raises(OSError, match="publication crash"):
        service.store.create(run, materialize_request=True)
    assert service.store.get(run.id).state == "queued"
    assert not (service.store.directory(run.id) / "request.json").exists()
    await service.startup()
    assert service.store.get(run.id).state == "interrupted"
    assert not service.comfy.submitted and service._task is None
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
@pytest.mark.parametrize("profile", ["baseline", "final_only"])
async def test_public_hydration_is_pure_sealed_canonical(tmp_path, monkeypatch, kind, profile):
    service = make_service(tmp_path)
    project = Path(__file__).resolve().parents[1]
    service.builder = WorkflowBuilder(project, output_profile=profile)
    options = ContinueRequest(seed=17, duration_seconds=2.3, prompt=None, reference_tail_seconds=2, include_audio=False)
    run = admitted(service, operation=kind, seed=17,
                   parent_id=str(uuid4()) if kind == "v2v" else None, continuation=options)
    # Round-trip provenance tuples through the actual request serialization contract.
    run = Run.model_validate_json(run.model_dump_json())

    def forbidden(*args, **kwargs):
        pytest.fail("pure hydration performed admission, I/O or allocated a UUID")

    cls = I2VPipe if kind == "i2v" else V2VPipe
    monkeypatch.setattr(cls, "_admit", forbidden)
    monkeypatch.setattr(service.store, "get", forbidden)
    monkeypatch.setattr(service.media, "verify_image", forbidden)
    monkeypatch.setattr(service.comfy, "ensure_idle", forbidden)
    monkeypatch.setattr(f"h3_backend.generation.{kind}.uuid4", forbidden)
    pipe = cls.from_run(service, run)
    assert pipe._sealed and pipe.state.run == run
    assert pipe.state.save_output
    assert pipe.state.workflow_config.operation == kind
    if kind == "v2v":
        assert pipe.state.request == options
        assert pipe.state.last_frame and pipe.state.original_identity and pipe.state.motion_tail
        assert pipe.state.parent_id == run.parent_id
    with pytest.raises(ValueError):
        pipe.save_chunk()
    with pytest.raises(ValueError, match="central worker"):
        await pipe.arun()
    run.seed = 999
    assert pipe.state.run.seed == 17
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("state", "running"), ("prompt_id", "already-submitted"), ("output", {"path": "chunk.mp4"}),
    ("decision", {"accepted": True}), ("progress", {"value": 1}), ("timings", {"seconds": 1}),
    ("seed", True), ("prompt", "  "), ("duration_seconds", float("nan")),
    ("workflow_hash", "altered"),
])
async def test_invalid_sealed_admission_is_rejected_without_execution(tmp_path, field, value):
    service = make_service(tmp_path)
    run = admitted(service)
    setattr(run, field, value)
    with pytest.raises(ValueError):
        I2VPipe.from_run(service, run)
    assert not service.comfy.submitted and not list(service.store.runs.iterdir())
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["root", "path", "role", "hash", "duplicate", "derived", "format",
                                         "provenance", "mode", "operation", "metadata"])
async def test_forged_identity_and_builder_metadata_fail_closed(tmp_path, mutation):
    service = make_service(tmp_path)
    run = admitted(service)
    ref = run.references[0]
    if mutation == "root":
        ref["source_root"] = "runs"
    elif mutation == "path":
        ref["source"] = "../escape.png"
    elif mutation == "role":
        ref["role"] = "initial_frame"
    elif mutation == "hash":
        ref["sha256"] = "not-sha256"
    elif mutation == "duplicate":
        run.references.append({**deepcopy(ref), "source": "./dance_reference.png"})
    elif mutation == "derived":
        ref["upload"] = {"filename": "old"}
    elif mutation == "format":
        ref["input_info"]["format"] = "VIDEO"
    elif mutation == "provenance":
        run.input_info["workflow_provenance"]["config"] = {"new_guide": True}
    elif mutation == "mode":
        run.input_info["mode"] = "continuation"
    elif mutation == "operation":
        run.input_info["operation"] = []
    else:
        run.input_info["workflow_api"] = "old.json"
    with pytest.raises(ValueError):
        I2VPipe.from_run(service, run)
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("option,value", [("seed", 99), ("prompt", "other"), ("duration_seconds", 1.0),
                                          ("reference_tail_seconds", 4), ("include_audio", "yes")])
async def test_continuation_options_must_exactly_agree(tmp_path, option, value):
    service = make_service(tmp_path)
    run = admitted(service, operation="v2v", parent_id=str(uuid4()))
    run.input_info["continuation"][option] = value
    with pytest.raises(ValueError):
        V2VPipe.from_run(service, run)
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["symlink", "fifo", "large", "cross_uuid", "unknown", "strict_seed"])
async def test_request_reader_bounds_identity_and_file_type(tmp_path, mutation):
    service = make_service(tmp_path)
    run = admitted(service)
    service.store.create(run, materialize_request=True)
    path = service.store.directory(run.id) / "request.json"
    if mutation == "symlink":
        target = tmp_path / "other.json"
        target.write_text(run.model_dump_json())
        path.unlink()
        path.symlink_to(target)
    elif mutation == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif mutation == "large":
        path.write_bytes(b" " * (256 * 1024 + 1))
    else:
        data = run.model_dump()
        if mutation == "cross_uuid":
            data["id"] = str(uuid4())
        elif mutation == "unknown":
            data["arbitrary_job"] = "comfy-prompt"
        else:
            data["seed"] = "7"
        path.write_text(json.dumps(data))
    with pytest.raises((ValueError, OSError)):
        service.store.request(run.id)
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["seed", "prompt", "duration_seconds", "references", "input_info"])
async def test_manifest_input_tamper_disagrees_with_request(tmp_path, field):
    service = make_service(tmp_path)
    run = admitted(service)
    service.store.create(run, materialize_request=True)
    changes = {"seed": 99, "prompt": "tampered", "duration_seconds": 1.0,
               "references": [], "input_info": {**run.input_info, "operation": "v2v"}}
    service.store.update(run.id, **{field: changes[field]})
    with pytest.raises(ValueError, match="disagree"):
        service.store.request(run.id)
    await service.shutdown()


@pytest.mark.asyncio
async def test_worker_uses_disk_not_caller_pipeline_and_one_http_wait(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    pipe = I2VPipe(service).have(RunRequest(seed=2026101205, duration_seconds=2.3)).with_workflow(I2V_CONFIG).save_chunk()
    run = await service.submit(pipe)
    # Corrupt the captured caller object's private state: the central worker must hydrate afresh.
    pipe._state = replace(pipe._state, request=None, run=None)
    monkeypatch.setattr(pipe, "arun", lambda: pytest.fail("RAM caller pipe executed"))
    assert service._active == run.id and service._task is not None
    app = create_app(service=service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fake") as client:
        response = await client.get(f"/runs/{run.id}?wait=true")
    assert response.status_code == 200 and response.json()["state"] == "ready_for_review"
    assert service.builder.calls[0]["seed"] == 2026101205
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_worker_rereads_request_after_reservation_and_rejects_tamper(tmp_path):
    service = make_service(tmp_path)
    run = await service.create(RunRequest(seed=7, duration_seconds=2.3))
    path = service.store.directory(run.id) / "request.json"
    data = json.loads(path.read_text())
    data["seed"] = 99
    path.write_text(json.dumps(data))
    await service._task
    assert service.store.get(run.id).state == "failed"
    assert not service.comfy.submitted and service._active is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_real_inotify_executes_only_new_committed_native_requests(tmp_path):
    service = make_service(tmp_path)
    old = admitted(service)
    service.store.create(old, materialize_request=True)
    original = (service.store.directory(old.id) / "request.json").read_bytes()
    await service.startup()
    assert service.store.get(old.id).state == "interrupted" and not service.comfy.submitted
    stream = service.watcher.events()
    assert await anext(stream) == ".data"
    fresh = admitted(service)
    service.store.create(fresh, materialize_request=True)
    await inode_barrier(service, stream, fresh.id)
    assert service._task is not None
    await service._task
    assert service.store.get(fresh.id).state == "ready_for_review"
    assert len(service.comfy.submitted) == 1
    assert (service.store.directory(old.id) / "request.json").read_bytes() == original
    await service.decide(fresh.id, True)
    options = ContinueRequest(seed=2026101206, duration_seconds=2.3, reference_tail_seconds=2, include_audio=False)
    child = admitted(service, operation="v2v", parent_id=fresh.id, seed=options.seed,
                     continuation=options)
    service.store.create(child, materialize_request=True)
    await inode_barrier(service, stream, child.id)
    await service._task
    final = service.store.get(child.id)
    assert final.state == "ready_for_review"
    assert final.references[0]["input_info"]["frame_index"] == 55
    assert final.references[1]["sha256"] == fresh.references[0]["sha256"]
    assert final.references[-1]["has_audio"] is False
    assert service.media.tails[-1][1:] == (2, False)
    assert len(service.comfy.submitted) == 2
    service.watcher.recover()
    assert service.store.get(old.id).state == "interrupted"
    service._request_hint(child.id)
    await service._candidates.join()
    assert len(service.comfy.submitted) == 2
    await stream.aclose()
    await service.shutdown()
    assert service.watcher.fd is None and service._observer_task.done()


@pytest.mark.asyncio
async def test_busy_events_fail_even_if_slot_frees_before_consumer(tmp_path):
    service = make_service(tmp_path)
    await service.startup()
    service.comfy.gate = asyncio.Event()
    active = await service.create(RunRequest(seed=7, duration_seconds=2.3))
    conflicting = admitted(service, seed=8)
    service.store.create(conflicting, materialize_request=True)
    service._request_hint(conflicting.id)
    service.comfy.gate.set()
    await service._task
    await service._candidates.join()
    assert service.store.get(active.id).state == "ready_for_review"
    assert service.store.get(conflicting.id).state == "failed"
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_external_request_ignores_low_ram_without_replay(tmp_path):
    service = make_service(tmp_path)
    await service.startup()
    service.memory_available = lambda: 0
    stream = service.watcher.events()
    await anext(stream)
    run = admitted(service)
    service.store.create(run, materialize_request=True)
    await inode_barrier(service, stream, run.id)
    await service._task
    assert service.store.get(run.id).state == "ready_for_review"
    service.memory_available = lambda: 8 * 1024**3
    service._request_hint(run.id)
    await service._candidates.join()
    assert service._task.done() and len(service.comfy.submitted) == 1
    await stream.aclose()
    await service.shutdown()


@pytest.mark.asyncio
async def test_http_202_registers_own_uuid_before_first_get_wait(tmp_path):
    service = make_service(tmp_path)
    service.comfy.gate = asyncio.Event()
    app = create_app(service=service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fake") as client:
        response = await client.post("/runs/i2v", json={"seed": 2026101205, "duration_seconds": 2.3})
        assert response.status_code == 202
        run_id = response.json()["id"]
        assert response.json()["state"] == "queued" and service._active == run_id
        assert service._task is not None and service.store.request(run_id).id == run_id
        waiter = asyncio.create_task(client.get(f"/runs/{run_id}?wait=true"))
        service.comfy.gate.set()
        final = await waiter
        assert final.status_code == 200 and final.json()["id"] == run_id
        assert final.json()["state"] == "ready_for_review"
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["baseline", "final_only"])
async def test_frozen_cli_three_stages_run_native_graphs_from_disk(tmp_path, profile):
    from test_benchmark import benchmark

    service = make_service(tmp_path)
    service.builder = WorkflowBuilder(Path(__file__).resolve().parents[1], output_profile=profile)
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
    graphs = []
    execute = service.comfy.execute

    async def recorded_execute(graph, **kwargs):
        graphs.append(deepcopy(graph))
        return await execute(graph, **kwargs)

    service.comfy.execute = recorded_execute
    parent_id = None
    original_sha = hashlib.sha256(b"fake-image").hexdigest()
    for index, stage in enumerate(benchmark.STAGES):
        if stage.operation == "i2v":
            run = await service.create(RunRequest(**stage.request()))
        else:
            run = await service.continue_run(parent_id, ContinueRequest(**stage.request()))
        snapshot = service.store.request(run.id)
        await service._task
        current = service.store.get(run.id)
        assert current.state == "ready_for_review"
        assert service.store.request(run.id) == snapshot
        graph = graphs[-1]
        assert graph["16"]["inputs"]["seed"] == stage.seed
        assert graph["22:23"]["inputs"]["value"] == 2.3
        assert service.frames_for_duration(current.duration_seconds) == 56
        assert current.prompt == stage.prompt and current.duration_seconds == 2.3
        identities = [r for r in current.references if r["role"] == "identity"]
        assert identities[0]["sha256"] == original_sha
        if stage.operation == "v2v":
            assert graph["272"]["inputs"]["frame_idx"] == 0
            assert current.references[0]["input_info"]["frame_index"] == 55
            assert current.references[-1]["has_audio"]
        if profile == "final_only":
            assert all(node not in graph for node in ("18", "176", "177"))
        if index < 2:
            await service.decide(run.id, True)
        parent_id = run.id
    assert service.store.get(parent_id).state == "ready_for_review"  # No automatic third decision.
    assert (tmp_path / "assets/dance_reference.png").read_bytes() == b"fake-image"
    assert len(service.comfy.submitted) == 3
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["manifest.json", "dance_reference.png"])
async def test_fifo_manifest_or_identity_never_blocks_worker(tmp_path, name):
    service = make_service(tmp_path)
    run = admitted(service)
    service.store.create(run, materialize_request=True)
    path = (service.store.directory(run.id) / name if name == "manifest.json"
            else tmp_path / "assets" / name)
    path.unlink()
    os.mkfifo(path)
    if name == "manifest.json":
        with pytest.raises(ValueError, match="bounded regular"):
            service.store.get(run.id)
    else:
        async with service._lock:
            await service._start_materialized(run.id)
        async with asyncio.timeout(3):
            await service._task
        assert service.store.get(run.id).state == "failed"
        assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_plain_queued_state_edit_cannot_replay_execution_evidence(tmp_path):
    service = make_service(tmp_path)
    run = await service.create(RunRequest(seed=7, duration_seconds=2.3))
    await service._task
    manifest = service.store.directory(run.id) / "manifest.json"
    data = json.loads(manifest.read_text())
    data["state"] = "queued"  # Hostile edit only in pytest's owned fake root.
    manifest.write_text(json.dumps(data))
    async with service._lock:
        with pytest.raises(ValueError, match="execution evidence"):
            await service._start_materialized(run.id)
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_malformed_external_record_fails_own_state_and_observer_keeps_running(tmp_path):
    service = make_service(tmp_path)
    await service.startup()
    stream = service.watcher.events()
    await anext(stream)
    bad = admitted(service)
    service.store.create(bad)
    path = service.store.directory(bad.id) / "request.json"
    path.write_text('{"operation":"arbitrary-job"}')
    await inode_barrier(service, stream, bad.id)
    assert service.store.get(bad.id).state == "failed"
    assert path.read_text() == '{"operation":"arbitrary-job"}'
    assert not service.comfy.submitted and not service._observer_task.done()
    good = admitted(service)
    service.store.create(good, materialize_request=True)
    await inode_barrier(service, stream, good.id)
    await service._task
    assert service.store.get(good.id).state == "ready_for_review"
    assert len(service.comfy.submitted) == 1
    await stream.aclose()
    await service.shutdown()


@pytest.mark.asyncio
async def test_terminal_request_events_never_repeat_or_decide_generation(tmp_path):
    service = make_service(tmp_path)
    await service.startup()
    run = await service.create(RunRequest(seed=7, duration_seconds=2.3))
    await service._task
    await service.decide(run.id, False)
    stream = service.watcher.events()
    await anext(stream)
    path = service.store.directory(run.id) / "request.json"
    original = path.read_bytes()
    # An external event with identical encoded bytes is not a new intent.
    path.write_bytes(original)
    await inode_barrier(service, stream, run.id)
    assert service.store.get(run.id).state == "rejected"
    assert path.read_bytes() == original and len(service.comfy.submitted) == 1
    await stream.aclose()
    await service.shutdown()


@pytest.mark.asyncio
async def test_runtime_lease_prevents_second_worker_and_hands_off_safely(tmp_path):
    service = make_service(tmp_path)
    await service.startup()
    other = Store(tmp_path)
    with pytest.raises(ValueError, match="Another backend"):
        other.hold_runtime()
    await service.shutdown()
    other.hold_runtime()
    other.release_runtime()
