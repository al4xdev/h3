from uuid import uuid4

import pytest

from h3_backend.generation.models import Run
from h3_backend.infrastructure.store import Store, contained, timestamp


def make_run():
    now = timestamp()
    return Run(
        id=str(uuid4()),
        created_at=now,
        updated_at=now,
        seed=7,
        prompt="SFW",
        duration_seconds=2.3,
        workflow_hash="baseline",
    )


def test_transitions_and_immutable_decisions(tmp_path):
    store = Store(tmp_path)
    run = store.create(make_run())
    with pytest.raises(ValueError):
        store.update(run.id, state="accepted")
    store.update(run.id, state="running", prompt_id=str(uuid4()))
    store.update(run.id, state="ready_for_review")
    store.update(run.id, state="accepted", decision={"accepted": True})
    with pytest.raises(ValueError):
        store.update(run.id, state="rejected")
    with pytest.raises(ValueError):
        store.update(run.id, error="mutated")
    assert Store(tmp_path).get(run.id).state == "accepted"
    assert not list(store.directory(run.id).glob(".manifest-*"))


def test_failed_not_accepted_and_pending_restore(tmp_path):
    store = Store(tmp_path)
    failed = store.create(make_run())
    store.update(failed.id, state="failed")
    with pytest.raises(ValueError):
        store.update(failed.id, state="accepted")
    queued = store.create(make_run())
    running = store.create(make_run())
    prompt_id = str(uuid4())
    store.update(running.id, state="running", prompt_id=prompt_id)
    restored = {r.id: r for r in Store(tmp_path).restore()}
    assert restored[failed.id].state == "failed"
    assert restored[queued.id].state == restored[running.id].state == "interrupted"
    assert restored[running.id].prompt_id == prompt_id
    assert "not resubmitted" in restored[running.id].error


def test_containment_rejects_traversal_and_symlinks(tmp_path):
    root = tmp_path / "safe"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (root / "escape").symlink_to(other, target_is_directory=True)
    for path in ("../other", str(other), "escape/file"):
        with pytest.raises(ValueError):
            contained(root, path)
    assert contained(root, "valid") == root / "valid"
    with pytest.raises(ValueError):
        Store(root).directory("../x")


def test_markdown_artifact_is_literal_and_never_overwritten(tmp_path):
    store = Store(tmp_path)
    run = store.create(make_run())
    text = "# Literal\r\n\r\n<Picture 1>  \n<Picture 2>\n"
    path = store.artifact_markdown(run.id, text)
    assert path.read_bytes() == text.encode("utf-8")
    with pytest.raises(FileExistsError):
        store.artifact_markdown(run.id, "replacement")
    assert path.read_bytes() == text.encode("utf-8")
    assert not list(store.directory(run.id).glob(".prompt-*"))
