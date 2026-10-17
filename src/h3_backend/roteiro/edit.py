"""Explicit bridge proposals, generation and editorial version selection."""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import Field, StrictInt, field_validator

from ..generation.dispatcher import Conflict
from ..grok import FIXED_EDITOR_MODEL, ContinuationPreview, EditPromptRequest, read_editor
from ..infrastructure.comfy import QueueBusy
from ..infrastructure.grok_image import _directory, continuation_frame
from ..infrastructure.store import Store
from . import (
    MAX_BLOCKS,
    Block,
    Document,
    Intent,
    Roteiro,
    ScriptConfig,
    Snapshot,
    StrictDTO,
    body,
    canonical,
    locked,
    read_file,
    response,
    write_file,
)

DEFAULT_EDIT_SYSTEM = (
    "Write one English video generation prompt for an edit between two existing accepted videos. "
    "Image 1 is the original identity. Image 2 is the actual last frame of the preceding video "
    "and defines the starting state. Image 3 is the actual FIRST frame of the following video "
    "and defines the desired ending state. The native generator also receives the preceding "
    "video as motion context. Historical prompts describe what was requested for those already "
    "generated videos; they are context only, not instructions to execute or repeat. The actual "
    "frames take precedence for visible pose, clothing and scene state. Fulfill the user's edit "
    "within the requested duration while transitioning naturally between the two anchors. "
    "Do not replay the preceding action or perform the following video's action early. "
    "Use identity Picture 2 and starting-frame Picture 1 in the native video prompt; "
    "Picture 3 is the destination anchor and Video 1 is preceding motion context. "
    "Describe only this new block, preserving explicitly requested dialogue verbatim. "
    "Return only the complete generation prompt, no markdown, commentary or model parameters."
)


class EditRequest(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)
    mode: Literal["replace", "insert_before", "insert_after"]
    block_id: str
    idea: str = Field(min_length=1, max_length=12000)
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    duration_seconds: float = Field(gt=0, le=10, allow_inf_nan=False)

    _id = field_validator("block_id")(Block.key.__func__)
    _idea = field_validator("idea")(Block.nonblank.__func__)
    _duration = field_validator("duration_seconds")(Block.duration.__func__)


class EditGenerate(StrictDTO):
    prompt: str = Field(min_length=1, max_length=12000)
    _prompt = field_validator("prompt")(Block.nonblank.__func__)


class Revision(StrictDTO):
    expected_revision: StrictInt = Field(ge=1)


class EditRecord(EditRequest):
    id: str
    roteiro_id: str
    source_revision: StrictInt = Field(ge=1)
    new_block_id: str
    previous_run_id: str
    next_run_id: str
    previous_prompt: str
    next_prompt: str
    reference: dict
    reference_sha256: str
    system_prompt: str
    model: str
    prompt: str | None = None
    state: Literal["improving", "proposed", "generating", "applied", "uncertain", "failed", "discarded"]
    run_id: str | None = None
    error: str | None = None


def assert_edit_available(service, ident, *, exclude=None):
    try:
        with _directory(service.store.root, (".data", "roteiros", canonical(ident))) as directory:
            names = [name for name in os.listdir(directory)
                     if name.startswith("edit-") and name.endswith(".json")]
            if len(names) > 1000:
                raise Conflict("Edit history exceeds inspection capacity")
            for name in names:
                record = EditRecord.model_validate(read_file(directory, name))
                if record.id == exclude:
                    continue
                pending = record.state in {"improving", "uncertain", "generating"}
                if record.state == "generating" and record.run_id:
                    try:
                        pending = service.store.get(record.run_id).state not in {"rejected", "interrupted", "failed"}
                    except FileNotFoundError:
                        pass
                if pending:
                    raise Conflict("Consulte a edição anterior: há uma resposta incerta ou um vídeo aguardando revisão/aplicação.")
    except FileNotFoundError:
        return


class RoteiroEdit:
    def __init__(self, service):
        self.service = service
        self.root = service.store.root
        self.roteiro = Roteiro(service)

    def config(self):
        model = read_editor(self.root).model
        if model != FIXED_EDITOR_MODEL:
            raise Conflict("Edit mode requires the fixed Grok model")
        try:
            with _directory(self.root, (".data", "roteiro-edits")) as directory:
                config = ScriptConfig.model_validate(read_file(directory, "editor.json"))
        except FileNotFoundError:
            config = ScriptConfig(system_prompt=DEFAULT_EDIT_SYSTEM)
        return {**config.model_dump(), "model": model}

    def save_config(self, config):
        self.config()
        with (_directory(self.root, (".data", "roteiro-edits"), create=True) as directory,
              locked(directory)):
            write_file(directory, "editor.json", config.model_dump())
        return self.config()

    def read(self, ident, edit_id):
        with _directory(self.root, (".data", "roteiros", canonical(ident))) as directory:
            record = EditRecord.model_validate(read_file(directory, f"edit-{canonical(edit_id)}.json"))
        if record.id != edit_id or record.roteiro_id != ident:
            raise ValueError("Edit ownership does not match its path")
        for value in (record.new_block_id, record.previous_run_id, record.next_run_id):
            canonical(value)
        if record.run_id is not None:
            canonical(record.run_id)
            if record.run_id != record.id:
                raise ValueError("Edit native run does not match its reserved ID")
        return record.model_dump()

    def save(self, record, *, exclusive=False):
        value = EditRecord.model_validate(record).model_dump()
        with (_directory(self.root, (".data", "roteiros", value["roteiro_id"])) as directory,
              locked(directory)):
            write_file(directory, f"edit-{value['id']}.json", value, exclusive=exclusive)

    def view(self, ident, edit_id):
        record = self.read(ident, edit_id)
        run = None
        if record["run_id"]:
            try:
                run = self.service.store.get(record["run_id"]).model_dump()
            except FileNotFoundError:
                pass
        return {**record, "run": run}

    def list(self, ident):
        self.roteiro.get(ident)
        with _directory(self.root, (".data", "roteiros", canonical(ident))) as directory:
            names = sorted(name for name in os.listdir(directory)
                           if name.startswith("edit-") and name.endswith(".json"))
        if len(names) > 1000:
            raise ValueError("Edit history exceeds 1000 records")
        return {"items": [self.view(ident, name[5:-5]) for name in names]}

    def anchors(self, doc, payload, *, edit_id=None):
        self.roteiro.check_revision(doc, payload.expected_revision, edit_id=edit_id)
        if not doc.adopted:
            raise Conflict("Use an adopted roteiro before editing")
        index = next((i for i, b in enumerate(doc.blocks) if b.id == payload.block_id), None)
        if index is None:
            raise FileNotFoundError("Unknown edit block")
        left = index if payload.mode == "insert_after" else index - 1
        right = index if payload.mode == "insert_before" else index + 1
        if left < 0:
            raise Conflict("A edição exige um vídeo anterior aceito; a abertura não possui essa âncora.")
        if right >= len(doc.blocks):
            raise Conflict("A edição exige um vídeo seguinte aceito. Use Tail para acrescentar ao fim.")
        if payload.mode != "replace" and len(doc.blocks) >= MAX_BLOCKS:
            raise Conflict(f"Roteiro already contains {MAX_BLOCKS} blocks")
        with self.roteiro.observing():
            if any(self.roteiro.observed(a)["state"] in {"uncertain", "queued", "running", "ready_for_review"}
                   for a in doc.attempts):
                raise Conflict("Resolva as tentativas pendentes de revisão ou resultado incerto antes de editar.")
        selected = []
        for position in (left, right):
            attempt = self.roteiro.selected_attempt(doc, doc.blocks[position].id)
            if attempt is None:
                raise Conflict("As duas âncoras precisam de vídeos aceitos.")
            observed = self.roteiro.observed(attempt)
            if observed["state"] != "accepted" or observed["run"] is None:
                raise Conflict("As versões selecionadas das duas âncoras precisam estar aceitas.")
            if not observed["run"].get("decision", {}).get("accepted"):
                raise Conflict("A decisão de aceitação da âncora não está confirmada.")
            self.service.video_path(attempt.run_id)
            selected.append(attempt)
        if payload.mode == "replace":
            attempt = self.roteiro.selected_attempt(doc, payload.block_id)
            if attempt is None or self.roteiro.observed(attempt)["state"] != "accepted":
                raise Conflict("Aceite uma versão do bloco antes de refazê-lo neste modo.")
        return selected

    def current(self, record):
        doc = self.roteiro.get(record["roteiro_id"])
        payload = EditRequest.model_validate({key: record[key] for key in EditRequest.model_fields})
        previous, following = self.anchors(doc, payload, edit_id=record["id"])
        if ((previous.run_id, following.run_id, previous.snapshot.prompt, following.snapshot.prompt)
                != (record["previous_run_id"], record["next_run_id"], record["previous_prompt"], record["next_prompt"])
                or doc.reference.model_dump() != record["reference"]
                or doc.reference_sha256 != record["reference_sha256"]):
            raise Conflict("As âncoras mudaram. Preserve esta proposta e releia o roteiro.")
        return doc

    async def propose(self, ident, edit_id, payload, grok):
        canonical(edit_id)
        doc = self.roteiro.get(ident)
        previous, following = self.anchors(doc, payload)
        if await self.roteiro.reference_digest(doc.reference) != doc.reference_sha256:
            raise Conflict("Original identity changed")
        config = self.config()
        record = EditRecord(**payload.model_dump(), id=edit_id, roteiro_id=doc.id,
                            source_revision=doc.revision,
                            new_block_id=payload.block_id if payload.mode == "replace" else str(uuid4()),
                            previous_run_id=previous.run_id, next_run_id=following.run_id,
                            previous_prompt=previous.snapshot.prompt, next_prompt=following.snapshot.prompt,
                            reference=doc.reference.model_dump(), reference_sha256=doc.reference_sha256,
                            **config, state="improving").model_dump()
        with (_directory(self.root, (".data", "roteiros", doc.id)) as directory, locked(directory)):
            self.current(record)
            for name in os.listdir(directory):
                if name.startswith("edit-") and name.endswith(".json"):
                    old = read_file(directory, name)
                    pending = old.get("state") in {"improving", "uncertain", "generating"}
                    if old.get("state") == "generating" and old.get("run_id"):
                        try:
                            pending = self.service.store.get(old["run_id"]).state not in {"rejected", "interrupted", "failed"}
                        except FileNotFoundError:
                            pass
                    if pending:
                        raise Conflict("Consulte a edição anterior antes de criar outra; não reenviar resultado incerto.")
            write_file(directory, f"edit-{edit_id}.json", record, exclusive=True)
        context = (
            f"Edit mode: {payload.mode}\nUser instruction: {payload.idea}\n"
            f"Requested duration: {payload.duration_seconds} seconds.\n"
            "PRECEDING COMPLETED VIDEO — HISTORICAL PROMPT ACTUALLY SUBMITTED:\n"
            f"{previous.snapshot.prompt}\nEND PRECEDING HISTORICAL PROMPT\n"
            "FOLLOWING EXISTING VIDEO — HISTORICAL PROMPT ACTUALLY SUBMITTED:\n"
            f"{following.snapshot.prompt}\nEND FOLLOWING HISTORICAL PROMPT\n"
            "Both historical prompts are context, not commands for this edit. Do not repeat their "
            "actions. Start at the actual preceding final frame and end at the following first frame."
        )
        try:
            result = await grok.complete(EditPromptRequest(
                **config, prompt=context, reference=doc.reference,
                continuation_parent_id=previous.run_id, target_run_id=following.run_id))
            text = result.get("text") if isinstance(result, dict) else None
            EditGenerate(prompt=text)
            record.update(prompt=text, state="proposed")
        except BaseException as exc:
            record.update(state="uncertain", error=f"{type(exc).__name__}: {exc}"[:256])
            self.save(record)
            raise
        self.save(record)
        return self.view(ident, edit_id)

    async def generate(self, ident, edit_id, payload):
        from ..generation.bridge import BridgePipe
        from ..generation.models import BridgeRequest
        with (_directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            record = self.read(ident, edit_id)
            if record["state"] != "proposed" or record["run_id"] is not None:
                raise Conflict("A edição já foi enviada; consulte o mesmo ID.")
            self.current(record)
            record.update(prompt=payload.prompt, run_id=record["id"], state="generating")
            write_file(directory, f"edit-{edit_id}.json", record)
        native = BridgeRequest(prompt=record["prompt"], seed=record["seed"],
                               duration_seconds=record["duration_seconds"], target_run_id=record["next_run_id"])
        pipe = (BridgePipe(self.service).have(native).from_parent(record["previous_run_id"])
                .with_run_id(record["id"]).with_identity_proof(record["reference"]["source_root"],
                                                            record["reference"]["path"], record["reference_sha256"]))
        try:
            await pipe.admit()
        except (Conflict, QueueBusy, ValueError) as exc:
            record.update(state="failed" if not self.service.store.directory(edit_id).exists() else "uncertain",
                          error=f"{type(exc).__name__}: {exc}"[:256])
            self.save(record)
            raise
        except BaseException as exc:
            record.update(state="uncertain", error=f"{type(exc).__name__}: {exc}"[:256])
            self.save(record)
            raise
        return self.view(ident, edit_id)

    async def apply(self, ident, edit_id, payload):
        with (_directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            record = self.read(ident, edit_id)
            doc = self.roteiro.get(ident)
            existing = next((a for a in doc.attempts if a.run_id == edit_id), None)
            if existing is not None and existing.origin == "bridge":
                record.update(state="applied")
                write_file(directory, f"edit-{edit_id}.json", record)
                return self.roteiro.view(doc)
            self.roteiro.check_revision(doc, payload.expected_revision, edit_id=edit_id)
            self.current(record)
            if record["state"] not in {"generating", "uncertain"} or record["run_id"] != edit_id:
                raise Conflict("Generate and review this edit before applying it")
            run = self.service.store.get(edit_id)
            if run.state != "accepted" or not (run.decision or {}).get("accepted"):
                raise Conflict("Aceite o vídeo editado antes de usá-lo no roteiro.")
            from ..generation.bridge import BridgePipe
            admitted = self.service.store.request(edit_id)
            pipe = BridgePipe.from_run(self.service, admitted)
            pipe.verify_anchors(admitted)
            if Store.input_projection(admitted) != Store.input_projection(run):
                raise ValueError("Edited video differs from its original native admission")
            self.service.video_path(edit_id)
            if run.input_info.get("continuation", {}).get("target_run_id") != record["next_run_id"]:
                raise ValueError("Edited video destination differs from its frozen proposal")
            if (run.parent_id, run.prompt, run.seed, run.duration_seconds) != (
                    record["previous_run_id"], record["prompt"], record["seed"], record["duration_seconds"]):
                raise ValueError("Edited video differs from its frozen proposal")
            attempt = Intent(intent_id=edit_id, run_id=edit_id, roteiro_id=ident,
                             block_id=record["new_block_id"], source_revision=doc.revision + 1,
                             origin="bridge", target_run_id=record["next_run_id"], admission="admitted",
                             snapshot=Snapshot(prompt=run.prompt, seed=run.seed,
                                               duration_seconds=run.duration_seconds, parent_id=run.parent_id,
                                               reference=doc.reference, reference_sha256=doc.reference_sha256))
            block = Block(id=record["new_block_id"], action=record["idea"], prompt=run.prompt,
                          seed=run.seed, duration_seconds=run.duration_seconds)
            blocks = list(doc.blocks)
            index = next(i for i, b in enumerate(blocks) if b.id == record["block_id"])
            if record["mode"] == "replace":
                blocks[index] = block
            else:
                blocks.insert(index + (record["mode"] == "insert_after"), block)
            selected = {b.id: a.run_id for b in doc.blocks
                        if (a := self.roteiro.selected_attempt(doc, b.id)) is not None}
            selected[block.id] = edit_id
            updated = Document(**{**doc.model_dump(), "revision": doc.revision + 1,
                                  "blocks": [b.model_dump() for b in blocks],
                                  "attempts": [a.model_dump() for a in [*doc.attempts, attempt]],
                                  "selected_runs": selected})
            with _directory(self.root, (".data", "roteiros", ".locks"), create=True) as markers:
                try:
                    write_file(markers, f"{edit_id}.json", attempt.model_dump(), exclusive=True)
                except (FileExistsError, Conflict):
                    if read_file(markers, f"{edit_id}.json") != attempt.model_dump():
                        raise Conflict("Edit intent marker belongs to another snapshot") from None
            write_file(directory, "plan.json", updated.model_dump())
            record.update(state="applied")
            write_file(directory, f"edit-{edit_id}.json", record)
        return self.roteiro.view(updated)

    def discard(self, ident, edit_id):
        with (_directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            record = self.read(ident, edit_id)
            if record["state"] not in {"proposed", "failed", "discarded", "generating"}:
                raise Conflict("Só é possível descartar uma edição com resultado conhecido.")
            if record["run_id"] and record["state"] != "failed":
                run = self.service.store.get(record["run_id"])
                if run.state not in {"accepted", "rejected", "interrupted", "failed"}:
                    raise Conflict("Revise o vídeo antes de descartar a edição.")
            record.update(state="discarded")
            write_file(directory, f"edit-{edit_id}.json", record)
        return self.view(ident, edit_id)

    def retry(self, ident, edit_id, new_id, payload):
        canonical(new_id)
        with (_directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            original = self.read(ident, edit_id)
            if original["state"] not in {"generating", "failed", "discarded"} or not original["run_id"]:
                raise Conflict("Only a known terminal video attempt can be prepared again")
            try:
                run = self.service.store.get(original["run_id"])
            except FileNotFoundError:
                if original["state"] != "failed":
                    raise Conflict("Native admission remains uncertain; inspect the same ID") from None
            else:
                if run.state not in {"failed", "interrupted", "rejected"}:
                    raise Conflict("Only failed, interrupted or rejected videos permit another attempt")
                from ..generation.bridge import BridgePipe
                from ..generation.models import BridgeRequest
                admitted = self.service.store.request(run.id)
                BridgePipe.from_run(self.service, admitted)
                expected = BridgeRequest(prompt=original["prompt"], seed=original["seed"],
                                         duration_seconds=original["duration_seconds"],
                                         target_run_id=original["next_run_id"])
                identities = [(r.get("source_root"), r.get("source"), r.get("sha256"))
                              for r in admitted.references if r.get("role") == "identity"]
                if (Store.input_projection(admitted) != Store.input_projection(run)
                        or admitted.parent_id != original["previous_run_id"]
                        or admitted.input_info["continuation"] != expected.model_dump()
                        or identities != [(original["reference"]["source_root"],
                                           original["reference"]["path"], original["reference_sha256"])]):
                    raise ValueError("Retry metadata disagrees with the original submitted instruction")
            record = {**original, "id": new_id, "run_id": None, "state": "proposed", "error": None,
                      "expected_revision": payload.expected_revision, "source_revision": payload.expected_revision}
            self.current(record)
            if record["mode"] != "replace":
                record["new_block_id"] = str(uuid4())
            write_file(directory, f"edit-{new_id}.json", record, exclusive=True)
        return self.view(ident, new_id)

    def recover(self):
        try:
            with _directory(self.root, (".data", "roteiros")) as directory:
                names = [name for name in os.listdir(directory) if not name.startswith(".") and len(name) == 36]
        except FileNotFoundError:
            return
        for ident in names:
            with (_directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
                  locked(directory)):
                for name in os.listdir(directory):
                    if name.startswith("edit-") and name.endswith(".json"):
                        record = EditRecord.model_validate(read_file(directory, name)).model_dump()
                        if record["state"] == "improving":
                            record.update(state="uncertain", error="Backend restarted; Grok result is unknown. No replay.")
                            write_file(directory, name, record)

    def select(self, ident, block_id, run_id, payload):
        with (_directory(self.root, (".data", "roteiros", canonical(ident))) as directory,
              locked(directory)):
            doc = self.roteiro.get(ident)
            self.roteiro.check_revision(doc, payload.expected_revision)
            attempt = next((a for a in doc.attempts if a.block_id == canonical(block_id)
                            and a.run_id == canonical(run_id)), None)
            with self.roteiro.observing():
                if attempt is None or self.roteiro.observed(attempt)["state"] != "accepted":
                    raise Conflict("Only an accepted owned block version can be selected")
                if any(self.roteiro.observed(a)["state"] in {"uncertain", "queued", "running", "ready_for_review"}
                       for a in doc.attempts):
                    raise Conflict("Resolve outstanding attempts before selecting versions")
            updated = doc.model_copy(update={"revision": doc.revision + 1,
                                            "selected_runs": {**doc.selected_runs, block_id: run_id},
                                            "blocks": [b.model_copy(update={
                                                "prompt": attempt.snapshot.prompt,
                                                "seed": attempt.snapshot.seed,
                                                "duration_seconds": attempt.snapshot.duration_seconds,
                                            }) if b.id == block_id else b for b in doc.blocks]})
            write_file(directory, "plan.json", updated.model_dump())
        return self.roteiro.view(updated)


router = APIRouter(tags=["roteiro-edits"])


def operation(request):
    return RoteiroEdit(request.app.state.service)


@router.get("/roteiro-edits/editor")
async def config(request: Request):
    return response(operation(request).config())


@router.put("/roteiro-edits/editor")
async def save_config(request: Request):
    return response(operation(request).save_config(await body(request, ScriptConfig)))


@router.get("/roteiro-edits/anchors/{run_id}/{edge}")
async def anchor(run_id: str, edge: Literal["first", "last"], request: Request):
    root = request.app.state.service.store.root
    canonical(run_id)
    stack = AsyncExitStack()
    try:
        frame, _, _ = await stack.enter_async_context(continuation_frame(root, run_id, edge=edge))
        return ContinuationPreview(frame, stack)
    except BaseException:
        await stack.aclose()
        raise


@router.get("/roteiros/{ident}/edits")
async def collection(ident: str, request: Request):
    return response(operation(request).list(ident))


@router.post("/roteiros/{ident}/edits/{edit_id}")
async def propose(ident: str, edit_id: str, request: Request):
    return response(await operation(request).propose(ident, edit_id, await body(request, EditRequest),
                                                    request.app.state.grok))


@router.get("/roteiros/{ident}/edits/{edit_id}")
async def get_edit(ident: str, edit_id: str, request: Request):
    return response(operation(request).view(ident, edit_id))


@router.post("/roteiros/{ident}/edits/{edit_id}/generate")
async def generate(ident: str, edit_id: str, request: Request):
    return response(await operation(request).generate(ident, edit_id, await body(request, EditGenerate)))


@router.post("/roteiros/{ident}/edits/{edit_id}/apply")
async def apply(ident: str, edit_id: str, request: Request):
    return response(await operation(request).apply(ident, edit_id, await body(request, Revision)))


class EmptyRequest(StrictDTO):
    pass


@router.post("/roteiros/{ident}/edits/{edit_id}/discard")
async def discard(ident: str, edit_id: str, request: Request):
    await body(request, EmptyRequest)
    return response(operation(request).discard(ident, edit_id))


@router.post("/roteiros/{ident}/edits/{edit_id}/retry/{new_id}")
async def retry(ident: str, edit_id: str, new_id: str, request: Request):
    return response(operation(request).retry(ident, edit_id, new_id, await body(request, Revision)))


@router.post("/roteiros/{ident}/blocks/{block_id}/versions/{run_id}")
async def select(ident: str, block_id: str, run_id: str, request: Request):
    return response(operation(request).select(ident, block_id, run_id, await body(request, Revision)))


@router.post("/roteiros/{ident}/assemblies/{assembly_id}")
async def assemble(ident: str, assembly_id: str, request: Request):
    from ..generation.assembly import AssemblyPipe
    payload = await body(request, Revision)
    op = operation(request)
    doc = op.roteiro.get(ident)
    op.roteiro.check_revision(doc, payload.expected_revision)
    pipe = AssemblyPipe(op.service).have(assembly_id).from_roteiro(ident, doc.revision).save_video()
    task = asyncio.create_task(pipe.arun(), name=f"h3-editorial-assembly-{assembly_id}")
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return response(await asyncio.shield(task))
