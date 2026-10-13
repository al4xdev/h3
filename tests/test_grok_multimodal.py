"""Offline/temp-root editor contracts; no provider, production data or generation imports."""

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from h3_backend.grok import (
    DEFAULT_EDITOR_SYSTEM,
    FIXED_EDITOR_MODEL,
    EditorConfig,
    Grok,
    PromptRequest,
    invoke,
    router,
    save_editor,
    seed_editor,
)
from h3_backend.infrastructure import grok_image
from h3_backend.infrastructure.grok_image import (
    BUFFER_BYTES,
    IMAGE_MAX_BYTES,
    EditorReference,
    image_json_body,
    owned_image,
)
from h3_backend.infrastructure.grok_oauth import OAuthError


def fixture_image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=red:s=16x16",
        "-frames:v", "1", "-threads", "1", "-update", "1", str(path),
    ], check=False, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode()
    return path.read_bytes()  # Only a tiny test fixture, never the runtime encoder.


def response():
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "status": "completed", "content": [{"type": "output_text", "text": "cena"}]}]}


class FakeManager:
    def __init__(self, handler, model=FIXED_EDITOR_MODEL):
        self.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.model = model
        self.catalogues = 0

    async def authorized_models(self, client, *, recover):
        assert recover is False
        self.catalogues += 1
        return SimpleNamespace(access="fake-private-access"), [{"id": self.model}]


def never(request):
    pytest.fail("Unexpected fake provider submission")


def input_fixture(root, *, corrupt=False, partial=False):
    ident = str(uuid4())
    path = root / ".data" / "inputs" / ident / "original.png"
    data = fixture_image(path)
    metadata = {"id": ident, "source_root": "inputs", "path": f"{ident}/original.png",
                "sha256": hashlib.sha256(data).hexdigest() if not corrupt else "0" * 64}
    (path.parent / "metadata.json").write_text(json.dumps(metadata))
    if partial:
        (path.parent / ".part").write_bytes(b"incomplete")
    return EditorReference(source_root="inputs", path=metadata["path"]), path


def run_fixture(root, *, migrated=False, legacy=False, frame="initial_frame.png"):
    ident = str(uuid4())
    path = root / ".data" / "runs" / ident / frame
    data = fixture_image(path)
    source = f".data/runs/{ident}/{frame}"
    digest = hashlib.sha256(data).hexdigest()
    references = [] if migrated else [{"type": "image", "source_root": "runs",
                                       "source": source, "sha256": digest}]
    (path.parent / "manifest.json").write_text(json.dumps({"id": ident, "references": references}))
    if migrated:
        migration_id = str(uuid4())
        inventory = {"run_ids": [ident], "files": {f"{ident}/{frame}": {"sha256": digest,
                                                                 "bytes": len(data)}}}
        receipt = {"id": migration_id, "schema_version": 1, "state": "complete",
                   "root": str(root), "destination": ".data/runs", "run_ids": [ident],
                   "inventory": inventory,
                   "inventory_sha256": hashlib.sha256(
                       json.dumps(inventory, sort_keys=True).encode()).hexdigest()}
        for marker in (root / ".data/state/migration.json",
                       root / f".data/migrations/{migration_id}/verified.json"):
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(receipt))
    return EditorReference(source_root="runs", path=f"runs/{ident}/{frame}" if legacy else source), path


def test_seed_pin_inert_restart_and_no_clobber(tmp_path, monkeypatch):
    monkeypatch.setenv("H3_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("H3_GROK_MODEL", "different-env")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        app.state.grok.manager.client_factory = lambda: pytest.fail("Unexpected network")
        assert client.get("/grok/editor").json()["model"] == "different-env"
        assert not (tmp_path / ".data").exists()
    assert seed_editor(tmp_path).model == FIXED_EDITOR_MODEL
    path = tmp_path / ".data/grok/editor.json"
    before = path.read_bytes()
    inode = path.stat().st_ino
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_nlink == 1
    assert seed_editor(tmp_path).model == FIXED_EDITOR_MODEL
    assert path.read_bytes() == before and path.stat().st_ino == inode
    with TestClient(app) as client:
        app.state.grok.manager.client_factory = lambda: pytest.fail("Unexpected network")
        assert client.get("/grok/editor").json()["model"] == FIXED_EDITOR_MODEL
        assert client.post("/grok", json={"prompt": "idea", "model": "different"}).json()["error"] == "model_fixed"
        assert client.put("/grok/editor", json={"system_prompt": "new"}).json() == {
            "system_prompt": "new", "model": FIXED_EDITOR_MODEL,
        }
        assert client.put("/grok/editor", json={"system_prompt": "newer", "model": ""}).status_code == 409
        assert client.put("/grok/editor", json={"system_prompt": "newer", "model": "wrong"}).status_code == 409
        assert client.get("/grok/editor").json()["system_prompt"] == "new"


def test_seed_preserves_existing_different_and_corrupt(tmp_path):
    save_editor(tmp_path, EditorConfig(system_prompt="owner", model="different-owner-model"))
    assert seed_editor(tmp_path).model == "different-owner-model"
    path = tmp_path / ".data/grok/editor.json"
    path.write_bytes(b"invalid")
    with pytest.raises(ValueError):
        seed_editor(tmp_path)
    assert path.read_bytes() == b"invalid"


def test_seed_publication_race_preserves_winner(tmp_path, monkeypatch):
    real_link = os.link
    def raced_link(*args, **kwargs):
        directory = kwargs["dst_dir_fd"]
        fd = os.open("editor.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
        with os.fdopen(fd, "w") as stream:
            stream.write('{"system_prompt":"other writer","model":"other"}')
        return real_link(*args, **kwargs)
    monkeypatch.setattr(os, "link", raced_link)
    assert seed_editor(tmp_path).model == "other"
    assert sorted(p.name for p in (tmp_path / ".data/grok").iterdir()) == ["editor.json"]


async def test_persisted_model_authority_reload_and_early_mismatch(tmp_path):
    seed_editor(tmp_path)
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    manager = FakeManager(handler)
    grok = Grok(manager, "wrong-env", root=tmp_path)
    assert (await grok.complete(PromptRequest(prompt="idea")))["model"] == FIXED_EDITOR_MODEL
    assert seen[0]["model"] == FIXED_EDITOR_MODEL
    with pytest.raises(OAuthError) as error:
        await grok.complete(PromptRequest(prompt="idea", model="override"))
    assert error.value.code == "model_fixed" and manager.catalogues == 1
    path = tmp_path / ".data/grok/editor.json"
    path.write_text('{"system_prompt":"admin change","model":"new-admin-pin"}')
    manager.model = "new-admin-pin"
    assert (await grok.complete(PromptRequest(prompt="idea")))["model"] == "new-admin-pin"
    path.write_bytes(b"invalid")
    with pytest.raises(OAuthError) as error:
        await grok.complete(PromptRequest(prompt="idea"))
    assert error.value.code == "editor_storage_error" and manager.catalogues == 2


async def test_missing_config_legacy_text_contract(tmp_path):
    seen = []
    manager = FakeManager(lambda request: (seen.append(json.loads(request.content))
                                         or httpx.Response(200, json=response())), model="legacy")
    result = await Grok(manager, "legacy", root=tmp_path).complete(PromptRequest(prompt="idea"))
    assert result == {"text": "cena", "model": "legacy"}
    assert seen[0]["input"] == [{"role": "user", "content": "idea"}]
    assert not (tmp_path / ".data").exists()


@pytest.mark.parametrize("kind", ["assets-png", "assets-jpeg", "inputs", "native-run", "migrated-run", "legacy-run"])
async def test_owned_image_responses_wire(tmp_path, kind):
    if kind.startswith("assets"):
        name = "dance_reference.png" if kind.endswith("png") else "chosen.jpg"
        path = tmp_path / "assets" / name
        data = fixture_image(path)
        reference = EditorReference(source_root="assets", path=name)
    elif kind == "inputs":
        reference, path = input_fixture(tmp_path)
        data = path.read_bytes()
    else:
        reference, path = run_fixture(tmp_path, migrated="run" in kind and kind != "native-run",
                                      legacy=kind == "legacy-run",
                                      frame="last_frame.png" if kind == "migrated-run" else "initial_frame.png")
        data = path.read_bytes()
    seen = []
    def handler(request):
        assert request.headers["content-type"] == "application/json"
        assert int(request.headers["content-length"]) == len(request.content)
        body = json.loads(request.content)
        seen.append(body)
        user = body["input"][-1]
        mime = "image/jpeg" if kind == "assets-jpeg" else "image/png"
        assert user == {"role": "user", "content": [
            {"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
            {"type": "input_text", "text": 'ideia "ação"\n'},
        ]}
        assert body["input"][0] == {"role": "system", "content": 'system "ação"\n'}
        assert body["store"] is False and body["stream"] is False
        assert body["max_output_tokens"] == 12000
        return httpx.Response(200, json=response())
    manager = FakeManager(handler)
    grok = Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path)
    result = await grok.complete(PromptRequest(prompt='ideia "ação"\n', system_prompt='system "ação"\n',
                                             reference=reference))
    assert result == {"text": "cena", "model": FIXED_EDITOR_MODEL}
    assert len(seen) == manager.catalogues == 1
    assert path.read_bytes() == data


@pytest.mark.parametrize("path", ["/etc/passwd", "../oauth.json", "x/../image.png", "x//image.png",
                                  "x/.private/image.png", "x\\image.png", "x\x00.png", "https://evil/image.png",
                                  ".data/grok/oauth.json", ".data/runs/x/.hidden.png"])
def test_reference_rejects_private_traversal_url(path):
    with pytest.raises(ValidationError):
        EditorReference(source_root="assets", path=path)


@pytest.mark.parametrize("case", ["missing", "symlink", "parent-link", "root-link", "hardlink", "fifo",
                                  "foreign-uid", "oversize", "webp", "fake-png", "multi-frame"])
async def test_invalid_asset_before_provider(tmp_path, case, monkeypatch):
    path = tmp_path / "assets" / "chosen.png"
    data = fixture_image(path)
    root = tmp_path
    if case == "missing":
        path.unlink()
    elif case == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "outside.png")
    elif case == "parent-link":
        path.parent.rename(tmp_path / "outside")
        path.parent.symlink_to(tmp_path / "outside", target_is_directory=True)
    elif case == "root-link":
        root = tmp_path / "root-link"
        root.symlink_to(tmp_path, target_is_directory=True)
    elif case == "hardlink":
        os.link(path, tmp_path / "other-link")
    elif case == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif case == "foreign-uid":
        real_stat = grok_image.os.fstat
        def foreign(fd):
            info = real_stat(fd)
            return SimpleNamespace(**{key: getattr(info, key) for key in (
                "st_mode", "st_size", "st_nlink", "st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns")},
                st_uid=os.getuid() + 1)
        monkeypatch.setattr(grok_image.os, "fstat", foreign)
    elif case == "oversize":
        with path.open("r+b") as stream:
            stream.truncate(IMAGE_MAX_BYTES + 1)
    elif case == "webp":
        path = path.with_suffix(".webp")
        path.write_bytes(b"unsupported")
    elif case == "fake-png":
        path.write_bytes(b"not an image")
    elif case == "multi-frame":
        path.write_bytes(data + data)
    manager = FakeManager(never)
    with pytest.raises(OAuthError) as error:
        await Grok(manager, FIXED_EDITOR_MODEL, root=root).complete(PromptRequest(
            prompt="idea", reference={"source_root": "assets", "path": path.name},
        ))
    expected = "editor_storage_error" if case == "root-link" else "invalid_reference"
    assert error.value.code == expected and manager.catalogues == 0


@pytest.mark.parametrize("case", ["missing-metadata", "mismatch-path", "hash", "partial", "metadata-link"])
async def test_input_proof_failures_before_provider(tmp_path, case):
    reference, path = input_fixture(tmp_path, corrupt=case == "hash", partial=case == "partial")
    marker = path.parent / "metadata.json"
    if case == "missing-metadata":
        marker.unlink()
    elif case == "mismatch-path":
        metadata = json.loads(marker.read_text())
        metadata["path"] = "another/original.png"
        marker.write_text(json.dumps(metadata))
    elif case == "metadata-link":
        os.link(marker, tmp_path / "other-metadata")
    manager = FakeManager(never)
    with pytest.raises(OAuthError) as error:
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(prompt="idea", reference=reference))
    assert error.value.code == "invalid_reference" and manager.catalogues == 0


@pytest.mark.parametrize("case", ["manifest-id", "no-proof", "receipt-mismatch", "inventory-hash", "frame-hash"])
async def test_run_proof_failures(tmp_path, case):
    reference, path = run_fixture(tmp_path, migrated=True)
    marker = path.parent / "manifest.json"
    receipt_path = tmp_path / ".data/state/migration.json"
    if case == "manifest-id":
        marker.write_text('{"id":"different","references":[]}')
    elif case == "no-proof":
        receipt_path.unlink()
    elif case == "receipt-mismatch":
        receipt = json.loads(receipt_path.read_text())
        receipt["state"] = "pending"
        receipt_path.write_text(json.dumps(receipt))
    elif case == "inventory-hash":
        receipt = json.loads(receipt_path.read_text())
        receipt["inventory_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt))
        (tmp_path / f'.data/migrations/{receipt["id"]}/verified.json').write_text(json.dumps(receipt))
    else:
        path.write_bytes(path.read_bytes() + b"changed")
    manager = FakeManager(never)
    with pytest.raises(OAuthError) as error:
        await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(prompt="idea", reference=reference))
    assert error.value.code == "invalid_reference" and manager.catalogues == 0


@pytest.mark.parametrize("mutation", ["inplace", "replace"])
async def test_source_mutation_during_copy(tmp_path, monkeypatch, mutation):
    path = tmp_path / "assets/chosen.png"
    fixture_image(path)
    real_read = grok_image.os.read
    mutated = False
    def raced_read(fd, size):
        nonlocal mutated
        block = real_read(fd, size)
        if not mutated and block:
            mutated = True
            if mutation == "inplace":
                path.write_bytes(b"changed image")
            else:
                replacement = tmp_path / "replacement.png"
                replacement.write_bytes(b"replacement")
                replacement.replace(path)
        return block
    monkeypatch.setattr(grok_image.os, "read", raced_read)
    with pytest.raises(ValueError, match="changed|replaced"):
        async with owned_image(tmp_path, EditorReference(source_root="assets", path="chosen.png")):
            pytest.fail("Mutated input accepted")


async def test_ownership_metadata_mutation_during_copy(tmp_path, monkeypatch):
    reference, path = input_fixture(tmp_path)
    marker = path.parent / "metadata.json"
    real_read = grok_image.os.read
    mutated = False
    def raced_read(fd, size):
        nonlocal mutated
        block = real_read(fd, size)
        if not mutated and block.startswith(b"\x89PNG"):
            mutated = True
            metadata = json.loads(marker.read_text())
            metadata["sha256"] = "0" * 64
            marker.write_text(json.dumps(metadata))
        return block
    monkeypatch.setattr(grok_image.os, "read", raced_read)
    with pytest.raises(ValueError, match="SHA"):
        async with owned_image(tmp_path, reference):
            pytest.fail("Changed ownership proof accepted")


@pytest.mark.parametrize("tail", [0, 1, 2])
async def test_incremental_base64_bound_and_exact_length(tail):
    with tempfile.TemporaryFile() as snapshot:
        for _ in range(100):
            snapshot.write(b"x" * BUFFER_BYTES)
        snapshot.write(b"a" * tail)
        snapshot.seek(0)
        body, length = image_json_body("pin", "", "idea", snapshot, "image/png")
        count, total = 0, 0
        previous = None
        async for chunk in body:
            if previous is not None and count > 1:
                assert len(previous) <= BUFFER_BYTES * 4 // 3
                assert base64.b64decode(previous) in (b"x" * BUFFER_BYTES, b"a" * tail)
            previous = chunk
            count += 1
            total += len(chunk)
        assert total == length and count == 102 + bool(tail)


async def test_snapshot_cleanup_on_validation_failure_and_cancel(tmp_path, monkeypatch):
    fixture_image(tmp_path / "assets/chosen.png")
    snapshots = []
    real_temp = grok_image.tempfile.TemporaryFile
    def tracked_temp(*args, **kwargs):
        stream = real_temp(*args, **kwargs)
        snapshots.append(stream)
        return stream
    monkeypatch.setattr(grok_image.tempfile, "TemporaryFile", tracked_temp)
    started = asyncio.Event()
    async def wait_validation(snapshot):
        started.set()
        await asyncio.Future()
    monkeypatch.setattr(grok_image, "_validate", wait_validation)
    async def submit():
        async with owned_image(tmp_path, EditorReference(source_root="assets", path="chosen.png")):
            pytest.fail("Cancelled validation reached provider")
    task = asyncio.create_task(submit())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(snapshots) == 1 and snapshots[0].closed


async def test_copy_cancellation_joins_thread_before_close(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    closed = []
    def copying(root, reference, snapshot):
        started.set()
        release.wait(timeout=5)
        closed.append(snapshot.closed)
        snapshot.write(b"x")
    monkeypatch.setattr(grok_image, "_copy_owned", copying)
    async def submit():
        async with owned_image(tmp_path, EditorReference(source_root="assets", path="chosen.png")):
            pytest.fail("Cancelled copy reached validation")
    task = asyncio.create_task(submit())
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [False]


async def test_network_failure_not_replayed_and_snapshot_closed(tmp_path, monkeypatch):
    fixture_image(tmp_path / "assets/chosen.png")
    snapshots, submissions = [], []
    real_temp = grok_image.tempfile.TemporaryFile
    def tracked_temp(*args, **kwargs):
        stream = real_temp(*args, **kwargs)
        snapshots.append(stream)
        return stream
    monkeypatch.setattr(grok_image.tempfile, "TemporaryFile", tracked_temp)
    def handler(request):
        submissions.append(request.url.path)
        raise httpx.ReadTimeout("fake-private-access", request=request)
    with pytest.raises(OAuthError) as error:
        await Grok(FakeManager(handler), FIXED_EDITOR_MODEL, root=tmp_path).complete(PromptRequest(
            prompt="idea", reference={"source_root": "assets", "path": "chosen.png"},
        ))
    assert error.value.code == "network_error" and "fake-private" not in str(error.value)
    assert submissions == ["/v1/responses"]
    assert all(s.closed for s in snapshots)


@pytest.mark.parametrize("short_read", [1, 2, 5, 7])
async def test_stream_short_reads_keep_base64_carry(short_read):
    with tempfile.TemporaryFile() as snapshot:
        original = b"some encoded bytes with a non-three-divisible length"
        snapshot.write(original)
        snapshot.seek(0)
        class ShortReader:
            def fileno(self):
                return snapshot.fileno()
            def read(self, size):
                return snapshot.read(min(size, short_read))
        body, length = image_json_body("pin", "", "idea", ShortReader(), "image/png")
        wire = b"".join([chunk async for chunk in body])
        value = json.loads(wire)
        assert len(wire) == length
        assert base64.b64decode(value["input"][0]["content"][0]["image_url"].split(",")[1]) == original


async def test_httpx_sends_async_chunks_without_materializing_body():
    class ChunkTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert not hasattr(request, "_content")
            total = count = 0
            async for chunk in request.stream:
                assert len(chunk) <= 65536
                total += len(chunk)
                count += 1
            assert total == int(request.headers["content-length"])
            assert count > 100
            return httpx.Response(200, json=response())
    with tempfile.TemporaryFile() as snapshot:
        for _ in range(101):
            snapshot.write(b"x" * BUFFER_BYTES)
        snapshot.seek(0)
        body, length = image_json_body("pin", "", "idea", snapshot, "image/png")
        manager = FakeManager(never, model="pin")
        manager.client_factory = lambda: httpx.AsyncClient(transport=ChunkTransport())
        assert await Grok(manager)._submit("pin", {"content": body}, length=length) == {
            "text": "cena", "model": "pin",
        }


async def test_provider_cancellation_closes_snapshot(tmp_path, monkeypatch):
    fixture_image(tmp_path / "assets/chosen.png")
    snapshots = []
    real_temp = grok_image.tempfile.TemporaryFile
    def tracked_temp(*args, **kwargs):
        snapshot = real_temp(*args, **kwargs)
        snapshots.append(snapshot)
        return snapshot
    monkeypatch.setattr(grok_image.tempfile, "TemporaryFile", tracked_temp)
    started = asyncio.Event()
    async def handler(request):
        started.set()
        await asyncio.Future()
    grok = Grok(FakeManager(handler), FIXED_EDITOR_MODEL, root=tmp_path)
    task = asyncio.create_task(grok.complete(PromptRequest(
        prompt="idea", reference={"source_root": "assets", "path": "chosen.png"},
    )))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(snapshots) == 1 and snapshots[0].closed
    assert not list((tmp_path / ".dumps/grok-editor").iterdir())


async def test_validation_failure_closes_snapshot(tmp_path, monkeypatch):
    fixture_image(tmp_path / "assets/chosen.png")
    snapshots = []
    async def invalid(snapshot):
        snapshots.append(snapshot)
        raise ValueError("invalid still")
    monkeypatch.setattr(grok_image, "_validate", invalid)
    with pytest.raises(ValueError):
        async with owned_image(tmp_path, EditorReference(source_root="assets", path="chosen.png")):
            pytest.fail("Invalid still accepted")
    assert len(snapshots) == 1 and snapshots[0].closed
    assert not list((tmp_path / ".dumps/grok-editor").iterdir())


@pytest.mark.parametrize("payload", [
    {"source_root": "private", "path": "image.png"},
    {"source_root": "assets", "path": "image.png", "mime": "image/png"},
    {"source_root": "assets", "path": "image.png", "image_url": "https://evil"},
    {"source_root": "assets", "path": 3},
    {"source_root": "assets", "path": "x" * 1025},
])
def test_strict_reference_dto(payload):
    with pytest.raises(ValidationError):
        PromptRequest(prompt="idea", reference=payload)


def test_seed_root_ancestor_link_rejected(tmp_path):
    real = tmp_path / "real"
    (real / "project").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        seed_editor(alias / "project")
    assert not (real / "project/.data").exists()


async def test_auth_storage_failure_is_not_an_image_error(tmp_path):
    fixture_image(tmp_path / "assets/chosen.png")
    manager = FakeManager(never)
    async def broken_auth(*args, **kwargs):
        raise OSError("fake-private-access")
    manager.authorized_models = broken_auth
    grok = Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path)
    result = await invoke(grok.complete, PromptRequest(
        prompt="idea", reference={"source_root": "assets", "path": "chosen.png"},
    ))
    assert result.status_code == 500
    assert json.loads(result.body)["error"] == "storage_error"
    assert b"fake-private" not in result.body


async def test_validation_command_metadata_bound():
    with tempfile.TemporaryFile() as snapshot, pytest.raises(ValueError, match="metadata exceeds"):
        await grok_image._command(snapshot.fileno(), sys.executable, "-c", "print('x' * 20000)")


async def test_cancellation_during_child_creation_reaps_child(monkeypatch):
    real_create = asyncio.create_subprocess_exec
    created, release = asyncio.Event(), asyncio.Event()
    processes = []
    async def delayed_create(*args, **kwargs):
        process = await real_create(*args, **kwargs)
        processes.append(process)
        created.set()
        await release.wait()
        return process
    monkeypatch.setattr(grok_image.asyncio, "create_subprocess_exec", delayed_create)
    with tempfile.TemporaryFile() as snapshot:
        task = asyncio.create_task(grok_image._command(
            snapshot.fileno(), sys.executable, "-c", "import time; time.sleep(60)",
        ))
        try:
            await created.wait()
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


def test_no_generation_business_imports():
    for module in (grok_image, __import__("h3_backend.grok", fromlist=["_"])):
        source = Path(module.__file__).read_text()
        for forbidden in ("from .generation", "from ..generation", "infrastructure.store", "PIL", "read_bytes("):
            assert forbidden not in source
    assert DEFAULT_EDITOR_SYSTEM and FIXED_EDITOR_MODEL == "grok-4.20-0309-non-reasoning"
