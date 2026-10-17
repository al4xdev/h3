"""Roteiro plans and explicit intents; native pipes remain the only video engine."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from stat import S_ISREG
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from ..generation.bridge import BridgePipe
from ..generation.dispatcher import Conflict
from ..generation.i2v import I2VPipe
from ..generation.models import BridgeRequest, ContinueRequest, RunRequest
from ..generation.v2v import V2VPipe
from ..generation.workflow import (
    BRIDGE_CONFIG,
    DEFAULT_DURATION_SECONDS,
    I2V_CONFIG,
    MAX_DURATION_SECONDS,
    V2V_CONFIG,
    frames_for_duration,
)
from ..grok import FIXED_EDITOR_MODEL, PromptRequest, read_editor
from ..infrastructure.comfy import QueueBusy
from ..infrastructure.grok_image import (
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
from ..infrastructure.grok_oauth import OAuthError
from ..infrastructure.store import Store

MAX_METADATA_BYTES = 16 * 1024 * 1024  # plan.json with up to 1000 blocks and their attempts.
MAX_RAW_TEXT_BYTES = 512 * 1024
MAX_BLOCKS = 1000  # Local planning budget (~1 h at 8 s), not a model or GPU capacity claim.
PLAN_CHUNK = 10  # Above this count planning becomes outline + parallel chunks.
PLAN_PARALLEL = 4
PLAN_EVIDENCE = ("draft_scenes", "scenes", "vision", "raw_texts")
CONTEXT_ACTIONS = 20  # Long-roteiro Grok context: recent intentions...
CONTEXT_PROMPTS = 3  # ...and submitted prompts only for the latest blocks.
BLOCK_STATES = {"accepted": "accepted", "ready_for_review": "ready_for_review",
                "queued": "active", "running": "active", "uncertain": "active"}
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
    # Present only for a bridge: the selected accepted run of the next block is the destination.
    target_run_id: str | None = None

    _prompt = field_validator("prompt")(Block.nonblank.__func__)
    _duration = field_validator("duration_seconds")(Block.duration.__func__)
    _parent = field_validator("parent_id", "target_run_id")(Snapshot.parent.__func__)

    @model_validator(mode="after")
    def bridge(self):
        if self.target_run_id is not None and (self.parent_id is None
                                               or self.target_run_id == self.parent_id):
            raise ValueError("A bridge requires a distinct accepted predecessor and destination")
        return self


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
    # Blocks taken out of the sequence keep their attempts, videos and decisions as history.
    removed_blocks: list[Block] = Field(default_factory=list)

    @model_validator(mode="after")
    def integrity(self):
        canonical(self.id)
        keys = {block.id for block in self.blocks}
        removed = {block.id for block in self.removed_blocks}
        if len(removed) != len(self.removed_blocks) or keys & removed:
            raise ValueError("Removed block keys must be unique and absent from the plan")
        ids = set()
        owned = set()
        for attempt in self.attempts:
            if (attempt.roteiro_id != self.id or attempt.block_id not in keys | removed
                    or attempt.source_revision > self.revision or attempt.intent_id in ids
                    or attempt.snapshot.reference != self.reference
                    or attempt.snapshot.reference_sha256 != self.reference_sha256):
                raise ValueError("Roteiro intent ownership or snapshot is corrupt")
            ids.add(attempt.intent_id)
            owned.add((attempt.block_id, attempt.run_id))
        if not removed <= {block for block, _ in owned}:
            raise ValueError("Only blocks with attempts are kept as removed history")
        for key, ident in self.selected_runs.items():
            if key not in keys or (key, ident) not in owned:
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


class Beat(StrictDTO):
    kind: Literal["action", "transition", "hold"]
    action: str = Field(min_length=1, max_length=12000)
    seconds: float = Field(gt=0, le=100000, allow_inf_nan=False)
    # Required-but-nullable: strict structured output rejects optional fields with defaults.
    dialogue: str | None = Field(min_length=1, max_length=4000)

    _action = field_validator("action")(Block.nonblank.__func__)


class Scene(StrictDTO):
    title: str = Field(min_length=1, max_length=256)
    beats: list[Beat] = Field(min_length=1, max_length=MAX_BLOCKS)

    _title = field_validator("title")(Block.nonblank.__func__)


class Timeline(StrictDTO):
    name: str = Field(min_length=1, max_length=256)
    scenes: list[Scene] = Field(min_length=1, max_length=MAX_BLOCKS)

    _name = field_validator("name")(Block.nonblank.__func__)


class Vision(StrictDTO):
    style: str = Field(min_length=1, max_length=4000)
    camera: str = Field(min_length=1, max_length=4000)
    light_and_color: str = Field(min_length=1, max_length=4000)
    rhythm: str = Field(min_length=1, max_length=4000)
    notes: str = Field(min_length=1, max_length=4000)


class Critique(StrictDTO):
    vision: Vision
    scenes: list[Scene] = Field(min_length=1, max_length=MAX_BLOCKS)


class SlicePrompt(StrictDTO):
    prompt: str = Field(min_length=1, max_length=12000)

    _prompt = field_validator("prompt")(Block.nonblank.__func__)


class PromptChunk(StrictDTO):
    blocks: list[SlicePrompt] = Field(min_length=1, max_length=PLAN_CHUNK)


# Planning is a chain of narrow calls with the owner's saved system prompt unchanged; every task
# text and output format travels in the user message and the structured output schema.
BEAT_FORMAT = '{"kind":"action","action":"...","seconds":30,"dialogue":null}'
TIMELINE_TASK = (
    "Step 1 of 3 (director): plan the film's timeline without writing video prompts. "
    "total_seconds is the whole film. Split it into scenes (a place, mood or situation), each "
    "lasting as long as the idea needs. Inside a scene, alternate actions with breathing room "
    'using contiguous beats: "action" = a sustained action; "hold" = the character holds a pose, '
    'reacts or breathes; "transition" = movement that links two actions (turning, walking into '
    "position, a clothing change in progress). After a strong action leave a hold. Sustained "
    "actions usually span 20-60 seconds, i.e. many blocks of block_seconds; do not cram a new "
    "action into every block. Scenes are contiguous, beats inside a scene are contiguous, and all "
    "beats together cover total_seconds. Each line of dialogue the user explicitly requested is "
    "placed ONCE, verbatim, in the dialogue field of exactly one beat; never repeat a requested "
    "line in several beats; dialogue is null otherwise. Future frames are unknown; do not claim "
    'exact timing or guaranteed artistic continuity. Output format for this step: {"name":"title",'
    f'"scenes":[{{"title":"scene","beats":[{BEAT_FORMAT}]}}]}}.'
)
CRITIC_TASK = (
    "Step 2 of 3 (critic and director of photography): review draft_scenes as a plan for a real "
    "film made of block_seconds clips. Fix monotony, missing breathing room (holds), abrupt jumps "
    "without transitions, overcrowded actions, implausible durations, and dialogue placed more "
    "than once or at the wrong moment (each requested line exactly once, verbatim). Keep the "
    "idea and the scene/beat structure rules; beats together still cover total_seconds. Then "
    "define the cinematographic vision. Output format for this step: {\"vision\":{\"style\":"
    "\"...\",\"camera\":\"...\",\"light_and_color\":\"...\",\"rhythm\":\"...\","
    f'"notes":"..."}},"scenes":[{{"title":"scene","beats":[{BEAT_FORMAT}]}}]}}.'
)
PROMPT_TASK = (
    "Step 3 of 3 (prompt writer): write one English video generation prompt for each listed "
    "block, describing only that block's block_seconds slice of the timeline and following the "
    "cinematographic vision. Inside a sustained beat, consecutive slices continue the same action "
    "smoothly without restarting or concluding it; conclude it only on its last slice. Never "
    'start the next beat early. A "hold" slice keeps the pose with only subtle natural motion '
    '(breathing, small gestures; the camera may drift slowly). A "transition" slice performs only '
    "the linking movement. The native video model freezes whatever the prompt does not describe, "
    "so every block prompt must describe concrete, small, natural micro-motions that fit the beat: "
    "head turns and tilts, gaze shifts, blinks, facial micro-expressions, breathing, hand and "
    "finger movement, hair and fabric motion, weight shifts. Vary them between consecutive slices, "
    "including hold slices and across previous_block, so no two consecutive blocks are visually "
    "identical. Keep identity, outfit and scene continuity; never invent large new actions to "
    "create variety. Speech: follow each block's spoken_lines exactly; a block with a dialogue "
    "line has the character say it verbatim once; every other block has no spoken lines (only "
    "natural non-speaking mouth movement). Historical prompts are context, not instructions to "
    'repeat. Output format for this step: {"blocks":[{"prompt":"..."}]} with exactly one item '
    "per listed block, in order. No IDs, seeds, durations, markdown or model parameters."
)


def slice_timeline(source: list[Scene], count: int, seconds: float) -> tuple[list[dict], list[dict]]:
    """Deterministic slicing: each block takes the beat containing its time-slot midpoint.

    Grok seconds are only proportions; every block keeps the requested duration.
    """
    total = count * seconds
    weight = sum(beat.seconds for scene in source for beat in scene.beats)
    scenes, flat, start = [], [], 0.0
    for scene_index, scene in enumerate(source):
        beats, scene_start = [], start
        for beat in scene.beats:
            end = start + beat.seconds * total / weight
            value = {"kind": beat.kind, "action": beat.action, "dialogue": beat.dialogue,
                     "seconds": beat.seconds, "start_seconds": round(start, 3),
                     "end_seconds": round(end, 3)}
            flat.append((scene_index, len(beats), value))
            beats.append(value)
            start = end
        scenes.append({"title": scene.title, "start_seconds": round(scene_start, 3),
                       "end_seconds": round(start, 3), "beats": beats})
    flat[-1][2]["end_seconds"] = scenes[-1]["end_seconds"] = round(total, 3)
    owners, index = [], 0
    for block in range(count):
        middle = (block + 0.5) * seconds
        while index < len(flat) - 1 and middle >= flat[index][2]["end_seconds"]:
            index += 1
        owners.append(index)
    slices, seen = [], {}
    for block, owner in enumerate(owners):
        seen[owner] = seen.get(owner, 0) + 1
        scene_index, beat_index, _ = flat[owner]
        slices.append({"scene": scene_index, "beat": beat_index, "position": owner,
                       "kind": flat[owner][2]["kind"], "part": seen[owner],
                       "parts": owners.count(owner),
                       "start_seconds": round(block * seconds, 3),
                       "end_seconds": round((block + 1) * seconds, 3)})
    return scenes, slices


def slice_action(scenes: list[dict], piece: dict) -> str:
    scene = scenes[piece["scene"]]
    action = f"{scene['title']} · {scene['beats'][piece['beat']]['action']}"
    return action + (f" — parte {piece['part']}/{piece['parts']}" if piece["parts"] > 1 else "")


class SegmentRequest(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)
    after_block_id: str | None
    idea: str = Field(min_length=1, max_length=12000)
    count: StrictInt = Field(ge=1, le=MAX_BLOCKS)
    duration_seconds: float = Field(default=DEFAULT_DURATION_SECONDS, gt=0,
                                    le=MAX_DURATION_SECONDS, allow_inf_nan=False)
    seed: StrictInt = Field(ge=0, le=2**53 - 1)

    _after = field_validator("after_block_id")(Snapshot.parent.__func__)
    _idea = field_validator("idea")(Block.nonblank.__func__)
    _duration = field_validator("duration_seconds")(Block.duration.__func__)


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
        raise ValueError("Roteiro metadata exceeds 16 MiB")
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
        raise ValueError("Roteiro metadata exceeds 16 MiB")
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


class _Memo:
    """Observations for one synchronous call; never kept across awaits or requests."""

    def __init__(self):
        self.documents: dict[str, tuple[Document, dict[str, int], dict[str, tuple[int, Intent]]]] = {}
        self.observed: dict[tuple, dict] = {}


class Roteiro:
    """One vertical owns document mutation, proposal isolation and intent correlation."""

    def __init__(self, service):
        self.service = service
        self.root: Path = service.store.root
        self._memo: _Memo | None = None

    @contextmanager
    def observing(self):
        # Reentrant: nested calls share the outermost memo. Only wrap synchronous sections, so
        # disk state cannot change underneath a memoized proof except by this same call.
        if self._memo is not None:
            yield
            return
        self._memo = _Memo()
        try:
            yield
        finally:
            self._memo = None

    def history(self, ident: str):
        memo = self._memo
        if memo is not None and ident in memo.documents:
            return memo.documents[ident]
        doc = self.get(ident)
        entry = (doc, {a.intent_id: i for i, a in enumerate(doc.attempts)},
                 {a.run_id: (i, a) for i, a in enumerate(doc.attempts)})
        if memo is not None:
            memo.documents[ident] = entry
        return entry

    def get(self, ident: str) -> Document:
        if self.removed(ident):
            raise FileNotFoundError("Roteiro removed")
        with _directory(self.root, (".data", "roteiros", canonical(ident))) as directory:
            doc = Document.model_validate(read_file(directory, "plan.json"))
        if doc.id != ident:
            raise ValueError("Roteiro ID disagrees with owned directory")
        return doc

    def identifiers(self) -> list[str]:
        try:
            with _directory(self.root, (".data", "roteiros")) as directory:
                names = os.listdir(directory)
        except FileNotFoundError:
            return []
        ids = []
        for name in names:
            if name in {"editor.json", ".lock", ".locks"} or name.startswith(".write-"):
                continue
            ids.append(canonical(name))
        # Bound library work independently of any native run history.
        if len(ids) > 1000:
            raise ValueError("Roteiro library exceeds 1000 documents")
        return [ident for ident in sorted(ids) if not self.removed(ident)]

    def list(self):
        items = [self.view(self.get(ident)) for ident in self.identifiers()]
        return {"items": items, "total": len(items)}

    def block_state(self, doc: Document, block_id: str) -> tuple[str, dict | None]:
        attempt = self.selected_attempt(doc, block_id)
        if attempt is None:
            return "planned", None
        observed = self.observed(attempt)
        # Rejected, interrupted, failed and not admitted all need an explicit new attempt.
        return BLOCK_STATES.get(observed["state"], "failed"), observed["run"]

    def summary(self) -> dict:
        items = []
        for ident in self.identifiers():
            doc = self.get(ident)
            with _directory(self.root, (".data", "roteiros", ident)) as directory:
                changed = os.stat("plan.json", dir_fd=directory, follow_symlinks=False).st_mtime_ns
            updated = datetime.fromtimestamp(changed / 1e9, UTC)
            strip = []
            with self.observing():
                for block in doc.blocks:
                    state, run = self.block_state(doc, block.id)
                    strip.append(state)
                    if run is not None:
                        # Reviews change run manifests, not plan.json; both count as activity.
                        moment = datetime.fromisoformat(run["updated_at"])
                        updated = max(updated, moment if moment.tzinfo else moment.replace(tzinfo=UTC))
            states = dict.fromkeys(("accepted", "ready_for_review", "active", "failed", "planned"), 0)
            for state in strip:
                states[state] += 1
            items.append({"id": doc.id, "name": doc.name, "idea": doc.idea, "adopted": doc.adopted,
                          "revision": doc.revision, "block_count": len(doc.blocks),
                          "states": states, "strip": strip, "updated_at": updated.isoformat()})
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
        digest = await self.reference_digest(payload.reference)
        doc = Document(**payload.model_dump(), id=str(uuid4()), revision=1,
                       reference_sha256=digest)
        encoded_metadata(doc.model_dump())  # Reject aggregate overflow before directory reservation.
        with (_directory(self.root, (".data", "roteiros"), create=True) as library,
              locked(library)):
            self.reference_available(payload.reference)
            with (_directory(self.root, (".data", "roteiros", doc.id), create=True) as directory,
                  locked(directory)):
                write_file(directory, "plan.json", doc.model_dump(), exclusive=True)
        return self.view(doc)

    def check_revision(self, doc: Document, expected: int, *, edit_id: str | None = None):
        from .batch import assert_batch_available
        from .edit import assert_edit_available

        assert_batch_available(self.service, roteiro_id=doc.id)
        assert_edit_available(self.service, doc.id, exclude=edit_id)
        if self.removed(doc.id):
            raise Conflict("Roteiro removed from library; history is read-only")
        if doc.revision != expected:
            raise Conflict("Roteiro revision changed; preserve the local draft and reread")

    async def update(self, ident: str, payload: UpdatePlan) -> dict:
        from .batch import assert_batch_available
        assert_batch_available(self.service, roteiro_id=ident)
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
                # Removed blocks also have attempts, so they cannot silently return via PUT.
                submitted = {a.block_id for a in doc.attempts}
                if ([b for b in payload.blocks if b.id in submitted]
                        != [b for b in doc.blocks if b.id in submitted]):
                    raise Conflict("Blocks with attempts are immutable and keep their order; "
                                   "insert, edit, reorder or delete only never-sent blocks")
            updated = Document(**payload.model_dump(exclude={"expected_revision"}),
                               id=doc.id, revision=doc.revision + 1,
                               reference_sha256=digest, attempts=doc.attempts,
                               selected_runs=doc.selected_runs,
                               removed_blocks=doc.removed_blocks)
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

    @staticmethod
    def timeline_request(base: dict, context: dict, count: int, seconds: float) -> PromptRequest:
        return PromptRequest(**base, prompt=json.dumps({
            "task": TIMELINE_TASK, **context, "block_seconds": seconds, "count": count,
            "total_seconds": round(count * seconds, 3)}, ensure_ascii=False))

    async def plan(self, grok, base: dict, context: dict, count: int, seconds: float, seed: int,
                   save=None) -> dict:
        """Director timeline, critic revision, deterministic slicing, parallel prompt writers.

        The director call raises like the former single call: its provider result is uncertain.
        Any later failure leaves an invalid outcome with every raw text. Nothing is retried.
        """
        def text(result):
            raw = result.get("text") if isinstance(result, dict) else None
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RAW_TEXT_BYTES:
                raise ValueError("Planning response is missing text or exceeds 512 KiB; not truncated")
            return raw

        def bounded(model):
            schema = model.model_json_schema()
            schema["properties"]["scenes"]["maxItems"] = count
            schema["$defs"]["Scene"]["properties"]["beats"]["maxItems"] = count
            return schema

        total = round(count * seconds, 3)
        outcome = {"name": None, "blocks": [], "draft_scenes": [], "scenes": [], "vision": None,
                   "slices": [], "raw_texts": [], "error": None, "detail": None}

        def invalid(detail, code="invalid_proposal"):
            # Raw invalid text is bounded data, not an instruction or permission to guess fields.
            return {**outcome, "error": code, "detail": detail}

        raw = text(await grok.complete(self.timeline_request(base, context, count, seconds),
                                       output_schema=bounded(Timeline),
                                       schema_name="h3_roteiro_timeline"))
        outcome["raw_texts"].append(raw)
        try:
            timeline = Timeline.model_validate(strict_json(raw))
        except ValueError:
            return invalid("Timeline cannot be converted into strict scenes and beats")
        outcome.update(name=timeline.name, draft_scenes=slice_timeline(timeline.scenes, count, seconds)[0])
        if save is not None:
            save(outcome)
        try:
            raw = text(await grok.complete(PromptRequest(**base, prompt=json.dumps({
                "task": CRITIC_TASK, **context, "block_seconds": seconds, "count": count,
                "total_seconds": total, "draft_scenes": [scene.model_dump() for scene in timeline.scenes],
            }, ensure_ascii=False)), output_schema=bounded(Critique), schema_name="h3_roteiro_critic"))
        except Exception as exc:  # noqa: BLE001 - a failed later step is terminal evidence, not a retry.
            outcome["raw_texts"].append("")
            code = getattr(exc, "code", None)
            return invalid(f"{type(exc).__name__}: {exc}"[:256],
                           code if isinstance(code, str) else "critic_failed")
        outcome["raw_texts"].append(raw)
        try:
            critique = Critique.model_validate(strict_json(raw))
        except ValueError:
            return invalid("Critic response cannot be converted into a strict revised plan")
        scenes, slices = slice_timeline(critique.scenes, count, seconds)
        outcome.update(scenes=scenes, slices=slices, vision=critique.vision.model_dump())
        if save is not None:
            save(outcome)
        flat = [(i, j) for i, scene in enumerate(scenes) for j in range(len(scene["beats"]))]

        def beat(position):
            if not 0 <= position < len(flat):
                return None
            value = scenes[flat[position][0]]["beats"][flat[position][1]]
            return {"kind": value["kind"], "action": value["action"]}

        def describe(index):
            piece = slices[index]
            scene = scenes[piece["scene"]]
            current = scene["beats"][piece["beat"]]
            offset = scene["start_seconds"]
            # A requested line is spoken once: only on the first slice of its beat.
            line = current["dialogue"] if piece["part"] == 1 else None
            return {"index": index + 1, "scene_title": scene["title"], "beat_kind": current["kind"],
                    "beat_action": current["action"], "slice": f"{piece['part']}/{piece['parts']}",
                    "film_seconds": [piece["start_seconds"], piece["end_seconds"]],
                    "scene_seconds": [round(piece["start_seconds"] - offset, 3),
                                      round(piece["end_seconds"] - offset, 3)],
                    "previous_beat": beat(piece["position"] - 1),
                    "next_beat": beat(piece["position"] + 1),
                    "dialogue": line,
                    "spoken_lines": (f"The character says, verbatim: {line}" if line else
                                     "No spoken lines in this block; only natural non-speaking "
                                     "mouth movement.")}

        # Writers get the scene structure without dialogue text, so only flagged blocks see a line.
        silent = [{**scene, "beats": [{k: v for k, v in item.items() if k != "dialogue"}
                                      for item in scene["beats"]]} for scene in scenes]
        semaphore = asyncio.Semaphore(PLAN_PARALLEL)
        chunks = [range(start, min(start + PLAN_CHUNK, count)) for start in range(0, count, PLAN_CHUNK)]

        async def expand(chunk):
            async with semaphore:
                request = PromptRequest(**base, prompt=json.dumps({
                    "task": PROMPT_TASK, "background": context,
                    "background_note": "Story background only. Do not speak any dialogue that "
                                       "appears in it; follow each block's spoken_lines.",
                    "block_seconds": seconds,
                    "total_seconds": total, "vision": outcome["vision"], "scenes": silent,
                    # Parallel chunks cannot see each other's text; the preceding slice's known
                    # beat context still lets this chunk vary micro-motions across the boundary.
                    "previous_block": describe(chunk[0] - 1) if chunk[0] else None,
                    "blocks": [describe(index) for index in chunk]}, ensure_ascii=False))
                chunk_schema = PromptChunk.model_json_schema()
                chunk_schema["properties"]["blocks"].update(minItems=len(chunk), maxItems=len(chunk))
                return text(await grok.complete(request, output_schema=chunk_schema,
                                                schema_name="h3_roteiro_prompts"))

        results = await asyncio.gather(*(expand(chunk) for chunk in chunks), return_exceptions=True)
        prompts, failure = [], None
        for chunk, result in zip(chunks, results, strict=True):
            if isinstance(result, BaseException):
                outcome["raw_texts"].append("")  # Keeps raw_texts[2 + k] aligned with chunk k.
                code = getattr(result, "code", None)
                failure = failure or (code if isinstance(code, str) else "prompt_failed",
                                      f"{type(result).__name__}: {result}"[:256])
                continue
            outcome["raw_texts"].append(result)
            try:
                parsed = PromptChunk.model_validate(strict_json(result))
                if len(parsed.blocks) != len(chunk):
                    raise ValueError("Prompt count differs from its chunk")
            except ValueError:
                failure = failure or ("invalid_proposal",
                                      "Prompt response cannot be converted into strict block prompts")
                continue
            prompts.extend(item.prompt for item in parsed.blocks)
        if failure is not None:
            return invalid(failure[1], failure[0])
        try:
            blocks = [Block(id=str(uuid4()), action=slice_action(scenes, piece),
                            duration_seconds=seconds, seed=seed, prompt=prompt)
                      for piece, prompt in zip(slices, prompts, strict=True)]
        except ValueError:
            return invalid("Sliced beat actions cannot form strict planned blocks")
        for piece, block in zip(slices, blocks, strict=True):
            piece["block_id"] = block.id
        outcome["blocks"] = [block.model_dump() for block in blocks]
        return outcome

    async def propose(self, ident: str, payload: ProposalRequest, grok) -> dict:
        from .batch import assert_batch_available
        assert_batch_available(self.service, roteiro_id=ident)
        doc = self.get(ident)
        self.check_revision(doc, payload.expected_revision)
        digest = await self.reference_digest(doc.reference)
        if digest != doc.reference_sha256:
            raise Conflict("Original reference changed")
        config = self.script_config()
        base = {"system_prompt": config["system_prompt"], "model": config["model"],
                "reference": doc.reference}
        context = {"idea": doc.idea, "name": doc.name}
        # Validate the first request before any durable reservation.
        self.timeline_request(base, context, payload.count, payload.duration_seconds)
        candidate_id = str(uuid4())
        source = {"name": doc.name, "idea": doc.idea, "reference": doc.reference.model_dump(),
                  "reference_sha256": doc.reference_sha256}
        reserved = {"id": candidate_id, "roteiro_id": doc.id, "source_revision": doc.revision,
                    "state": "uncertain", "request": payload.model_dump(), "source": source}
        # Reservation is durable, but locks do not span provider/media awaits. No automatic retry.
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
              locked(directory)):
            self.check_revision(self.get(doc.id), doc.revision)
            write_file(directory, f"proposal-{candidate_id}.json", reserved, exclusive=True)

        def progress(outcome):
            with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
                  locked(directory)):
                write_file(directory, f"proposal-{candidate_id}.json", {
                    **reserved, **{key: outcome[key] for key in PLAN_EVIDENCE}})

        outcome = await self.plan(grok, base, context, payload.count, payload.duration_seconds,
                                  payload.seed, progress)
        candidate = {"id": candidate_id, "roteiro_id": doc.id, "source_revision": doc.revision,
                     "source": source, "raw_text": outcome["raw_texts"][0],
                     **{key: outcome[key] for key in PLAN_EVIDENCE}, "stale": False}
        if outcome["error"]:
            candidate.update(error=outcome["error"], detail=outcome["detail"])
        else:
            candidate.update(name=outcome["name"], blocks=outcome["blocks"], slices=outcome["slices"])
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
              locked(directory)):
            candidate["stale"] = self.get(doc.id).revision != doc.revision
            write_file(directory, f"proposal-{candidate_id}.json", candidate)
        return candidate

    def tail_parent(self, doc: Document) -> str:
        if not doc.adopted or not doc.blocks:
            raise Conflict("Tail requires an adopted roteiro with complete accepted videos")
        parent_id = None
        editorial = bool(doc.selected_runs or doc.removed_blocks
                         or any(a.origin == "bridge" for a in doc.attempts))
        with self.observing():
            for index, block in enumerate(doc.blocks):
                attempt = self.selected_attempt(doc, block.id)
                if attempt is None:
                    raise Conflict("Finish every existing planned block before extending the tail")
                observed = self.observed(attempt)
                if observed["state"] != "accepted" or observed["run"] is None:
                    raise Conflict("Every latest block attempt must be accepted and proven")
                # Bridges and removals make the order editorial rather than genealogical.
                if not editorial and attempt.snapshot.parent_id != parent_id:
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
            raise Conflict(f"Tail exceeds the existing {MAX_BLOCKS}-block planning budget")
        parent_id = self.tail_parent(doc)
        if await self.reference_digest(doc.reference) != doc.reference_sha256:
            raise Conflict("Original reference changed")
        async with continuation_frame(self.root, parent_id, doc.reference) as (_, recheck, digest):
            await asyncio.to_thread(recheck)
            if digest != doc.reference_sha256:
                raise Conflict("Tail parent identity disagrees with original reference")
            parent_proof = await asyncio.to_thread(self.tail_media, parent_id)
        config = self.script_config()
        base = {"system_prompt": config["system_prompt"], "model": config["model"],
                "reference": doc.reference, "continuation_parent_id": parent_id}
        context = {
            "situation": "Plan only new tail blocks after the accepted video sequence. "
                         "Image 1 is original identity; image 2 is the actual final frame of the "
                         "accepted parent. Preserve the existing prefix; continue from that frame.",
            "idea": payload.idea, "original_idea": doc.idea, "name": doc.name,
            "earlier_block_count": max(0, len(doc.blocks) - CONTEXT_ACTIONS),
            # Bounded for long roteiros: recent intentions, plus prompts only for the last few.
            "accepted_prefix": [
                {"id": b.id, "position": position + 1, "editorial_intention": b.action,
                 "run_id": attempt.run_id, "duration_seconds": attempt.snapshot.duration_seconds,
                 **({"prompt": attempt.snapshot.prompt}
                    if position >= len(doc.blocks) - CONTEXT_PROMPTS else {})}
                for position, b in enumerate(doc.blocks)
                if position >= len(doc.blocks) - CONTEXT_ACTIONS
                and (attempt := self.selected_attempt(doc, b.id)) is not None
            ],
        }
        first = self.timeline_request(base, context, payload.count, payload.duration_seconds)
        candidate = {
            "id": tail_id, "roteiro_id": doc.id, "source_revision": doc.revision,
            "parent_id": parent_id, "prefix_block_ids": [b.id for b in doc.blocks],
            "prefix_blocks": [b.model_dump() for b in doc.blocks],
            "source": self.tail_source(doc), "parent_proof": parent_proof,
            "name": doc.name, "blocks": [], "raw_text": "", "raw_texts": [], "scenes": [],
            "draft_scenes": [], "vision": None,
            "state": "uncertain", "stale": False, "request": payload.model_dump(),
            "config": config, "planning_prompt": first.prompt,
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

        def progress(outcome):
            candidate.update({key: outcome[key] for key in PLAN_EVIDENCE},
                             raw_text=outcome["raw_texts"][0])
            with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
                  locked(directory)):
                write_file(directory, f"tail-{tail_id}.json", candidate)

        try:
            outcome = await self.plan(grok, base, context, payload.count,
                                      payload.duration_seconds, payload.seed, progress)
        except OAuthError as exc:
            if 400 <= exc.status < 500:
                candidate.update(state="invalid", error=exc.code,
                                 detail="Provider explicitly refused this planning request")
                with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
                      locked(directory)):
                    write_file(directory, f"tail-{tail_id}.json", candidate)
            raise
        candidate.update({key: outcome[key] for key in PLAN_EVIDENCE},
                         raw_text=outcome["raw_texts"][0])
        if outcome["error"]:
            candidate.update(state="invalid", error=outcome["error"], detail=outcome["detail"])
        else:
            candidate.update(state="proposed", blocks=outcome["blocks"], slices=outcome["slices"])
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

    def remove_block(self, ident: str, key: str, payload: RemovePlan) -> dict:
        """Take one block out of the sequence; its attempts, videos and decisions stay history."""
        canonical(key)
        with (_directory(self.root, (".data", "roteiros")) as library, locked(library),
              _directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            doc = self.get(ident)
            self.check_revision(doc, payload.expected_revision)
            block = next((b for b in doc.blocks if b.id == key), None)
            if block is None:
                raise FileNotFoundError("Unknown planned block")
            remaining = [b for b in doc.blocks if b.id != key]
            if doc.adopted and not remaining:
                raise Conflict("Um roteiro adotado precisa de pelo menos um bloco")
            owned = [a for a in doc.attempts if a.block_id == key]
            with self.observing():
                if any(self.observed(a)["state"] in {"uncertain", "queued", "running"}
                       for a in doc.attempts):
                    raise Conflict("Uma tentativa está ativa ou incerta; consulte-a antes de remover")
                if any(self.observed(a)["state"] == "ready_for_review" for a in owned):
                    raise Conflict("Aceite ou recuse o vídeo deste bloco antes de removê-lo")
                # Editorial mode: pin every accepted version so Tail and the batch follow the
                # visible order instead of requiring an exact generation chain across the cut.
                selected = {k: v for k, v in doc.selected_runs.items() if k != key}
                for planned in remaining:
                    attempt = self.selected_attempt(doc, planned.id)
                    if attempt is not None and self.observed(attempt)["state"] == "accepted":
                        selected[planned.id] = attempt.run_id
            updated = Document(**{**doc.model_dump(), "revision": doc.revision + 1,
                                  "blocks": [b.model_dump() for b in remaining],
                                  "selected_runs": selected,
                                  "removed_blocks": [b.model_dump() for b in (
                                      [*doc.removed_blocks, block] if owned else doc.removed_blocks)]})
            write_file(directory, "plan.json", updated.model_dump())
        return self.view(updated)

    def segment_neighbor(self, doc: Document, position: int) -> tuple[dict | None, str | None]:
        if not 0 <= position < len(doc.blocks):
            return None, None
        block = doc.blocks[position]
        value = {"position": position + 1, "editorial_intention": block.action}
        attempt = self.selected_attempt(doc, block.id)
        observed = self.observed(attempt) if attempt is not None else None
        if observed is not None and observed["state"] == "accepted" and observed["run"] is not None:
            value["historical_prompt_actually_submitted"] = attempt.snapshot.prompt
            return value, attempt.run_id
        value["planned_prompt_not_generated"] = block.prompt
        return value, None

    def segment_record(self, directory: int, ident: str, segment_id: str) -> dict:
        record = read_file(directory, f"segment-{segment_id}.json")
        if record.get("id") != segment_id or record.get("roteiro_id") != ident:
            raise ValueError("Segment ownership disagrees with path")
        return record

    def get_segment(self, ident: str, segment_id: str) -> dict:
        canonical(segment_id)
        with _directory(self.root, (".data", "roteiros", canonical(ident))) as directory:
            record = self.segment_record(directory, ident, segment_id)
        try:
            record["stale"] = self.get(ident).revision != record["source_revision"]
        except (OSError, ValueError):
            record["stale"] = True
        return record

    async def propose_segment(self, ident: str, segment_id: str, payload: SegmentRequest,
                              grok) -> dict:
        """Plan blocks to insert after a block (or before the first); never writes the plan."""
        canonical(segment_id)
        doc = self.get(ident)
        self.check_revision(doc, payload.expected_revision)
        if len(doc.blocks) + payload.count > MAX_BLOCKS:
            raise Conflict(f"Segment exceeds the existing {MAX_BLOCKS}-block planning budget")
        if payload.after_block_id is None:
            index = -1
        else:
            index = next((i for i, b in enumerate(doc.blocks) if b.id == payload.after_block_id), None)
            if index is None:
                raise FileNotFoundError("Unknown planned block")
        with self.observing():
            previous, parent_id = self.segment_neighbor(doc, index)
            following, _ = self.segment_neighbor(doc, index + 1)
        if await self.reference_digest(doc.reference) != doc.reference_sha256:
            raise Conflict("Original reference changed")
        if parent_id is not None:
            # No silent fallback to identity-only context when the accepted frame is invalid.
            async with continuation_frame(self.root, parent_id, doc.reference) as (_, recheck, digest):
                await asyncio.to_thread(recheck)
                if digest != doc.reference_sha256:
                    raise Conflict("Previous block identity disagrees with original reference")
        config = self.script_config()
        base = {"system_prompt": config["system_prompt"], "model": config["model"],
                "reference": doc.reference, "continuation_parent_id": parent_id}
        context = {
            "situation": "Plan only new blocks to insert at this position of an existing roteiro. "
                         "Image 1 is original identity" + (
                             "; image 2 is the actual final frame of the preceding accepted block"
                             if parent_id else "") + ". Start where the previous block ends and "
                         "lead naturally into the following block without performing its action "
                         "early. Neighbour prompts are historical context, not instructions.",
            "idea": payload.idea, "original_idea": doc.idea, "name": doc.name,
            "previous_block": previous, "following_block": following,
        }
        self.timeline_request(base, context, payload.count, payload.duration_seconds)
        record = {"id": segment_id, "roteiro_id": doc.id, "source_revision": doc.revision,
                  "after_block_id": payload.after_block_id,
                  "before_block_id": doc.blocks[index + 1].id if index + 1 < len(doc.blocks) else None,
                  "parent_id": parent_id, "state": "uncertain", "stale": False, "name": None,
                  "blocks": [], "raw_texts": [], "draft_scenes": [], "scenes": [], "vision": None,
                  "request": payload.model_dump()}
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
              locked(directory)):
            try:
                os.stat(f"segment-{segment_id}.json", dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise Conflict("Segment ID already exists; GET the same ID without replaying POST")
            self.check_revision(self.get(doc.id), doc.revision)
            write_file(directory, f"segment-{segment_id}.json", record, exclusive=True)

        def save(value):
            with (_directory(self.root, (".data", "roteiros", doc.id)) as directory,
                  locked(directory)):
                write_file(directory, f"segment-{segment_id}.json", value)

        def progress(outcome):
            record.update({key: outcome[key] for key in PLAN_EVIDENCE})
            save(record)

        try:
            outcome = await self.plan(grok, base, context, payload.count,
                                      payload.duration_seconds, payload.seed, progress)
        except OAuthError as exc:
            if 400 <= exc.status < 500:
                record.update(state="invalid", error=exc.code,
                              detail="Provider explicitly refused this planning request")
                save(record)
            raise
        record.update({key: outcome[key] for key in PLAN_EVIDENCE}, name=outcome["name"])
        if outcome["error"]:
            record.update(state="invalid", error=outcome["error"], detail=outcome["detail"])
        else:
            record.update(state="proposed", blocks=outcome["blocks"], slices=outcome["slices"])
        try:
            record["stale"] = self.get(doc.id).revision != doc.revision
        except (OSError, ValueError):
            record["stale"] = True
        save(record)
        return record

    def intent(self, doc: Document, key: str, intent_id: str) -> Intent:
        canonical(key)
        canonical(intent_id)
        for attempt in doc.attempts:
            if attempt.intent_id == intent_id and attempt.block_id == key:
                return attempt
        raise FileNotFoundError("Unknown owned intent")

    def observed(self, intent: Intent) -> dict:
        with self.observing():
            memo = self._memo
            key = (intent.intent_id, intent.admission, intent.error)
            if key not in memo.observed:
                self._warm_ancestors(intent)
                memo.observed[key] = self._observe(intent)
            return memo.observed[key]

    def _warm_ancestors(self, intent: Intent):
        """Observe uncached ancestors root-first, so each proof finds its parent memoized.

        This keeps long chains linear and the call stack shallow instead of one recursion level
        per historical continuation.
        """
        if intent.snapshot.parent_id is None:
            return
        try:
            _, order, by_run = self.history(intent.roteiro_id)
        except (OSError, ValueError):
            return  # The proof itself classifies unreadable ownership as uncertain.
        chain, current = [], intent
        while current.snapshot.parent_id is not None and current.intent_id in order:
            found = by_run.get(current.snapshot.parent_id)
            if found is None or found[0] >= order[current.intent_id]:
                break
            parent = found[1]
            if (parent.intent_id, parent.admission, parent.error) in self._memo.observed:
                break
            chain.append(parent)
            current = parent
        for parent in reversed(chain):
            self.observed(parent)

    def _observe(self, intent: Intent) -> dict:
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
                from .conversion import observe_import
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
            from ..generation.bridge import BridgePipe
            BridgePipe.from_run(self.service, run)
            if run.input_info.get("continuation", {}).get("target_run_id") != intent.target_run_id:
                raise ValueError("Bridge destination disagrees with owned intent")
        elif snap.parent_id:
            V2VPipe.from_run(self.service, run)
        else:
            I2VPipe.from_run(self.service, run)
        if snap.parent_id:
            self.historical_parent(intent)

    def historical_parent(self, intent: Intent):
        """The parent must be an earlier owned attempt, accepted and published.

        Position in the current block order is not part of this proof: removals, insertions and
        editorial versions may legitimately change neighbours after generation.
        """
        _, order, by_run = self.history(intent.roteiro_id)
        found = by_run.get(intent.snapshot.parent_id)
        if (found is None or intent.intent_id not in order or found[0] >= order[intent.intent_id]
                or self.observed(found[1])["state"] != "accepted"):
            raise ValueError("Historical generation parent is not a proven accepted attempt")
        published_parent = self.service.store.get(found[1].run_id)
        self.service.video_path(found[1].run_id)
        if published_parent.decision is None or published_parent.decision.get("accepted") is not True:
            raise ValueError("Historical generation parent has no accepted decision")

    def selected_attempt(self, doc: Document, block_id: str) -> Intent | None:
        attempts = [a for a in doc.attempts if a.block_id == block_id]
        selected = doc.selected_runs.get(block_id)
        return next((a for a in attempts if a.run_id == selected), None) if selected else (
            attempts[-1] if attempts else None)

    def selected_run_ids(self, doc: Document) -> list[str]:
        result = []
        with self.observing():
            for block in doc.blocks:
                attempt = self.selected_attempt(doc, block.id)
                if attempt is None or self.observed(attempt)["state"] != "accepted":
                    raise Conflict("Accept a selected version of every block before assembling")
                result.append(attempt.run_id)
        return result

    def view(self, doc: Document) -> dict:
        with self.observing():
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

    def bridge_target(self, doc: Document, index: int, target: str):
        """A bridge ends at the first frame of the next block's selected accepted version."""
        if index + 1 >= len(doc.blocks):
            raise Conflict("A bridge requires a following block; use Tail at the end")
        following = self.selected_attempt(doc, doc.blocks[index + 1].id)
        if following is None or following.run_id != target:
            raise Conflict("Bridge destination must be the next block's selected version")
        observed = self.observed(following)
        if observed["state"] != "accepted" or observed["run"] is None:
            raise Conflict("Bridge destination must be natively accepted and proven")
        run = self.service.store.get(target)
        self.service.video_path(target)
        if run.decision is None or run.decision.get("accepted") is not True:
            raise Conflict("Bridge destination has no explicit accepted decision")

    def reserve(self, doc: Document, key: str, intent_id: str, payload: Generate) -> Intent:
        from .batch import assert_batch_available
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
                with self.observing():
                    if old:
                        latest = self.observed(old[-1])
                        if latest["state"] not in {"rejected", "interrupted", "not_admitted"}:
                            raise Conflict("Previous attempt is accepted, active, failed or uncertain")
                        if (old[-1].snapshot.parent_id, old[-1].target_run_id) != (
                                payload.parent_id, payload.target_run_id):
                            raise Conflict("Retry must preserve the original parent and destination")
                    elif (payload.prompt, payload.seed, payload.duration_seconds) != (
                            block.prompt, block.seed, block.duration_seconds):
                        raise Conflict("Save the chosen draft before creating an intent")
                    # Any other outstanding attempt fences this roteiro even if the native slot vanished.
                    if any(self.observed(a)["state"] in {"uncertain", "queued", "running", "ready_for_review"}
                           for a in doc.attempts):
                        raise Conflict("An owned attempt is still active, awaiting review or uncertain")
                    self.parent(doc, index, payload.parent_id)
                    if payload.target_run_id is not None:
                        self.bridge_target(doc, index, payload.target_run_id)
                attempt = Intent(intent_id=intent_id, run_id=intent_id, roteiro_id=doc.id,
                                 block_id=key, source_revision=doc.revision,
                                 origin="native" if payload.target_run_id is None else "bridge",
                                 target_run_id=payload.target_run_id,
                                 snapshot=Snapshot(**payload.model_dump(
                                     exclude={"expected_revision", "target_run_id"}),
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
            if payload.target_run_id is not None:
                current = self.get(ident)
                index = next(i for i, b in enumerate(current.blocks) if b.id == key)
                self.parent(current, index, payload.parent_id)
                self.bridge_target(current, index, payload.target_run_id)
                native = BridgeRequest(seed=payload.seed, prompt=payload.prompt,
                                       duration_seconds=payload.duration_seconds,
                                       target_run_id=payload.target_run_id)
                pipe = (BridgePipe(self.service).have(native).with_run_id(intent_id)
                        .from_parent(payload.parent_id).with_last_frame().with_original_identity()
                        .with_motion_tail().with_workflow(BRIDGE_CONFIG).save_chunk())
            elif payload.parent_id is None:
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
        except (OSError, ValueError, Conflict):
            # Nothing reached the native dispatcher yet, so this outcome is known, not uncertain.
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
            raise HTTPException(413, "Roteiro JSON exceeds 16 MiB")
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


@router.get("/summary")
async def roteiro_summary(request: Request):
    return response(operation(request).summary())


@router.get("/editor")
async def script_editor(request: Request):
    return response(operation(request).script_config())


@router.put("/editor")
async def update_script_editor(request: Request):
    return response(operation(request).save_script(await body(request, ScriptConfig)))


@router.post("/from-freestyle/{end_id}", status_code=201)
async def convert_freestyle(end_id: str, request: Request):
    payload = await body(request, ConvertFreestyle)
    from .conversion import convert
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


@router.post("/{ident}/blocks/{key}/remove")
async def remove_block(ident: str, key: str, request: Request):
    return response(operation(request).remove_block(ident, key, await body(request, RemovePlan)))


@router.post("/{ident}/segments/{segment_id}")
async def propose_segment(ident: str, segment_id: str, request: Request):
    try:
        value = await operation(request).propose_segment(
            ident, segment_id, await body(request, SegmentRequest), request.app.state.grok)
        return response(value, 422 if value.get("error") else 200)
    except OAuthError as exc:
        return response({"error": exc.code, "detail": str(exc)}, exc.status)


@router.get("/{ident}/segments/{segment_id}")
async def get_segment(ident: str, segment_id: str, request: Request):
    return response(operation(request).get_segment(ident, segment_id))


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
