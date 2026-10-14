"""Roteiro plans and explicit intents; native pipes remain the only video engine."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from stat import S_ISREG
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .generation.dispatcher import Conflict
from .generation.i2v import I2VPipe
from .generation.models import ContinueRequest, RunRequest
from .generation.v2v import V2VPipe
from .generation.workflow import (
    DEFAULT_DURATION_SECONDS,
    I2V_CONFIG,
    MAX_DURATION_SECONDS,
    V2V_CONFIG,
    frames_for_duration,
)
from .grok import FIXED_EDITOR_MODEL, PromptRequest, read_editor
from .infrastructure.comfy import QueueBusy
from .infrastructure.grok_image import (
    IMAGE_MAX_BYTES,
    VIDEO_MAX_BYTES,
    EditorReference,
    _directory,
    _file_digest,
    _parent,
    _source,
    continuation_frame,
    owned_image,
    snapshot_digest,
)
from .infrastructure.grok_oauth import OAuthError
from .infrastructure.store import Store

MAX_METADATA_BYTES = 1024 * 1024
MAX_BLOCKS = 50  # Local planning budget, not a model or GPU capacity claim.
DEFAULT_SCRIPT_SYSTEM = (
    'Divide the user idea into consecutive video blocks without generating videos. '
    'Preserve identity, actions and the order of changes. Do not invent facts about future frames. '
    'Return only strict JSON: {"name":"title", "blocks":['
    '{"action":"action", "duration_seconds":8, "prompt":"editable base instruction"}]}. '
    'Use exactly the requested block count and positive durations up to 10 seconds with at most '
    'two decimal places. Action and prompt must be nonempty and at most 12000 characters. '
    'Write each video prompt in English, preserving any explicitly requested dialogue verbatim. '
    'Do not include IDs, seeds, explanations, markdown or model parameters.'
)


def canonical(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected a canonical UUID")
    return value


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Block(StrictDTO):
    id: str = Field(min_length=36, max_length=36)
    action: str = Field(min_length=1, max_length=12000)
    duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS, allow_inf_nan=False)
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    prompt: str = Field(min_length=1, max_length=12000)

    @field_validator("id")
    @classmethod
    def key(cls, value):
        return canonical(value)

    @field_validator("action", "prompt")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Text cannot be whitespace")
        return value

    @field_validator("duration_seconds")
    @classmethod
    def duration(cls, value):
        if Decimal(str(value)) % Decimal("0.01"):
            raise ValueError("Duration requires at most two decimal places")
        frames_for_duration(value)
        return value


class PlanFields(StrictDTO):
    name: str = Field(max_length=256)
    idea: str = Field(min_length=1, max_length=12000)
    reference: EditorReference
    adopted: bool
    blocks: list[Block] = Field(max_length=MAX_BLOCKS)

    @field_validator("idea")
    @classmethod
    def idea_nonblank(cls, value):
        return Block.nonblank(value)

    @model_validator(mode="after")
    def unique(self):
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Duplicate planned block key")
        if self.adopted and not self.blocks:
            raise ValueError("An adopted plan requires blocks")
        return self


class CreatePlan(PlanFields):
    name: str = Field(default="", max_length=256)
    adopted: bool = False
    blocks: list[Block] = Field(default_factory=list, max_length=MAX_BLOCKS)


class UpdatePlan(PlanFields):
    expected_revision: StrictInt = Field(ge=1)


class ConvertFreestyle(StrictDTO):
    roteiro_id: str

    _id = field_validator("roteiro_id")(Block.key.__func__)


class RemovePlan(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)


class Snapshot(StrictDTO):
    prompt: str = Field(min_length=1, max_length=12000)
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS, allow_inf_nan=False)
    parent_id: str | None
    reference: EditorReference
    reference_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    _prompt = field_validator("prompt")(Block.nonblank.__func__)
    _duration = field_validator("duration_seconds")(Block.duration.__func__)

    @field_validator("parent_id")
    @classmethod
    def parent(cls, value):
        return canonical(value) if value is not None else None


class Generate(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=12000)
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS, allow_inf_nan=False)
    parent_id: str | None

    _prompt = field_validator("prompt")(Block.nonblank.__func__)
    _duration = field_validator("duration_seconds")(Block.duration.__func__)
    _parent = field_validator("parent_id")(Snapshot.parent.__func__)


class MediaProof(StrictDTO):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: StrictInt = Field(gt=0)
    device: StrictInt = Field(ge=0)
    inode: StrictInt = Field(ge=0)
    mtime_ns: StrictInt
    ctime_ns: StrictInt


class ImportedSource(StrictDTO):
    projection: dict
    manifest: dict
    media: MediaProof | None


class Intent(StrictDTO):
    intent_id: str
    run_id: str
    roteiro_id: str
    block_id: str
    source_revision: StrictInt = Field(ge=1)
    snapshot: Snapshot
    origin: Literal["native", "freestyle", "bridge"] = "native"
    target_run_id: str | None = None
    source: ImportedSource | None = None
    admission: Literal["uncertain", "admitted", "rejected"] = "uncertain"
    error: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def identity(self):
        for value in (self.intent_id, self.run_id, self.roteiro_id, self.block_id):
            canonical(value)
        if (self.origin == "freestyle") != (self.source is not None):
            raise ValueError("Imported attempt requires explicit source evidence")
        if self.intent_id != self.run_id:
            raise ValueError("Intent and native Run IDs must be identical")
        if (self.origin == "bridge") != (self.target_run_id is not None):
            raise ValueError("Bridge intent requires its target anchor")
        if self.target_run_id is not None:
            canonical(self.target_run_id)
        return self


class Document(PlanFields):
    id: str
    revision: StrictInt = Field(ge=1)
    reference_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    attempts: list[Intent] = Field(default_factory=list)
    selected_runs: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def integrity(self):
        canonical(self.id)
        keys = {block.id for block in self.blocks}
        ids = set()
        for attempt in self.attempts:
            if (attempt.roteiro_id != self.id or attempt.block_id not in keys
                    or attempt.source_revision > self.revision or attempt.intent_id in ids
                    or attempt.snapshot.reference != self.reference
                    or attempt.snapshot.reference_sha256 != self.reference_sha256):
                raise ValueError("Roteiro intent ownership or snapshot is corrupt")
            ids.add(attempt.intent_id)
        for key, ident in self.selected_runs.items():
            if key not in keys or not any(a.block_id == key and a.run_id == ident for a in self.attempts):
                raise ValueError("Selected version must belong to its planned block")
        return self


class ProposalRequest(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)
    count: StrictInt = Field(ge=1, le=MAX_BLOCKS)
    duration_seconds: float = Field(default=DEFAULT_DURATION_SECONDS, gt=0,
                                    le=MAX_DURATION_SECONDS, allow_inf_nan=False)
    seed: StrictInt = Field(ge=0, le=2**53 - 1)

    _duration = field_validator("duration_seconds")(Block.duration.__func__)


class TailRequest(ProposalRequest):
    idea: str = Field(min_length=1, max_length=12000)

    _idea = field_validator("idea")(Block.nonblank.__func__)


class AdoptTail(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)
    blocks: list[Block] = Field(min_length=1, max_length=MAX_BLOCKS)

    @model_validator(mode="after")
    def unique(self):
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Duplicate tail block key")
        return self


class ProposedBlock(StrictDTO):
    action: str = Field(min_length=1, max_length=12000)
    duration_seconds: float = Field(gt=0, le=MAX_DURATION_SECONDS, allow_inf_nan=False)
    prompt: str = Field(min_length=1, max_length=12000)

    _action = field_validator("action")(Block.nonblank.__func__)
    _prompt = field_validator("prompt")(Block.nonblank.__func__)
    _duration = field_validator("duration_seconds")(Block.duration.__func__)


class ProposedPlan(StrictDTO):
    name: str = Field(min_length=1, max_length=256)
    blocks: list[ProposedBlock] = Field(min_length=1, max_length=MAX_BLOCKS)

    _name = field_validator("name")(Block.nonblank.__func__)


class ScriptConfig(StrictDTO):
    system_prompt: str = Field(min_length=1, max_length=100000)

    _system = field_validator("system_prompt")(Block.nonblank.__func__)


def strict_json(raw: bytes | str):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("Non-finite JSON number")

    if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > MAX_METADATA_BYTES:
        raise ValueError("Roteiro metadata exceeds 1 MiB")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid structured JSON") from exc


def read_file(directory: int, name: str):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or not 0 < info.st_size <= MAX_METADATA_BYTES):
            raise ValueError("Roteiro metadata must be bounded, regular and owned")
        raw = stream.read(MAX_METADATA_BYTES + 1)
        after = os.fstat(stream.fileno())
        if (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Roteiro metadata changed while reading")
    return strict_json(raw)


def encoded_metadata(value) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("Roteiro metadata exceeds 1 MiB")
    return raw


def write_file(directory: int, name: str, value, *, exclusive: bool = False):
    raw = encoded_metadata(value)
    # Inspect existing evidence, including ownership and corruption, before replacement.
    try:
        read_file(directory, name)
    except FileNotFoundError:
        pass
    else:
        if exclusive:
            raise Conflict("Owned intent or document already exists")
    temporary = f".write-{uuid4()}.part"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass  # Atomic replacement already consumed this invocation's temporary.


@contextmanager
def locked(directory: int):
    fd = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("Invalid roteiro writer lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Conflict("Roteiro is being changed by another writer") from exc
        yield
    finally:
        os.close(fd)


class Roteiro:
    """One vertical owns document mutation, proposal isolation and intent correlation."""

    def __init__(self, service):
        self.service = service
        self.root: Path = service.store.root

    def get(self, ident: str) -> Document:
        if self.removed(ident):
            raise FileNotFoundError("Roteiro removed")
        with _directory(self.root, (".data", "roteiros", canonical(ident))) as directory:
            doc = Document.model_validate(read_file(directory, "plan.json"))
        if doc.id != ident:
            raise ValueError("Roteiro ID disagrees with owned directory")
        return doc

    def list(self):
        try:
            with _directory(self.root, (".data", "roteiros")) as directory:
                names = os.listdir(directory)
        except FileNotFoundError:
            return {"items": [], "total": 0}
        ids = []
        for name in names:
            if name in {"editor.json", ".lock", ".locks"} or name.startswith(".write-"):
                continue
            ids.append(canonical(name))
        # Bound library work independently of any native run history.
        if len(ids) > 1000:
            raise ValueError("Roteiro library exceeds 1000 documents")
        items = [self.view(self.get(ident)) for ident in sorted(ids) if not self.removed(ident)]
        return {"items": items, "total": len(items)}

    def removed(self, ident: str) -> bool:
        with _directory(self.root, (".data", "roteiros", canonical(ident))) as directory:
            try:
                marker = read_file(directory, "removed.json")
            except FileNotFoundError:
                return False
        if marker != {"id": ident, "removed": True}:
            raise ValueError("Invalid roteiro removal marker")
        return True

    async def reference_digest(self, reference: EditorReference) -> str:
        async with owned_image(self.root, reference) as (snapshot, _):
            return await asyncio.to_thread(snapshot_digest, snapshot)

    def reference_available(self, reference):
        if reference.source_root == "runs":
            run_id, _ = self.service.store.run_image_parts(reference.path)
            self.service.store.get(run_id)

    async def create(self, payload: CreatePlan) -> dict:
        from .roteiro_batch import assert_batch_available
        assert_batch_available(self.service)
        digest = await self.reference_digest(payload.reference)
        doc = Document(**payload.model_dump(), id=str(uuid4()), revision=1,
                       reference_sha256=digest)
        encoded_metadata(doc.model_dump())  # Reject aggregate overflow before directory reservation.
        with (_directory(self.root, (".data", "roteiros"), create=True) as library,
              locked(library)):
            assert_batch_available(self.service)
            self.reference_available(payload.reference)
            with (_directory(self.root, (".data", "roteiros", doc.id), create=True) as directory,
                  locked(directory)):
                write_file(directory, "plan.json", doc.model_dump(), exclusive=True)
        return self.view(doc)

    def check_revision(self, doc: Document, expected: int, *, edit_id: str | None = None):
        from .roteiro_batch import assert_batch_available
        from .roteiro_edit import assert_edit_available

        assert_batch_available(self.service)
        assert_edit_available(self.service, doc.id, exclude=edit_id)
        if self.removed(doc.id):
            raise Conflict("Roteiro removed from library; history is read-only")
        if doc.revision != expected:
            raise Conflict("Roteiro revision changed; preserve the local draft and reread")

    async def update(self, ident: str, payload: UpdatePlan) -> dict:
        from .roteiro_batch import assert_batch_available
        assert_batch_available(self.service)
        original = self.get(ident)
        self.check_revision(original, payload.expected_revision)
        digest = await self.reference_digest(payload.reference)
        with (_directory(self.root, (".data", "roteiros")) as library, locked(library),
              _directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            self.reference_available(payload.reference)
            doc = self.get(ident)
            self.check_revision(doc, payload.expected_revision)
            if doc.attempts:
                if (payload.reference != doc.reference or digest != doc.reference_sha256
                        or payload.idea != doc.idea or not payload.adopted):
                    raise Conflict("Submitted identity, idea and adoption are immutable")
                submitted = {a.block_id for a in doc.attempts}
                frozen = max(i for i, block in enumerate(doc.blocks) if block.id in submitted) + 1
                if payload.blocks[:frozen] != doc.blocks[:frozen]:
                    raise Conflict("Submitted prefix is immutable; edit only future unsent blocks")
            updated = Document(**payload.model_dump(exclude={"expected_revision"}),
                               id=doc.id, revision=doc.revision + 1,
                               reference_sha256=digest, attempts=doc.attempts,
                               selected_runs=doc.selected_runs)
            write_file(directory, "plan.json", updated.model_dump())
        return self.view(updated)

    def script_config(self) -> dict:
        # Current pin is read through the normal public editor config, never OAuth.
        model = read_editor(self.root).model
        if model != FIXED_EDITOR_MODEL:
            raise Conflict("Roteirista requires the current fixed Grok editor model")
        try:
            with _directory(self.root, (".data", "roteiros")) as directory:
                config = ScriptConfig.model_validate(read_file(directory, "editor.json"))
        except FileNotFoundError:
            config = ScriptConfig(system_prompt=DEFAULT_SCRIPT_SYSTEM)
        return {**config.model_dump(), "model": model}

    def save_script(self, payload: ScriptConfig) -> dict:
        current = self.script_config()
        with (_directory(self.root, (".data", "roteiros"), create=True) as directory,
              locked(directory)):
            write_file(directory, "editor.json", payload.model_dump())
        return {**payload.model_dump(), "model": current["model"]}

    async def propose(self, ident: str, payload: ProposalRequest, grok) -> dict:
        from .roteiro_batch import assert_batch_available
        assert_batch_available(self.service)
        doc = self.get(ident)
        self.check_revision(doc, payload.expected_revision)
        digest = await self.reference_digest(doc.reference)
        if digest != doc.reference_sha256:
            raise Conflict("Original reference changed")
        config = self.script_config()
        prompt = json.dumps({"idea": doc.idea, "name": doc.name, "count": payload.count,
                             "duration_seconds": payload.duration_seconds}, ensure_ascii=False)
        candidate_id = str(uuid4())
        source = {"name": doc.name, "idea": doc.idea, "reference": doc.reference.model_dump(),
                  "reference_sha256": doc.reference_sha256}
        # Reservation is durable, but locks do not span provider/media awaits. No automatic retry.
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
              locked(directory)):
            self.check_revision(self.get(doc.id), doc.revision)
            write_file(directory, f"proposal-{candidate_id}.json", {
                "id": candidate_id, "roteiro_id": doc.id, "source_revision": doc.revision,
                "state": "uncertain", "request": payload.model_dump(), "source": source,
            }, exclusive=True)
        schema = ProposedPlan.model_json_schema()
        schema["properties"]["blocks"]["minItems"] = payload.count
        schema["properties"]["blocks"]["maxItems"] = payload.count
        result = await grok.complete(PromptRequest(system_prompt=config["system_prompt"],
                                                  prompt=prompt, model=config["model"],
                                                  reference=doc.reference),
                                     output_schema=schema, schema_name="h3_roteiro")
        raw = result.get("text") if isinstance(result, dict) else None
        if not isinstance(raw, str):
            raise ValueError("Grok proposal did not contain text")  # noqa: TRY004 - invalid wire response.
        if len(raw.encode("utf-8")) > MAX_METADATA_BYTES // 2:
            raise ValueError("Proposal text exceeds 512 KiB; not truncated or adopted")
        try:
            proposed = ProposedPlan.model_validate(strict_json(raw))
            if len(proposed.blocks) != payload.count:
                raise ValueError("Proposal count does not match the explicit request")
        except ValueError:
            # Raw invalid text is bounded data, not an instruction or permission to guess fields.
            invalid = {"id": candidate_id, "roteiro_id": doc.id, "source_revision": doc.revision,
                       "source": source,
                       "raw_text": raw, "error": "invalid_proposal",
                       "detail": "Response cannot be converted into strict planned blocks",
                       "stale": self.get(doc.id).revision != doc.revision}
            with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
                  locked(directory)):
                invalid["stale"] = self.get(doc.id).revision != doc.revision
                write_file(directory, f"proposal-{candidate_id}.json", invalid)
            return invalid
        blocks = [Block(id=str(uuid4()), seed=payload.seed, **b.model_dump())
                  for b in proposed.blocks]
        candidate = {"id": candidate_id, "roteiro_id": doc.id, "source_revision": doc.revision,
                     "source": source,
                     "name": proposed.name, "blocks": [b.model_dump() for b in blocks],
                     "raw_text": raw, "stale": False}
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
              locked(directory)):
            candidate["stale"] = self.get(doc.id).revision != doc.revision
            write_file(directory, f"proposal-{candidate_id}.json", candidate)
        return candidate

    def tail_parent(self, doc: Document) -> str:
        if not doc.adopted or not doc.blocks:
            raise Conflict("Tail requires an adopted roteiro with complete accepted videos")
        parent_id = None
        for index, block in enumerate(doc.blocks):
            attempts = [a for a in doc.attempts if a.block_id == block.id]
            if not attempts:
                raise Conflict("Finish every existing planned block before extending the tail")
            attempt = self.selected_attempt(doc, block.id)
            observed = self.observed(attempt)
            if observed["state"] != "accepted" or observed["run"] is None:
                raise Conflict("Every latest block attempt must be accepted and proven")
            if not doc.selected_runs and attempt.snapshot.parent_id != parent_id:
                raise Conflict("Accepted blocks do not form the exact current sequence")
            self.parent(doc, index + 1, attempt.run_id)
            parent_id = attempt.run_id
        return parent_id

    def tail_media(self, parent_id: str) -> dict:
        manifest, _, _, _, _ = _parent(self.root, parent_id)
        identity, digest = _file_digest(
            self.root, (".data", "runs", parent_id, "chunk.mp4"), VIDEO_MAX_BYTES)
        return {"manifest": manifest, "video_identity": list(identity), "video_sha256": digest}

    def tail_source(self, doc: Document) -> dict:
        return {"name": doc.name, "idea": doc.idea, "reference": doc.reference.model_dump(),
                "reference_sha256": doc.reference_sha256}

    def tail_current(self, doc: Document, candidate: dict):
        if (doc.revision != candidate["source_revision"]
                or [b.model_dump() for b in doc.blocks] != candidate["prefix_blocks"]
                or self.tail_source(doc) != candidate["source"]
                or self.tail_parent(doc) != candidate["parent_id"]
                or self.tail_media(candidate["parent_id"]) != candidate["parent_proof"]
                or _file_digest(self.root, _source(self.root, doc.reference)[0],
                                IMAGE_MAX_BYTES)[1] != doc.reference_sha256):
            raise Conflict("Tail source, accepted parent or publication changed; preserve proposal")

    def get_tail(self, ident: str, tail_id: str) -> dict:
        canonical(tail_id)
        with (_directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            candidate = read_file(directory, f"tail-{tail_id}.json")
            if candidate.get("id") != tail_id or candidate.get("roteiro_id") != ident:
                raise ValueError("Tail candidate ownership disagrees with path")
            doc = self.get(ident)
            if candidate["state"] == "adopting":
                combined = candidate["prefix_blocks"] + candidate["adopted_blocks"]
                if (doc.revision == candidate["source_revision"] + 1
                        and [b.model_dump() for b in doc.blocks] == combined
                        and self.tail_source(doc) == candidate["source"]):
                    candidate["state"] = "adopted"
                    candidate["adopted_revision"] = doc.revision
                    write_file(directory, f"tail-{tail_id}.json", candidate)
                elif doc.revision == candidate["source_revision"]:
                    candidate["state"] = "proposed"
                    write_file(directory, f"tail-{tail_id}.json", candidate)
            candidate["stale"] = doc.revision != candidate.get(
                "adopted_revision", candidate["source_revision"])
            if candidate["state"] != "adopted":
                try:
                    self.tail_current(doc, candidate)
                except (Conflict, OSError, ValueError):
                    candidate["stale"] = True
            return candidate

    async def propose_tail(self, ident: str, tail_id: str, payload: TailRequest, grok,
                           *, submission: dict | None = None) -> dict:
        canonical(tail_id)
        doc = self.get(ident)
        self.check_revision(doc, payload.expected_revision)
        if len(doc.blocks) + payload.count > MAX_BLOCKS:
            raise Conflict("Tail exceeds the existing 50-block planning budget")
        parent_id = self.tail_parent(doc)
        if await self.reference_digest(doc.reference) != doc.reference_sha256:
            raise Conflict("Original reference changed")
        async with continuation_frame(self.root, parent_id, doc.reference) as (_, recheck, digest):
            await asyncio.to_thread(recheck)
            if digest != doc.reference_sha256:
                raise Conflict("Tail parent identity disagrees with original reference")
            parent_proof = await asyncio.to_thread(self.tail_media, parent_id)
        config = self.script_config()
        prompt = json.dumps({
            "task": "Plan only new tail block intentions after the accepted video sequence. "
                    "Image 1 is original identity; image 2 is the actual final frame of the "
                    "accepted parent. Future frames are unknown. Preserve the existing prefix. "
                    "Do not claim exact timing or guaranteed artistic continuity.",
            "original_idea": doc.idea, "name": doc.name,
            "accepted_prefix": [
                {"id": b.id, "editorial_intention": b.action, "run_id": attempt.run_id,
                 "prompt": attempt.snapshot.prompt, "duration_seconds": attempt.snapshot.duration_seconds}
                for b in doc.blocks if (attempt := self.selected_attempt(doc, b.id)) is not None
            ],
            "tail_idea": payload.idea, "count": payload.count,
            "duration_seconds": payload.duration_seconds,
        }, ensure_ascii=False)
        candidate = {
            "id": tail_id, "roteiro_id": doc.id, "source_revision": doc.revision,
            "parent_id": parent_id, "prefix_block_ids": [b.id for b in doc.blocks],
            "prefix_blocks": [b.model_dump() for b in doc.blocks],
            "source": self.tail_source(doc), "parent_proof": parent_proof,
            "name": doc.name, "blocks": [], "raw_text": "",
            "state": "uncertain", "stale": False, "request": payload.model_dump(),
            "config": config, "planning_prompt": prompt,
        }
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
              locked(directory)):
            for name in os.listdir(directory):
                if name == f"tail-{tail_id}.json":
                    if submission is not None:
                        submission["reserved"] = True
                    raise Conflict("Tail ID already exists; GET the same ID without replaying POST")
                if (name.startswith("tail-") and name.endswith(".json")
                        and read_file(directory, name).get("state") in {"uncertain", "adopting"}):
                    raise Conflict("An earlier tail request remains uncertain; recover its ID")
            self.check_revision(self.get(doc.id), doc.revision)
            self.tail_current(self.get(doc.id), candidate)
            if submission is not None:
                submission["reserved"] = True
            write_file(directory, f"tail-{tail_id}.json", candidate, exclusive=True)
        schema = ProposedPlan.model_json_schema()
        schema["properties"]["blocks"].update(minItems=payload.count, maxItems=payload.count)
        try:
            result = await grok.complete(PromptRequest(
                system_prompt=config["system_prompt"], prompt=prompt, model=config["model"],
                reference=doc.reference, continuation_parent_id=parent_id),
                output_schema=schema, schema_name="h3_roteiro")
        except OAuthError as exc:
            if 400 <= exc.status < 500:
                candidate.update(state="invalid", error=exc.code,
                                 detail="Provider explicitly refused this planning request")
                with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
                      locked(directory)):
                    write_file(directory, f"tail-{tail_id}.json", candidate)
            raise
        raw = result.get("text") if isinstance(result, dict) else None
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_METADATA_BYTES // 2:
            raise ValueError("Tail response is missing text or exceeds 512 KiB; not truncated")
        candidate["raw_text"] = raw
        try:
            proposed = ProposedPlan.model_validate(strict_json(raw))
            if len(proposed.blocks) != payload.count:
                raise ValueError("Tail proposal count differs from request")
            candidate["blocks"] = [Block(id=str(uuid4()), seed=payload.seed, **b.model_dump())
                                   .model_dump() for b in proposed.blocks]
            candidate["state"] = "proposed"
        except ValueError:
            candidate.update(state="invalid", error="invalid_proposal",
                             detail="Response cannot be converted into strict new tail blocks")
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
              locked(directory)):
            try:
                self.tail_current(self.get(doc.id), candidate)
            except (Conflict, OSError, ValueError):
                candidate["stale"] = True
            write_file(directory, f"tail-{tail_id}.json", candidate)
        return candidate

    async def adopt_tail(self, ident: str, tail_id: str, payload: AdoptTail) -> dict:
        candidate = self.get_tail(ident, tail_id)
        if candidate["state"] == "adopted":
            raise Conflict("Tail already adopted; GET the same ID and reread the roteiro")
        if candidate["state"] != "proposed":
            raise Conflict("Only a valid proposed tail may be explicitly adopted")
        doc = self.get(ident)
        if await self.reference_digest(doc.reference) != doc.reference_sha256:
            raise Conflict("Original reference changed")
        with (_directory(self.root, (".data", "roteiros")) as library, locked(library),
              _directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            candidate = read_file(directory, f"tail-{canonical(tail_id)}.json")
            if candidate["state"] != "proposed":
                raise Conflict("Tail state changed; recover the same ID")
            doc = self.get(ident)
            self.check_revision(doc, payload.expected_revision)
            self.tail_current(doc, candidate)
            proposed_ids = {b["id"] for b in candidate["blocks"]}
            if not {b.id for b in payload.blocks} <= proposed_ids:
                raise Conflict("Adopt only new block IDs belonging to this tail proposal")
            updated = Document(**{**doc.model_dump(), "revision": doc.revision + 1,
                                  "blocks": [b.model_dump() for b in doc.blocks + payload.blocks]})
            encoded_metadata(updated.model_dump())
            candidate.update(state="adopting", adopted_blocks=[b.model_dump() for b in payload.blocks])
            # This recovery marker precedes plan publication; same-ID GET proves a partial commit.
            write_file(directory, f"tail-{tail_id}.json", candidate)
            write_file(directory, "plan.json", updated.model_dump())
            candidate.update(state="adopted", adopted_revision=updated.revision, stale=False)
            write_file(directory, f"tail-{tail_id}.json", candidate)
        return self.view(updated)

    def intent(self, doc: Document, key: str, intent_id: str) -> Intent:
        canonical(key)
        canonical(intent_id)
        for attempt in doc.attempts:
            if attempt.intent_id == intent_id and attempt.block_id == key:
                return attempt
        raise FileNotFoundError("Unknown owned intent")

    def observed(self, intent: Intent) -> dict:
        value = intent.model_dump()
        value["snapshot"]["reference"] = {
            **value["snapshot"]["reference"], "sha256": intent.snapshot.reference_sha256,
        }
        value["snapshot"].pop("reference_sha256")
        value.update(state="not_admitted" if intent.admission == "rejected" else "uncertain",
                     run=None)
        if intent.admission == "rejected":
            return value
        try:
            if intent.origin == "freestyle":
                from .roteiro_conversion import observe_import
                current = observe_import(self, intent)
                value.update(admission="admitted", state=current.state, run=current.model_dump())
                value["error"] = None
                return value
            with _directory(self.root, (".data", "roteiros", ".locks")) as directory:
                marker = Intent.model_validate(read_file(directory, f"{intent.intent_id}.json"))
            if marker.model_dump(exclude={"admission", "error"}) != intent.model_dump(
                    exclude={"admission", "error"}):
                raise ValueError("Native correlation belongs to another intent")
            admitted = self.service.store.request(intent.run_id)
            current = self.service.store.get(intent.run_id)
            self.prove(intent, admitted)
            if Store.input_projection(admitted) != Store.input_projection(current):
                raise ValueError("Native manifest changed its immutable input")
            value.update(admission="admitted", state=current.state, run=current.model_dump())
            value["error"] = None
        except (OSError, ValueError, KeyError, TypeError, Conflict):
            # Missing/corrupt request after in-flight is uncertainty, never permission to POST again.
            value["admission"] = "uncertain"
        return value

    def prove(self, intent: Intent, run):
        snap = intent.snapshot
        operation = "bridge" if intent.origin == "bridge" else "v2v" if snap.parent_id else "i2v"
        identities = [r for r in run.references if r.get("role") == "identity"]
        if (run.id != intent.run_id or run.prompt != snap.prompt or run.seed != snap.seed
                or run.duration_seconds != snap.duration_seconds or run.parent_id != snap.parent_id
                or len(identities) != 1 or identities[0].get("source_root") != snap.reference.source_root
                or identities[0].get("source") != snap.reference.path
                or identities[0].get("sha256") != snap.reference_sha256
                or run.workflow_hash != self.service.builder.hash_for(operation)):
            raise ValueError("Native input does not prove this owned intent snapshot")
        # Hydration validates canonical continuation options and provenance without executing.
        if intent.origin == "bridge":
            from .generation.bridge import BridgePipe
            BridgePipe.from_run(self.service, run)
            if run.input_info.get("continuation", {}).get("target_run_id") != intent.target_run_id:
                raise ValueError("Bridge destination disagrees with owned intent")
        elif snap.parent_id:
            V2VPipe.from_run(self.service, run)
        else:
            I2VPipe.from_run(self.service, run)
        if snap.parent_id:
            doc = self.get(intent.roteiro_id)
            earlier = doc.attempts[:next(i for i, a in enumerate(doc.attempts)
                                       if a.intent_id == intent.intent_id)]
            parent = next((a for a in earlier if a.run_id == snap.parent_id), None)
            if parent is None or self.observed(parent)["state"] != "accepted":
                raise ValueError("Historical generation parent is not a proven accepted attempt")
            published_parent = self.service.store.get(parent.run_id)
            self.service.video_path(parent.run_id)
            if published_parent.decision is None or published_parent.decision.get("accepted") is not True:
                raise ValueError("Historical generation parent has no accepted decision")

    def selected_attempt(self, doc: Document, block_id: str) -> Intent | None:
        attempts = [a for a in doc.attempts if a.block_id == block_id]
        selected = doc.selected_runs.get(block_id)
        return next((a for a in attempts if a.run_id == selected), None) if selected else (
            attempts[-1] if attempts else None)

    def selected_run_ids(self, doc: Document) -> list[str]:
        result = []
        for block in doc.blocks:
            attempt = self.selected_attempt(doc, block.id)
            if attempt is None or self.observed(attempt)["state"] != "accepted":
                raise Conflict("Accept a selected version of every block before assembling")
            result.append(attempt.run_id)
        return result

    def view(self, doc: Document) -> dict:
        return {**doc.model_dump(), "attempts": [self.observed(a) for a in doc.attempts]}

    def parent(self, doc: Document, index: int, selected: str | None):
        if index == 0:
            if selected is not None:
                raise Conflict("The first planned block has no parent")
            return
        if selected is None:
            raise Conflict("Continuation requires its exact accepted predecessor")
        previous = doc.blocks[index - 1]
        if previous.id in doc.selected_runs and doc.selected_runs[previous.id] != selected:
            raise Conflict("Parent must be the selected accepted predecessor version")
        prior = next((a for a in doc.attempts
                      if a.block_id == previous.id and a.run_id == selected), None)
        if prior is None:
            raise Conflict("Parent is not an owned predecessor attempt")
        observed = self.observed(prior)
        if observed["state"] != "accepted" or observed["run"] is None:
            raise Conflict("Predecessor must be natively accepted and proven")
        parent = self.service.store.get(selected)
        self.service.video_path(selected)  # Existing publication/ownership guard, no new media engine.
        if parent.decision is None or parent.decision.get("accepted") is not True:
            raise Conflict("Predecessor has no explicit accepted decision")
        # observed(prior) recursively proves that parent's original owned ancestry as well.

    def reserve(self, doc: Document, key: str, intent_id: str, payload: Generate) -> Intent:
        from .roteiro_batch import assert_batch_available
        assert_batch_available(self.service)
        canonical(intent_id)
        canonical(key)
        with _directory(self.root, (".data", "roteiros", doc.id)) as directory:  # noqa: SIM117
            with locked(directory):
                doc = self.get(doc.id)
                if any(a.intent_id == intent_id for a in doc.attempts):
                    raise Conflict("Intent already exists; GET this same ID, never replay POST")
                if self.service.store.directory(intent_id).exists():
                    raise Conflict("Run UUID already exists outside this new intent")
                self.check_revision(doc, payload.expected_revision)
                if not doc.adopted:
                    raise Conflict("Adopt the roteiro explicitly before generating")
                index = next((i for i, b in enumerate(doc.blocks) if b.id == key), None)
                if index is None:
                    raise FileNotFoundError("Unknown planned block")
                block = doc.blocks[index]
                old = [a for a in doc.attempts if a.block_id == key]
                if old:
                    latest = self.observed(old[-1])
                    if latest["state"] not in {"rejected", "interrupted", "not_admitted"}:
                        raise Conflict("Previous attempt is accepted, active, failed or uncertain")
                    if old[-1].snapshot.parent_id != payload.parent_id:
                        raise Conflict("Retry must preserve the original parent")
                elif (payload.prompt, payload.seed, payload.duration_seconds) != (
                        block.prompt, block.seed, block.duration_seconds):
                    raise Conflict("Save the chosen draft before creating an intent")
                # Any other outstanding attempt fences this roteiro even if the native slot vanished.
                if any(self.observed(a)["state"] in {"uncertain", "queued", "running", "ready_for_review"}
                       for a in doc.attempts):
                    raise Conflict("An owned attempt is still active, awaiting review or uncertain")
                self.parent(doc, index, payload.parent_id)
                attempt = Intent(intent_id=intent_id, run_id=intent_id, roteiro_id=doc.id,
                                 block_id=key, source_revision=doc.revision,
                                 snapshot=Snapshot(**payload.model_dump(exclude={"expected_revision"}),
                                                   reference=doc.reference,
                                                   reference_sha256=doc.reference_sha256))
                # The intent is the first durable write. A crash at any later boundary stays fenced.
                updated = doc.model_copy(update={"attempts": [*doc.attempts, attempt]})
                write_file(directory, "plan.json", updated.model_dump())
                try:
                    with _directory(self.root, (".data", "roteiros", ".locks"), create=True) as markers:
                        write_file(markers, f"{intent_id}.json", attempt.model_dump(), exclusive=True)
                except (Conflict, FileExistsError):
                    self.finish(attempt, "rejected", "Intent UUID already belongs to another request",
                                directory=directory)
                    raise Conflict("Intent UUID already reserved; use GET, never replay") from None
                return attempt

    def finish(self, intent: Intent, admission: str, error: str | None = None, *, directory=None):
        def save(fd):
            doc = self.get(intent.roteiro_id)
            attempts = [a.model_copy(update={"admission": admission, "error": error})
                        if a.intent_id == intent.intent_id else a for a in doc.attempts]
            write_file(fd, "plan.json", doc.model_copy(update={"attempts": attempts}).model_dump())
        if directory is not None:
            save(directory)
        else:
            with (_directory(self.root, (".data", "roteiros", intent.roteiro_id)) as fd,
                  locked(fd)):
                save(fd)

    async def generate(self, ident: str, key: str, intent_id: str, payload: Generate) -> dict:
        doc = self.get(ident)
        attempt = self.reserve(doc, key, intent_id, payload)
        try:
            digest = await self.reference_digest(attempt.snapshot.reference)
            if digest != attempt.snapshot.reference_sha256:
                raise Conflict("Original reference changed; native admission was not attempted")
            if payload.parent_id is None:
                native = RunRequest(seed=payload.seed, prompt=payload.prompt,
                                    duration_seconds=payload.duration_seconds,
                                    references=[attempt.snapshot.reference.model_dump()])
                pipe = (I2VPipe(self.service).have(native).with_run_id(intent_id)
                        .with_workflow(I2V_CONFIG).save_chunk())
            else:
                self.parent(self.get(ident), next(i for i, b in enumerate(doc.blocks) if b.id == key),
                            payload.parent_id)
                native = ContinueRequest(seed=payload.seed, prompt=payload.prompt,
                                         duration_seconds=payload.duration_seconds)
                pipe = (V2VPipe(self.service).have(native).with_run_id(intent_id)
                        .from_parent(payload.parent_id).with_last_frame().with_original_identity()
                        .with_motion_tail().with_workflow(V2V_CONFIG).save_chunk())
            pipe.with_identity_proof(attempt.snapshot.reference.source_root,
                                     attempt.snapshot.reference.path,
                                     attempt.snapshot.reference_sha256)
        except (OSError, ValueError):
            self.finish(attempt, "rejected", "Preflight rejected before native submission")
            raise
        try:
            await self.service.submit(pipe)
        except (Conflict, QueueBusy, ValueError) as exc:
            # These explicit native rejections are known only if admission did not seal a Run.
            if (not pipe._sealed and pipe.state.run is None
                    and not self.service.store.directory(intent_id).exists()):
                self.finish(attempt, "rejected", type(exc).__name__)
                raise
            self.finish(attempt, "uncertain", "Native admission result requires same-ID recovery")
        except Exception:  # noqa: BLE001 - preserve all uncertain native admissions, never replay.
            # A lost response or unexpected Store/dispatcher failure cannot allocate a replacement ID.
            self.finish(attempt, "uncertain", "Native admission result requires same-ID recovery")
        else:
            self.finish(attempt, "admitted")
        return self.observed(self.intent(self.get(ident), key, intent_id))


router = APIRouter(prefix="/roteiros", tags=["roteiros"])


def operation(request: Request) -> Roteiro:
    return Roteiro(request.app.state.service)


async def body(request: Request, model):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_METADATA_BYTES:
            raise HTTPException(413, "Roteiro JSON exceeds 1 MiB")
        raw.extend(chunk)
    try:
        return model.model_validate(strict_json(bytes(raw)))
    except ValueError as exc:
        raise HTTPException(422, "Invalid strict roteiro JSON") from exc


def response(value, status=200):
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


@router.get("")
async def list_roteiros(request: Request):
    return response(operation(request).list())


@router.post("", status_code=201)
async def create_roteiro(request: Request):
    return response(await operation(request).create(await body(request, CreatePlan)), 201)


@router.get("/editor")
async def script_editor(request: Request):
    return response(operation(request).script_config())


@router.put("/editor")
async def update_script_editor(request: Request):
    return response(operation(request).save_script(await body(request, ScriptConfig)))


@router.post("/from-freestyle/{end_id}", status_code=201)
async def convert_freestyle(end_id: str, request: Request):
    payload = await body(request, ConvertFreestyle)
    from .roteiro_conversion import convert
    return response(await convert(operation(request), end_id, payload.roteiro_id), 201)


@router.get("/{ident}")
async def get_roteiro(ident: str, request: Request):
    op = operation(request)
    return response(op.view(op.get(ident)))


@router.put("/{ident}")
async def update_roteiro(ident: str, request: Request):
    return response(await operation(request).update(ident, await body(request, UpdatePlan)))


@router.post("/{ident}/proposal")
async def propose_roteiro(ident: str, request: Request):
    try:
        value = await operation(request).propose(ident, await body(request, ProposalRequest),
                                                request.app.state.grok)
        return response(value, 422 if value.get("error") else 200)
    except OAuthError as exc:
        return response({"error": exc.code, "detail": str(exc)}, exc.status)


@router.post("/{ident}/blocks/{key}/attempts/{intent_id}", status_code=202)
async def generate_block(ident: str, key: str, intent_id: str, request: Request):
    return response(await operation(request).generate(ident, key, intent_id,
                                                      await body(request, Generate)), 202)


@router.get("/{ident}/blocks/{key}/attempts/{intent_id}")
async def get_intent(ident: str, key: str, intent_id: str, request: Request):
    op = operation(request)
    return response(op.observed(op.intent(op.get(ident), key, intent_id)))


@router.post("/{ident}/tail/{tail_id}")
async def propose_tail(ident: str, tail_id: str, request: Request):
    submission = {"reserved": True}
    try:
        op = operation(request)
        try:
            with _directory(op.root, (".data", "roteiros", canonical(ident))) as directory:
                os.stat(f"tail-{canonical(tail_id)}.json", dir_fd=directory,
                        follow_symlinks=False)
        except FileNotFoundError:
            submission["reserved"] = False
        value = await op.propose_tail(
            ident, tail_id, await body(request, TailRequest), request.app.state.grok,
            submission=submission)
        return response(value, 422 if value.get("error") else 200)
    except (HTTPException, OAuthError, Conflict, FileNotFoundError, ValueError) as exc:
        if isinstance(exc, OAuthError):
            error = {"error": exc.code, "detail": str(exc)}
            status = exc.status
        elif isinstance(exc, HTTPException):
            error, status = {"detail": exc.detail}, exc.status_code
        else:
            status = 409 if isinstance(exc, Conflict) else (
                404 if isinstance(exc, FileNotFoundError) else 400)
            error = {"detail": str(exc)}
        if not submission["reserved"]:
            try:
                with _directory(op.root, (".data", "roteiros", canonical(ident))) as directory:
                    os.stat(f"tail-{canonical(tail_id)}.json", dir_fd=directory,
                            follow_symlinks=False)
            except FileNotFoundError:
                error.update(tail_not_submitted=True, id=tail_id, roteiro_id=ident)
        return response(error, status)


@router.get("/{ident}/tail/{tail_id}")
async def get_tail(ident: str, tail_id: str, request: Request):
    return response(operation(request).get_tail(ident, tail_id))


@router.put("/{ident}/tail/{tail_id}")
async def adopt_tail(ident: str, tail_id: str, request: Request):
    return response(await operation(request).adopt_tail(
        ident, tail_id, await body(request, AdoptTail)))
