"""Explicit adoption of one existing native branch, without submitting inference."""

import hashlib
import os
from stat import S_ISREG
from uuid import uuid4

from .generation.dispatcher import Conflict
from .generation.i2v import I2VPipe
from .generation.models import Run
from .generation.v2v import V2VPipe
from .infrastructure.grok_image import EditorReference, _directory, _thread
from .infrastructure.store import Store
from .roteiro import (
    MAX_BLOCKS,
    Block,
    Document,
    ImportedSource,
    Intent,
    MediaProof,
    Snapshot,
    canonical,
    encoded_metadata,
    locked,
    read_file,
    write_file,
)


def validate_native(op, run):
    canonical(run.id)
    with _directory(op.root, tuple(op.service.store.directory(run.id).relative_to(op.root).parts)) as fd:
        owned = Run.model_validate(read_file(fd, "manifest.json"))
    if owned != run:
        raise ValueError("Source manifest changed during conversion")
    admitted = op.service.store.request(run.id)
    (V2VPipe if run.parent_id else I2VPipe).from_run(op.service, admitted)
    if run.parent_id:
        options = run.input_info["continuation"]
        if options["reference_tail_seconds"] != 3 or options["include_audio"] is not True:
            raise ValueError("Continuation options cannot be preserved by this roteiro")
    identities = [ref for ref in run.references if ref.get("role") == "identity"]
    if len(identities) != 1:
        raise ValueError("Conversion requires exactly one original identity")
    identity = identities[0]
    reference = EditorReference(source_root=identity["source_root"], path=identity["source"])
    if run.state not in {"accepted", "ready_for_review", "rejected", "interrupted"}:
        raise Conflict("Source branch is active, failed or uncertain")
    if (run.state in {"accepted", "rejected"}
            and (run.decision is None
                 or run.decision.get("accepted") is not (run.state == "accepted"))):
        raise ValueError("Source decision does not prove terminal review")
    if run.state in {"accepted", "ready_for_review", "rejected"}:
        op.service.video_path(run.id)
    return reference, identity["sha256"]


def media_signature(info):
    if (not S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_size <= 0):
        raise ValueError("Published media must be a nonempty owned single-link regular file")
    return {"size": info.st_size, "device": info.st_dev, "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def media_proof(op, run, *, expected=None):
    if run.state == "interrupted":
        if expected is not None:
            raise ValueError("Interrupted source cannot acquire a publication")
        return None
    path = op.service.store.own_artifact(run.id, run.output.get("path"), "chunk.mp4")
    parts = tuple(path.parent.relative_to(op.root).parts)
    with _directory(op.root, parts) as directory:
        fd = os.open("chunk.mp4", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = media_signature(os.fstat(stream.fileno()))
            if expected is not None:
                if before != expected.model_dump(exclude={"sha256"}):
                    raise ValueError("Imported published media identity changed")
            else:
                digest = hashlib.sha256()
                remaining = before["size"]
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Published media was truncated while hashing")
                    digest.update(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise ValueError("Published media grew while hashing")
            after = media_signature(os.fstat(stream.fileno()))
            current = media_signature(os.stat("chunk.mp4", dir_fd=directory,
                                              follow_symlinks=False))
            if before != after or after != current:
                raise ValueError("Published media changed while proving ownership")
    return expected if expected is not None else MediaProof(sha256=digest.hexdigest(), **before)


def observe_import(op, intent):
    source = intent.source
    original = Run.model_validate(source.manifest)
    if Store.input_projection(original) != source.projection:
        raise ValueError("Imported evidence disagrees with its immutable projection")
    current = op.service.store.get(intent.run_id)
    reference, digest = validate_native(op, current)
    if current.output != original.output:
        raise ValueError("Imported publication metadata changed")
    if original.state != "interrupted" and source.media is None:
        raise ValueError("Imported publication has no media proof")
    media_proof(op, current, expected=source.media)
    snap = intent.snapshot
    if (Store.input_projection(current) != source.projection
            or current.id != intent.run_id or current.prompt != snap.prompt
            or current.seed != snap.seed or current.duration_seconds != snap.duration_seconds
            or current.parent_id != snap.parent_id or reference != snap.reference
            or digest != snap.reference_sha256):
        raise ValueError("Imported source changed its immutable input")
    if original.state != "ready_for_review":
        if current.state != original.state or current.decision != original.decision:
            raise ValueError("Imported terminal decision changed")
    elif current.state not in {"ready_for_review", "accepted", "rejected"}:
        raise ValueError("Imported review has an invalid transition")
    doc = op.get(intent.roteiro_id)
    index = next(i for i, block in enumerate(doc.blocks) if block.id == intent.block_id)
    op.parent(doc, index, snap.parent_id)
    return current


async def convert(op, end_id, roteiro_id):
    canonical(end_id)
    canonical(roteiro_id)
    async with op.service.cpu_slot(f"conversion-{uuid4()}"):
        with (_directory(op.root, (".data", "roteiros"), create=True) as library,
              locked(library)):
            try:
                with _directory(op.root, (".data", "roteiros", roteiro_id)):
                    pass
            except FileNotFoundError:
                pass
            else:
                raise Conflict("Conversion UUID already exists; GET this ID, never replay")
            sequence = op.service.store.sequence(end_id)
            if not 1 <= len(sequence["blocks"]) <= MAX_BLOCKS:
                raise ValueError("Source branch exceeds the local roteiro block budget")
            runs = [op.service.store.get(block["id"]) for block in sequence["blocks"]]
            selected = {run.id for run in runs}
            for name in op.list()["items"]:
                if any(attempt["run_id"] in selected for attempt in name["attempts"]):
                    raise Conflict("Source branch already belongs to a roteiro")
            references = [validate_native(op, run) for run in runs]
            reference, digest = references[0]
            if any(value != (reference, digest) for value in references):
                raise ValueError("Source branch changed original identity")
            if await op.reference_digest(reference) != digest:
                raise ValueError("Original identity bytes changed")
            op.reference_available(reference)
            media = [await _thread(media_proof, op, run) for run in runs]
            ident = roteiro_id
            blocks = [Block(id=str(uuid4()), action=run.prompt, prompt=run.prompt,
                            seed=run.seed, duration_seconds=run.duration_seconds) for run in runs]
            attempts = [Intent(intent_id=run.id, run_id=run.id, roteiro_id=ident,
                               block_id=block.id, source_revision=1, origin="freestyle",
                               admission="admitted", source=ImportedSource(
                                   projection=Store.input_projection(run), manifest=run.model_dump(),
                                   media=proof),
                               snapshot=Snapshot(prompt=run.prompt, seed=run.seed,
                                                 duration_seconds=run.duration_seconds,
                                                 parent_id=run.parent_id, reference=reference,
                                                 reference_sha256=digest))
                        for run, block, proof in zip(runs, blocks, media, strict=True)]
            doc = Document(id=ident, revision=1, name=f"Freestyle · {runs[0].id[:8]}",
                           idea=runs[0].prompt, reference=reference, reference_sha256=digest,
                           adopted=True, blocks=blocks, attempts=attempts)
            encoded_metadata(doc.model_dump())
            with (_directory(op.root, (".data", "roteiros", ident), create=True) as directory,
                  locked(directory)):
                write_file(directory, "plan.json", doc.model_dump(), exclusive=True)
        return op.view(doc)
