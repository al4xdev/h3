"""Atomic manifests; terminal decisions cannot be overwritten."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from ..generation.models import Run

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


def safe_path(root: Path, relative: str | Path) -> Path:
    """Storage cannot use symlinks, even aliases pointing back inside the project."""
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("Path must be relative and contained")
    target = root / value
    for part in (target, *target.parents):
        if part.is_symlink():
            raise ValueError("Storage symlinks are not allowed")
    return contained(root, value)


def storage_lock(root: Path, *, exclusive: bool = False):
    """One project-scoped OS lock coordinates runtimes, mutations and offline cutover."""
    path = safe_path(root, ".data/state/storage.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        stream.close()
        raise ValueError("Storage is held by a runtime or migration; stop the owned runtime first") from exc
    return stream


@contextmanager
def storage_guard(root: Path):
    stream = storage_lock(root)
    try:
        yield
    finally:
        stream.close()


ARTIFACTS = frozenset({
    "chunk.mp4", "initial_frame.png", "last_frame.png", "reference_tail.mp4",
    "workflow_api.json", "prompt.md", "telemetry.jsonl", "telemetry_error.json",
})


class Store:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve()
        self.runs = safe_path(self.root, ".data/runs")
        self._migrated: set[str] = set()
        self._initialized = False
        self._runtime_lock = None
        self._backend_lock = None
        self._lock = threading.RLock()
        legacy = safe_path(self.root, "runs")
        intents = safe_path(self.root, ".data/migrations")
        # Keep fresh-project construction compatible without creating a competing legacy authority.
        if not (legacy.exists() and any(legacy.iterdir())) and not intents.exists():
            with storage_guard(self.root):
                self._authority()

    def hold_runtime(self) -> None:
        try:
            if self._backend_lock is None:
                lease = safe_path(self.root, ".data/state/runtime.lock")
                lease.parent.mkdir(parents=True, exist_ok=True)
                self._backend_lock = lease.open("a+b")
                try:
                    fcntl.flock(self._backend_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ValueError("Another backend owns this project's runtime") from exc
            if self._runtime_lock is None:
                self._runtime_lock = storage_lock(self.root)
            self._authority()
        except Exception:
            self.release_runtime()
            raise

    def release_runtime(self) -> None:
        if self._runtime_lock is not None:
            self._runtime_lock.close()
            self._runtime_lock = None
        if self._backend_lock is not None:
            self._backend_lock.close()
            self._backend_lock = None

    def _authority(self) -> None:
        if self._initialized:
            return
        receipt_path = safe_path(self.root, ".data/state/migration.json")
        legacy = safe_path(self.root, "runs")
        intents = safe_path(self.root, ".data/migrations")
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            migration_id = receipt.get("id", "")
            if str(UUID(migration_id)) != migration_id:
                raise ValueError("Invalid migration receipt id")
            proof_path = safe_path(self.root, f".data/migrations/{migration_id}/verified.json")
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            if (receipt.get("schema_version") != 1 or receipt.get("state") != "complete"
                    or receipt.get("root") != str(self.root) or proof != receipt
                    or receipt.get("destination") != ".data/runs" or not self.runs.is_dir()
                    or receipt.get("run_ids") != receipt.get("inventory", {}).get("run_ids")
                    or receipt.get("inventory_sha256") != hashlib.sha256(
                        json.dumps(receipt.get("inventory"), sort_keys=True).encode()
                    ).hexdigest()):
                raise ValueError("Invalid or incomplete migration receipt")
            self._migrated = set(receipt["run_ids"])
            if any(str(UUID(i)) != i for i in self._migrated):
                raise ValueError("Invalid migrated run identity")
            if any(not safe_path(self.runs, i).is_dir() for i in self._migrated):
                raise ValueError("Migrated run directory is missing")
        elif ((legacy.exists() and any(legacy.iterdir()))
              or (intents.exists() and any(intents.iterdir()))):
            raise ValueError("Legacy or incomplete migration exists; run the offline migration tool")
        self.runs.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    def relative_artifact(self, run_id: str, filename: str) -> str:
        if filename not in ARTIFACTS:
            raise ValueError("Unsupported own artifact")
        self.directory(run_id)
        return f".data/runs/{run_id}/{filename}"

    def own_artifact(self, run_id: str, persisted: str, filename: str) -> Path:
        """Logical legacy alias only for receipt-owned IDs; never a filesystem symlink."""
        expected = self.relative_artifact(run_id, filename)
        if persisted != expected and not (
            run_id in self._migrated and persisted == f"runs/{run_id}/{filename}"
        ):
            raise ValueError("Artifact path must be the run's own canonical or verified legacy path")
        return safe_path(self.runs, f"{run_id}/{filename}")

    def directory(self, run_id: str) -> Path:
        if str(UUID(run_id)) != run_id:
            raise ValueError("Invalid run id")
        with storage_guard(self.root):
            self._authority()
            return safe_path(self.runs, run_id)

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
        with self._lock, storage_guard(self.root):
            if self.directory(run.id).exists():
                raise ValueError("Run already exists")
            self._save(run)
            return run.model_copy(deep=True)

    def get(self, run_id: str) -> Run:
        with self._lock, storage_guard(self.root):
            path = safe_path(self.directory(run_id), "manifest.json")
            run = Run.model_validate_json(path.read_text(encoding="utf-8"))
            if run.id != run_id:
                raise ValueError("Manifest ID does not match its directory")
            return run

    def sequence(self, run_id: str) -> dict:
        """Read only the selected ancestor chain; never discover/choose a sibling branch."""
        with self._lock, storage_guard(self.root):
            chain = []
            seen = set()
            current_id = run_id
            while current_id is not None:
                if current_id in seen:
                    raise ValueError("Cycle in run sequence")
                seen.add(current_id)
                try:
                    run = self.get(current_id)
                except FileNotFoundError as exc:
                    if current_id == run_id:
                        raise
                    raise ValueError("Sequence parent is missing") from exc
                if chain and run.state != "accepted":
                    raise ValueError("Sequence ancestor must be accepted")
                if (
                    run.decision is not None and run.state in {"accepted", "rejected"}
                    and run.decision.get("accepted") is not (run.state == "accepted")
                ):
                    raise ValueError("Sequence state disagrees with approval")
                chain.append(run)
                current_id = run.parent_id
            blocks = []
            for index, run in enumerate(reversed(chain)):
                path = run.output.get("path")
                if path is not None:
                    if not isinstance(path, str):
                        raise ValueError("Invalid sequence output path")
                    self.own_artifact(run.id, path, "chunk.mp4")
                probe = run.output.get("probe", {})
                if not isinstance(probe, dict):
                    # ValueError is the API's malformed-manifest -> HTTP400 boundary.
                    raise ValueError("Invalid sequence probe metadata")  # noqa: TRY004
                streams = probe.get("streams", [])
                if not isinstance(streams, list) or any(not isinstance(s, dict) for s in streams):
                    raise ValueError("Invalid sequence stream metadata")
                video = next((s for s in streams if s.get("codec_type") == "video"), {})
                duration = video.get("duration")
                try:
                    if isinstance(duration, bool):
                        raise TypeError
                    seconds = float(duration) if duration is not None else run.duration_seconds
                except (TypeError, ValueError) as exc:
                    raise ValueError("Invalid sequence duration") from exc
                if not math.isfinite(seconds) or seconds <= 0:
                    raise ValueError("Invalid sequence duration")
                blocks.append({
                    "index": index,
                    "id": run.id,
                    "parent_id": run.parent_id,
                    "state": run.state,
                    "accepted": run.state == "accepted",
                    "duration_seconds": seconds,
                    "duration_source": "verified_video" if duration is not None else "requested",
                    "video_url": f"/runs/{run.id}/video"
                        if run.state in {"ready_for_review", "accepted", "rejected"} else None,
                })
            return {
                "schema_version": 1,
                "root_id": chain[-1].id,
                "end_run_id": run_id,
                "blocks": blocks,
            }

    def list_runs(self, *, limit: int = 50, offset: int = 0) -> tuple[list[Run], int]:
        """Bounded metadata page; never probe videos, select siblings or touch ComfyUI."""
        if type(limit) is not int or type(offset) is not int or not (
            1 <= limit <= 100 and 0 <= offset <= 10000
        ):
            raise ValueError("Invalid metadata page bounds")
        with self._lock, storage_guard(self.root):
            self._authority()
            runs = [self.get(path.parent.name) for path in self.runs.glob("*/manifest.json")]
            runs.sort(key=lambda run: (run.created_at, run.id), reverse=True)
            return runs[offset:offset + limit], len(runs)

    def update(self, run_id: str, *, state: str | None = None, **changes) -> Run:
        with self._lock, storage_guard(self.root):
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
        return self._artifact(run_id, filename, json.dumps(data, indent=2), ".artifact-")

    def artifact_markdown(self, run_id: str, text: str) -> Path:
        """Publish the exact encoder input without rendering or stripping whitespace."""
        return self._artifact(run_id, "prompt.md", text, ".prompt-")

    def _artifact(self, run_id: str, filename: str, text: str, prefix: str) -> Path:
        with self._lock, storage_guard(self.root):
            directory = self.directory(run_id)
            destination = safe_path(directory, filename)
            fd, name = tempfile.mkstemp(prefix=prefix, dir=directory)
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
        with storage_guard(self.root):
            self._authority()
        restored = []
        for path in sorted(self.runs.glob("*/manifest.json")):
            run = self.get(path.parent.name)
            if run.state in {"queued", "running"}:
                run = self.update(
                    run.id, state="interrupted", error="Backend restarted; job was not resubmitted"
                )
            restored.append(run)
        return restored
