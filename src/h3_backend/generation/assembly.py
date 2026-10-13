"""Explicit CPU-only sequence preview; immutable files, not the HTTP waiter, own execution."""

from __future__ import annotations

import asyncio
import json
import math
import os
import stat
import tempfile
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..infrastructure.store import safe_path, storage_guard, timestamp
from .dispatcher import Conflict

MAX_METADATA = 256 * 1024
MAX_BODY = 1024
MECHANISM = "external_concat_no_overlap_trim_no_crossfade"


def canonical_id(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Assembly and run IDs must be canonical UUIDs")
    return value


class AssemblyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    end_run_id: str

    _id = field_validator("end_run_id")(canonical_id)


class AssemblyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    run_id: str
    parent_id: str | None
    path: str = Field(max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(gt=0)
    state: Literal["accepted", "ready_for_review"]
    frames: int = Field(gt=0, le=10_000_000)
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    fps: str
    codec: str
    pixel_format: str
    has_audio: bool

    @model_validator(mode="after")
    def own_clip(self):
        canonical_id(self.run_id)
        if self.parent_id is not None:
            canonical_id(self.parent_id)
        if self.path not in (f".data/runs/{self.run_id}/chunk.mp4", f"runs/{self.run_id}/chunk.mp4"):
            raise ValueError("Assembly input must be its own logical chunk path")
        try:
            rate = Fraction(self.fps)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("Invalid assembly frame rate") from exc
        if not 0 < rate <= 240 or self.width * self.height > 16_000_000:
            raise ValueError("Unsafe input timing or geometry")
        return self


class AssemblyIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    operation: Literal["assembly"] = "assembly"
    id: str
    end_run_id: str
    created_at: str
    mode: Literal["preview", "accepted_sequence"]
    inputs: list[AssemblyInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def ordered_chain(self):
        canonical_id(self.id)
        canonical_id(self.end_run_id)
        previous = None
        signature = None
        seen = set()
        for index, clip in enumerate(self.inputs):
            if clip.run_id in seen or clip.parent_id != previous:
                raise ValueError("Assembly intent is not an ordered ancestor chain")
            if index < len(self.inputs) - 1 and clip.state != "accepted":
                raise ValueError("Every assembly ancestor must be accepted")
            current = (clip.width, clip.height, Fraction(clip.fps), clip.codec, clip.pixel_format, clip.has_audio)
            if signature is not None and signature != current:
                raise ValueError("Assembly inputs have incompatible video or audio parameters")
            signature, previous = current, clip.run_id
            seen.add(previous)
        if previous != self.end_run_id or self.mode != (
            "preview" if self.inputs[-1].state == "ready_for_review" else "accepted_sequence"
        ):
            raise ValueError("Assembly end or review mode disagrees with its intent")
        return self


class AssemblyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    id: str
    end_run_id: str
    state: Literal["running", "failed", "interrupted", "completed"]
    mode: Literal["preview", "accepted_sequence"]
    created_at: str
    updated_at: str
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error: str | None = Field(default=None, max_length=2000)


@dataclass(frozen=True)
class AssemblyState:
    id: str | None = None
    end_run_id: str | None = None
    save_output: bool = False


def _directory(root: Path, assembly_id: str) -> Path:
    return safe_path(root, f".data/assemblies/{canonical_id(assembly_id)}")


def _regular(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    stream = os.fdopen(fd, "rb")
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_size <= 0):
        stream.close()
        raise ValueError("Assembly evidence must be a nonempty regular own file")
    return stream


def _json(path: Path) -> dict:
    with _regular(path) as stream:
        if os.fstat(stream.fileno()).st_size > MAX_METADATA:
            raise ValueError("Assembly metadata exceeds size limit")
        data = stream.read(MAX_METADATA + 1)
    if len(data) > MAX_METADATA:
        raise ValueError("Assembly metadata exceeds size limit")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("Assembly metadata must be an object")  # noqa: TRY004 - malformed metadata -> HTTP400.
    return result


def _sync(directory: Path):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path: Path, data: dict, *, replace_existing=False):
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_METADATA:
        raise ValueError("Assembly metadata exceeds size limit")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if replace_existing:
            # Metadata is the sole mutable lifecycle file; private/foreign targets still fail closed.
            with _regular(safe_path(path.parent, path.name)):
                pass
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        _sync(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def _thread(function, *arguments):
    # Cancellation must not release the CPU/runtime lease while an owned hashing thread is still reading.
    task = asyncio.create_task(asyncio.to_thread(function, *arguments))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def _digest(path: Path) -> tuple[int, str]:
    import hashlib

    with _regular(path) as stream:
        initial = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        final = os.fstat(stream.fileno())
    if (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
        raise ValueError("Assembly source changed during hashing")
    return initial.st_size, digest


def _intent(root: Path, assembly_id: str) -> AssemblyIntent:
    path = safe_path(_directory(root, assembly_id), "request.json")
    intent = AssemblyIntent.model_validate(_json(path))
    if intent.id != assembly_id:
        raise ValueError("Assembly request ID disagrees with its directory")
    return intent


def _metadata(root: Path, assembly_id: str) -> AssemblyMetadata:
    path = safe_path(_directory(root, assembly_id), "metadata.json")
    meta = AssemblyMetadata.model_validate(_json(path))
    canonical_id(meta.end_run_id)
    if meta.id != assembly_id or (meta.state == "completed") != (meta.output_sha256 is not None):
        raise ValueError("Assembly lifecycle disagrees with its own commit proof")
    return meta


def _set_state(root: Path, assembly_id: str, state: str, *, error=None, output_sha256=None):
    meta = _metadata(root, assembly_id)
    if meta.state != "running":
        raise Conflict("Assembly terminal decisions are immutable")
    updated = meta.model_copy(update={"state": state, "error": error, "output_sha256": output_sha256,
                                     "updated_at": timestamp()})
    _write(safe_path(_directory(root, assembly_id), "metadata.json"), updated.model_dump(), replace_existing=True)


def _timing(probe: dict) -> dict:
    if not isinstance(probe, dict) or not isinstance(probe.get("streams"), list) or any(
        not isinstance(stream, dict) for stream in probe["streams"]
    ):
        raise ValueError("Invalid assembly stream metadata")
    videos = [stream for stream in probe["streams"] if stream.get("codec_type") == "video"]
    if len(videos) != 1:
        raise ValueError("Assembly clip must have exactly one video stream")
    video = videos[0]
    try:
        frames = int(video.get("nb_read_frames", video.get("nb_frames", -1)))
        fps = Fraction(video.get("avg_frame_rate", "0"))
        duration = float(video.get("duration", probe.get("format", {}).get("duration", "nan")))
        width, height = int(video["width"]), int(video["height"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("Invalid assembly video metadata") from exc
    if (frames <= 0 or fps <= 0 or not math.isfinite(duration)
            or abs(duration - frames / float(fps)) > max(0.01, 1 / float(fps))):
        raise ValueError("Assembly clip has invalid or variable frame timing")
    audio = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if len(audio) > 1:
        raise ValueError("Assembly clip must have at most one audio stream")
    return {"frames": frames, "width": width, "height": height,
            "fps": f"{fps.numerator}/{fps.denominator}", "codec": video.get("codec_name", ""),
            "pixel_format": video.get("pix_fmt", ""), "has_audio": bool(audio)}


def _verify_output(intent: AssemblyIntent, probe: dict):
    actual = _timing(probe)
    first = intent.inputs[0]
    if (actual["frames"] != sum(clip.frames for clip in intent.inputs)
            or (actual["width"], actual["height"], Fraction(actual["fps"]), actual["has_audio"])
            != (first.width, first.height, Fraction(first.fps), first.has_audio)):
        raise ValueError("Assembled output lost frames or changed geometry, rate or audio presence")
    if first.has_audio:
        audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
        duration = float(audio.get("duration", "nan"))
        expected = actual["frames"] / float(Fraction(first.fps))
        if (audio.get("codec_name") != "aac" or int(audio.get("sample_rate", 0)) <= 0
                or int(audio.get("channels", 0)) <= 0 or not math.isfinite(duration)
                or abs(duration - expected) > max(0.1, 2 / float(Fraction(first.fps)))):
            raise ValueError("Assembly audio does not span its ordered chunk boundaries")


def get_assembly(root: Path, assembly_id: str) -> dict:
    """Metadata-only rediscovery: no media probing, execution or completion recovery."""
    with storage_guard(root):
        directory = _directory(root, assembly_id)
        meta = _metadata(root, assembly_id)
        request_path = safe_path(directory, "request.json")
        if not request_path.exists() and meta.state != "completed":
            return {**meta.model_dump(), "label": "Montagem sem intenção materializada — não executável",
                    "input_ids": [], "frames": None, "fps": None, "video_url": None, "output": None}
        intent = _intent(root, assembly_id)
        if (meta.request_sha256 != _digest(request_path)[1]
                or (meta.end_run_id, meta.created_at, meta.mode) != (intent.end_run_id, intent.created_at, intent.mode)):
            raise ValueError("Assembly lifecycle disagrees with its immutable request")
        output = None
        if meta.state == "completed":
            output_path = safe_path(directory, "output.json")
            output = _json(output_path)
            expected_path = f".data/assemblies/{assembly_id}/video.mp4"
            boundaries = []
            total = 0
            for clip in intent.inputs[:-1]:
                total += clip.frames
                boundaries.append(total)
            if (_digest(output_path)[1] != meta.output_sha256 or output.get("id") != assembly_id
                    or output.get("request_sha256") != meta.request_sha256
                    or output.get("path") != expected_path or output.get("mode") != intent.mode
                    or output.get("boundaries") != boundaries or output.get("assembly") != MECHANISM):
                raise ValueError("Assembly output proof disagrees with its original request")
            _verify_output(intent, output.get("probe", {}))
            video = safe_path(directory, "video.mp4")
            with _regular(video) as stream:
                if os.fstat(stream.fileno()).st_size != output.get("bytes"):
                    raise ValueError("Assembly video size disagrees with its output proof")
            if not isinstance(output.get("sha256"), str) or len(output["sha256"]) != 64:
                raise ValueError("Assembly video hash proof is missing")
        return {**meta.model_dump(), "label": "Montagem de prévia — revisão pendente" if meta.mode == "preview"
                else "Montagem da sequência aceita", "input_ids": [clip.run_id for clip in intent.inputs],
                "frames": sum(clip.frames for clip in intent.inputs), "fps": intent.inputs[0].fps,
                "video_url": f"/assemblies/{assembly_id}/video" if output else None, "output": output}


def assembly_video(root: Path, assembly_id: str) -> Path:
    record = get_assembly(root, assembly_id)
    if record["state"] != "completed":
        raise Conflict("Assembly has no committed completed video")
    path = safe_path(_directory(root, assembly_id), "video.mp4")
    if _digest(path) != (record["output"]["bytes"], record["output"]["sha256"]):
        raise ValueError("Assembly video hash disagrees with its output proof")
    return path


def list_assemblies(root: Path, *, end_run_id=None, limit=50, offset=0) -> dict:
    if end_run_id is not None:
        canonical_id(end_run_id)
    if type(limit) is not int or type(offset) is not int or not (1 <= limit <= 100 and 0 <= offset <= 10000):
        raise ValueError("Invalid assembly page bounds")
    with storage_guard(root):
        base = safe_path(root, ".data/assemblies")
        order = []
        if base.exists():
            with os.scandir(base) as entries:
                for index, entry in enumerate(entries):
                    if index >= 10000:
                        raise ValueError("Assembly catalog exceeds metadata capacity")
                    if entry.name.startswith("."):
                        continue
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        raise ValueError("Assembly catalog contains an unsafe directory")
                    canonical_id(entry.name)
                    if not safe_path(Path(entry.path), "metadata.json").exists():
                        continue  # Partial admission evidence is neither completion nor replayable intent.
                    meta = _metadata(root, entry.name)
                    if end_run_id is None or meta.end_run_id == end_run_id:
                        order.append((meta.created_at, meta.id))
        order.sort(reverse=True)
        return {"items": [get_assembly(root, ident) for _, ident in order[offset:offset + limit]],
                "total": len(order), "limit": limit, "offset": offset}


def restore_interrupted(root: Path):
    """Runtime lease is held by the caller. Never render historical or partially committed intents."""
    with storage_guard(root):
        base = safe_path(root, ".data/assemblies")
        if not base.exists():
            return
        with os.scandir(base) as entries:
            for index, entry in enumerate(entries):
                if index >= 10000:
                    raise ValueError("Assembly restore exceeds metadata capacity")
                if entry.name.startswith("."):
                    continue
                canonical_id(entry.name)
                directory = _directory(root, entry.name)
                if safe_path(directory, "metadata.json").exists():
                    meta = _metadata(root, entry.name)
                    if meta.state == "running":
                        _set_state(root, meta.id, "interrupted", error="Backend stopped; no automatic assembly replay")


class AssemblyPipe:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.state = AssemblyState()
        self._started = False

    def have(self, assembly_id: str):
        self._compose(id=canonical_id(assembly_id))
        return self

    def from_end(self, end_run_id: str):
        self._compose(end_run_id=canonical_id(end_run_id))
        return self

    def save_video(self):
        self._compose(save_output=True)
        return self

    def _compose(self, **values):
        if self._started:
            raise Conflict("Assembly composition is already sealed")
        self.state = replace(self.state, **values)

    async def _admit(self):
        service, state = self.dispatcher, self.state
        if _directory(service.settings.project_root, state.id).exists():
            raise FileExistsError("Assembly UUID is already reserved; no overwrite or replay")
        # Cap traversal BEFORE calling the existing read-only sequence method.
        current, seen = state.end_run_id, set()
        while current is not None:
            if current in seen or len(seen) >= 100:
                raise ValueError("Assembly chain exceeds capacity or contains a cycle")
            seen.add(current)
            run = service.store.get(current)
            if run.state not in ({"ready_for_review", "accepted"} if current == state.end_run_id else {"accepted"}):
                raise Conflict("End must be ready or accepted; every ancestor must be accepted")
            current = run.parent_id
        sequence = service.store.sequence(state.end_run_id)
        inputs = []
        for block in sequence["blocks"]:
            run = service.store.get(block["id"])
            path = service.video_path(run.id)
            size, digest = await _thread(_digest, path)
            details = _timing(await service.media.probe(path))
            inputs.append(AssemblyInput(run_id=run.id, parent_id=run.parent_id,
                                        path=run.output.get("path", service.store.relative_artifact(run.id, "chunk.mp4")),
                                        sha256=digest, bytes=size, state=run.state, **details))
        intent = AssemblyIntent(id=state.id, end_run_id=state.end_run_id, created_at=timestamp(),
                                mode="preview" if inputs[-1].state == "ready_for_review" else "accepted_sequence",
                                inputs=inputs)
        with storage_guard(service.settings.project_root):
            directory = _directory(service.settings.project_root, intent.id)
            directory.parent.mkdir(exist_ok=True)
            directory.mkdir(exist_ok=False)
            _sync(directory.parent)
            encoded = json.dumps(intent.model_dump(), ensure_ascii=False, allow_nan=False).encode()
            import hashlib

            meta = AssemblyMetadata(id=intent.id, end_run_id=intent.end_run_id, state="running", mode=intent.mode,
                                    created_at=intent.created_at, updated_at=intent.created_at,
                                    request_sha256=hashlib.sha256(encoded).hexdigest())
            _write(safe_path(directory, "metadata.json"), meta.model_dump())
            try:
                _write(safe_path(directory, "request.json"), intent.model_dump())  # Immutable admission marker LAST.
            except BaseException as exc:
                terminal = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
                _set_state(service.settings.project_root, intent.id, terminal, error=f"{type(exc).__name__}: {exc}"[:2000])
                raise

    def _sources(self, intent: AssemblyIntent) -> list[Path]:
        sources = []
        for clip in intent.inputs:
            run = self.dispatcher.store.get(clip.run_id)
            logical = run.output.get("path", self.dispatcher.store.relative_artifact(run.id, "chunk.mp4"))
            if (run.parent_id, run.state, logical) != (clip.parent_id, clip.state, clip.path):
                raise ValueError("Assembly review snapshot changed during execution")
            path = self.dispatcher.store.own_artifact(clip.run_id, clip.path, "chunk.mp4")
            if _digest(path) != (clip.bytes, clip.sha256):
                raise ValueError("Assembly source changed after admission")
            sources.append(path)
        return sources

    async def arun(self) -> dict:
        if self._started or not (self.state.id and self.state.end_run_id and self.state.save_output):
            raise Conflict("Assembly requires one sealed composition and a preknown UUID")
        self._started = True
        root, ident = self.dispatcher.settings.project_root, self.state.id
        async with self.dispatcher.cpu_slot(ident):
            admitted = False
            try:
                await self._admit()
                admitted = True
                intent = _intent(root, ident)  # Reopen disk authority; no caller snapshot executes.
                get_assembly(root, ident)  # Bind that immutable request to its own admission proof.
                sources = await _thread(self._sources, intent)
                destination = safe_path(_directory(root, ident), "video.mp4")
                result = await self.dispatcher.media.concatenate(sources, destination)
                if result.get("assembly") != MECHANISM:
                    raise ValueError("Unexpected assembly mechanism")
                probe = await self.dispatcher.media.probe(destination)
                _verify_output(intent, probe)
                await _thread(self._sources, intent)  # Refuse a mixed/tampered capture before completion.
                get_assembly(root, ident)
                if _intent(root, ident) != intent:
                    raise ValueError("Assembly immutable request changed during execution")
                with _regular(destination) as stream:
                    os.fsync(stream.fileno())
                size, digest = await _thread(_digest, destination)
                total, boundaries = 0, []
                for clip in intent.inputs[:-1]:
                    total += clip.frames
                    boundaries.append(total)
                output = {"schema_version": 1, "id": ident, "request_sha256": _metadata(root, ident).request_sha256,
                          "mode": intent.mode, "path": f".data/assemblies/{ident}/video.mp4", "bytes": size,
                          "sha256": digest, "probe": probe, "assembly": MECHANISM, "boundaries": boundaries,
                          "preservation": "ordered frames/count and padded audio; CRF18 re-encode is not RGB or MP4 byte identity"}
                output_path = safe_path(_directory(root, ident), "output.json")
                _write(output_path, output)
                _set_state(root, ident, "completed", output_sha256=_digest(output_path)[1])  # Only playable commit LAST.
                return get_assembly(root, ident)
            except BaseException as exc:
                if admitted and _metadata(root, ident).state == "running":
                    state = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
                    _set_state(root, ident, state, error=f"{type(exc).__name__}: {exc}"[:2000])
                raise


router = APIRouter()


def _service(request: Request):
    return request.app.state.service


@router.post("/assemblies/{assembly_id}")
async def assemble(assembly_id: str, request: Request):
    canonical_id(assembly_id)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            raise HTTPException(413, "Assembly request exceeds metadata limit")
        body.extend(chunk)
    try:
        dto = AssemblyRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid assembly request") from exc
    pipe = AssemblyPipe(_service(request)).have(assembly_id).from_end(dto.end_run_id).save_video()
    task = asyncio.create_task(pipe.arun(), name=f"h3-assembly-{assembly_id}")
    # The shielded task owns the CPU lease; disconnected HTTP must neither cancel it nor orphan exceptions.
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return await asyncio.shield(task)


@router.get("/assemblies")
def collection(request: Request, end_run_id: str | None = None,
               limit: str = Query("50", max_length=5), offset: str = Query("0", max_length=5)):
    if not all(value.isascii() and value.isdecimal() for value in (limit, offset)):
        raise ValueError("Assembly page bounds must be unsigned integers")
    return list_assemblies(_service(request).settings.project_root, end_run_id=end_run_id,
                          limit=int(limit), offset=int(offset))


@router.get("/assemblies/{assembly_id}")
def metadata(assembly_id: str, request: Request):
    return get_assembly(_service(request).settings.project_root, assembly_id)


@router.get("/assemblies/{assembly_id}/video")
async def video(assembly_id: str, request: Request):
    path = await _thread(assembly_video, _service(request).settings.project_root, assembly_id)
    return FileResponse(path, media_type="video/mp4", filename="assembly.mp4", content_disposition_type="inline")
