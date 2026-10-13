"""Assembly operates on temporary encoded clips and external FFmpeg, never Comfy/xAI."""

import asyncio
import json
import shutil
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from test_file_worker import admitted
from test_service import make_service
from test_store import make_run

from h3_backend import api
from h3_backend.generation import assembly
from h3_backend.generation.assembly import (
    AssemblyPipe,
    assembly_video,
    get_assembly,
    restore_interrupted,
)
from h3_backend.generation.dispatcher import Conflict
from h3_backend.generation.models import RunRequest
from h3_backend.infrastructure import media


@pytest.fixture(scope="session")
def source_clips(tmp_path_factory):
    root = tmp_path_factory.mktemp("assembly-encoded-synthetic")
    clips = []
    for index, color in enumerate(("red", "green", "blue")):
        path = root / f"source-{index}.mp4"
        asyncio.run(media._command(
            "ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i", f"color=c={color}:s=48x64:r=24:d=0.208334",
            "-f", "lavfi", "-i", "anullsrc=r=32000:cl=stereo:d=0.15", "-map", "0:v:0", "-map", "1:a:0",
            "-frames:v", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)))
        clips.append(path)
    return clips


def chain(tmp_path, source_clips, *, end_state="ready_for_review"):
    service = make_service(tmp_path)
    service.media.probe = media.probe
    service.media.concatenate = media.concatenate
    runs = []
    for source in source_clips:
        run = make_run().model_copy(update={"parent_id": runs[-1].id if runs else None})
        service.store.create(run)
        destination = service.store.directory(run.id) / "chunk.mp4"
        shutil.copyfile(source, destination)
        service.store.update(run.id, state="running")
        service.store.update(run.id, state="ready_for_review", output={"path": service.store.relative_artifact(run.id, "chunk.mp4")})
        if len(runs) < 2 or end_state == "accepted":
            service.store.update(run.id, state="accepted", decision={"accepted": True})
        elif end_state == "rejected":
            service.store.update(run.id, state="rejected", decision={"accepted": False})
        runs.append(service.store.get(run.id))
    return service, runs


def client(service):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.create_app(service=service)), base_url="http://local")


def pipe(service, end, ident=None):
    return AssemblyPipe(service).have(ident or str(uuid4())).from_end(end).save_video()


def bytes_before(service, runs):
    return {run.id: {name: (service.store.directory(run.id) / name).read_bytes()
                     for name in ("manifest.json", "chunk.mp4")} for run in runs}


@pytest.mark.asyncio
@pytest.mark.parametrize("end_state", ["ready_for_review", "accepted"])
async def test_real_external_concat_commits_last_preserves_inputs_and_range(tmp_path, source_clips, end_state):
    service, runs = chain(tmp_path, source_clips, end_state=end_state)
    before = bytes_before(service, runs)
    ident = str(uuid4())
    async with client(service) as http:
        assert (await http.get("/app/config")).json()["assembly_enabled"] is True
        response = await http.post(f"/assemblies/{ident}", json={"end_run_id": runs[-1].id})
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["state"] == "completed" and record["id"] == ident
        assert record["input_ids"] == [run.id for run in runs]
        assert record["frames"] == 15 and record["fps"] == "24/1"
        assert record["output"]["boundaries"] == [5, 10]
        assert record["video_url"] == f"/assemblies/{ident}/video"
        if end_state == "ready_for_review":
            assert record["mode"] == "preview" and "revisão pendente" in record["label"]
        details = await media.probe(assembly_video(tmp_path, ident))
        video = next(s for s in details["streams"] if s["codec_type"] == "video")
        audio = next(s for s in details["streams"] if s["codec_type"] == "audio")
        assert int(video["nb_read_frames"]) == 15 and (video["width"], video["height"]) == (48, 64)
        assert abs(float(video["duration"]) - 15 / 24) < 0.001
        assert (audio["codec_name"], audio["sample_rate"], audio["channels"]) == ("aac", "32000", 2)
        assert abs(float(audio["duration"]) - 15 / 24) < 0.1
        assert (await http.get(f"/assemblies/{ident}")).json() == record
        ranged = await http.get(record["video_url"], headers={"Range": "bytes=0-15"})
        assert ranged.status_code == 206 and len(ranged.content) == 16
        collection = (await http.get("/assemblies", params={"end_run_id": runs[-1].id, "limit": 1})).json()
        assert collection["total"] == 1 and collection["items"][0]["id"] == ident
        assert (await http.get("/assemblies", params={"end_run_id": runs[0].id})).json()["total"] == 0
        assert (await http.post(f"/assemblies/{ident}", json={"end_run_id": runs[-1].id})).status_code == 409
    assert bytes_before(service, runs) == before
    assert service.store.get(runs[-1].id).state == end_state and not service.comfy.submitted
    assert service._cpu_active is None and service._cpu_task is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_pure_fluent_state_and_disk_not_caller_state_executes(tmp_path, source_clips, monkeypatch):
    service, runs = chain(tmp_path, source_clips)
    original_get = service.store.get

    def forbidden(*args, **kwargs):
        pytest.fail("fluent composition performed I/O")

    monkeypatch.setattr(service.store, "get", forbidden)
    composed = pipe(service, runs[-1].id)
    assert not (tmp_path / ".data/assemblies").exists()
    monkeypatch.setattr(service.store, "get", original_get)
    admit = composed._admit

    async def change_ram():
        await admit()
        composed.state = replace(composed.state, end_run_id=str(uuid4()), save_output=False)

    monkeypatch.setattr(composed, "_admit", change_ram)
    result = await composed.arun()
    assert result["end_run_id"] == runs[-1].id
    with pytest.raises(Conflict):
        composed.from_end(runs[0].id)
    with pytest.raises(Conflict):
        await composed.arun()
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"end_run_id": "bad"}, {"end_run_id": 3}, {"end_run_id": None},
                                      {"end_run_id": str(uuid4()), "accept": True}, ["bad"]])
async def test_strict_body_no_extra_intention_or_inference(tmp_path, payload):
    service = make_service(tmp_path)
    async with client(service) as http:
        response = await http.post(f"/assemblies/{uuid4()}", json=payload)
        assert response.status_code == 422
    assert service._cpu_active is None and not (tmp_path / ".data/assemblies").exists()
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=10001", "limit=1.0",
                                    "limit=+1", "limit=1e1", "end_run_id=../run"])
async def test_strict_collection_bounds_and_missing_id(tmp_path, query):
    service = make_service(tmp_path)
    async with client(service) as http:
        assert (await http.get(f"/assemblies?{query}")).status_code in {400, 422}
        assert (await http.get(f"/assemblies/{uuid4()}")).status_code == 404
    await service.shutdown()


@pytest.mark.asyncio
async def test_bounded_raw_metadata_body_and_canonical_id(tmp_path):
    service = make_service(tmp_path)
    async with client(service) as http:
        assert (await http.post(f"/assemblies/{uuid4()}", content=b" " * 1025)).status_code == 413
        assert (await http.post("/assemblies/BAD", json={"end_run_id": str(uuid4())})).status_code == 400
        assert (await http.post(f"/assemblies/{uuid4()}", json={"end_run_id": str(uuid4())},
                                headers={"Origin": "https://foreign"})).status_code == 403
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["queued", "failed", "interrupted", "rejected"])
async def test_ineligible_end_never_publishes_or_renders(tmp_path, state):
    service = make_service(tmp_path)
    run = make_run().model_copy(update={"state": state})
    service.store.create(run)
    with pytest.raises(Conflict, match="End must"):
        await pipe(service, run.id).arun()
    assert not (tmp_path / ".data/assemblies").exists() and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "ancestor", "cycle", "capacity"])
async def test_invalid_chain_is_bounded_before_render(tmp_path, failure):
    service = make_service(tmp_path)
    if failure == "missing":
        end = str(uuid4())
        expected = FileNotFoundError
    else:
        count = 101 if failure == "capacity" else 2
        parent = None
        runs = []
        for _ in range(count):
            run = make_run().model_copy(update={"state": "accepted", "parent_id": parent})
            service.store.create(run)
            runs.append(run)
            parent = run.id
        end = runs[-1].id
        if failure == "ancestor":
            path = service.store.directory(runs[0].id) / "manifest.json"
            data = json.loads(path.read_text())
            data["state"] = "failed"
            path.write_text(json.dumps(data))
            expected = Conflict
        elif failure == "cycle":
            path = service.store.directory(runs[0].id) / "manifest.json"
            data = json.loads(path.read_text())
            data["parent_id"] = end  # Isolated malformed external record, not a public terminal transition.
            path.write_text(json.dumps(data))
            expected = ValueError
        else:
            expected = ValueError
    with pytest.raises(expected):
        await pipe(service, end).arun()
    assert not (tmp_path / ".data/assemblies").exists()
    await service.shutdown()


@pytest.mark.asyncio
async def test_global_cpu_native_review_and_filesystem_busy_capture(tmp_path, source_clips):
    service, runs = chain(tmp_path, source_clips)
    await service.startup()
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.media.concatenate

    async def delayed(chunks, destination):
        entered.set()
        await release.wait()
        return await original(chunks, destination)

    service.media.concatenate = delayed
    operation = pipe(service, runs[-1].id)
    task = asyncio.create_task(operation.arun())
    await entered.wait()
    assert service._cpu_active == operation.state.id and service._cpu_task is task
    with pytest.raises(Conflict):
        await service.create(RunRequest(seed=7, duration_seconds=2.3))
    with pytest.raises(Conflict):
        await service.decide(runs[-1].id, True)
    with pytest.raises(Conflict):
        await pipe(service, runs[-1].id).arun()
    # Explicit native intent committed during CPU ownership must not queue for later generation.
    external = admitted(service)
    service.store.create(external, materialize_request=True)
    service._request_hint(external.id)
    await service._candidates.join()
    assert service.store.get(external.id).state == "failed"
    release.set()
    await task
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_native_job_prevents_cpu_assembly_admission(tmp_path):
    service = make_service(tmp_path)
    service.comfy.gate = asyncio.Event()
    run = await service.create(RunRequest(seed=7, duration_seconds=2.3))
    with pytest.raises(Conflict):
        await pipe(service, run.id).arun()
    assert not (tmp_path / ".data/assemblies").exists()
    service.comfy.gate.set()
    await service.wait_run(run.id)
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [0, 1536 * 1024**2 - 1, None])
async def test_cpu_slot_ignores_ram_but_preserves_missing_input_guard(tmp_path, available):
    consulted = []

    def sensor():
        consulted.append(True)
        if available is None:
            raise RuntimeError("Host RAM sensor unavailable")
        return available

    service = make_service(tmp_path, memory_available=sensor)
    async with service.cpu_slot("fake-assembly"):
        assert service._cpu_active == "fake-assembly"
    with pytest.raises(FileNotFoundError):
        await pipe(service, str(uuid4())).arun()
    assert consulted == [] and service._cpu_active is None
    assert not (tmp_path / ".data/assemblies").exists() and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["complete", "cancel", "shutdown"])
async def test_ram_drop_does_not_interrupt_owned_cpu_render(tmp_path, finish):
    source = tmp_path / "fake-source.mp4"
    source.write_bytes(b"fake encoded clip")
    service, runs = chain(tmp_path, [source] * 3)

    async def probe(path):
        frames = 15 if path.name == "video.mp4" else 5
        return {"streams": [{
            "codec_type": "video", "width": 48, "height": 64,
            "avg_frame_rate": "24/1", "duration": str(frames / 24),
            "nb_frames": str(frames), "codec_name": "h264", "pix_fmt": "yuv420p",
        }]}

    service.media.probe = probe
    service.settings = replace(service.settings, memory_check_interval=0.001)
    entered, release = asyncio.Event(), asyncio.Event()
    available = [8 * 1024**3]
    consulted = []

    def sensor():
        consulted.append(True)
        return available[0]

    service.memory_available = sensor

    async def blocked(chunks, destination):
        entered.set()
        await release.wait()
        assert len(chunks) == 3
        destination.write_bytes(b"fake assembled clip")
        return {"assembly": assembly.MECHANISM}

    service.media.concatenate = blocked
    operation = pipe(service, runs[-1].id)
    task = asyncio.create_task(operation.arun())
    await entered.wait()
    available[0] = 0
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(release.wait(), timeout=0.02)
    assert not task.done() and service._cpu_task is task
    if finish == "complete":
        release.set()
        await task
        record = get_assembly(tmp_path, operation.state.id)
        assert record["state"] == "completed" and record["error"] is None
    else:
        if finish == "shutdown":
            await service.shutdown()
        else:
            task.cancel("Explicit own cancellation")
        with pytest.raises(asyncio.CancelledError):
            await task
        record = get_assembly(tmp_path, operation.state.id)
        assert record["state"] == "interrupted" and record["video_url"] is None
    assert consulted == []
    assert not service.comfy.submitted and service._cpu_task is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_http_disconnect_leaves_owned_shielded_cpu_task(tmp_path, source_clips):
    service, runs = chain(tmp_path, source_clips)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.media.concatenate

    async def delayed(chunks, destination):
        entered.set()
        await release.wait()
        return await original(chunks, destination)

    service.media.concatenate = delayed
    ident = str(uuid4())
    async with client(service) as http:
        waiter = asyncio.create_task(http.post(f"/assemblies/{ident}", json={"end_run_id": runs[-1].id}))
        await entered.wait()
        owned = service._cpu_task
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not owned.cancelled()
        running = (await http.get(f"/assemblies/{ident}")).json()
        assert running["state"] == "running" and running["video_url"] is None
        assert (await http.get(f"/assemblies/{ident}/video")).status_code == 409
        release.set()
        await owned
        assert (await http.get(f"/assemblies/{ident}")).json()["state"] == "completed"
    await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_only_own_cpu_child_and_records_interruption(tmp_path, source_clips, monkeypatch):
    service, runs = chain(tmp_path, source_clips)
    processes = []
    child_started = asyncio.Event()
    create = asyncio.create_subprocess_exec

    async def tracked(*args, **kwargs):
        process = await create(*args, **kwargs)
        processes.append(process)
        if args[0] == "ffmpeg":
            child_started.set()
        return process

    entered = asyncio.Event()

    async def owned_child(chunks, destination):
        destination.write_bytes(b"partial own encoded evidence")
        entered.set()
        # Same external-command ownership/cancellation path, not a foreign Comfy cancellation.
        await media._command("ffmpeg", "-v", "error", "-re", "-f", "lavfi", "-i", "color=s=48x64:r=24",
                             "-t", "60", "-f", "null", "-")

    service.media.concatenate = owned_child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", tracked)
    operation = pipe(service, runs[-1].id)
    task = asyncio.create_task(operation.arun())
    await entered.wait()
    # Child creation itself is awaited before cancellation to avoid a subprocess-spawn race in the fixture.
    await child_started.wait()
    await service.shutdown()
    assert task.cancelled() and processes[-1].returncode is not None
    record = get_assembly(tmp_path, operation.state.id)
    assert record["state"] == "interrupted" and record["video_url"] is None
    assert (tmp_path / ".data/assemblies" / operation.state.id / "video.mp4").read_bytes() == b"partial own encoded evidence"
    assert not service.comfy.submitted and service._active is None and service._cpu_active is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["source", "request", "review", "render", "frames", "marker"])
async def test_mid_render_failure_never_commits_or_replays(tmp_path, source_clips, monkeypatch, failure):
    service, runs = chain(tmp_path, source_clips)
    operation = pipe(service, runs[-1].id)
    original = service.media.concatenate

    async def disrupted(chunks, destination):
        if failure == "render":
            destination.write_bytes(b"partial encoding")
            raise ValueError("fake render failure")
        result = await original(chunks, destination)
        if failure == "source":
            chunks[0].write_bytes(b"source changed after rendering")
        elif failure == "request":
            path = destination.parent / "request.json"
            data = json.loads(path.read_text())
            data["created_at"] = "tampered"
            path.write_text(json.dumps(data))
        elif failure == "review":
            service.store.update(runs[-1].id, state="accepted", decision={"accepted": True})
        elif failure == "frames":
            async def wrong_probe(path):
                details = await media.probe(path)
                next(s for s in details["streams"] if s["codec_type"] == "video")["nb_read_frames"] = "14"
                return details
            service.media.probe = wrong_probe
        return result

    service.media.concatenate = disrupted
    if failure == "marker":
        write = assembly._write

        def no_complete(path, data, **kwargs):
            if path.name == "metadata.json" and data.get("state") == "completed":
                raise OSError("fake completed marker failure")
            return write(path, data, **kwargs)

        monkeypatch.setattr(assembly, "_write", no_complete)
    with pytest.raises((ValueError, OSError)):
        await operation.arun()
    root = tmp_path / ".data/assemblies" / operation.state.id
    assert json.loads((root / "metadata.json").read_text())["state"] == "failed"
    assert (root / "request.json").is_file() and (root / "video.mp4").is_file()
    restore_interrupted(tmp_path)
    assert json.loads((root / "metadata.json").read_text())["state"] == "failed"
    with pytest.raises((Conflict, ValueError)):
        assembly_video(tmp_path, operation.state.id)
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_startup_marks_old_pending_interrupted_never_runs_output_or_request(tmp_path, source_clips):
    service, runs = chain(tmp_path, source_clips)
    operation = pipe(service, runs[-1].id)
    async with service.cpu_slot(operation.state.id):
        await operation._admit()
    directory = tmp_path / ".data/assemblies" / operation.state.id
    (directory / "video.mp4").write_bytes(b"orphan output is not completion")

    async def forbidden(*args, **kwargs):
        pytest.fail("startup or GET re-executed a historical assembly")

    service.media.concatenate = forbidden
    await service.startup()
    record = get_assembly(tmp_path, operation.state.id)
    assert record["state"] == "interrupted" and record["video_url"] is None
    assert (directory / "video.mp4").read_bytes() == b"orphan output is not completion"
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["source_symlink", "source_fifo", "cross_run", "dir_symlink", "collision"])
async def test_unsafe_source_or_destination_before_render_keeps_original(tmp_path, source_clips, fault):
    import os

    service, runs = chain(tmp_path, source_clips)
    operation = pipe(service, runs[-1].id)
    if fault in {"source_symlink", "source_fifo"}:
        source = service.store.directory(runs[0].id) / "chunk.mp4"
        source.unlink()
        if fault == "source_symlink":
            source.symlink_to(source_clips[0])
        else:
            os.mkfifo(source)
    elif fault == "cross_run":
        path = service.store.directory(runs[0].id) / "manifest.json"
        data = json.loads(path.read_text())
        data["output"] = {"path": service.store.relative_artifact(runs[1].id, "chunk.mp4")}
        path.write_text(json.dumps(data))
    else:
        base = tmp_path / ".data/assemblies"
        base.mkdir()
        path = base / operation.state.id
        if fault == "collision":
            path.mkdir()
            (path / "video.mp4").write_bytes(b"owned prior evidence")
        else:
            path.symlink_to(service.store.directory(runs[0].id), target_is_directory=True)
    with pytest.raises((ValueError, FileExistsError, FileNotFoundError)):
        await operation.arun()
    if fault == "collision":
        assert (path / "video.mp4").read_bytes() == b"owned prior evidence"
    assert not service.comfy.submitted and service._cpu_active is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_verified_legacy_clip_aliases_keep_original_and_migrated_bytes(tmp_path, source_clips):
    from test_data_storage import legacy, migration

    runs = []
    for index, source in enumerate(source_clips):
        run = legacy(tmp_path, state="accepted" if index < 2 else "ready_for_review", parent=runs[-1].id if runs else None)
        shutil.copyfile(source, tmp_path / "runs" / run.id / "chunk.mp4")
        runs.append(run)
    migration.migrate(tmp_path, execute=True, offline=True)
    service = make_service(tmp_path)
    service.media.probe, service.media.concatenate = media.probe, media.concatenate
    original = {run.id: (tmp_path / "runs" / run.id / "chunk.mp4").read_bytes() for run in runs}
    result = await pipe(service, runs[-1].id).arun()
    request = json.loads((tmp_path / ".data/assemblies" / result["id"] / "request.json").read_text())
    assert [item["path"] for item in request["inputs"]] == [f"runs/{run.id}/chunk.mp4" for run in runs]
    assert result["frames"] == 15 and result["mode"] == "preview"
    for run in runs:
        assert (tmp_path / "runs" / run.id / "chunk.mp4").read_bytes() == original[run.id]
        assert (service.store.directory(run.id) / "chunk.mp4").read_bytes() == original[run.id]
    await service.shutdown()


@pytest.mark.asyncio
async def test_failed_admission_marker_is_visible_but_not_executable_or_reusable(tmp_path, source_clips, monkeypatch):
    service, runs = chain(tmp_path, source_clips)
    operation = pipe(service, runs[-1].id)
    write = assembly._write

    def marker_failure(path, data, **kwargs):
        if path.name == "request.json":
            raise OSError("fake admission marker failure")
        return write(path, data, **kwargs)

    monkeypatch.setattr(assembly, "_write", marker_failure)
    with pytest.raises(OSError):
        await operation.arun()
    async with client(service) as http:
        record = (await http.get(f"/assemblies/{operation.state.id}")).json()
        assert record["state"] == "failed" and record["video_url"] is None and record["input_ids"] == []
        assert (await http.get("/assemblies")).json()["total"] == 1
        assert (await http.get(f"/assemblies/{operation.state.id}/video")).status_code == 409
        async def no_probe(*args, **kwargs):
            pytest.fail("duplicate reserved UUID touched FFmpeg/probe")
        service.media.probe = no_probe
        assert (await http.post(f"/assemblies/{operation.state.id}", json={"end_run_id": runs[-1].id})).status_code == 409
    await service.shutdown()


@pytest.mark.asyncio
async def test_foreign_owner_metadata_is_not_exposed(tmp_path, source_clips, monkeypatch):
    import os

    service, runs = chain(tmp_path, source_clips)
    result = await pipe(service, runs[-1].id).arun()
    original = os.fstat

    def foreign_owner(fd):
        values = list(original(fd))
        values[4] = os.getuid() + 1
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", foreign_owner)
    with pytest.raises(ValueError, match="own file"):
        get_assembly(tmp_path, result["id"])
    monkeypatch.setattr(os, "fstat", original)
    await service.shutdown()


@pytest.mark.asyncio
async def test_no_audio_inputs_remain_no_audio_without_new_config(tmp_path, source_clips):
    silent = tmp_path / "silent.mp4"
    await media._command("ffmpeg", "-v", "error", "-n", "-i", str(source_clips[0]), "-an", "-c:v", "copy", str(silent))
    fixture_root = tmp_path / "local-app"
    fixture_root.mkdir()
    service, runs = chain(fixture_root, [silent] * 3)
    result = await pipe(service, runs[-1].id).arun()
    assert result["frames"] == 15 and all(stream["codec_type"] != "audio" for stream in result["output"]["probe"]["streams"])
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["output", "metadata", "request", "video", "same_size_video", "fifo", "foreign_id", "hardlink_video", "metadata_symlink", "oversize_json"])
async def test_completed_proof_binding_and_nonregular_files_fail_closed(tmp_path, source_clips, fault):
    import os

    service, runs = chain(tmp_path, source_clips)
    result = await pipe(service, runs[-1].id).arun()
    directory = tmp_path / ".data/assemblies" / result["id"]
    if fault in {"output", "metadata", "request"}:
        path = directory / f"{fault}.json"
        data = json.loads(path.read_text())
        data["id"] = str(uuid4())
        path.write_text(json.dumps(data))
    elif fault == "video":
        (directory / "video.mp4").write_bytes(b"incorrect encoded output")
    elif fault == "same_size_video":
        video = directory / "video.mp4"
        size = video.stat().st_size
        video.write_bytes(b"x" * size)
    elif fault == "fifo":
        path = directory / "output.json"
        path.unlink()
        os.mkfifo(path)
    elif fault == "hardlink_video":
        os.link(directory / "video.mp4", tmp_path / "external-link.mp4")
    elif fault == "metadata_symlink":
        path = directory / "metadata.json"
        saved = tmp_path / "external-metadata.json"
        path.rename(saved)
        path.symlink_to(saved)
    elif fault == "oversize_json":
        (directory / "output.json").write_bytes(b" " * (assembly.MAX_METADATA + 1))
    else:
        destination = directory.parent / str(uuid4())
        directory.rename(destination)
        with pytest.raises(ValueError):
            get_assembly(tmp_path, destination.name)
        await service.shutdown()
        return
    with pytest.raises(ValueError):
        assembly_video(tmp_path, result["id"])
    assert not service.comfy.submitted
    await service.shutdown()
