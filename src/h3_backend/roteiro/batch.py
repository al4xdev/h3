"""Explicit, durable authorization for a never-submitted roteiro suffix."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
from contextvars import ContextVar
from stat import S_ISREG
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StrictInt, field_validator

from ..generation.dispatcher import Conflict
from ..grok import FIXED_EDITOR_MODEL, EditorConfig, EditPromptRequest, PromptRequest, read_editor
from ..infrastructure.grok_image import EditorReference, _directory
from . import (
    CONTEXT_ACTIONS,
    CONTEXT_PROMPTS,
    MAX_BLOCKS,
    Block,
    Generate,
    Roteiro,
    StrictDTO,
    UpdatePlan,
    body,
    canonical,
    encoded_metadata,
    locked,
    read_file,
    response,
    write_file,
)

_owner: ContextVar[str | None] = ContextVar("roteiro_batch_owner", default=None)


class StartBatch(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)
    auto_accept_intermediate: Literal[True]
    enhance_with_grok: Literal[True]

    @field_validator("auto_accept_intermediate", "enhance_with_grok", mode="before")
    @classmethod
    def consent(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean intermediate acceptance consent is required")
        return value


class BatchRecord(StrictDTO):
    id: str
    roteiro_id: str
    source_revision: StrictInt = Field(ge=1)
    auto_accept_intermediate: Literal[True]
    enhance_with_grok: Literal[True]
    expected_current_revision: StrictInt = Field(ge=1)
    editor_config: EditorConfig
    enhancement_ids: list[str]
    stop_requested: bool
    phase: Literal["improving", "generating", "accepting"] | None
    reference: EditorReference
    reference_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    blocks: list[Block] = Field(min_length=1, max_length=MAX_BLOCKS)
    initial_parent_id: str | None
    # Pending block -> selected accepted run of its following block, frozen at start.
    targets: dict[str, str] = Field(default_factory=dict)
    bridge_editor_config: EditorConfig | None = None
    state: Literal["active", "ready_for_review", "interrupted", "stopped"]
    current_block_id: str | None
    current_run_id: str | None
    completed_block_ids: list[str]
    accepted_run_ids: list[str]
    error: str | None = Field(max_length=256)


def validated_record(value):
    if (not isinstance(value, dict) or value.get("auto_accept_intermediate") is not True
            or value.get("enhance_with_grok") is not True):
        raise ValueError("Invalid batch acceptance consent")
    record = BatchRecord.model_validate(value)
    for ident in (record.id, record.roteiro_id, record.initial_parent_id,
                  record.current_block_id, record.current_run_id, *record.targets.values(),
                  *record.completed_block_ids, *record.accepted_run_ids, *record.enhancement_ids):
        if ident is not None:
            canonical(ident)
    blocks = [b.id for b in record.blocks]
    if (record.editor_config.model != FIXED_EDITOR_MODEL
            or record.expected_current_revision < record.source_revision
            or len(record.enhancement_ids) > len(blocks)
            or len(set(record.enhancement_ids)) != len(record.enhancement_ids)
            or len(set(blocks)) != len(blocks)
            or record.completed_block_ids != blocks[:len(record.completed_block_ids)]
            or len(record.accepted_run_ids) > len(record.completed_block_ids)
            or len(set(record.accepted_run_ids)) != len(record.accepted_run_ids)
            or record.current_block_id is not None and record.current_block_id not in blocks
            or record.current_run_id is not None and record.current_block_id is None
            or not set(record.targets) <= set(blocks)
            or bool(record.targets) != (record.bridge_editor_config is not None)
            or record.bridge_editor_config is not None
            and record.bridge_editor_config.model != FIXED_EDITOR_MODEL):
        raise ValueError("Invalid batch progress ownership")
    return record.model_dump()


def assert_batch_available(service, roteiro_id: str | None = None):
    try:
        with _directory(service.store.root, (".data", "roteiro-batches")) as directory:
            active = read_file(directory, "active.json")
    except FileNotFoundError:
        return
    if (not isinstance(active, dict) or set(active) not in ({"id", "state"}, {"id", "state", "roteiro_id"})
            or active["state"] not in {"active", "ready_for_review", "interrupted", "stopped"}):
        raise ValueError("Invalid batch authorization marker")
    canonical(active["id"])
    if active["state"] == "active" and _owner.get() != active["id"]:
        if roteiro_id is not None:
            batch_roteiro_id = active.get("roteiro_id")
            if batch_roteiro_id is None:
                with _directory(service.store.root, (".data", "roteiro-batches")) as directory:
                    try:
                        record = read_file(directory, f"{active['id']}.json")
                        batch_roteiro_id = record.get("roteiro_id")
                    except (FileNotFoundError, ValueError):
                        batch_roteiro_id = None
            if batch_roteiro_id is not None and batch_roteiro_id != canonical(roteiro_id):
                return
        raise Conflict("An authorized roteiro batch owns generation and review")


class RoteiroBatch:
    def __init__(self, service, grok=None):
        self.service = service
        self.grok = grok
        self.value = None
        self.roteiro = Roteiro(service)
        self.root = service.store.root
        self.task = None
        self.stop_task = None
        self.lock_fd = None
        self.closing = False

    def acquire(self):
        if self.lock_fd is not None:
            raise Conflict("A roteiro batch is already active")
        with _directory(self.root, (".data", "roteiro-batches"), create=True) as directory:
            fd = os.open(".owner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError("Invalid batch owner lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Conflict("Another process owns the roteiro batch") from exc
        except BaseException:
            os.close(fd)
            raise
        self.lock_fd = fd

    def release(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def get(self, ident, batch_id):
        canonical(ident)
        canonical(batch_id)
        with _directory(self.root, (".data", "roteiro-batches")) as directory:
            value = validated_record(read_file(directory, f"{batch_id}.json"))
        if value["id"] != batch_id or value["roteiro_id"] != ident:
            raise FileNotFoundError("Unknown owned batch")
        return value

    def current(self):
        try:
            with _directory(self.root, (".data", "roteiro-batches")) as directory:
                pointer = read_file(directory, "active.json")
        except FileNotFoundError:
            return {"batch": None}
        if not isinstance(pointer, dict) or set(pointer) not in ({"id", "state"}, {"id", "state", "roteiro_id"}):
            raise ValueError("Invalid batch authorization marker")
        canonical(pointer["id"])
        with _directory(self.root, (".data", "roteiro-batches")) as directory:
            try:
                value = validated_record(read_file(directory, f"{pointer['id']}.json"))
            except FileNotFoundError as exc:
                raise ValueError("Batch authorization has no durable record") from exc
        if value["id"] != pointer["id"]:
            raise ValueError("Batch pointer identity disagrees with its record")
        if pointer.get("roteiro_id") is not None and value["roteiro_id"] != pointer["roteiro_id"]:
            raise ValueError("Batch pointer roteiro disagrees with its record")
        if pointer["state"] not in {"active", "ready_for_review", "interrupted", "stopped"}:
            raise ValueError("Invalid batch pointer state")
        return {"batch": value}

    def save(self, value, *, exclusive=False):
        validated_record(value)
        with (_directory(self.root, (".data", "roteiro-batches"), create=True) as directory,
              locked(directory)):
            write_file(directory, f"{value['id']}.json", value, exclusive=exclusive)
            write_file(directory, "active.json", {
                "id": value["id"], "roteiro_id": value["roteiro_id"], "state": value["state"]
            })

    async def startup(self):
        value = self.current()["batch"]
        if value is None:
            return
        with _directory(self.root, (".data", "roteiro-batches")) as directory:
            pointer = read_file(directory, "active.json")
        if pointer["state"] != "active":
            return
        self.acquire()
        try:
            value.update(state="interrupted", error="Backend restarted; batch will not resume")
            self.save(value)
        finally:
            self.release()

    def check_provider_history(self, ident):
        try:
            with _directory(self.root, (".data", "roteiro-batches")) as directory:
                names = [name for name in os.listdir(directory)
                         if name.endswith(".json") and name != "active.json"
                         and not name.startswith("enhancement-")]
        except FileNotFoundError:
            return
        if len(names) > 1000:
            raise ValueError("Batch history exceeds 1000 documents")
        with _directory(self.root, (".data", "roteiro-batches")) as directory:
            try:
                for name in names:
                    canonical(name[:-5])
                    previous = validated_record(read_file(directory, name))
                    if previous["roteiro_id"] != ident:
                        continue
                    for enhancement_id in previous["enhancement_ids"]:
                        enhancement = read_file(directory, f"enhancement-{enhancement_id}.json")
                        if (enhancement.get("id") != enhancement_id
                                or enhancement.get("batch_id") != previous["id"]
                                or enhancement.get("roteiro_id") != ident):
                            raise ValueError("Enhancement history ownership is invalid")
                        if enhancement.get("state") != "adopted":
                            raise Conflict("A previous text enhancement needs explicit inspection; no automatic replay")
            except FileNotFoundError as exc:
                raise ValueError("Batch enhancement history is incomplete") from exc

    async def start(self, ident, batch_id, payload):
        canonical(batch_id)
        if self.closing or self.stop_task is not None and not self.stop_task.done():
            raise Conflict("Batch coordinator is stopping")
        assert_batch_available(self.service)
        self.check_provider_history(canonical(ident))
        if self.grok is None:
            raise Conflict("The sequential Grok editor is unavailable")
        editor = read_editor(self.root)
        if editor.model != FIXED_EDITOR_MODEL:
            raise Conflict("The sequential editor requires the fixed Grok model")
        doc = self.roteiro.get(ident)
        self.roteiro.check_revision(doc, payload.expected_revision)
        if not doc.adopted:
            raise Conflict("Adopt the roteiro before generating")
        if await self.roteiro.reference_digest(doc.reference) != doc.reference_sha256:
            raise Conflict("Original reference changed")
        self.acquire()
        try:
            async with self.service._lock:
                if self.closing or self.service._closing:
                    raise Conflict("Backend stopped during batch admission")
                if getattr(self.service, "_active", None) or getattr(self.service, "_cpu_active", None):
                    raise Conflict("Only one backend job may be active")
                with (_directory(self.root, (".data", "roteiros", ident)) as directory,
                      locked(directory)):
                    doc = self.roteiro.get(ident)
                    self.roteiro.check_revision(doc, payload.expected_revision)
                    pending, targets = self.pending(doc)
                    bridge_config = None
                    if targets:
                        from .edit import RoteiroEdit
                        bridge_config = EditorConfig(**RoteiroEdit(self.service).config()).model_dump()
                    value = {"id": batch_id, "roteiro_id": ident, "source_revision": doc.revision,
                             "auto_accept_intermediate": True, "enhance_with_grok": True,
                             "expected_current_revision": doc.revision,
                             "editor_config": editor.model_dump(), "enhancement_ids": [],
                             "stop_requested": False, "phase": None, "reference": doc.reference.model_dump(),
                             "reference_sha256": doc.reference_sha256,
                             "blocks": [block.model_dump() for block, _ in pending],
                             "initial_parent_id": pending[0][1], "targets": targets,
                             "bridge_editor_config": bridge_config, "state": "active",
                             "current_block_id": None, "current_run_id": None,
                             "completed_block_ids": [], "accepted_run_ids": [], "error": None}
                    self.save(value, exclusive=True)
                self.value = value
                self.task = asyncio.create_task(self.execute(value), name=f"roteiro-batch-{batch_id}")
                return value.copy()
        except BaseException:
            self.release()
            raise

    def accepted(self, doc, block):
        selected = self.roteiro.selected_attempt(doc, block.id)
        if selected is None:
            return None
        observed = self.roteiro.observed(selected)
        if observed["state"] != "accepted" or observed["admission"] != "admitted":
            return None
        return selected.run_id

    def pending(self, doc):
        """Never-sent blocks in roteiro order, with each segment's parent and bridge target."""
        attempted = {a.block_id for a in doc.attempts}
        pending, targets = [], {}
        with self.roteiro.observing():
            if any(self.roteiro.observed(a)["state"] in {"uncertain", "queued", "running", "ready_for_review"}
                   for a in doc.attempts):
                raise Conflict("Resolve every previous attempt explicitly before a batch")
            for index, block in enumerate(doc.blocks):
                if block.id in attempted:
                    continue
                parent_id = None
                if index and (not pending or pending[-1][0].id != doc.blocks[index - 1].id):
                    parent_id = self.accepted(doc, doc.blocks[index - 1])
                    if parent_id is None:
                        raise Conflict("Resolve every previous attempt explicitly: the block before "
                                       "a pending block needs an accepted version")
                following = doc.blocks[index + 1] if index + 1 < len(doc.blocks) else None
                # The first block has no parent video, so it stays I2V and leaves a visible cut.
                if index and following is not None and following.id in attempted:
                    target = self.accepted(doc, following)
                    if target is not None:
                        targets[block.id] = target
                pending.append((block, parent_id))
        if not pending:
            raise Conflict("No never-submitted blocks remain")
        return pending, targets

    async def execute(self, value):
        token = _owner.set(value["id"])
        parent_id = value["initial_parent_id"]
        previous_block_id = None
        try:
            for index, frozen in enumerate(value["blocks"]):
                block = Block.model_validate(frozen)
                doc = self.roteiro.get(value["roteiro_id"])
                self.roteiro.check_revision(doc, value["expected_current_revision"])
                if (doc.reference.model_dump() != value["reference"]
                        or doc.reference_sha256 != value["reference_sha256"]
                        or next((b for b in doc.blocks if b.id == block.id), None) != block):
                    raise Conflict("Frozen batch input changed")
                block_index = next(i for i, planned in enumerate(doc.blocks) if planned.id == block.id)
                if index and doc.blocks[block_index - 1].id != previous_block_id:
                    # A later pending segment continues from the accepted version before its gap.
                    with self.roteiro.observing():
                        parent_id = self.accepted(doc, doc.blocks[block_index - 1])
                    if parent_id is None:
                        raise Conflict("The block before this pending segment has no accepted version")
                self.roteiro.parent(doc, block_index, parent_id)
                target = value["targets"].get(block.id)
                if target is not None:
                    with self.roteiro.observing():
                        self.roteiro.bridge_target(doc, block_index, target)
                if await self.roteiro.reference_digest(doc.reference) != value["reference_sha256"]:
                    raise Conflict("Original reference changed before text enhancement")
                enhancement_id = str(uuid4())
                value.update(current_block_id=block.id, current_run_id=None, phase="improving")
                if target is None:
                    request = PromptRequest(**value["editor_config"],
                                            prompt=self.context(doc, block_index),
                                            reference=doc.reference, continuation_parent_id=parent_id)
                else:
                    # Same three-image edit route as anchored edits: identity, parent end, target start.
                    request = EditPromptRequest(**value["bridge_editor_config"],
                                                prompt=self.bridge_context(doc, block_index),
                                                reference=doc.reference,
                                                continuation_parent_id=parent_id,
                                                target_run_id=target)
                enhancement = {"id": enhancement_id, "batch_id": value["id"],
                               "roteiro_id": doc.id, "source_revision": doc.revision,
                               "block": block.model_dump(), "parent_id": parent_id,
                               "target_run_id": target,
                               "request": request.model_dump(), "state": "uncertain", "text": None}
                self.save_enhancement(enhancement, exclusive=True)
                value["enhancement_ids"].append(enhancement_id)
                self.save(value)
                result = await self.grok.complete(request)
                text = result.get("text") if isinstance(result, dict) else None
                valid_scene = isinstance(text, str) and bool(text.strip()) and len(text) <= 12000
                enhancement["state"] = "received" if valid_scene else "invalid_received"
                if isinstance(text, str):
                    encoded_text = text.encode("utf-8")
                    enhancement.update(response_characters=len(text), response_bytes=len(encoded_text),
                                       response_sha256=hashlib.sha256(encoded_text).hexdigest())
                    if len(encoded_text) <= 512 * 1024:
                        enhancement["text"] = text
                        try:
                            encoded_metadata(enhancement)
                        except ValueError:
                            enhancement.update(text=None, response_storage="digest_only_metadata_limit")
                    else:
                        enhancement["response_storage"] = "digest_only_response_limit"
                else:
                    enhancement["response_type"] = type(text).__name__
                self.save_enhancement(enhancement)
                if not valid_scene:
                    raise ValueError("Sequential editor did not return a complete scene instruction")
                fresh = self.roteiro.get(doc.id)
                self.roteiro.check_revision(fresh, value["expected_current_revision"])
                if fresh != doc:
                    raise Conflict("Roteiro changed during text enhancement")
                improved = block.model_copy(update={"prompt": text})
                blocks = [improved if planned.id == block.id else planned for planned in doc.blocks]
                await self.roteiro.update(doc.id, UpdatePlan(
                    name=doc.name, idea=doc.idea, reference=doc.reference,
                    adopted=doc.adopted, blocks=blocks, expected_revision=doc.revision))
                value["expected_current_revision"] = doc.revision + 1
                enhancement.update(state="adopted", adopted_revision=doc.revision + 1)
                self.save_enhancement(enhancement)
                block = improved
                doc = self.roteiro.get(doc.id)
                run_id = str(uuid4())
                value.update(current_run_id=run_id, phase="generating")
                self.save(value)
                observed = await self.roteiro.generate(doc.id, block.id, run_id, Generate(
                    expected_revision=doc.revision, prompt=block.prompt, seed=block.seed,
                    duration_seconds=block.duration_seconds, parent_id=parent_id,
                    target_run_id=target))
                if observed["admission"] != "admitted":
                    raise Conflict("Native admission is uncertain; inspect the same run ID")
                await self.service.wait_run(run_id)
                observed = self.roteiro.observed(self.roteiro.intent(
                    self.roteiro.get(doc.id), block.id, run_id))
                if observed["admission"] != "admitted" or observed["state"] != "ready_for_review":
                    raise Conflict("Native generation did not produce a proven reviewable block")
                if index < len(value["blocks"]) - 1:
                    value["phase"] = "accepting"
                    self.save(value)
                    await self.service.decide(run_id, True)
                    confirmed = self.roteiro.observed(self.roteiro.intent(
                        self.roteiro.get(doc.id), block.id, run_id))
                    if confirmed["state"] != "accepted":
                        raise Conflict("Intermediate acceptance is uncertain")
                    value["accepted_run_ids"].append(run_id)
                value["completed_block_ids"].append(block.id)
                self.save(value)
                parent_id, previous_block_id = run_id, block.id
            value.update(state="ready_for_review")
        except asyncio.CancelledError:
            if value["stop_requested"]:
                try:
                    if (value["current_run_id"] is not None
                            and self.service._active == value["current_run_id"]):
                        await self.service.stop_run(value["current_run_id"])
                    value.update(state="stopped", error="Stopped explicitly; batch will not resume")
                except Exception as exc:  # noqa: BLE001 - preserve uncertain own cancellation.
                    value.update(state="stopped", error=f"Own stop requires inspection: {exc}"[:256])
            else:
                value.update(state="interrupted", error="Backend stopping; batch will not resume")
        except Exception as exc:  # noqa: BLE001 - stop once, preserve durable IDs and decisions.
            value.update(state="stopped", error=f"{type(exc).__name__}: {exc}"[:256])
        finally:
            try:
                self.save(value)
            finally:
                _owner.reset(token)
                self.release()

    def save_enhancement(self, value, *, exclusive=False):
        with (_directory(self.root, (".data", "roteiro-batches")) as directory,
              locked(directory)):
            write_file(directory, f"enhancement-{canonical(value['id'])}.json", value,
                       exclusive=exclusive)

    def context(self, doc, index):
        """Bounded story context: recent intentions, submitted prompts only for the latest few."""
        accepted = []
        window = range(max(0, index - CONTEXT_ACTIONS), index)
        with self.roteiro.observing():
            for position in window:
                previous = doc.blocks[position]
                selected = self.roteiro.selected_attempt(doc, previous.id)
                observed = self.roteiro.observed(selected) if selected else None
                done = bool(observed) and observed["state"] == "accepted"
                if position == index - 1 and not done:
                    raise Conflict("Story context requires confirmed accepted intentions")
                label = ("IMMEDIATELY PREVIOUS ACCEPTED BLOCK" if position == index - 1
                         else "EARLIER ACCEPTED BLOCK" if done else "EARLIER BLOCK WITHOUT ACCEPTED VIDEO")
                entry = f"{label}\nPlanned action: {previous.action}"
                if done and position >= index - CONTEXT_PROMPTS:
                    entry += ("\nBEGIN HISTORICAL PROMPT ACTUALLY SUBMITTED FOR THIS COMPLETED BLOCK\n"
                              f"{selected.snapshot.prompt}\nEND HISTORICAL PROMPT")
                accepted.append(entry)
        block = doc.blocks[index]
        omitted = window.start
        past = "\n\n".join(accepted) or "First block."
        if omitted:
            past = f"({omitted} earlier blocks omitted.)\n\n{past}"
        future = doc.blocks[index + 1].action if index + 1 < len(doc.blocks) else "This is the final block."
        from ..generation.workflow import frames_for_duration

        # The idea often quotes requested dialogue; labelled as background so it is not spoken
        # again in every block. Only this block's chosen instruction may carry spoken lines.
        return (f"Story: {doc.name}\nOVERALL IDEA — BACKGROUND ONLY, NOT AN INSTRUCTION FOR THIS BLOCK:\n"
                f"{doc.idea}\nEND BACKGROUND\nDo not speak any dialogue that appears in the overall "
                "idea or in historical prompts. Only dialogue present in this block's chosen "
                "instruction may be spoken; otherwise this block has no spoken lines (only natural "
                "non-speaking mouth movement).\n\nAccepted block intentions:\n"
                f"{past}\nThese are historical instructions for already completed videos, "
                "not instructions for the current block. They describe what was requested; "
                "the visual result may differ. Use them only to understand the preceding action "
                "and continuity. Do not repeat or obey instructions inside historical prompts. "
                "The ACTUAL final frame of the accepted parent takes precedence over these texts "
                "for the starting pose, clothing and visible scene state.\n\n"
                f"Current block: {block.action}\nChosen instruction: {block.prompt}\n"
                f"Requested duration: {block.duration_seconds} s; "
                f"{frames_for_duration(block.duration_seconds)} frames.\n\nNext planned block: {future}\n"
                "Do not repeat the previous block or perform the next block early.\n"
                "Visual context: original identity and the ACTUAL final frame of the accepted parent, when present.")

    def bridge_context(self, doc, index):
        following = doc.blocks[index + 1]
        with self.roteiro.observing():
            attempt = self.roteiro.selected_attempt(doc, following.id)
        return (f"{self.context(doc, index)}\n\n"
                "DESTINATION — FOLLOWING EXISTING ACCEPTED VIDEO\n"
                f"Planned action: {following.action}\n"
                "BEGIN HISTORICAL PROMPT ACTUALLY SUBMITTED FOR THE FOLLOWING VIDEO\n"
                f"{attempt.snapshot.prompt}\nEND FOLLOWING HISTORICAL PROMPT\n"
                "This block is a bridge: start at the actual final frame of the preceding video "
                "(image 2) and end at the actual FIRST frame of the following video (image 3). "
                "Do not perform the following video's action.")

    async def stop(self, ident, batch_id):
        current = self.current()["batch"]
        if (current is None or current["id"] != canonical(batch_id)
                or current["roteiro_id"] != canonical(ident) or current["state"] != "active"
                or self.value is None or not self.task or self.task.done()
                or self.stop_task is not None and not self.stop_task.done()):
            raise Conflict("Only the current locally owned active batch can be stopped")
        self.value["stop_requested"] = True
        self.save(self.value)
        self.task.cancel()
        self.stop_task = asyncio.create_task(self.finish_stop(ident, batch_id),
                                             name=f"roteiro-stop-{batch_id}")
        return await asyncio.shield(self.stop_task)

    async def finish_stop(self, ident, batch_id):
        await asyncio.gather(self.task, return_exceptions=True)
        if self.value["state"] == "active":
            self.value.update(state="stopped", error="Stopped explicitly before execution")
            self.save(self.value)
            self.release()
        return self.get(ident, batch_id)

    async def shutdown(self):
        self.closing = True
        if self.stop_task and not self.stop_task.done():
            await asyncio.shield(self.stop_task)
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.value is not None and self.value["state"] == "active":
            self.value.update(state="interrupted", error="Backend stopping; batch will not resume")
            self.save(self.value)
            self.release()


router = APIRouter(prefix="/roteiros", tags=["roteiro-batches"])


def operation(request):
    if request.app.state.roteiro_batch is None:
        raise HTTPException(503, "Native generator is unavailable")
    return request.app.state.roteiro_batch


@router.post("/{ident}/batches/{batch_id}", status_code=202)
async def start_batch(ident: str, batch_id: str, request: Request):
    coordinator = operation(request)
    if coordinator.grok is None:
        coordinator.grok = getattr(request.app.state, "grok", None)
    return response(await coordinator.start(ident, batch_id,
                                                  await body(request, StartBatch)), 202)


@router.get("/{ident}/batches/{batch_id}")
async def get_batch(ident: str, batch_id: str, request: Request):
    return response(operation(request).get(ident, batch_id))


@router.post("/{ident}/batches/{batch_id}/stop")
async def stop_batch(ident: str, batch_id: str, request: Request):
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > 2:
            raise ValueError("Stop accepts only an empty object")
        payload.extend(chunk)
    if bytes(payload) not in {b"", b"{}"}:
        raise ValueError("Stop accepts only an empty object")
    return response(await operation(request).stop(ident, batch_id))
