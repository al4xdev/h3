"""Atomic manifests; terminal decisions cannot be overwritten."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

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


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
IMAGE_NAMES = frozenset({"initial_frame.png", "last_frame.png"})


ARTIFACTS = frozenset({
    "chunk.mp4", "initial_frame.png", "last_frame.png", "reference_tail.mp4",
    "target_frame.png", "bridge_parent.mp4", "bridge_target.mp4",
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

    @staticmethod
    def run_image_parts(source: str) -> tuple[str, str]:
        parts = source.split("/")
        if len(parts) == 4 and parts[:2] == [".data", "runs"]:
            run_id, filename = parts[2:]
        elif len(parts) == 3 and parts[0] == "runs":
            run_id, filename = parts[1:]
        else:
            raise ValueError("Run image must use an own canonical or verified legacy path")
        if str(UUID(run_id)) != run_id or filename not in IMAGE_NAMES:
            raise ValueError("Only own initial_frame.png or last_frame.png are identity sources")
        return run_id, filename

    def reference_path(self, source_root: str, source: str) -> Path:
        """Resolve only public still-image categories, never an arbitrary project path."""
        if (not isinstance(source, str) or not source or len(source) > 1024
                or "\\" in source or any(ord(c) < 32 for c in source)
                or Path(source).is_absolute() or ".." in Path(source).parts):
            raise ValueError("Invalid reference path")
        if source_root == "runs":
            run_id, filename = self.run_image_parts(source)
            self.get(run_id)  # A UUID-shaped folder alone is not a valid own run.
            path = self.own_artifact(run_id, source, filename)
        elif source_root in ("assets", "inputs"):
            if any(part.startswith(".") for part in Path(source).parts):
                raise ValueError("Private or temporary images are not public references")
            base = self.root / ("assets" if source_root == "assets" else ".data/inputs")
            path = safe_path(base, source)
            if source_root == "inputs" and (path.parent / ".part").exists() and not (path.parent / "metadata.json").exists():
                raise ValueError("Input publication is incomplete")
        else:
            raise ValueError("Unsupported reference root")
        if path.suffix.lower() not in IMAGE_TYPES:
            raise ValueError("Unsupported reference image extension")
        if not path.exists():
            raise FileNotFoundError(path)
        if not path.is_file():
            raise ValueError("Reference must be a regular image file")
        return path

    @staticmethod
    def _image_item(source_root: str, source: str, *, name: str | None = None, info=None) -> dict:
        info = info or {}
        if not isinstance(info, dict):
            raise ValueError("Invalid image metadata")  # noqa: TRY004 - malformed metadata is HTTP400.
        dimensions = {key: value if type(value := info.get(key)) is int and value > 0 else None
                      for key in ("width", "height")}
        if source_root == "runs":
            run_id, filename = Store.run_image_parts(source)
            url = f"/runs/{run_id}/image?name={filename}"
        else:
            url = f"/{source_root}/image?path={quote(source, safe='/')}"
        return {
            "id": f"{source_root}:{source}", "source_root": source_root, "path": source,
            "name": name if name is not None else Path(source).name, "image_url": url,
            **dimensions,
        }

    @staticmethod
    def _image_files(base: Path):
        """Finite metadata traversal; no symlink follows or media reads/probes."""
        if not base.exists():
            return
        directories = [safe_path(base, ".")]
        visited = 0
        while directories:
            directory = directories.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > 10000:
                        raise ValueError("Reference catalog exceeds metadata capacity")
                    if entry.name.startswith(".") or entry.is_symlink():
                        continue
                    path = directory / entry.name
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(path)
                    elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in IMAGE_TYPES:
                        yield path

    @staticmethod
    def _input_metadata(path: Path) -> dict:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16384:
                raise ValueError("Input metadata must be a bounded regular file")
            data = stream.read(16385)
        if len(data) > 16384:
            raise ValueError("Input metadata exceeds size limit")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("Invalid input metadata")  # noqa: TRY004 - malformed metadata is HTTP400.
        return result

    def list_inputs(self, *, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        if type(limit) is not int or type(offset) is not int or not (
            1 <= limit <= 100 and 0 <= offset <= 10000
        ):
            raise ValueError("Invalid metadata page bounds")
        with self._lock, storage_guard(self.root):
            self._authority()
            items = []
            for category, base in (("assets", safe_path(self.root, "assets")),
                                   ("inputs", safe_path(self.root, ".data/inputs"))):
                for path in self._image_files(base):
                    source = path.relative_to(base).as_posix()
                    metadata = path.parent / "metadata.json"
                    name, info = path.name, {}
                    if category == "inputs":
                        if (path.parent / ".part").exists() and not metadata.exists():
                            continue  # Upload failure evidence is not a manually placed reference.
                        if metadata.exists():
                            info = self._input_metadata(safe_path(path.parent, "metadata.json"))
                            if (info.get("source_root") != "inputs" or info.get("path") != source
                                    or info.get("id") != path.parent.name
                                    or not isinstance(info.get("name"), str)):
                                raise ValueError("Input metadata disagrees with its own image path")
                            name = info["name"]
                    items.append(self._image_item(category, source, name=name, info=info))
                    if len(items) > 10000:
                        raise ValueError("Reference catalog exceeds metadata capacity")
            for index, manifest in enumerate(self.runs.glob("*/manifest.json")):
                if index >= 10000:
                    raise ValueError("Run image catalog exceeds metadata capacity")
                run = self.get(manifest.parent.name)
                for filename in sorted(IMAGE_NAMES):
                    source = self.relative_artifact(run.id, filename)
                    path = self.own_artifact(run.id, source, filename)
                    if path.is_file():
                        info = next((ref.get("input_info", {}) for ref in run.references
                                     if ref.get("source") in (source, f"runs/{run.id}/{filename}")), {})
                        items.append(self._image_item("runs", source, info=info))
                        if len(items) > 10000:
                            raise ValueError("Reference catalog exceeds metadata capacity")
            items.sort(key=lambda item: (item["source_root"] != "assets", item["source_root"], item["path"]))
            return items[offset:offset + limit], len(items)

    def reserve_input(self) -> tuple[str, Path]:
        with self._lock, storage_guard(self.root):
            self._authority()
            base = safe_path(self.root, ".data/inputs")
            base.mkdir(exist_ok=True)
            input_id = str(uuid4())
            directory = safe_path(base, input_id)
            directory.mkdir(exist_ok=False)
            part = safe_path(directory, ".part")
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            os.close(fd)
            return input_id, part

    def publish_input(self, input_id: str, name: str, info: dict, digest: str) -> dict:
        """Publish original encoded bytes without overwrite; metadata is the last commit marker."""
        if str(UUID(input_id)) != input_id:
            raise ValueError("Invalid input id")
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[info["format"]]
        with self._lock, storage_guard(self.root):
            base = safe_path(self.root, ".data/inputs")
            directory = safe_path(base, input_id)
            part = safe_path(directory, ".part")
            if not part.is_file():
                raise ValueError("Upload evidence must be a regular own file")
            source = f"{input_id}/original{suffix}"
            destination = safe_path(base, source)
            marker = safe_path(directory, "metadata.json")
            if marker.exists():
                raise FileExistsError("Input metadata already exists")
            # Any collision retains .part evidence and does not replace the original.
            os.link(part, destination)
            for path in (directory, base):
                fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            metadata = {"id": input_id, "source_root": "inputs", "path": source,
                        "name": name, **info, "sha256": digest, "created_at": timestamp()}
            fd, temporary = tempfile.mkstemp(prefix=".metadata-", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(metadata, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, marker)
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                os.unlink(temporary)
            part.unlink()
            return self._image_item("inputs", source, name=name, info=info)

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

    def create(self, run: Run, *, materialize_request: bool = False) -> Run:
        with self._lock, storage_guard(self.root):
            if self.directory(run.id).exists():
                raise ValueError("Run already exists")
            if materialize_request:
                self.validate_request(run)
            # The directory reservation is exclusive, unlike later lifecycle saves.
            self.directory(run.id).mkdir(exist_ok=False)
            self._save(run)
            if materialize_request:
                # Persist the UUID directory reservation before its last commit marker.
                parent_fd = os.open(self.runs, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                # Last publication is the commit marker. Imports and fixtures opt out.
                self._artifact(run.id, "request.json", run.model_dump_json(indent=2), ".request-")
            return run.model_copy(deep=True)

    @staticmethod
    def validate_request(run: Run) -> None:
        """Validate a sealed admission record without filesystem or business I/O."""
        if (str(UUID(run.id)) != run.id or run.state != "queued"
                or run.created_at != run.updated_at or run.prompt_id is not None
                or run.output or run.progress or run.timings or run.decision is not None
                or run.error is not None or run.publication_mode is not None):
            raise ValueError("Request must be an untouched queued admission snapshot")
        expected_keys = {
            "mode", "operation", "continuation", "workflow_provenance", "comfy_extra_pnginfo",
        }
        if run.input_info.get("operation") == "bridge":
            expected_keys.add("bridge_anchors")
        if set(run.input_info) != expected_keys:
            raise ValueError("Request contains non-admission input metadata")
        if (not isinstance(run.input_info["operation"], str)
                or run.input_info["operation"] not in {"i2v", "v2v", "bridge"}):
            raise ValueError("Unsupported materialized operation")
        maximum = 7 if run.input_info["operation"] == "bridge" else (9 if run.parent_id is None else 8)
        if not 1 <= len(run.references) <= maximum:
            raise ValueError("Invalid admitted identity count")
        sources = set()
        for reference in run.references:
            if (set(reference) != {"type", "role", "source", "source_root", "sha256", "input_info"}
                    or reference.get("type") != "image" or reference.get("role") != "identity"
                    or reference.get("source_root") not in ("assets", "inputs", "runs")):
                raise ValueError("Request must contain only original identity references")
            source = reference["source"]
            if (not isinstance(source, str) or not source or "\\" in source
                    or Path(source).is_absolute() or ".." in Path(source).parts
                    or any(ord(c) < 32 for c in source)
                    or (reference["source_root"], Path(source).as_posix()) in sources):
                raise ValueError("Invalid or duplicate identity path")
            if reference["source_root"] == "runs":
                Store.run_image_parts(source)
            sources.add((reference["source_root"], Path(source).as_posix()))
            digest = reference["sha256"]
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                    or not isinstance(reference["input_info"], dict)):
                raise ValueError("Invalid identity hash or input metadata")
            info = reference["input_info"]
            if (set(info) != {"width", "height", "format"}
                    or type(info["width"]) is not int or type(info["height"]) is not int
                    or min(info["width"], info["height"]) <= 0
                    or info["width"] * info["height"] > 16_000_000
                    or info["format"] not in ("PNG", "JPEG", "WEBP")):
                raise ValueError("Invalid admitted image geometry or format")
        if run.parent_id is not None and str(UUID(run.parent_id)) != run.parent_id:
            raise ValueError("Invalid request parent")
        if run.input_info["operation"] == "bridge":
            if not isinstance(run.input_info["continuation"], dict):
                raise ValueError("Bridge requires its explicit continuation options")
            anchors = run.input_info["bridge_anchors"]
            if not isinstance(anchors, dict) or set(anchors) != {"parent", "target"}:
                raise ValueError("Bridge requires exactly two frozen anchors")
            for role, anchor in anchors.items():
                if not isinstance(anchor, dict) or set(anchor) != {
                    "run_id", "video_path", "video_sha256", "manifest_sha256",
                }:
                    raise ValueError("Invalid bridge anchor metadata")
                identifier = anchor["run_id"]
                if (not isinstance(identifier, str) or str(UUID(identifier)) != identifier
                        or anchor["video_path"] != f".data/runs/{identifier}/chunk.mp4"):
                    raise ValueError("Bridge anchors must own their video")
                for field in ("video_sha256", "manifest_sha256"):
                    digest = anchor[field]
                    if (not isinstance(digest, str) or len(digest) != 64
                            or any(c not in "0123456789abcdef" for c in digest)):
                        raise ValueError("Invalid bridge anchor hash")
                if role == "parent" and identifier != run.parent_id:
                    raise ValueError("Bridge parent disagrees with frozen anchor")
            if (anchors["target"]["run_id"] != run.input_info["continuation"].get("target_run_id")
                    or anchors["target"]["run_id"] == run.parent_id):
                raise ValueError("Bridge requires a distinct target matching its request")

    @staticmethod
    def input_projection(run: Run) -> dict:
        """Execution may enrich references and lifecycle, but never admitted input identity."""
        return {
            **{key: getattr(run, key) for key in (
                "id", "created_at", "seed", "prompt", "duration_seconds", "workflow_hash", "parent_id",
            )},
            "references": [
                {key: reference.get(key) for key in (
                    "type", "role", "source", "source_root", "sha256", "input_info",
                )}
                for reference in run.references if reference.get("role") == "identity"
            ],
            "input_info": {key: run.input_info.get(key) for key in (
                "mode", "operation", "continuation", "workflow_provenance", "comfy_extra_pnginfo",
            ) + (("bridge_anchors",) if run.input_info.get("operation") == "bridge" else ())},
        }

    def request(self, run_id: str) -> Run:
        """Bounded, no-follow read of the immutable commit marker for this same UUID."""
        with self._lock, storage_guard(self.root):
            path = safe_path(self.directory(run_id), "request.json")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or not 0 < info.st_size <= 256 * 1024):
                    raise ValueError("Invalid request file type, owner or size")
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError("Request exceeds metadata size limit")
            run = Run.model_validate_json(raw, strict=True)
            self.validate_request(run)
            if run.id != run_id:
                raise ValueError("Request ID does not match its directory")
            if self.input_projection(run) != self.input_projection(self.get(run_id)):
                raise ValueError("Manifest inputs disagree with immutable request")
            return run

    def get(self, run_id: str) -> Run:
        with self._lock, storage_guard(self.root):
            if self.removed(run_id):
                raise FileNotFoundError("Block removed")
            path = safe_path(self.directory(run_id), "manifest.json")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024 * 1024:
                    raise ValueError("Manifest must be bounded regular metadata")
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Manifest exceeds metadata size limit")
            run = Run.model_validate_json(raw)
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

    def removed(self, run_id: str) -> bool:
        path = safe_path(self.directory(run_id), "removed.json")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or not 0 < info.st_size <= 1024):
                    raise ValueError("Invalid block removal marker")
                raw = stream.read(1025)
        except FileNotFoundError:
            return False
        if len(raw) > 1024 or json.loads(raw) != {"id": run_id, "removed": True}:
            raise ValueError("Invalid block removal marker")
        return True

    def list_runs(self, *, limit: int = 50, offset: int = 0,
                  excluded_ids: frozenset[str] = frozenset()) -> tuple[list[Run], int]:
        """Bounded metadata page; never probe videos, select siblings or touch ComfyUI."""
        if type(limit) is not int or type(offset) is not int or not (
            1 <= limit <= 100 and 0 <= offset <= 10000
        ):
            raise ValueError("Invalid metadata page bounds")
        with self._lock, storage_guard(self.root):
            self._authority()
            order = []
            for path in self.runs.glob("*/manifest.json"):
                if path.parent.name in excluded_ids:
                    continue
                if self.removed(path.parent.name):
                    continue
                if len(order) >= 10000:
                    raise ValueError("Run catalog exceeds metadata capacity")
                run = self.get(path.parent.name)
                order.append((run.created_at, run.id))
            # Keep only ordering keys for the catalog, not every run's provenance/output payload.
            order.sort(reverse=True)
            return [self.get(run_id) for _, run_id in order[offset:offset + limit]], len(order)

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
                directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
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
            if self.removed(path.parent.name):
                continue
            run = self.get(path.parent.name)
            if run.state in {"queued", "running"}:
                run = self.update(
                    run.id, state="interrupted", error="Backend restarted; job was not resubmitted"
                )
            restored.append(run)
        return restored
