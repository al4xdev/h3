"""Continuation proofs use temporary CPU media and fake provider factories only."""

import asyncio
import base64
import hashlib
import json
import os
import subprocess
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_grok_multimodal import FakeManager, fixture_image, never, response

from h3_backend.grok import FIXED_EDITOR_MODEL, Grok, PromptRequest, router
from h3_backend.infrastructure import grok_image
from h3_backend.infrastructure.grok_image import continuation_frame
from h3_backend.infrastructure.grok_oauth import OAuthError
from h3_backend.infrastructure.media import prepare_last_frame


def command(*args):
    result = subprocess.run(args, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout


def parent_fixture(root):
    ident = str(uuid4())
    image = root / "assets/original.jpg"
    original = fixture_image(image)
    video = root / ".data/runs" / ident / "chunk.mp4"
    video.parent.mkdir(parents=True)
    command("ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
            "testsrc2=size=32x32:rate=4:duration=1", "-c:v", "libx264", "-threads", "1",
            "-pix_fmt", "yuv420p", str(video))
    reference = {"source_root": "assets", "path": "original.jpg"}
    manifest = {"id": ident, "state": "accepted", "decision": {"accepted": True},
                "publication_mode": "atomic_copy_from_comfy_output", "error": None,
                "output": {"path": f".data/runs/{ident}/chunk.mp4",
                           "source": "/private/comfy/NEVER-read.mp4"},
                "references": [{"type": "image", "role": "identity", "source_root": "assets",
                                "source": "original.jpg", "sha256": hashlib.sha256(original).hexdigest()}]}
    marker = video.parent / "manifest.json"
    marker.write_text(json.dumps(manifest))
    return ident, reference, video, marker


def rgb_hash(path):
    return command("ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-pix_fmt",
                   "rgb24", "-f", "hash", "-hash", "sha256", "-")


async def test_final_decoded_frame_matches_native_without_legacy_frame(tmp_path):
    ident, _, video, marker = parent_fixture(tmp_path)
    before = video.read_bytes(), marker.read_bytes()
    native = tmp_path / "native.png"
    await prepare_last_frame(video, native)
    async with continuation_frame(tmp_path, ident) as (frame, _, _):
        derived = tmp_path / "derived.png"
        derived.write_bytes(frame.read())  # Tiny fixture bytes, no Python pixel decode.
        assert rgb_hash(native) == rgb_hash(derived)
    assert not (video.parent / "last_frame.png").exists()
    assert (video.read_bytes(), marker.read_bytes()) == before
    assert not list((tmp_path / ".dumps/grok-editor").iterdir())


def test_preview_cpu_only_no_auth_provider_or_business_writes(tmp_path, monkeypatch):
    ident, _, video, marker = parent_fixture(tmp_path)
    before = video.read_bytes(), marker.read_bytes()
    monkeypatch.setenv("H3_PROJECT_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        app.state.grok.manager.client_factory = lambda: pytest.fail("Unexpected OAuth/provider")
        result = client.get(f"/grok/continuation/{ident}/last-frame")
        assert result.status_code == 200
        assert result.headers["content-type"] == "image/png"
        assert len(result.content) == int(result.headers["content-length"])
        assert result.content.startswith(b"\x89PNG")
        assert result.headers["cache-control"] == "no-store"
        assert client.get("/grok/continuation/not-a-uuid/last-frame").status_code == 400
    assert (video.read_bytes(), marker.read_bytes()) == before
    assert not (tmp_path / ".data/grok").exists()
    assert not (video.parent / "last_frame.png").exists()


async def test_two_flat_images_order_labels_literal_prompt_and_content_length(tmp_path):
    ident, reference, _, _ = parent_fixture(tmp_path)
    original = (tmp_path / "assets/original.jpg").read_bytes()
    seen = []
    def handler(request):
        wire = request.content
        assert len(wire) == int(request.headers["content-length"])
        body = json.loads(wire)
        seen.append(body)
        assert body["input"][0] == {"role": "system", "content": 'custom "sistema"\n'}
        content = body["input"][1]["content"]
        assert content[0]["text"] == grok_image.CONTINUATION_LABEL
        assert content[-1] == {"type": "input_text", "text": 'literal "ação"\n '}
        images = [part["image_url"] for part in content if part["type"] == "input_image"]
        assert len(images) == 2
        assert images[0].startswith("data:image/jpeg;base64,")
        assert base64.b64decode(images[0].split(",")[1]) == original
        frame = base64.b64decode(images[1].split(",")[1])
        assert images[1].startswith("data:image/png;base64,") and frame.startswith(b"\x89PNG")
        assert frame != original
        assert body["model"] == FIXED_EDITOR_MODEL
        assert body["store"] is False and body["stream"] is False
        assert body["max_output_tokens"] == 8192
        return httpx.Response(200, json=response())
    manager = FakeManager(handler)
    result = await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
        prompt='literal "ação"\n ', system_prompt='custom "sistema"\n', reference=reference,
        continuation_parent_id=ident))
    assert result["text"] == "cena" and len(seen) == manager.catalogues == 1
    assert not (tmp_path / ".data/grok").exists()


@pytest.mark.parametrize("case", [
    "missing", "corrupt", "failed", "rejected", "not-accepted", "decision", "manifest-id",
    "publication", "path", "video-missing", "video-link", "manifest-link", "video-hardlink",
    "video-corrupt", "huge-video", "huge-metadata", "role", "multi-identity", "type",
    "identity-sha", "identity-path", "identity-root", "image-link", "image-corrupt",
])
async def test_parent_failures_before_auth(tmp_path, case):
    ident, reference, video, marker = parent_fixture(tmp_path)
    manifest = json.loads(marker.read_text())
    if case == "missing":
        marker.unlink()
    elif case == "corrupt":
        marker.write_bytes(b"not-json")
    elif case in ("failed", "rejected", "not-accepted"):
        manifest["state"] = "ready_for_review" if case == "not-accepted" else case
    elif case == "decision":
        manifest["decision"]["accepted"] = False
    elif case == "manifest-id":
        manifest["id"] = str(uuid4())
    elif case == "publication":
        manifest["publication_mode"] = None
    elif case == "path":
        manifest["output"]["path"] = "/private/comfy/video.mp4"
    elif case == "video-missing":
        video.unlink()
    elif case == "video-link":
        video.unlink()
        video.symlink_to(tmp_path / "outside.mp4")
    elif case == "manifest-link":
        marker.unlink()
        marker.symlink_to(tmp_path / "outside.json")
    elif case == "video-hardlink":
        os.link(video, tmp_path / "other.mp4")
    elif case == "video-corrupt":
        video.write_bytes(b"not-video")
    elif case == "huge-video":
        with video.open("r+b") as stream:
            stream.truncate(grok_image.VIDEO_MAX_BYTES + 1)
    elif case == "huge-metadata":
        marker.write_bytes(b"x" * (grok_image.METADATA_MAX_BYTES + 1))
    elif case == "role":
        manifest["references"][0]["role"] = "initial_frame"
    elif case == "multi-identity":
        manifest["references"].append(dict(manifest["references"][0]))
    elif case == "type":
        manifest["references"][0]["type"] = "video"
    elif case == "identity-sha":
        manifest["references"][0]["sha256"] = "0" * 64
    elif case == "identity-path":
        manifest["references"][0]["source"] = "other.jpg"
    elif case == "identity-root":
        manifest["references"][0]["source_root"] = "inputs"
    elif case == "image-link":
        image = tmp_path / "assets/original.jpg"
        image.unlink()
        image.symlink_to(tmp_path / "outside.jpg")
    elif case == "image-corrupt":
        (tmp_path / "assets/original.jpg").write_bytes(b"not-image")
    if case in ("failed", "rejected", "not-accepted", "decision", "manifest-id", "publication",
                "path", "role", "multi-identity", "type", "identity-sha", "identity-path", "identity-root"):
        marker.write_text(json.dumps(manifest))
    manager = FakeManager(never)
    with pytest.raises(OAuthError) as error:
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert error.value.status == 400 and manager.catalogues == 0


@pytest.mark.parametrize("parent_id", ["", "not-a-uuid", "A" * 36,
                                       "00000000000000000000000000000000", 3])
def test_invalid_uuid(parent_id):
    with pytest.raises(ValidationError):
        PromptRequest(prompt="idea", reference={"source_root": "assets", "path": "original.jpg"},
                      continuation_parent_id=parent_id)


def test_parent_requires_original_reference():
    with pytest.raises(ValidationError):
        PromptRequest(prompt="idea", continuation_parent_id=str(uuid4()))


@pytest.mark.parametrize("case", ["manifest", "video", "identity"])
async def test_post_snapshot_publication_replacement_fails_before_auth(tmp_path, monkeypatch, case):
    ident, reference, video, marker = parent_fixture(tmp_path)
    native = grok_image._final_frame
    async def raced_decode(*args):
        await native(*args)
        if case == "manifest":
            manifest = json.loads(marker.read_text())
            manifest["state"] = "rejected"
            marker.write_text(json.dumps(manifest))
        elif case == "video":
            replacement = tmp_path / "replacement.mp4"
            replacement.write_bytes(video.read_bytes())
            replacement.replace(video)
        else:
            (tmp_path / "assets/original.jpg").write_bytes(b"changed")
    monkeypatch.setattr(grok_image, "_final_frame", raced_decode)
    manager = FakeManager(never)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert manager.catalogues == 0


async def test_cancel_second_snapshot_closes_all_files(tmp_path, monkeypatch):
    ident, reference, _, _ = parent_fixture(tmp_path)
    snapshots = []
    temporary = grok_image.tempfile.TemporaryFile
    def tracked(*args, **kwargs):
        stream = temporary(*args, **kwargs)
        snapshots.append(stream)
        return stream
    monkeypatch.setattr(grok_image.tempfile, "TemporaryFile", tracked)
    started = asyncio.Event()
    async def blocked(*args):
        started.set()
        await asyncio.Future()
    monkeypatch.setattr(grok_image, "_final_frame", blocked)
    manager = FakeManager(never)
    task = asyncio.create_task(Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
        prompt="idea", reference=reference, continuation_parent_id=ident)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(snapshots) == 3 and all(stream.closed for stream in snapshots)
    assert manager.catalogues == 0


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_continuation_provider_errors_no_retries(tmp_path, status):
    ident, reference, _, _ = parent_fixture(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status)
    manager = FakeManager(handler)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert len(requests) == manager.catalogues == 1
    assert not list((tmp_path / ".dumps/grok-editor").iterdir())


async def test_decoded_frame_budget_rejects_before_auth(tmp_path, monkeypatch):
    ident, reference, _, _ = parent_fixture(tmp_path)
    monkeypatch.setattr(grok_image, "VIDEO_MAX_FRAMES", 3)
    manager = FakeManager(never)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert manager.catalogues == 0


async def test_animated_identity_rejected_before_auth(tmp_path):
    ident, reference, _, marker = parent_fixture(tmp_path)
    image = tmp_path / "assets/original.jpg"
    image.write_bytes(image.read_bytes() * 2)
    manifest = json.loads(marker.read_text())
    manifest["references"][0]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    marker.write_text(json.dumps(manifest))
    manager = FakeManager(never)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert manager.catalogues == 0


async def test_identical_manifest_replacement_fails_closed(tmp_path, monkeypatch):
    ident, reference, _, marker = parent_fixture(tmp_path)
    native = grok_image._final_frame
    async def replace_manifest(*args):
        await native(*args)
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(marker.read_bytes())
        replacement.replace(marker)
    monkeypatch.setattr(grok_image, "_final_frame", replace_manifest)
    manager = FakeManager(never)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert manager.catalogues == 0


async def test_video_replacement_during_copy_fails_closed(tmp_path, monkeypatch):
    ident, reference, video, _ = parent_fixture(tmp_path)
    read = grok_image.os.read
    replaced = False
    def raced_read(fd, size):
        nonlocal replaced
        block = read(fd, size)
        if not replaced and b"ftyp" in block[:32]:
            replaced = True
            replacement = tmp_path / "replacement.mp4"
            replacement.write_bytes(video.read_bytes())
            replacement.replace(video)
        return block
    monkeypatch.setattr(grok_image.os, "read", raced_read)
    manager = FakeManager(never)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert replaced and manager.catalogues == 0


async def test_preview_disconnect_closes_snapshots(tmp_path, monkeypatch):
    from contextlib import AsyncExitStack

    from h3_backend.grok import ContinuationPreview

    ident, _, _, _ = parent_fixture(tmp_path)
    snapshots = []
    temporary = grok_image.tempfile.TemporaryFile
    def tracked(*args, **kwargs):
        stream = temporary(*args, **kwargs)
        snapshots.append(stream)
        return stream
    monkeypatch.setattr(grok_image.tempfile, "TemporaryFile", tracked)
    stack = AsyncExitStack()
    frame, _, _ = await stack.enter_async_context(continuation_frame(tmp_path, ident))
    preview = ContinuationPreview(frame, stack)
    first_chunk = asyncio.Event()
    sent = []
    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body":
            first_chunk.set()
            await asyncio.Future()
    async def receive():
        await first_chunk.wait()
        return {"type": "http.disconnect"}
    await preview({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
    assert sent[0]["type"] == "http.response.start"
    assert len(snapshots) == 2 and all(stream.closed for stream in snapshots)
    assert not list((tmp_path / ".dumps/grok-editor").iterdir())


@pytest.mark.parametrize("tail", [0, 1, 2])
async def test_two_image_encoded_stream_bounded_exact_length(tmp_path, tail):
    with grok_image._snapshot(tmp_path) as first, grok_image._snapshot(tmp_path) as second:
        for snapshot in (first, second):
            for _ in range(101):
                snapshot.write(b"x" * grok_image.BUFFER_BYTES)
            snapshot.write(b"a" * tail)
            snapshot.seek(0)
        body, length = grok_image.images_json_body("pin", "system", "literal", [
            (first, "image/jpeg"), (second, "image/png")])
        total = count = 0
        async for chunk in body:
            assert len(chunk) <= grok_image.BUFFER_BYTES * 4 // 3
            total += len(chunk)
            count += 1
        assert total == length and count > 200


async def test_provider_cancel_closes_both_images_and_video(tmp_path, monkeypatch):
    ident, reference, _, _ = parent_fixture(tmp_path)
    snapshots = []
    temporary = grok_image.tempfile.TemporaryFile
    def tracked(*args, **kwargs):
        stream = temporary(*args, **kwargs)
        snapshots.append(stream)
        return stream
    monkeypatch.setattr(grok_image.tempfile, "TemporaryFile", tracked)
    started = asyncio.Event()
    async def handler(request):
        started.set()
        await asyncio.Future()
    manager = FakeManager(handler)
    task = asyncio.create_task(Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
        prompt="idea", reference=reference, continuation_parent_id=ident)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(snapshots) == 3 and all(stream.closed for stream in snapshots)
    assert manager.catalogues == 1


def migrated_video_proof(root, ident, video, marker):
    manifest = json.loads(marker.read_text())
    manifest["output"]["path"] = f"runs/{ident}/chunk.mp4"
    manifest["publication_mode"] = None
    marker.write_text(json.dumps(manifest))
    migration_id = str(uuid4())
    inventory = {"run_ids": [ident], "files": {f"{ident}/chunk.mp4": {
        "sha256": hashlib.sha256(video.read_bytes()).hexdigest(), "bytes": video.stat().st_size}}}
    receipt = {"id": migration_id, "schema_version": 1, "state": "complete", "root": str(root),
               "destination": ".data/runs", "run_ids": [ident], "inventory": inventory,
               "inventory_sha256": hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()}
    for path in (root / ".data/state/migration.json",
                 root / f".data/migrations/{migration_id}/verified.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt))


async def test_legacy_alias_reads_only_verified_canonical_video(tmp_path):
    ident, reference, video, marker = parent_fixture(tmp_path)
    migrated_video_proof(tmp_path, ident, video, marker)
    requests = []
    manager = FakeManager(lambda request: (requests.append(request)
                                          or httpx.Response(200, json=response())))
    result = await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
        prompt="idea", reference=reference, continuation_parent_id=ident))
    assert result["text"] == "cena" and len(requests) == manager.catalogues == 1
    assert not (tmp_path / "runs").exists()
    assert not (video.parent / "last_frame.png").exists()


@pytest.mark.parametrize("case", ["missing", "mismatch", "video-sha"])
async def test_legacy_alias_requires_verified_video_sha(tmp_path, case):
    ident, reference, video, marker = parent_fixture(tmp_path)
    migrated_video_proof(tmp_path, ident, video, marker)
    receipt = tmp_path / ".data/state/migration.json"
    if case == "missing":
        receipt.unlink()
    elif case == "mismatch":
        receipt.write_bytes(b"{}")
    else:
        video.write_bytes(video.read_bytes() + b"changed")
    manager = FakeManager(never)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert manager.catalogues == 0


async def test_large_literal_text_envelope_also_streams_bounded(tmp_path):
    with grok_image._snapshot(tmp_path) as first, grok_image._snapshot(tmp_path) as second:
        for snapshot in (first, second):
            snapshot.write(b"encoded")
            snapshot.seek(0)
        literal = "ação" * 25000
        body, length = grok_image.images_json_body("pin", "custom" * 16000, literal,
                                                  [(first, "image/jpeg"), (second, "image/png")])
        chunks = [chunk async for chunk in body]
        assert all(len(chunk) <= grok_image.BUFFER_BYTES for chunk in chunks)
        wire = b"".join(chunks)  # Bounded fixture envelope, not runtime materialization.
        assert len(wire) == length
        assert json.loads(wire)["input"][-1]["content"][-1]["text"] == literal


async def test_nonprivate_scratch_rejects_before_auth(tmp_path):
    ident, reference, _, _ = parent_fixture(tmp_path)
    directory = tmp_path / ".dumps/grok-editor"
    directory.mkdir(parents=True)
    directory.chmod(0o755)
    manager = FakeManager(never)
    with pytest.raises(OAuthError):
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference=reference, continuation_parent_id=ident))
    assert manager.catalogues == 0 and not list(directory.iterdir())


async def test_cancel_real_two_descriptor_child_creation_reaps(tmp_path, monkeypatch):
    create = asyncio.create_subprocess_exec
    spawned, release = asyncio.Event(), asyncio.Event()
    processes = []
    async def delayed_create(*args, **kwargs):
        process = await create(*args, **kwargs)
        processes.append(process)
        spawned.set()
        await release.wait()
        return process
    monkeypatch.setattr(grok_image.asyncio, "create_subprocess_exec", delayed_create)
    with grok_image._snapshot(tmp_path) as first, grok_image._snapshot(tmp_path) as output:
        task = asyncio.create_task(grok_image._command(
            (first.fileno(), output.fileno()), "ffmpeg", "-v", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=red:s=16x16", "-frames:v", "1", "-threads", "1",
            "-c:v", "png", "-f", "image2pipe", f"/proc/self/fd/{output.fileno()}"))
        try:
            await spawned.wait()
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(processes) == 1 and processes[0].returncode is not None
        finally:
            release.set()
            for process in processes:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
