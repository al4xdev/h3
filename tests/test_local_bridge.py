"""Thin local bridge on pytest-owned roots; only fake Comfy inference is used."""

import asyncio
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from test_file_worker import admitted
from test_service import make_service

from h3_backend import api
from h3_backend.generation.i2v import I2VPipe
from h3_backend.generation.models import CONTINUATION_PROMPT, DEFAULT_PROMPT, RunRequest
from h3_backend.generation.workflow import WorkflowBuilder
from h3_backend.infrastructure import media


def encoded_image(format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (48, 64), "#735a42").save(output, format=format)
    return output.getvalue()


def client(service):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.create_app(service=service)), base_url="http://fake")


@pytest.mark.asyncio
async def test_fixed_packaged_assets_config_and_read_only_requests(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    await service.startup()

    def forbidden(*args, **kwargs):
        pytest.fail("metadata read invoked media/Comfy inference")

    monkeypatch.setattr(service.comfy, "ensure_idle", forbidden)
    monkeypatch.setattr(service.comfy, "execute", forbidden)
    monkeypatch.setattr(service.media, "verify_image", forbidden)
    monkeypatch.setattr(service.media, "probe", forbidden)
    async with client(service) as http:
        for path, mime in (("/", "text/html"), ("/index", "text/html"),
                           ("/ui/app.css", "text/css"), ("/ui/app.js", "text/javascript")):
            response = await http.get(path)
            assert response.status_code == 200 and response.headers["content-type"].startswith(mime)
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert "script-src 'self'" in response.headers["content-security-policy"]
        assert (await http.get("/favicon.ico")).status_code == 204
        for path in ("/ui/models.py", "/ui/../api.py", "/.data/state/migration.json", "/assets/prompts/initial.md"):
            assert (await http.get(path)).status_code == 404
        config = (await http.get("/app/config")).json()
        assert config == {"default_prompt": DEFAULT_PROMPT, "continuation_prompt": CONTINUATION_PROMPT,
                          "reference_image": "dance_reference.png", "duration_seconds": 2.3,
                          "workflow_output_profile": "baseline", "filesystem_events": True,
                          "reference_library": True, "assembly_enabled": True,
                          "duration_capabilities": {
                              "default_requested_seconds": 2.3, "min_requested_seconds": 0,
                              "min_exclusive": True, "max_requested_seconds": 10,
                              "input_step": 0.01, "fps": 24, "frame_base": 5,
                              "frame_stride": 17, "rounding": "half_even", "max_frames": 243,
                              "max_actual_seconds": 10.125,
                          }}
        assert (await http.get("/runs")).json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
        refs = (await http.get("/inputs")).json()
        assert refs["total"] == 1 and refs["items"][0]["source_root"] == "assets"
        assert refs["items"][0]["path"] == "dance_reference.png"
    assert not service.comfy.submitted and service._task is None
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=10001", "limit=1.0",
                                    "limit=1e1", "limit=true", "limit=+1", "offset=9999999"])
@pytest.mark.parametrize("route", ["/runs", "/inputs"])
async def test_metadata_pagination_is_strict_and_bounded(tmp_path, query, route):
    service = make_service(tmp_path)
    async with client(service) as http:
        assert (await http.get(f"{route}?{query}")).status_code in {400, 422}
    await service.shutdown()


@pytest.mark.asyncio
async def test_run_collection_state_missing_video_and_unsafe_paths(tmp_path):
    service = make_service(tmp_path)
    first = admitted(service)
    second = admitted(service, seed=8)
    service.store.create(first)
    service.store.create(second)
    service.store.update(first.id, state="running")
    service.store.update(first.id, state="ready_for_review")
    service.store.update(second.id, state="failed")
    async with client(service) as http:
        page = (await http.get("/runs?limit=1&offset=0")).json()
        assert page["total"] == 2 and page["items"][0]["id"] == second.id
        assert page["items"][0]["video_url"] is None
        assert (await http.get("/runs?offset=1")).json()["items"][0]["video_url"] is None
        video = service.store.directory(first.id) / "chunk.mp4"
        video.write_bytes(b"encoded-video")
        service.store.update(first.id, output={"path": service.store.relative_artifact(first.id, "chunk.mp4")})
        result = (await http.get("/runs?offset=1")).json()
        assert result["items"][0]["video_url"] == f"/runs/{first.id}/video"
        response = await http.get(f"/runs/{first.id}/video", headers={"Range": "bytes=1-4"})
        assert response.status_code == 206 and response.content == b"ncod"
        service.store.update(first.id, output={"path": f".data/runs/{second.id}/chunk.mp4"})
        assert (await http.get("/runs")).status_code == 400  # Never turn unsafe metadata into 'missing'.
    await service.shutdown()


@pytest.mark.asyncio
async def test_manual_images_known_run_frames_and_metadata_only_catalog(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    base = tmp_path / ".data/inputs/nested"
    base.mkdir(parents=True)
    (base / "foto azul.png").write_bytes(b"manual encoded image")
    (base / "video.mp4").write_bytes(b"not an identity")
    (base / ".private.png").write_bytes(b"private")
    (base / "alias.png").symlink_to("foto azul.png")
    pending = tmp_path / ".data/inputs" / str(uuid4())
    pending.mkdir()
    (pending / ".part").write_bytes(b"failed upload evidence")
    (pending / "original.png").write_bytes(b"uncommitted")
    run = admitted(service)
    service.store.create(run)
    frame = service.store.directory(run.id) / "initial_frame.png"
    frame.write_bytes(b"encoded initial frame")
    service.store.update(run.id, state="failed")
    before = (service.store.directory(run.id) / "manifest.json").read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("catalog must not read/probe binary media")

    monkeypatch.setattr(service.media, "verify_image", forbidden)
    monkeypatch.setattr(service.media, "probe", forbidden)
    async with client(service) as http:
        page = (await http.get("/inputs")).json()
        assert page["total"] == 3
        items = {(item["source_root"], item["path"]): item for item in page["items"]}
        manual = items[("inputs", "nested/foto azul.png")]
        assert manual["width"] is None and manual["height"] is None
        assert manual["image_url"] == "/inputs/image?path=nested/foto%20azul.png"
        own = items[("runs", f".data/runs/{run.id}/initial_frame.png")]
        assert own["image_url"] == f"/runs/{run.id}/image?name=initial_frame.png"
        assert (await http.get(manual["image_url"])).content == b"manual encoded image"
        assert (await http.get(own["image_url"])).content == b"encoded initial frame"
        assert (await http.get("/runs")).json()["items"][0]["state"] == "failed"
        assert (await http.get("/runs")).json()["items"][0]["video_url"] is None
    assert (service.store.directory(run.id) / "manifest.json").read_bytes() == before
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../outside.png", "/etc/passwd", "nested/../photo.png", "a\\b.png", ".private.png",
                                   "metadata.json", "photo.mp4"])
@pytest.mark.parametrize("root", ["assets", "inputs"])
async def test_image_roots_do_not_expose_arbitrary_files(tmp_path, path, root):
    service = make_service(tmp_path)
    async with client(service) as http:
        response = await http.get(f"/{root}/image", params={"path": path})
        assert response.status_code in {400, 404}
    await service.shutdown()


@pytest.mark.asyncio
async def test_image_symlinks_fifo_and_run_uuid_allowlist(tmp_path):
    import os

    service = make_service(tmp_path)
    base = tmp_path / ".data/inputs"
    base.mkdir()
    (tmp_path / "outside.png").write_bytes(b"outside")
    (base / "alias.png").symlink_to(tmp_path / "outside.png")
    os.mkfifo(base / "pipe.png")
    run = admitted(service)
    service.store.create(run)
    (service.store.directory(run.id) / "initial_frame.png").symlink_to(tmp_path / "outside.png")
    async with client(service) as http:
        assert (await http.get("/inputs/image?path=alias.png")).status_code == 400
        assert (await http.get("/inputs/image?path=pipe.png")).status_code == 400
        assert (await http.get(f"/runs/{run.id}/image?name=initial_frame.png")).status_code == 400
        for name in ("chunk.mp4", "manifest.json", "../initial_frame.png", f"{uuid4()}/last_frame.png"):
            assert (await http.get(f"/runs/{run.id}/image", params={"name": name})).status_code == 400
        assert (await http.get("/runs/not-uuid/image?name=last_frame.png")).status_code == 400
        assert (await http.get(f"/runs/{uuid4()}/image?name=last_frame.png")).status_code == 404
    with pytest.raises(ValueError):
        service.store.reference_path("runs", f".data/runs/{run.id}/chunk.mp4")
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("format,suffix", [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")])
async def test_raw_upload_external_codec_original_bytes_and_no_inference(tmp_path, monkeypatch, format, suffix):
    service = make_service(tmp_path)
    data = encoded_image(format)

    async def forbidden_body(*args, **kwargs):
        pytest.fail("raw upload must stream, never call request.body()")

    monkeypatch.setattr(api.Request, "body", forbidden_body)

    async def chunks():
        for offset in range(0, len(data), 17):
            yield data[offset:offset + 17]

    name = '../../<img onerror="bad()"> café.wrong'
    async with client(service) as http:
        response = await http.post("/inputs", params={"name": name}, content=chunks(), headers={"Content-Type": "application/octet-stream"})
        assert response.status_code == 201, response.text
        item = response.json()
        assert item["source_root"] == "inputs" and item["path"].endswith(f"/original{suffix}")
        assert item["name"] == name and (item["width"], item["height"]) == (48, 64)
        original = service.store.reference_path("inputs", item["path"])
        assert original.read_bytes() == data
        metadata = json.loads((original.parent / "metadata.json").read_text())
        assert metadata["sha256"] == hashlib.sha256(data).hexdigest()
        assert not (original.parent / ".part").exists()
        assert (await http.get(item["image_url"])).content == data
        assert (await http.get("/inputs")).json()["total"] == 2
    assert not service.comfy.submitted and service._task is None
    assert not list(service.store.runs.iterdir())
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty", "corrupt", "oversize", "animated"])
async def test_invalid_upload_retains_part_without_catalog_publication(tmp_path, monkeypatch, failure):
    service = make_service(tmp_path)
    if failure == "empty":
        data = b""
    elif failure == "corrupt":
        data = b"not a PNG despite the MIME header"
    elif failure == "oversize":
        monkeypatch.setattr(api, "MAX_INPUT_BYTES", 32)
        data = b"x" * 33
    else:
        output = io.BytesIO()
        images = [Image.new("RGB", (48, 64), color) for color in ("red", "blue")]
        images[0].save(output, format="PNG", save_all=True, append_images=images[1:], duration=100, loop=0)
        data = output.getvalue()
    async with client(service) as http:
        response = await http.post("/inputs?name=pretend.png", content=data, headers={"Content-Type": "image/png"})
        assert response.status_code == (413 if failure == "oversize" else 400), response.text
        assert (await http.get("/inputs")).json()["total"] == 1
    directories = list((tmp_path / ".data/inputs").iterdir())
    assert len(directories) == 1 and (directories[0] / ".part").exists()
    assert not (directories[0] / "metadata.json").exists()
    assert not service.comfy.submitted and not list(service.store.runs.iterdir())
    await service.shutdown()


@pytest.mark.asyncio
async def test_upload_collision_never_replaces_existing_original_or_metadata(tmp_path):
    service = make_service(tmp_path)
    input_id, part = service.store.reserve_input()
    part.write_bytes(b"incoming")
    destination = part.parent / "original.png"
    destination.write_bytes(b"already owned")
    with pytest.raises(FileExistsError):
        service.store.publish_input(input_id, "untrusted.png", {"format": "PNG", "width": 1, "height": 1}, "a" * 64)
    assert destination.read_bytes() == b"already owned" and part.read_bytes() == b"incoming"
    assert not (part.parent / "metadata.json").exists()
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://outside.invalid", "null", "http://fake:81", "http://fake:0", "http://fake@outside.invalid", "http://fake/path"])
async def test_browser_mutations_require_same_origin_but_cli_remains_compatible(tmp_path, origin):
    service = make_service(tmp_path)
    async with client(service) as http:
        for route, body in (("/inputs", b"not materialized"), ("/runs", b'{}'), (f"/runs/{uuid4()}/accept", b"")):
            response = await http.post(route, content=body, headers={"Origin": origin})
            assert response.status_code == 403
        assert (await http.get("/app/config", headers={"Origin": origin})).status_code == 200
        assert (await http.post("/runs", json={"seed": 7}, headers={"Origin": "http://fake"})).status_code == 202
        await service._task
    assert len(service.comfy.submitted) == 1 and not (tmp_path / ".data/inputs").exists()
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"references": [{"source_root": "pc", "path": "photo.png"}]},
    {"references": [{"source_root": "inputs", "path": "../photo.png"}]},
    {"references": [{"source_root": "inputs", "path": "a\\b.png"}]},
    {"references": [{"source_root": "inputs", "path": "./photo.png"}]},
    {"references": [{"source_root": "inputs", "path": "a//photo.png"}]},
    {"references": [{"source_root": "inputs", "path": "photo.png", "url": "outside"}]},
    {"references": [{"source_root": "inputs", "path": "photo.png"}], "images": ["other.png"]},
    {"references": [{"source_root": "inputs", "path": "photo.png"}], "image": "other.png"},
    {"references": [{"source_root": "inputs", "path": "photo.png"}] * 9},
])
async def test_typed_references_are_bounded_exclusive_and_path_only(tmp_path, payload):
    service = make_service(tmp_path)
    async with client(service) as http:
        assert (await http.post("/runs/i2v", json={"seed": 7, **payload})).status_code == 422
    assert not service.comfy.submitted and not list(service.store.runs.iterdir())
    await service.shutdown()


def configure_native_builder(service, profile):
    service.builder = WorkflowBuilder(Path(__file__).resolve().parents[1], output_profile=profile)
    graph = service.builder.baseline_for("v2v")
    info = {node["class_type"]: {"input": {"required": {}}} for node in graph.values()}
    for node_id, field in (("171:4", "unet_name"), ("171:3", "clip_name"), ("171:2", "vae_name"),
                           ("171:1", "vae_name"), ("22:6", "sampler_name"), ("22:7", "scheduler"),
                           ("18", "format"), ("34", "format")):
        node = graph[node_id]
        choices = info[node["class_type"]]["input"]["required"].setdefault(field, [[]])[0]
        if node["inputs"][field] not in choices:
            choices.append(node["inputs"][field])

    async def object_info():
        return info

    service.comfy.object_info = object_info
    service.media.verify_image = media.verify_image


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["baseline", "final_only"])
async def test_uploaded_original_flows_through_native_i2v_and_continuation_unchanged(tmp_path, profile):
    from test_benchmark import benchmark

    service = make_service(tmp_path)
    configure_native_builder(service, profile)
    await service.startup()
    data = encoded_image()
    digest = hashlib.sha256(data).hexdigest()
    async with client(service) as http:
        item = (await http.post("/inputs?name=original.png", content=data)).json()
        assert not service.comfy.submitted
        payload = benchmark.STAGES[0].request()
        payload.pop("image")
        payload["references"] = [{"source_root": "inputs", "path": item["path"]}]
        response = await http.post("/runs/i2v", json=payload)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        snapshot = service.store.request(run_id)
        ready = (await http.get(f"/runs/{run_id}?wait=true")).json()
        assert ready["state"] == "ready_for_review" and ready["references"][0]["sha256"] == digest
        assert service.store.request(run_id) == snapshot
        assert I2VPipe.from_run(service, snapshot).state.request.references[0].path == item["path"]
        for stage in benchmark.STAGES[1:]:
            assert (await http.post(f"/runs/{run_id}/accept")).status_code == 200
            response = await http.post(f"/runs/{run_id}/v2v", json=stage.request())
            assert response.status_code == 202, response.text
            run_id = response.json()["id"]
            final = (await http.get(f"/runs/{run_id}?wait=true")).json()
            assert final["state"] == "ready_for_review" and final["seed"] == stage.seed
            assert final["prompt"] == stage.prompt and final["duration_seconds"] == 2.3
            assert final["references"][0]["input_info"]["frame_index"] == 55
            original = final["references"][1]
            assert original["role"] == "identity" and original["source_root"] == "inputs"
            assert original["source"] == item["path"] and original["sha256"] == digest
            assert final["references"][-1]["has_audio"] is True
            graph = json.loads((service.store.directory(run_id) / "workflow_api.json").read_text())
            assert graph["272"]["inputs"]["frame_idx"] == 0
            assert graph["16"]["inputs"]["seed"] == stage.seed
        assert (await http.get(f"/runs/{run_id}")).json()["state"] == "ready_for_review"
    assert service.store.reference_path("inputs", item["path"]).read_bytes() == data
    assert len(service.comfy.submitted) == 3
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["inputs", "runs"])
async def test_manual_or_owned_run_frame_can_be_explicit_new_identity(tmp_path, category):
    service = make_service(tmp_path)
    data = encoded_image()
    if category == "inputs":
        directory = tmp_path / ".data/inputs/manual"
        directory.mkdir(parents=True)
        path = "manual/photo.png"
        (directory / "photo.png").write_bytes(data)
    else:
        source = admitted(service)
        service.store.create(source)
        service.store.update(source.id, state="failed")
        path = service.store.relative_artifact(source.id, "last_frame.png")
        (service.store.directory(source.id) / "last_frame.png").write_bytes(data)
    service.media.verify_image = media.verify_image
    run = await service.create(RunRequest(seed=7, references=[{"source_root": category, "path": path}]))
    await service._task
    current = service.store.get(run.id)
    assert current.state == "ready_for_review"
    assert current.references[0]["source_root"] == category
    assert current.references[0]["source"] == path and current.references[0]["sha256"] == hashlib.sha256(data).hexdigest()
    await service.shutdown()


def test_verified_legacy_run_image_alias_resolves_only_to_own_data_copy(tmp_path):
    from test_data_storage import legacy, migration

    from h3_backend.infrastructure.store import Store

    run = legacy(tmp_path)
    original = tmp_path / "runs" / run.id / "last_frame.png"
    original.write_bytes(encoded_image())
    before = original.read_bytes()
    migration.migrate(tmp_path, execute=True, offline=True)
    store = Store(tmp_path)
    expected = tmp_path / ".data/runs" / run.id / "last_frame.png"
    assert store.reference_path("runs", f"runs/{run.id}/last_frame.png") == expected
    assert store.reference_path("runs", f".data/runs/{run.id}/last_frame.png") == expected
    assert original.read_bytes() == expected.read_bytes() == before
    with pytest.raises(ValueError):
        store.reference_path("runs", f"runs/{run.id}/chunk.mp4")


@pytest.mark.asyncio
async def test_publication_crash_hides_original_and_retains_evidence(tmp_path, monkeypatch):
    import os

    service = make_service(tmp_path)
    input_id, part = service.store.reserve_input()
    part.write_bytes(encoded_image())
    link = os.link

    def fail_marker(source, destination):
        if destination.name == "metadata.json":
            raise OSError("fake marker publication crash")
        return link(source, destination)

    monkeypatch.setattr(os, "link", fail_marker)
    with pytest.raises(OSError, match="publication crash"):
        service.store.publish_input(input_id, "original.png", {"format": "PNG", "width": 48, "height": 64}, "a" * 64)
    assert part.is_file() and (part.parent / "original.png").is_file()
    assert not (part.parent / "metadata.json").exists()
    async with client(service) as http:
        assert (await http.get("/inputs")).json()["total"] == 1
        assert (await http.get("/inputs/image", params={"path": f"{input_id}/original.png"})).status_code == 400
    await service.shutdown()


@pytest.mark.asyncio
async def test_mixed_categories_hydrate_without_io_and_distinct_identity_paths(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    base = tmp_path / ".data/inputs"
    base.mkdir()
    (base / "dance_reference.png").write_bytes(b"different-original-identity")
    request = RunRequest(seed=7, references=[{"source_root": "assets", "path": "dance_reference.png"},
                                            {"source_root": "inputs", "path": "dance_reference.png"}])
    run = await service.create(request)
    snapshot = service.store.request(run.id)
    await service._task

    def forbidden(*args, **kwargs):
        pytest.fail("hydration performed filesystem/media I/O")

    monkeypatch.setattr(service.store, "reference_path", forbidden)
    monkeypatch.setattr(service.media, "verify_image", forbidden)
    pipe = I2VPipe.from_run(service, snapshot)
    assert [ref.source_root for ref in pipe.state.request.references] == ["assets", "inputs"]
    assert [ref["source_root"] for ref in pipe.state.run.references] == ["assets", "inputs"]
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_reference_catalog_capacity_does_not_create_jobs(tmp_path, monkeypatch):
    service = make_service(tmp_path)

    def too_many(base):
        for _ in range(10001):
            yield base / "dance_reference.png"

    monkeypatch.setattr(service.store, "_image_files", too_many)
    async with client(service) as http:
        response = await http.get("/inputs")
        assert response.status_code == 400 and "capacity" in response.json()["detail"]
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_input_mutation_after_admission_fails_before_comfy_upload(tmp_path):
    service = make_service(tmp_path)
    base = tmp_path / ".data/inputs"
    base.mkdir()
    source = base / "photo.png"
    source.write_bytes(encoded_image())
    run = await service.create(RunRequest(seed=7, references=[{"source_root": "inputs", "path": "photo.png"}]))
    source.write_bytes(b"tampered after admission")
    await service._task
    assert service.store.get(run.id).state == "failed"
    assert not service.comfy.uploads and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_sse_finite_hints_are_path_only_initial_and_close_source(tmp_path):
    service = make_service(tmp_path)

    class Watcher:
        closed = False

        async def events(self):
            try:
                for path in (".data", ".data/inputs/metadata.json", '.data/inputs/quote".png'):
                    yield path
            finally:
                self.closed = True

    watcher = service.watcher = Watcher()
    async with client(service) as http:
        response = await http.get("/events")
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        frames = response.text.strip().split("\n\n")
        assert len(frames) == 3
        for frame in frames:
            assert frame.startswith("event: change\ndata: ")
            value = json.loads(frame.split("data: ")[1])
            assert set(value) == {"path", "invalidation"} and value["invalidation"] is True
        assert json.loads(frames[0].split("data: ")[1])["path"] == ".data"
    assert watcher.closed and not service.comfy.submitted
    service.watcher = None
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("slow", [False, True])
async def test_real_shared_sse_disconnect_or_overflow_cleans_subscription(tmp_path, slow):
    service = make_service(tmp_path)
    await service.startup()
    watcher = service.watcher
    app = api.create_app(service=service)
    disconnected = asyncio.Event()
    received = False
    frames = []

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            frames.append(message["body"])
            if slow:
                for _ in range(100):
                    watcher._emit(".data/inputs/metadata.json")
            else:
                disconnected.set()

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
             "http_version": "1.1", "method": "GET", "scheme": "http", "path": "/events",
             "raw_path": b"/events", "query_string": b"", "headers": [(b"host", b"fake")],
             "server": ("fake", 80), "client": ("client", 1), "root_path": ""}
    async with asyncio.timeout(3):
        await app(scope, receive, send)
    assert frames and b'"path": ".data"' in frames[0]
    assert not watcher._subscribers and service.watcher is watcher
    assert service._task is None and not service.comfy.submitted
    await service.shutdown()
    assert watcher.fd is None
