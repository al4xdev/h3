"""Isolated editor config: temporary PC roots only, no provider or credentials."""

import json
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from h3_backend.grok import DEFAULT_EDITOR_SYSTEM, EDITOR_MAX_BYTES, router


@contextmanager
def editor_client(root, monkeypatch, model=""):
    monkeypatch.setenv("H3_PROJECT_ROOT", str(root))
    monkeypatch.setenv("H3_GROK_MODEL", model)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        # Any accidental provider/auth call fails this isolated contract.
        app.state.grok.manager.client_factory = lambda: pytest.fail("Unexpected provider call")
        yield client


def test_default_get_inert_no_directory_or_auth(tmp_path, monkeypatch):
    with editor_client(tmp_path, monkeypatch, model="explicit-env-model") as client:
        response = client.get("/grok/editor")
        assert response.status_code == 200
        assert response.json() == {"system_prompt": DEFAULT_EDITOR_SYSTEM,
                                   "model": "explicit-env-model"}
        assert response.headers["cache-control"] == "no-store"
        assert not (tmp_path / ".data").exists()


def test_save_restart_unicode_and_separate_opaque_file(tmp_path, monkeypatch):
    directory = tmp_path / ".data" / "grok"
    directory.mkdir(parents=True)
    # This is our own opaque fixture, not an application credential.
    opaque = directory / "oauth.json"
    opaque.write_bytes(b"opaque fixture, never parsed by editor")
    before = opaque.stat()
    config = {"system_prompt": "  Preserve ação, roupa e ordem.\n<img onerror=evil>  ",
              "model": "catalog-model-explicit"}
    with editor_client(tmp_path, monkeypatch) as client:
        response = client.put("/grok/editor", json=config)
        assert response.status_code == 200
        assert response.json() == config
        assert response.headers["cache-control"] == "no-store"
    with editor_client(tmp_path, monkeypatch, model="different-env") as client:
        assert client.get("/grok/editor").json() == config
    assert json.loads((directory / "editor.json").read_text()) == config
    assert opaque.stat().st_mtime_ns == before.st_mtime_ns
    assert opaque.stat().st_ino == before.st_ino
    assert sorted(path.name for path in directory.iterdir()) == ["editor.json", "oauth.json"]


@pytest.mark.parametrize("payload", [
    {}, {"system_prompt": ""}, {"system_prompt": " "}, {"system_prompt": 3},
    {"system_prompt": "x" * 100_001}, {"system_prompt": "x", "model": "m" * 257},
    {"system_prompt": "x", "model": None}, {"system_prompt": "x", "model": " "},
    {"system_prompt": "x", "path": "../oauth.json"},
])
def test_strict_invalid_payload_no_write(tmp_path, monkeypatch, payload):
    with editor_client(tmp_path, monkeypatch) as client:
        assert client.put("/grok/editor", json=payload).status_code == 422
        assert not (tmp_path / ".data").exists()


def test_maximum_system_and_empty_model(tmp_path, monkeypatch):
    payload = {"system_prompt": "é" * 100_000, "model": ""}
    with editor_client(tmp_path, monkeypatch) as client:
        assert client.put("/grok/editor", json=payload).json() == payload
        assert client.get("/grok/editor").json() == payload


def test_oversized_and_malformed_json_rejected_before_write(tmp_path, monkeypatch):
    with editor_client(tmp_path, monkeypatch) as client:
        assert client.put("/grok/editor", content=b"x" * (EDITOR_MAX_BYTES + 1)).status_code == 413
        assert client.put("/grok/editor", content=b"not json").status_code == 422
        assert not (tmp_path / ".data").exists()


@pytest.mark.parametrize("raw", [b"not json", b'{"system_prompt":"x","unknown":1}',
                                 b"x" * (EDITOR_MAX_BYTES + 1)])
def test_corrupt_existing_is_fail_closed_and_preserved(tmp_path, monkeypatch, raw):
    path = tmp_path / ".data" / "grok" / "editor.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    with editor_client(tmp_path, monkeypatch) as client:
        assert client.get("/grok/editor").status_code == 409
        assert client.put("/grok/editor", json={"system_prompt": "replacement"}).status_code == 409
    assert path.read_bytes() == raw


@pytest.mark.parametrize("level", ["root", ".data", "grok", "editor.json"])
def test_symlinks_rejected_without_touching_target(tmp_path, monkeypatch, level):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    if level == "root":
        link = tmp_path / "root-link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif level == ".data":
        (root / ".data").symlink_to(target, target_is_directory=True)
    elif level == "grok":
        (root / ".data").mkdir()
        (root / ".data" / "grok").symlink_to(target, target_is_directory=True)
    else:
        (root / ".data" / "grok").mkdir(parents=True)
        (target / "opaque").write_bytes(b"opaque")
        (root / ".data" / "grok" / "editor.json").symlink_to(target / "opaque")
    before = sorted(path.name for path in target.iterdir())
    with editor_client(root, monkeypatch) as client:
        assert client.get("/grok/editor").status_code == 409
        assert client.put("/grok/editor", json={"system_prompt": "scene"}).status_code == 409
    assert sorted(path.name for path in target.iterdir()) == before


def test_directory_never_read_as_config(tmp_path, monkeypatch):
    path = tmp_path / ".data" / "grok" / "editor.json"
    path.mkdir(parents=True)
    with editor_client(tmp_path, monkeypatch) as client:
        assert client.get("/grok/editor").status_code == 409
        assert client.put("/grok/editor", json={"system_prompt": "scene"}).status_code == 409


def test_atomic_replace_failure_preserves_old_and_cleans_own_temp(tmp_path, monkeypatch):
    import h3_backend.grok as module

    old = {"system_prompt": "old", "model": ""}
    with editor_client(tmp_path, monkeypatch) as client:
        assert client.put("/grok/editor", json=old).status_code == 200
        def fail_replace(*args, **kwargs):
            raise OSError("simulated atomic failure")
        monkeypatch.setattr(module.os, "replace", fail_replace)
        assert client.put("/grok/editor", json={"system_prompt": "new"}).status_code == 409
        assert client.get("/grok/editor").json() == old
    assert [path.name for path in (tmp_path / ".data" / "grok").iterdir()] == ["editor.json"]
