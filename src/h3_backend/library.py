"""Explicit library removal with recoverable media evacuation and immutable history."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request

from .generation.assembly import _intent, _metadata, _thread, _write
from .generation.dispatcher import Conflict
from .infrastructure.grok_image import _directory
from .infrastructure.store import safe_path, timestamp
from .roteiro import RemovePlan, Roteiro, body, canonical, locked, response, write_file

router = APIRouter()
MEDIA = {".mp4", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".flac", ".webm"}


class Library:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.root = self.store.root
        self.roteiro = Roteiro(service)

    def documents(self):
        base = safe_path(self.root, ".data/roteiros")
        if not base.exists():
            return []
        names = [p.name for p in base.iterdir() if not p.name.startswith(".") and p.name != "editor.json"]
        if len(names) > 1000:
            raise ValueError("Roteiro library exceeds metadata capacity")
        return sorted(canonical(name) for name in names)

    def dependency_reference(self, reference, selected):
        if reference.get("source_root") == "runs":
            return self.store.run_image_parts(reference.get("path", reference.get("source", "")))[0] in selected
        return False

    def prepare(self, selected, documents, owner):
        if not selected:
            return [], {}
        runs, total = self.store.list_runs(limit=100)
        for offset in range(100, min(total, 1000), 100):
            page, _ = self.store.list_runs(limit=100, offset=offset)
            runs.extend(page)
        if total > 1000:
            raise Conflict("Run library exceeds removal audit capacity")
        chosen = {ident: self.store.get(ident) for ident in selected}
        for run in chosen.values():
            if run.state in {"queued", "running"}:
                raise Conflict("Active or uncertain generation cannot be removed")
        for run in runs:
            if run.id not in selected and (run.parent_id in selected or any(
                    self.dependency_reference(ref, selected) for ref in run.references)):
                raise Conflict("Another block depends on this media")
        for doc in documents:
            if doc.id == owner:
                continue
            if any(a.run_id in selected or a.snapshot.parent_id in selected for a in doc.attempts):
                raise Conflict("Another roteiro owns or depends on this block")
            if self.dependency_reference(doc.reference.model_dump(), selected):
                raise Conflict("Another roteiro uses this identity image")
        directories = [("runs", ident, self.store.directory(ident)) for ident in sorted(selected)]
        base = safe_path(self.root, ".data/assemblies")
        if base.exists():
            entries = sorted(path for path in base.iterdir() if not path.name.startswith("."))
            if len(entries) > 1000:
                raise Conflict("Assembly library exceeds removal audit capacity")
            for path in entries:
                ident = canonical(path.name)
                directory = safe_path(base, ident)
                if safe_path(directory, "removed.json").exists():
                    continue
                try:
                    intent = _intent(self.root, ident)
                except (OSError, ValueError) as exc:
                    raise Conflict("Assembly dependencies cannot be verified") from exc
                inputs = {clip.run_id for clip in intent.inputs}
                if not inputs.intersection(selected):
                    continue
                if not inputs.issubset(selected):
                    raise Conflict("A shared assembly depends on this block")
                if _metadata(self.root, ident).state == "running":
                    raise Conflict("Active or uncertain assembly cannot be removed")
                directories.append(("assemblies", ident, directory))
        return directories, chosen

    @staticmethod
    def transfer(source, destination):
        digest = hashlib.sha256()
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(source_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise ValueError("Removal requires private regular artifacts")
            with (os.fdopen(source_fd, "rb", closefd=False) as reader,
                  destination.open("xb") as writer):
                os.fchmod(writer.fileno(), stat.S_IMODE(info.st_mode))
                while chunk := reader.read(1024 * 1024):
                    writer.write(chunk)
                    digest.update(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            current = source.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != (
                    info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                raise ValueError("Artifact changed during removal")
            source.unlink()
            for directory in {source.parent, destination.parent}:
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return digest.hexdigest()
        finally:
            os.close(source_fd)

    def evacuate(self, directories, chosen, owner):
        trash = Path(tempfile.mkdtemp(prefix="h3-trash-", dir="/tmp"))
        os.chmod(trash, 0o700)
        moves = []
        markers = []
        journal = {"operation": "library-removal", "created_at": timestamp(), "roteiro_id": owner,
                   "runs": [run.model_dump() for run in chosen.values()], "moves": [], "state": "prepared"}
        _write(trash / "journal.json", journal)
        try:
            for _, ident, directory in directories:
                marker = directory / "removed.json"
                markers.append(marker)
                _write(marker, {"id": ident, "removed": True})
            if owner:
                markers.append(safe_path(self.root, f".data/roteiros/{owner}/removed.json"))
                with _directory(self.root, (".data", "roteiros", owner)) as fd:
                    write_file(fd, "removed.json", {"id": owner, "removed": True}, exclusive=True)
            for kind, ident, directory in directories:
                entries = []
                for path in directory.rglob("*"):
                    entries.append(path)
                    if len(entries) > 1000:
                        raise ValueError("Run artifacts exceed removal capacity")
                for path in sorted(entries):
                    relative = path.relative_to(directory)
                    source = safe_path(directory, relative)
                    info = source.lstat()
                    if stat.S_ISDIR(info.st_mode):
                        continue
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                            or info.st_nlink != 1):
                        raise ValueError("Removal refuses nonregular artifacts")
                    if source.suffix.lower() not in MEDIA:
                        continue
                    destination = trash / kind / ident / relative
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    moves.append((source, destination))
                    journal["moves"].append({"source": str(source.relative_to(self.root)),
                                             "trash": str(destination.relative_to(trash)), "bytes": info.st_size})
                    _write(trash / "journal.json", journal, replace_existing=True)
                    journal["moves"][-1]["sha256"] = self.transfer(source, destination)
                    _write(trash / "journal.json", journal, replace_existing=True)
            journal["state"] = "completed"
            _write(trash / "journal.json", journal, replace_existing=True)
        except (OSError, ValueError):
            journal["state"] = "rollback"
            try:
                for source, destination in reversed(moves):
                    if source.exists():
                        if destination.exists():
                            os.replace(destination, trash / f"partial-copy-{uuid4()}")
                        continue
                    self.transfer(destination, source)
                for marker in markers:
                    if not marker.exists():
                        continue
                    self.transfer(marker, trash / f"rollback-marker-{uuid4()}.json")
                journal["state"] = "rolled_back"
            except (OSError, ValueError) as exc:
                journal["state"] = "partial"
                journal["error"] = type(exc).__name__
            _write(trash / "journal.json", journal, replace_existing=True)
            raise Conflict(f"Removal did not complete; evidence retained at {trash}") from None
        return {"removed": True, "run_ids": sorted(chosen), "trash_path": str(trash)}

    async def remove(self, ident, *, revision=None):
        canonical(ident)
        async with self.service.cpu_slot(f"library-{uuid4()}"):
            with ExitStack() as stack:
                fd = stack.enter_context(_directory(self.root, (".data", "roteiros"), create=True))
                stack.enter_context(locked(fd))
                documents = []
                for name in self.documents():
                    fd = stack.enter_context(_directory(self.root, (".data", "roteiros", name)))
                    stack.enter_context(locked(fd))
                    if not self.roteiro.removed(name):
                        documents.append(self.roteiro.get(name))
                owner = ident if revision is not None else None
                if owner:
                    doc = self.roteiro.get(ident)
                    self.roteiro.check_revision(doc, revision)
                    selected = set()
                    for attempt in doc.attempts:
                        observed = self.roteiro.observed(attempt)
                        if observed["state"] in {"uncertain", "queued", "running"}:
                            raise Conflict("Uncertain native admission cannot be removed")
                        if observed["admission"] == "admitted":
                            selected.add(attempt.run_id)
                else:
                    selected = {ident}
                directories, chosen = self.prepare(selected, documents, owner)
                return await _thread(self.evacuate, directories, chosen, owner)


@router.delete("/runs/{ident}")
async def remove_run(ident: str, request: Request):
    async for chunk in request.stream():
        if chunk:
            raise ValueError("Block removal does not accept a body")
    return response(await Library(request.app.state.service).remove(ident))


@router.delete("/roteiros/{ident}")
async def remove_roteiro(ident: str, request: Request):
    payload = await body(request, RemovePlan)
    return response(await Library(request.app.state.service).remove(ident, revision=payload.expected_revision))
