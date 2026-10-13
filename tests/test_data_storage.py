import importlib.util
import json
from pathlib import Path

import pytest
from test_store import make_run

from h3_backend.infrastructure.store import Store, storage_lock

SPEC = importlib.util.spec_from_file_location("migrate_state", Path(__file__).resolve().parents[1] / "tools/migrate_state.py")
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def legacy(root, *, state="accepted", parent=None):
    run = make_run().model_copy(update={"state": state, "parent_id": parent,
        "decision": {"accepted": True} if state == "accepted" else None})
    directory = root / "runs" / run.id
    directory.mkdir(parents=True)
    if state != "failed":
        run.output = {"path": f"runs/{run.id}/chunk.mp4"}
        (directory / "chunk.mp4").write_bytes(b"real-looking-fixture-only")
    (directory / "manifest.json").write_text(run.model_dump_json(indent=2))
    (directory / ".hidden").write_bytes(b"hidden provenance")
    (directory / "nested").mkdir()
    (directory / "nested/proof.json").write_bytes(b"{\"literal\":true}")
    return run


def test_default_new_writes_and_resources_root(tmp_path):
    store = Store(tmp_path)
    run = store.create(make_run())
    assert store.root == tmp_path
    assert store.directory(run.id) == tmp_path / ".data/runs" / run.id
    assert store.relative_artifact(run.id, "chunk.mp4") == f".data/runs/{run.id}/chunk.mp4"
    assert not (tmp_path / "runs").exists()
    assert not list((tmp_path / ".data/migrations").glob("*"))


def test_verified_copy_preserves_every_byte_and_aliases(tmp_path):
    run = legacy(tmp_path)
    failed = legacy(tmp_path, state="failed")
    marker = tmp_path / ".data/benchmark-mcp/jobs/example.json"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"untouched MCP")
    before = migration.inventory(tmp_path / "runs")
    preflight = migration.migrate(tmp_path)
    assert preflight["state"] == "preflight_safe"
    assert not (tmp_path / ".data/runs").exists()
    receipt = migration.migrate(tmp_path, execute=True, offline=True)
    assert receipt["state"] == "complete"
    assert migration.inventory(tmp_path / "runs") == before == migration.inventory(tmp_path / ".data/runs")
    store = Store(tmp_path)
    assert store.get(failed.id).state == "failed"
    assert not (store.directory(failed.id) / "chunk.mp4").exists()
    assert store.own_artifact(run.id, run.output["path"], "chunk.mp4") == store.directory(run.id) / "chunk.mp4"
    assert store.sequence(run.id)["blocks"][0]["video_url"] == f"/runs/{run.id}/video"
    assert marker.read_bytes() == b"untouched MCP"
    assert migration.migrate(tmp_path)["state"] == "already_complete"


def test_idempotence_does_not_restore_stale_decision(tmp_path):
    run = legacy(tmp_path, state="ready_for_review")
    migration.migrate(tmp_path, execute=True, offline=True)
    store = Store(tmp_path)
    store.update(run.id, state="accepted", decision={"accepted": True})
    newer = store.create(make_run())
    report = migration.migrate(tmp_path, execute=True, offline=True)
    assert not report["canonical_mutable_data_compared_to_legacy"]
    assert store.get(run.id).state == "accepted" and store.get(newer.id).state == "queued"
    assert json.loads((tmp_path / "runs" / run.id / "manifest.json").read_text())["state"] == "ready_for_review"


@pytest.mark.parametrize("fault", ["legacy", "collision", "pending", "symlink_file", "symlink_parent", "bad_id"])
def test_preflight_fail_closed(tmp_path, fault):
    run = legacy(tmp_path, state="queued" if fault == "pending" else "accepted")
    if fault == "collision":
        (tmp_path / ".data/runs").mkdir(parents=True)
    elif fault == "symlink_file":
        (tmp_path / "runs" / run.id / "alias").symlink_to("chunk.mp4")
    elif fault == "symlink_parent":
        (tmp_path / ".data").symlink_to(tmp_path / "runs", target_is_directory=True)
    elif fault == "bad_id":
        (tmp_path / "runs/not-a-uuid").mkdir()
    if fault == "legacy":
        with pytest.raises(ValueError, match="Legacy"):
            Store(tmp_path).get(run.id)
    else:
        with pytest.raises((ValueError, OSError)):
            migration.migrate(tmp_path, execute=True, offline=True)
    assert (tmp_path / "runs" / run.id / "manifest.json").is_file()


@pytest.mark.parametrize("value", ["../x", "/tmp/x", "runs/OTHER/chunk.mp4", ".data/runs/OTHER/chunk.mp4", "runs/{id}/prompt.md", "runs/{id}/nested/proof.json", ".data/runs/{id}/../chunk.mp4", "./.data/runs/{id}/chunk.mp4"])
def test_own_artifact_rejects_noncanonical_cross_owned_paths(tmp_path, value):
    run = legacy(tmp_path)
    migration.migrate(tmp_path, execute=True, offline=True)
    store = Store(tmp_path)
    with pytest.raises(ValueError):
        store.own_artifact(run.id, value.format(id=run.id), "chunk.mp4")


def test_unmigrated_id_cannot_use_legacy_alias(tmp_path):
    store = Store(tmp_path)
    run = store.create(make_run())
    with pytest.raises(ValueError):
        store.own_artifact(run.id, f"runs/{run.id}/chunk.mp4", "chunk.mp4")


def test_receipt_tampering_rejected(tmp_path):
    run = legacy(tmp_path)
    migration.migrate(tmp_path, execute=True, offline=True)
    path = tmp_path / ".data/state/migration.json"
    receipt = json.loads(path.read_text())
    receipt["root"] = "/other/project"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="receipt"):
        Store(tmp_path).get(run.id)


def test_migrated_symlink_even_inside_same_run_rejected(tmp_path):
    run = legacy(tmp_path)
    migration.migrate(tmp_path, execute=True, offline=True)
    store = Store(tmp_path)
    (store.directory(run.id) / "initial_frame.png").symlink_to("chunk.mp4")
    with pytest.raises(ValueError, match="symlinks"):
        store.own_artifact(run.id, f"runs/{run.id}/initial_frame.png", "initial_frame.png")


def test_runtime_lock_prevents_migration_and_is_released(tmp_path):
    store = Store(tmp_path)
    store.hold_runtime()
    with pytest.raises(ValueError, match="held"):
        migration.migrate(tmp_path, execute=True, offline=True)
    store.release_runtime()
    assert migration.migrate(tmp_path)["state"] == "fresh_project"


def test_migration_lock_prevents_store_mutations(tmp_path):
    lock = storage_lock(tmp_path, exclusive=True)
    try:
        with pytest.raises(ValueError, match="held"):
            Store(tmp_path).create(make_run())
    finally:
        lock.close()
    Store(tmp_path).create(make_run())


def test_crash_after_publication_requires_explicit_reconciliation(tmp_path, monkeypatch):
    run = legacy(tmp_path)
    original = migration._finish
    with monkeypatch.context() as context:
        context.setattr(migration, "_finish", lambda *args: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError):
            migration.migrate(tmp_path, execute=True, offline=True)
    migration_id = next((tmp_path / ".data/migrations").iterdir()).name
    assert (tmp_path / ".data/runs" / run.id / "chunk.mp4").exists()
    with pytest.raises(ValueError, match="incomplete"):
        Store(tmp_path).get(run.id)
    with pytest.raises(ValueError, match="Incomplete"):
        migration.migrate(tmp_path, execute=True, offline=True)
    assert migration._finish is original
    assert migration.migrate(tmp_path, execute=True, offline=True, reconcile=migration_id)["state"] == "complete"
    assert Store(tmp_path).get(run.id).state == "accepted"


@pytest.mark.parametrize("failure", ["source_change", "copy_error", "disk_full", "destination_race"])
def test_copy_failures_preserve_source_and_never_publish_unverified(tmp_path, monkeypatch, failure):
    run = legacy(tmp_path)
    before = migration.inventory(tmp_path / "runs")
    publish = migration.publish_directory
    if failure == "disk_full":
        usage = migration.shutil.disk_usage(tmp_path)
        monkeypatch.setattr(migration.shutil, "disk_usage", lambda _: usage._replace(free=0))
    else:
        def fail(source, destination):
            if failure == "destination_race":
                destination.mkdir()
                return publish(source, destination)
            if failure == "source_change":
                (tmp_path / "runs" / run.id / ".hidden").write_bytes(b"external mutation")
                return publish(source, destination)
            raise OSError("simulated copy/publication failure")
        monkeypatch.setattr(migration, "publish_directory", fail)
    with pytest.raises((ValueError, OSError)):
        migration.migrate(tmp_path, execute=True, offline=True)
    assert not (tmp_path / ".data/state/migration.json").exists()
    if failure != "source_change":
        assert migration.inventory(tmp_path / "runs") == before
    if (tmp_path / ".data/migrations").exists():
        with pytest.raises(ValueError):
            migration.migrate(tmp_path, execute=True, offline=True)


def test_restore_only_canonical_without_replay(tmp_path):
    run = legacy(tmp_path)
    migration.migrate(tmp_path, execute=True, offline=True)
    store = Store(tmp_path)
    queued = store.create(make_run())
    assert {r.id: r.state for r in Store(tmp_path).restore()} == {run.id: "accepted", queued.id: "interrupted"}
    assert json.loads((tmp_path / "runs" / run.id / "manifest.json").read_text())["state"] == "accepted"


def test_second_backend_runtime_refused_but_store_reads_share_process(tmp_path):
    first, second = Store(tmp_path), Store(tmp_path)
    run = first.create(make_run())
    assert second.get(run.id).id == run.id
    first.hold_runtime()
    try:
        with pytest.raises(ValueError, match="Another backend"):
            second.hold_runtime()
        assert second.get(run.id).state == "queued"
    finally:
        first.release_runtime()
    second.hold_runtime()
    second.release_runtime()


def test_partial_staging_failure_is_not_replayed(tmp_path, monkeypatch):
    run = legacy(tmp_path)
    before = migration.inventory(tmp_path / "runs")
    original_open = Path.open
    def fail_copy(path, mode="r", *args, **kwargs):
        if "staging" in path.parts and mode == "xb":
            raise OSError("disk write interrupted")
        return original_open(path, mode, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(Path, "open", fail_copy)
        with pytest.raises(OSError, match="interrupted"):
            migration.migrate(tmp_path, execute=True, offline=True)
    assert migration.inventory(tmp_path / "runs") == before
    assert not (tmp_path / ".data/runs").exists()
    migration_id = next((tmp_path / ".data/migrations").iterdir()).name
    with pytest.raises(ValueError, match="incomplete"):
        migration.migrate(tmp_path, execute=True, offline=True, reconcile=migration_id)
    with pytest.raises(ValueError):
        Store(tmp_path).restore()
    assert (tmp_path / "runs" / run.id / "manifest.json").exists()


@pytest.mark.asyncio
async def test_migrated_accepted_parent_continues_into_new_layout_without_gpu(tmp_path):
    import hashlib

    from test_service import make_service

    from h3_backend.generation.models import ContinueRequest
    parent = legacy(tmp_path)
    parent.references = [{"type": "image", "role": "identity", "source_root": "assets",
        "source": "dance_reference.png", "sha256": hashlib.sha256(b"fake-image").hexdigest(),
        "input_info": {"format": "PNG"}}]
    historical = tmp_path / "runs" / parent.id / "manifest.json"
    historical.write_text(parent.model_dump_json(indent=2))
    original = historical.read_bytes()
    migration.migrate(tmp_path, execute=True, offline=True)
    service = make_service(tmp_path)
    await service.startup()
    try:
        child = await service.continue_run(parent.id, ContinueRequest(seed=55, duration_seconds=2.3))
        await service._task
        run = service.store.get(child.id)
        assert run.state == "ready_for_review"
        assert run.output["path"] == f".data/runs/{child.id}/chunk.mp4"
        assert [r["role"] for r in run.references] == ["initial_frame", "identity", "motion_video"]
        assert run.references[0]["input_info"]["frame_index"] == 55
        assert (service.store.directory(child.id) / "initial_frame.png").read_bytes() == b"exact-last-frame"
        assert service.media.tails[0][0] == service.store.directory(parent.id) / "chunk.mp4"
        assert run.references[2]["input_info"]["actual_seconds"] == 56 / 24
        assert run.references[1]["sha256"] == parent.references[0]["sha256"]
        assert [slot["tag"] for slot in run.input_info["slot_map"]] == ["<Picture 1>", "<Picture 2>", "<Video 1>"]
        assert all(r["source"].startswith(f".data/runs/{child.id}/") for r in (run.references[0], run.references[2]))
        assert historical.read_bytes() == original
        assert [b["id"] for b in service.store.sequence(child.id)["blocks"]] == [parent.id, child.id]
        assert len(service.comfy.submitted) == 1  # Fake Comfy only; no transport/model inference.
    finally:
        await service.shutdown()


def test_explicit_reconcile_verified_unpublished_stage(tmp_path, monkeypatch):
    run = legacy(tmp_path)
    (tmp_path / "runs" / run.id / ".empty").mkdir()
    publish = migration.publish_directory
    with monkeypatch.context() as context:
        context.setattr(migration, "publish_directory", lambda *args: (_ for _ in ()).throw(OSError("interrupted before rename")))
        with pytest.raises(OSError):
            migration.migrate(tmp_path, execute=True, offline=True)
    intent = next((tmp_path / ".data/migrations").iterdir()).name
    assert migration.publish_directory is publish
    assert migration.migrate(tmp_path, execute=True, offline=True, reconcile=intent)["state"] == "complete"
    assert (Store(tmp_path).directory(run.id) / ".empty").is_dir()


def test_benchmark_legacy_lookup_requires_verified_receipt(tmp_path):
    from test_benchmark import benchmark
    run = legacy(tmp_path)
    pipe = benchmark.BenchmarkPipe("http://fake", Path(".dumps/benchmarks/test"),
        technical_acceptance=True, project_root=tmp_path)
    pipe.root = tmp_path
    expected = tmp_path / ".data/runs" / run.id / "chunk.mp4"
    with pytest.raises(benchmark.BenchmarkError):
        pipe._file(run.output["path"], expected)
    migration.migrate(tmp_path, execute=True, offline=True)
    assert pipe._file(run.output["path"], expected) == expected
    with pytest.raises(benchmark.BenchmarkError):
        pipe._file(f"runs/{run.id}/nested/proof.json", expected)


def test_migrated_sequence_reads_only_selected_manifests(tmp_path, monkeypatch):
    parent = legacy(tmp_path)
    child = legacy(tmp_path, state="ready_for_review", parent=parent.id)
    migration.migrate(tmp_path, execute=True, offline=True)
    store = Store(tmp_path)
    store.get(child.id)  # Verify receipt before testing the metadata-only query boundary.
    reader = Path.read_text
    def only_manifests(path, *args, **kwargs):
        assert path.name == "manifest.json"
        return reader(path, *args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("Sequence must not open binary data")
    with monkeypatch.context() as context:
        context.setattr(Path, "read_text", only_manifests)
        context.setattr(Path, "read_bytes", forbidden)
        assert [b["id"] for b in store.sequence(child.id)["blocks"]] == [parent.id, child.id]


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (50, -1), (50, 10001), (True, 0), (1, True), ("50", 0)])
def test_list_bounds_strict(tmp_path, limit, offset):
    with pytest.raises(ValueError, match="bounds"):
        Store(tmp_path).list_runs(limit=limit, offset=offset)


def test_list_metadata_page_sorted_without_media_reads(tmp_path, monkeypatch):
    old = legacy(tmp_path, state="failed")
    recent = legacy(tmp_path, state="ready_for_review")
    migration.migrate(tmp_path, execute=True, offline=True)
    store = Store(tmp_path)
    store.get(old.id)
    reader = Path.read_text
    def only_manifests(path, *args, **kwargs):
        assert path.name == "manifest.json"
        return reader(path, *args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("Library metadata must not read binary artifacts")
    with monkeypatch.context() as context:
        context.setattr(Path, "read_text", only_manifests)
        context.setattr(Path, "read_bytes", forbidden)
        page, total = store.list_runs(limit=1)
        assert total == 2 and page[0].id == recent.id
        assert store.list_runs(limit=1, offset=1)[0][0].id == old.id
        assert store.list_runs(offset=2) == ([], 2)


def test_frozen_benchmark_scenario_source_unchanged():
    import ast
    import subprocess
    root = Path(__file__).resolve().parents[1]
    before = subprocess.check_output(["git", "show", "b83c6ca:tools/benchmark_h3.py"], cwd=root, text=True)
    after = (root / "tools/benchmark_h3.py").read_text()
    def scenario(source):
        return [ast.dump(node, include_attributes=False) for node in ast.parse(source).body
            if (isinstance(node, ast.ClassDef) and node.name == "Stage") or
            (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and
                target.id in {"STAGES", "REFERENCE"} for target in node.targets))]
    assert scenario(before) == scenario(after)


def test_offline_optin_required_and_import_inert(tmp_path):
    legacy(tmp_path)
    with pytest.raises(ValueError, match="offline"):
        migration.migrate(tmp_path, execute=True)
    assert not (tmp_path / ".data").exists()
