"""Atomic manifests; terminal decisions cannot be overwritten."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .models import Run

TRANSITIONS = {
    "queued": {"running", "failed", "interrupted"},
    "running": {"ready_for_review", "failed", "interrupted"},
    "ready_for_review": {"accepted", "rejected"},
    "accepted": set(),
    "rejected": set(),
    "failed": set(),
    "interrupted": set(),
}


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def contained(root: Path, relative: str | Path, *, must_exist: bool = False) -> Path:
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("Path must be relative and contained")
    base = root.resolve()
    target = (base / value).resolve(strict=must_exist)
    if not target.is_relative_to(base):
        raise ValueError("Path escapes configured root")
    return target


class Store:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve()
        self.runs = contained(self.root, "runs")
        self.runs.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def directory(self, run_id: str) -> Path:
        if str(UUID(run_id)) != run_id:
            raise ValueError("Invalid run id")
        return contained(self.runs, run_id)

    def _save(self, run: Run) -> None:
        directory = self.directory(run.id)
        directory.mkdir(exist_ok=True)
        destination = contained(directory, "manifest.json")
        fd, name = tempfile.mkstemp(prefix=".manifest-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(run.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def create(self, run: Run) -> Run:
        with self._lock:
            if self.directory(run.id).exists():
                raise ValueError("Run already exists")
            self._save(run)
            return run.model_copy(deep=True)

    def get(self, run_id: str) -> Run:
        with self._lock:
            path = contained(self.directory(run_id), "manifest.json", must_exist=True)
            run = Run.model_validate_json(path.read_text(encoding="utf-8"))
            if run.id != run_id:
                raise ValueError("Manifest ID does not match its directory")
            return run

    def update(self, run_id: str, *, state: str | None = None, **changes) -> Run:
        with self._lock:
            run = self.get(run_id)
            if state is not None and state != run.state and state not in TRANSITIONS[run.state]:
                raise ValueError(f"Invalid transition {run.state} -> {state}")
            if run.state in {"accepted", "rejected", "failed", "interrupted"}:
                raise ValueError("Terminal manifest is immutable")
            values = run.model_dump()
            values.update(changes, updated_at=timestamp())
            if state is not None:
                values["state"] = state
            updated = Run.model_validate(values)
            self._save(updated)
            return updated

    def artifact_json(self, run_id: str, filename: str, data: dict) -> Path:
        """Write per-run diagnostics without overwriting an existing artifact."""
        if filename not in {"workflow_api.json", "telemetry_error.json"}:
            raise ValueError("Unsupported artifact")
        directory = self.directory(run_id)
        destination = contained(directory, filename)
        fd, name = tempfile.mkstemp(prefix=".artifact-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return destination

    def artifact_markdown(self, run_id: str, text: str) -> Path:
        """Publish the exact encoder input without rendering or stripping whitespace."""
        directory = self.directory(run_id)
        destination = contained(directory, "prompt.md")
        fd, name = tempfile.mkstemp(prefix=".prompt-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return destination

    def restore(self) -> list[Run]:
        """Never replay submissions after a restart, including unknown submission outcomes."""
        restored = []
        for path in sorted(self.runs.glob("*/manifest.json")):
            run = self.get(path.parent.name)
            if run.state in {"queued", "running"}:
                run = self.update(
                    run.id, state="interrupted", error="Backend restarted; job was not resubmitted"
                )
            restored.append(run)
        return restored
