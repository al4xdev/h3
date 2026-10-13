import asyncio
from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest
from test_service import make_service

from h3_backend.generation.i2v import I2VPipe
from h3_backend.generation.models import ContinueRequest, RunRequest
from h3_backend.generation.v2v import V2VPipe
from h3_backend.generation.workflow import I2V_CONFIG, V2V_CONFIG


def i2v(service, request=None):
    return (I2VPipe(service).have(request or RunRequest(seed=17))
            .with_workflow(I2V_CONFIG).save_chunk())


def v2v(service, parent_id, request=None):
    return (V2VPipe(service).have(request or ContinueRequest(seed=18))
            .from_parent(parent_id).with_last_frame().with_original_identity()
            .with_motion_tail().with_workflow(V2V_CONFIG).save_chunk())


async def accepted_parent(service):
    run = await service.create(RunRequest(seed=1))
    await service._task
    return await service.decide(run.id, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_fluent_composition_is_pure_and_returns_same_object(tmp_path, kind):
    service = make_service(tmp_path)
    if kind == "i2v":
        pipe = I2VPipe(service)
        assert pipe.have(RunRequest(seed=7)) is pipe
        assert pipe.with_workflow(I2V_CONFIG) is pipe
    else:
        pipe = V2VPipe(service)
        assert pipe.have(ContinueRequest(seed=8)) is pipe
        assert pipe.from_parent("00000000-0000-0000-0000-000000000001") is pipe
        assert pipe.with_last_frame() is pipe
        assert pipe.with_original_identity() is pipe
        assert pipe.with_motion_tail() is pipe
        assert pipe.with_workflow(V2V_CONFIG) is pipe
    assert pipe.save_chunk() is pipe
    assert is_dataclass(pipe.state)
    assert {field.name for field in fields(pipe.state)} >= {"request", "run", "references", "workflow"}
    assert pipe.state.run is None
    assert not pipe.state.references and not pipe.state.workflow
    assert not service.builder.calls and not service.builder.validations
    assert not service.comfy.uploads and not service.comfy.submitted
    assert not list(service.store.runs.iterdir())
    assert service._active is None and service._task is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_dataclass_state_and_collections_are_per_request(tmp_path):
    service = make_service(tmp_path)
    first, second = i2v(service), i2v(service)
    assert first.state is not second.state
    assert first.state.references is not second.state.references
    assert first.state.workflow is not second.state.workflow
    first.state.references.append({"source": "must not leak"})
    first.state.workflow["private"] = True
    assert not second.state.references and not second.state.workflow
    with pytest.raises(FrozenInstanceError):
        first.state.save_output = False
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_request_snapshot_and_post_admission_freeze(tmp_path, kind):
    service = make_service(tmp_path)
    markdown = "# Snapshot\n\n<Picture 1>  \n<Picture 2>\n<Video 1>\n"
    if kind == "i2v":
        request = RunRequest(seed=17, prompt=markdown)
        pipe = i2v(service, request)
        config = I2V_CONFIG
    else:
        parent = await accepted_parent(service)
        request = ContinueRequest(seed=17, prompt=markdown)
        pipe = v2v(service, parent.id, request)
        config = V2V_CONFIG
    request.seed = 999
    request.prompt = "modified original"
    pipe.state.request.seed = 888
    pipe.state.request.prompt = "modified public view"
    run = await service.submit(pipe)
    assert run.seed == 17 and run.prompt == markdown
    pipe.state.run.seed = 777
    pipe.state.request.seed = 666
    with pytest.raises(ValueError):
        pipe.have(request)
    with pytest.raises(ValueError):
        pipe.with_workflow(config)
    with pytest.raises(ValueError):
        pipe.save_chunk()
    if kind == "v2v":
        for method in (pipe.with_last_frame, pipe.with_original_identity, pipe.with_motion_tail):
            with pytest.raises(ValueError):
                method()
        with pytest.raises(ValueError):
            pipe.from_parent(run.id)
    await service._task
    result = service.store.get(run.id)
    assert result.state == "ready_for_review"
    assert service.builder.calls[-1]["seed"] == 17
    assert service.builder.calls[-1]["prompt"] == markdown
    submitted = len(service.comfy.submitted)
    with pytest.raises(ValueError):
        await service.submit(pipe)
    assert len(service.comfy.submitted) == submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["no_request", "no_workflow", "no_output", "wrong_mode",
                                   "no_parent", "no_anchor", "no_identity", "no_tail"])
async def test_invalid_pipeline_configuration_creates_no_run(tmp_path, fault):
    service = make_service(tmp_path)
    with pytest.raises(ValueError):
        if fault in {"no_request", "no_workflow", "no_output", "wrong_mode"}:
            pipe = I2VPipe(service)
            if fault != "no_request":
                pipe.have(RunRequest(seed=7))
            if fault != "no_workflow":
                pipe.with_workflow(V2V_CONFIG if fault == "wrong_mode" else I2V_CONFIG)
            if fault != "no_output":
                pipe.save_chunk()
        else:
            pipe = V2VPipe(service).have(ContinueRequest(seed=8))
            if fault != "no_parent":
                pipe.from_parent("00000000-0000-0000-0000-000000000001")
            if fault != "no_anchor":
                pipe.with_last_frame()
            if fault != "no_identity":
                pipe.with_original_identity()
            if fault != "no_tail":
                pipe.with_motion_tail()
            pipe.with_workflow(V2V_CONFIG).save_chunk()
        await service.submit(pipe)
    assert not list(service.store.runs.iterdir())
    assert service._active is None
    assert not service.comfy.submitted and not service.comfy.uploads
    await service.shutdown()


@pytest.mark.asyncio
async def test_direct_fluent_admit_uses_same_global_dispatcher(tmp_path):
    service = make_service(tmp_path)
    service.comfy.gate = asyncio.Event()
    pipe = i2v(service)
    run = await pipe.admit()
    assert service._active == run.id
    with pytest.raises(ValueError):
        await i2v(service).admit()
    service.comfy.gate.set()
    await service._task
    assert service.store.get(run.id).state == "ready_for_review"
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
@pytest.mark.parametrize("failure", [None, "upload", "build", "execute", "probe"])
async def test_execution_is_sequential_and_failure_stops_downstream_steps(tmp_path, kind, failure):
    service = make_service(tmp_path)
    parent = await accepted_parent(service) if kind == "v2v" else None
    events = []
    cleaned = asyncio.Event()
    original_frame = service.media.prepare_last_frame
    original_tail = service.media.prepare_tail
    original_upload = service.comfy.upload
    original_build = service.builder.build
    original_execute = service.comfy.execute
    original_probe = service.media.probe

    def stage(name):
        events.append(name)
        if name.split(":")[0] == failure:
            raise RuntimeError(f"Injected {failure} failure")

    async def frame(*args, **kwargs):
        stage("last_frame")
        return await original_frame(*args, **kwargs)

    async def tail(*args, **kwargs):
        stage("tail")
        return await original_tail(*args, **kwargs)

    async def upload(path, name):
        label = {"initial_frame.png": "frame", "reference_tail.mp4": "video"}.get(
            path.name, "identity"
        )
        stage(f"upload:{label}")
        return await original_upload(path, name)

    def build(**kwargs):
        stage("build")
        return original_build(**kwargs)

    async def execute(*args, **kwargs):
        stage("execute")
        return await original_execute(*args, **kwargs)

    async def probe(*args, **kwargs):
        stage("probe")
        return await original_probe(*args, **kwargs)

    async def recorder(comfy, path, stop, **kwargs):
        try:
            await stop.wait()
        finally:
            cleaned.set()

    service.media.prepare_last_frame = frame
    service.media.prepare_tail = tail
    service.comfy.upload = upload
    service.builder.build = build
    service.comfy.execute = execute
    service.media.probe = probe
    service.telemetry = recorder
    pipe = i2v(service) if kind == "i2v" else v2v(service, parent.id)
    run = await service.submit(pipe)
    await service._task
    result = service.store.get(run.id)
    expected = (["upload:identity", "build", "execute", "probe"] if kind == "i2v" else
                ["last_frame", "upload:frame", "upload:identity", "tail", "upload:video",
                 "build", "execute", "probe"])
    if failure:
        end = next(index for index, name in enumerate(expected) if name.split(":")[0] == failure)
        assert events == expected[:end + 1]
        assert result.state == "failed" and f"Injected {failure}" in result.error
        assert not (service.store.directory(run.id) / "chunk.mp4").exists()
    else:
        assert events == expected
        assert result.state == "ready_for_review"
    assert cleaned.is_set()
    assert service._active is None and service._task.done()
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"reference_tail_seconds": 2}, {"include_audio": False}])
async def test_tail_configuration_cannot_silently_override_request(tmp_path, overrides):
    service = make_service(tmp_path)
    pipe = V2VPipe(service).have(ContinueRequest(seed=7, reference_tail_seconds=3, include_audio=True))
    with pytest.raises(ValueError):
        pipe.with_motion_tail(**overrides)
    assert not list(service.store.runs.iterdir()) and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_low_memory_does_not_stop_preparation_before_prompt_submission(tmp_path, kind):
    service = make_service(tmp_path)
    parent = await accepted_parent(service) if kind == "v2v" else None
    submitted = len(service.comfy.submitted)
    pipe = i2v(service) if kind == "i2v" else v2v(service, parent.id)
    run = await service.submit(pipe)
    service.memory_available = lambda: 0
    await service._task
    final = service.store.get(run.id)
    assert final.state == "ready_for_review" and final.prompt_id is not None
    assert final.error is None
    assert len(service.comfy.submitted) == submitted + 1
    assert service._active is None
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_pipeline_execution_cannot_bypass_central_worker_or_replay(tmp_path, kind):
    service = make_service(tmp_path)
    parent = await accepted_parent(service) if kind == "v2v" else None
    pipe = i2v(service) if kind == "i2v" else v2v(service, parent.id)
    with pytest.raises(AttributeError):
        pipe.dispatcher = object()
    with pytest.raises(ValueError):
        await pipe.arun()
    before = (len(service.comfy.uploads), len(service.comfy.submitted))
    run = await service.submit(pipe)
    with pytest.raises(ValueError):
        await pipe.arun()
    assert (len(service.comfy.uploads), len(service.comfy.submitted)) == before
    await service._task
    assert service.store.get(run.id).state == "ready_for_review"
    after = (len(service.comfy.uploads), len(service.comfy.submitted))
    with pytest.raises(ValueError):
        await pipe.arun()
    assert (len(service.comfy.uploads), len(service.comfy.submitted)) == after
    await service.shutdown()


@pytest.mark.asyncio
async def test_pipeline_cannot_be_admitted_by_foreign_dispatcher(tmp_path):
    first = make_service(tmp_path)
    other_root = tmp_path / "other"
    other_root.mkdir()
    second = make_service(other_root)
    pipe = i2v(first)
    with pytest.raises(ValueError, match="another dispatcher"):
        await second.submit(pipe)
    assert not list(first.store.runs.iterdir()) and not list(second.store.runs.iterdir())
    run = await first.submit(pipe)
    await first._task
    assert first.store.get(run.id).state == "ready_for_review"
    assert not second.comfy.submitted
    await first.shutdown()
    await second.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_returned_admission_run_is_not_the_worker_snapshot(tmp_path, kind):
    service = make_service(tmp_path)
    parent = await accepted_parent(service) if kind == "v2v" else None
    pipe = i2v(service) if kind == "i2v" else v2v(service, parent.id)
    run = await service.submit(pipe)
    original_id, original_seed, original_prompt = run.id, run.seed, run.prompt
    run.id = "00000000-0000-0000-0000-000000000000"
    run.seed = 999
    run.prompt = "caller mutation"
    run.references.clear()
    await service._task
    result = service.store.get(original_id)
    assert result.state == "ready_for_review"
    assert result.seed == original_seed and result.prompt == original_prompt
    assert service.builder.calls[-1]["seed"] == original_seed
    assert service.builder.calls[-1]["prompt"] == original_prompt
    assert result.references and service._active is None
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_shutdown_during_admission_never_spawns_a_worker(tmp_path, kind):
    service = make_service(tmp_path)
    parent = await accepted_parent(service) if kind == "v2v" else None
    submitted = len(service.comfy.submitted)
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_admission():
        entered.set()
        await release.wait()

    service.comfy.ensure_idle = paused_admission
    pipe = i2v(service) if kind == "i2v" else v2v(service, parent.id)
    admission = asyncio.create_task(service.submit(pipe))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(service.shutdown(), timeout=2)
    finally:
        release.set()
    with pytest.raises(ValueError):
        await admission
    assert len(service.comfy.submitted) == submitted
    assert service._active is None
    assert service._task is None or service._task.done()
    assert all(service.store.get(path.parent.name).state not in {"queued", "running"}
               for path in service.store.runs.glob("*/manifest.json"))

