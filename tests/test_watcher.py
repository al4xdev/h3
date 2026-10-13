"""Real inotify on pytest-owned roots; no API, polling, media or Comfy process."""

import asyncio
import fcntl
import os
from uuid import uuid4

import pytest

from h3_backend.infrastructure.watcher import HEADER, OVERFLOW, FileWatcher


async def hint(stream, expected):
    async with asyncio.timeout(3):
        async for path in stream:
            assert isinstance(path, str) and not path.startswith("/")
            if path == expected:
                return path
    pytest.fail("filesystem hint missing")


@pytest.mark.asyncio
async def test_native_fd_and_metadata_only_initial_scan(tmp_path):
    run_id = str(uuid4())
    directory = tmp_path / ".data" / "runs" / run_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text("old explicit intent")
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    assert not candidates
    assert len(watcher._watches) == 5  # .data, three fixed roots, one UUID.
    assert fcntl.fcntl(watcher.fd, fcntl.F_GETFL) & os.O_NONBLOCK
    assert fcntl.fcntl(watcher.fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    stream = watcher.events()
    assert await anext(stream) == ".data"
    watcher.recover()
    assert await anext(stream) == ".data"
    assert not candidates
    watcher.close()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert watcher.fd is None and not watcher._watches and not watcher._subscribers


@pytest.mark.asyncio
async def test_roteiro_and_batch_changes_notify_without_generation(tmp_path):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    try:
        batch_root = tmp_path / ".data" / "roteiro-batches"
        batch_root.mkdir()
        await hint(stream, ".data/roteiro-batches")
        (batch_root / "active.json").write_text('{"state":"active"}')
        await hint(stream, ".data/roteiro-batches/active.json")
        story_root = tmp_path / ".data" / "roteiros"
        story_root.mkdir()
        await hint(stream, ".data/roteiros")
        ident = str(uuid4())
        directory = story_root / ident
        directory.mkdir()
        await hint(stream, f".data/roteiros/{ident}")
        (directory / "plan.json").write_text('{"blocks":[]}')
        await hint(stream, f".data/roteiros/{ident}/plan.json")
        assert candidates == []
        watcher.recover()
        await hint(stream, ".data")
        assert candidates == []
    finally:
        await stream.aclose()
        watcher.close()


@pytest.mark.asyncio
async def test_register_new_directory_before_immediate_request_scan(tmp_path):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    run_id = str(uuid4())
    directory = tmp_path / ".data" / "runs" / run_id
    # All contents are committed before asyncio can deliver CREATE(directory).
    directory.mkdir()
    (directory / "request.json").write_text("already committed")
    await hint(stream, f".data/runs/{run_id}")
    assert candidates == [run_id]
    assert directory in watcher._watches.values()
    (directory / "manifest.json").write_text("new metadata")
    await hint(stream, f".data/runs/{run_id}/manifest.json")
    assert candidates == [run_id]
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
async def test_atomic_moved_directory_and_hardlink_marker(tmp_path):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    run_id = str(uuid4())
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "request.json").write_text("committed")
    directory = tmp_path / ".data" / "runs" / run_id
    staged.rename(directory)
    await hint(stream, f".data/runs/{run_id}")
    assert candidates == [run_id]
    marker = directory / "request.json"
    marker.unlink()
    part = directory / ".request-part"
    part.write_text("next marker")
    os.link(part, marker)
    await hint(stream, f".data/runs/{run_id}/request.json")
    assert candidates[-1] == run_id
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
async def test_slow_subscriber_disconnects_instead_of_retaining_payloads(tmp_path):
    watcher = FileWatcher(tmp_path, queue_size=2)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    for _ in range(10):
        watcher._emit(".data/inputs/metadata.json")
    assert not watcher._subscribers
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    watcher.close()


@pytest.mark.asyncio
async def test_bounded_subscribers_and_cancellation_cleanup(tmp_path):
    watcher = FileWatcher(tmp_path, max_subscribers=1)
    watcher.start()
    first = watcher.events()
    await anext(first)
    second = watcher.events()
    with pytest.raises(ValueError, match="Too many"):
        await anext(second)
    pending = asyncio.create_task(anext(first))
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await first.aclose()
    assert not watcher._subscribers
    watcher.close()


@pytest.mark.asyncio
async def test_overflow_reinstalls_without_replaying_existing_request(tmp_path, monkeypatch):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    run_id = str(uuid4())
    directory = tmp_path / ".data" / "runs" / run_id
    directory.mkdir()
    (directory / "request.json").write_text("unobserved intent before event loss")
    read = os.read
    injected = [True]

    def overflow(fd, size):
        if fd == watcher.fd and injected[0]:
            injected[0] = False
            return HEADER.pack(-1, OVERFLOW, 0, 0)
        return read(fd, size)

    monkeypatch.setattr(os, "read", overflow)
    watcher._readable()
    assert await anext(stream) == ".data"
    assert directory in watcher._watches.values()
    assert not candidates
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
async def test_no_symlink_or_non_uuid_directory_watch_or_generation(tmp_path):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "request.json").write_text("not authorized")
    symlink = tmp_path / ".data" / "runs" / str(uuid4())
    symlink.symlink_to(external, target_is_directory=True)
    non_uuid = tmp_path / ".data" / "runs" / "arbitrary"
    non_uuid.mkdir()
    (non_uuid / "request.json").write_text("not authorized")
    upload = tmp_path / ".data" / "inputs" / "reference.png"
    upload.write_bytes(b"encoded media only")
    await hint(stream, ".data/inputs/reference.png")
    assert not candidates
    assert external not in watcher._watches.values()
    assert symlink not in watcher._watches.values()
    assert non_uuid not in watcher._watches.values()
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
async def test_partial_dotfile_metadata_and_lock_do_not_authorize_execution(tmp_path):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    run_id = str(uuid4())
    directory = tmp_path / ".data" / "runs" / run_id
    directory.mkdir()
    for name in (".request-part", ".lock", "manifest.json", "chunk.mp4"):
        (directory / name).write_text("no inference")
    await hint(stream, f".data/runs/{run_id}")
    assert not candidates
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
async def test_watch_budget_is_bounded_and_overflow_only_invalidates_metadata(tmp_path):
    watcher = FileWatcher(tmp_path, max_watches=4)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    for _ in range(5):
        (tmp_path / ".data" / "runs" / str(uuid4())).mkdir()
    await hint(stream, ".data")
    assert len(watcher._watches) == 4
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
async def test_missing_root_recreation_is_observed_without_replay(tmp_path):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    inputs = tmp_path / ".data" / "inputs"
    inputs.rmdir()
    await hint(stream, ".data")
    inputs.mkdir()
    await hint(stream, ".data/inputs")
    assert inputs in watcher._watches.values()
    (inputs / "metadata.json").write_text("new upload metadata")
    await hint(stream, ".data/inputs/metadata.json")
    assert not candidates
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
async def test_start_failure_does_not_leak_fd_and_close_is_idempotent(tmp_path, monkeypatch):
    watcher = FileWatcher(tmp_path)
    original = watcher._register

    def fail(directory, *, execute):
        original(directory, execute=execute)
        raise OSError("fake watch failure")

    monkeypatch.setattr(watcher, "_register", fail)
    with pytest.raises(OSError, match="watch failure"):
        watcher.start()
    assert watcher.fd is None and not watcher._watches
    watcher.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["inputs", "assemblies"])
async def test_deep_manual_file_changes_emit_hints_never_inference(tmp_path, category):
    candidates = []
    watcher = FileWatcher(tmp_path, on_request=candidates.append)
    watcher.start()
    stream = watcher.events()
    await anext(stream)
    directory = tmp_path / ".data" / category / "a/b/c/d/e"
    directory.mkdir(parents=True)
    await hint(stream, f".data/{category}/a")
    assert directory in watcher._watches.values()
    (directory / "photo.png").write_bytes(b"manual encoded image")
    await hint(stream, f".data/{category}/a/b/c/d/e/photo.png")
    (directory / "request.json").write_text("never a native request here")
    await hint(stream, f".data/{category}/a/b/c/d/e/request.json")
    assert not candidates
    await stream.aclose()
    watcher.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["inputs", "assemblies"])
async def test_category_relative_unicode_length_boundary_and_fixed_roots(tmp_path, category):
    watcher = FileWatcher(tmp_path)
    watcher.start()
    # These are lexical guard checks: no overly long real filename/directory is created.
    base = tmp_path / ".data" / category
    assert watcher._allowed_directory(base / ("é" * 1024))
    assert not watcher._allowed_directory(base / ("é" * 1025))
    assert not watcher._allowed_directory(tmp_path / ".data" / "other" / "deep")
    assert not watcher._allowed_directory(tmp_path / ".data" / "runs" / str(uuid4()) / "nested")
    assert len(watcher._watches) == 4
    watcher.close()
