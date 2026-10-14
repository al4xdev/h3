"""Native video bridge between two frozen accepted anchors."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from fastapi import APIRouter, Request

from ..infrastructure.media import await_thread, sha256_file
from ..infrastructure.store import Store, contained, timestamp
from .dispatcher import Conflict, output_source, publish, verify_video
from .models import CONTINUATION_PROMPT, BridgeRequest, ImageReference, Run
from .workflow import BRIDGE_CONFIG, WorkflowConfig


def _owned_file(path: Path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Bridge media cannot use symlinks")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    stream = os.fdopen(fd, "rb")
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size <= 0:
        stream.close()
        raise ValueError("Bridge media must be a nonempty owned regular file")
    return stream


def owned_sha256(path: Path) -> str:
    with _owned_file(path) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot_video(source: Path, destination: Path, expected_sha256: str) -> None:
    fd, name = tempfile.mkstemp(prefix=".bridge-", suffix=".mp4", dir=destination.parent)
    try:
        digest = hashlib.sha256()
        with os.fdopen(fd, "wb") as output, _owned_file(source) as incoming:
            before = os.fstat(incoming.fileno())
            while block := incoming.read(1024 * 1024):
                digest.update(block)
                output.write(block)
            after = os.fstat(incoming.fileno())
            if (digest.hexdigest() != expected_sha256
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise Conflict("Bridge video changed while freezing its encoded bytes")
            output.flush()
            os.fsync(output.fileno())
        os.link(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass(frozen=True)
class BridgePipeState:
    run_id: str | None = None
    identity_proof: tuple[str, str, str] | None = None
    request: BridgeRequest | None = None
    parent_id: str | None = None
    workflow_config: WorkflowConfig | None = BRIDGE_CONFIG
    save_output: bool = True
    last_frame: bool = True
    original_identity: bool = True
    motion_tail: bool = True
    run: Run | None = None
    references: list[dict] = field(default_factory=list)
    workflow: dict = field(default_factory=dict)


class BridgePipe:
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self._state = BridgePipeState()
        self._sealed = False
        self._submitting = False

    @classmethod
    def from_run(cls, dispatcher, run: Run) -> BridgePipe:
        """Restore the exact continuation options, never infer them from runtime defaults."""
        Store.validate_request(run)
        info = run.input_info
        if (run.parent_id is None or info["operation"] != "bridge"
                or info["mode"] != BRIDGE_CONFIG.mode
                or run.workflow_hash != dispatcher.builder.hash_for("bridge")
                or json.dumps(info["workflow_provenance"], sort_keys=True) != json.dumps(
                    dispatcher.builder.provenance("bridge"), sort_keys=True,
                ) or info["comfy_extra_pnginfo"] != getattr(dispatcher.builder, "extra_pnginfo", {})):
            raise ValueError("Bridge admission disagrees with its canonical builder")
        if not isinstance(info["continuation"], dict) or set(info["continuation"]) != set(
            BridgeRequest.model_fields
        ):
            raise ValueError("Continuation snapshot must contain every native option")
        request = BridgeRequest.model_validate(info["continuation"], strict=True)
        if (request.seed != run.seed or request.duration_seconds != run.duration_seconds
                or (request.prompt if request.prompt is not None else CONTINUATION_PROMPT) != run.prompt
                or not run.prompt.strip()):
            raise ValueError("Continuation options disagree with admitted input")
        dispatcher.frames_for_duration(request.duration_seconds)
        pipe = (cls(dispatcher).have(request).from_parent(run.parent_id).with_last_frame()
                .with_original_identity().with_motion_tail().with_workflow(BRIDGE_CONFIG).save_chunk())
        pipe._state = replace(pipe._state, run=run.model_copy(deep=True))
        pipe._sealed = True
        return pipe

    @property
    def dispatcher(self):
        return self._dispatcher

    @property
    def state(self) -> BridgePipeState:
        # Inspection must not expose mutable worker/config objects to callers.
        return deepcopy(self._state)

    def _configure(self, **changes) -> BridgePipe:
        if self._sealed or self._submitting:
            raise Conflict("Pipeline configuration is immutable after submission")
        self._state = replace(self._state, **changes)
        return self

    def have(self, request: BridgeRequest) -> BridgePipe:
        if not isinstance(request, BridgeRequest):
            raise TypeError("Expected BridgeRequest")
        snapshot = BridgeRequest.model_validate(request.model_dump())
        return self._configure(request=snapshot)

    def with_workflow(self, config: WorkflowConfig) -> BridgePipe:
        if config != BRIDGE_CONFIG:
            raise ValueError("Bridge requires its canonical workflow configuration")
        return self._configure(workflow_config=config)

    def save_chunk(self) -> BridgePipe:
        return self._configure(save_output=True)

    def with_run_id(self, run_id: str) -> BridgePipe:
        # Explicit caller intent correlation; composition remains pure and legacy IDs unchanged.
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
            raise ValueError("Run ID must be a canonical UUID")
        return self._configure(run_id=run_id)

    def with_identity_proof(self, source_root: str, path: str, sha256: str) -> BridgePipe:
        reference = ImageReference(source_root=source_root, path=path)
        if (not isinstance(sha256, str) or len(sha256) != 64
                or any(c not in "0123456789abcdef" for c in sha256)):
            raise ValueError("Identity proof requires a lowercase SHA256")
        return self._configure(identity_proof=(reference.source_root, reference.path, sha256))

    async def admit(self) -> Run:
        return await self.dispatcher.submit(self)

    def from_parent(self, parent_id: str) -> BridgePipe:
        if not isinstance(parent_id, str) or str(UUID(parent_id)) != parent_id:
            raise ValueError("Bridge requires a canonical parent UUID")
        return self._configure(parent_id=parent_id)

    def with_last_frame(self) -> BridgePipe:
        return self._configure(last_frame=True)

    def with_original_identity(self) -> BridgePipe:
        return self._configure(original_identity=True)

    def with_motion_tail(
        self, reference_tail_seconds: int | None = None, include_audio: bool | None = None,
    ) -> BridgePipe:
        if self._state.request is None:
            raise ValueError("Configure a request before its motion tail")
        request = self._state.request.model_copy(deep=True)
        if (reference_tail_seconds is not None
                and reference_tail_seconds != request.reference_tail_seconds):
            raise ValueError("Motion tail must match the request snapshot")
        if include_audio is not None and include_audio != request.include_audio:
            raise ValueError("Motion audio must match the request snapshot")
        return self._configure(motion_tail=True)

    async def _admit(self) -> Run:
        service = self.dispatcher
        if self._state.request is None or self._state.workflow_config != BRIDGE_CONFIG:
            raise ValueError("Incomplete bridge request/workflow configuration")
        if not self._state.save_output:
            raise ValueError("Pipeline must publish its chunk")
        if not (self._state.parent_id and self._state.last_frame
                and self._state.original_identity and self._state.motion_tail):
            raise ValueError("Continuation requires parent, last frame, identity and motion tail")
        parent_id = self._state.parent_id
        request = self._state.request.model_copy(deep=True)
        service.frames_for_duration(request.duration_seconds)
        if request.prompt is not None and not request.prompt.strip():
            raise ValueError("Prompt cannot be whitespace")
        parent = service.store.get(parent_id)
        if parent.state != "accepted":
            raise Conflict("Continuation requires an explicitly accepted parent")
        references = []
        identities = []
        for reference in parent.references:
            if reference.get("type") != "image":
                continue
            role = reference.get("role")
            if role == "initial_frame" or (role == "target_frame"
                                            and parent.input_info.get("operation") == "bridge"):
                continue
            if role not in (None, "identity"):
                raise ValueError("Ambiguous parent image role")
            if reference.get("source_root", "assets") not in ("assets", "inputs", "runs"):
                raise ValueError("Identity must originate inside a public image category")
            # Legacy role-less sources retain their assets category; no root is inferred from paths.
            identities.append(reference)
        sources = [reference["source"] for reference in identities]
        if not sources:
            raise ValueError("At least one identity image is required")
        if len(sources) > 7:
            raise ValueError("Bridge permits at most seven identity images")
        paths = [service.store.reference_path(ref.get("source_root", "assets"), ref["source"])
                 for ref in identities]
        # Compare resolved paths so lexical and symlink aliases cannot consume extra slots.
        if len(set(paths)) != len(paths):
            raise ValueError("Duplicate identity sources are ambiguous")
        for original, path in zip(identities, paths, strict=True):
            source = original["source"]
            if not path.is_file():
                raise ValueError("Reference must be a regular image file")
            info = await asyncio.to_thread(service.media.verify_image, path)
            digest = await asyncio.to_thread(
                sha256_file, path
            )
            if original["sha256"] != digest:
                raise ValueError("Original identity image changed since parent generation")
            references.append(
                {
                    "type": "image", "role": "identity", "source": source,
                    "source_root": original.get("source_root", "assets"),
                    "sha256": digest, "input_info": info,
                }
            )
        # Optional caller metadata binds the fresh native hash before materialization or worker I/O.
        if self._state.identity_proof is not None and [self._state.identity_proof] != [
            (ref["source_root"], ref["source"], ref["sha256"]) for ref in references
        ]:
            raise Conflict("Identity changed from the explicit caller snapshot")
        anchors = await self._anchors(parent, request.target_run_id, references)
        await service.comfy.ensure_idle()
        service.builder.validate_object_info(await service.comfy.object_info(), operation="bridge")
        now = timestamp()
        run = service.store.create(
            Run(
                id=self._state.run_id or str(uuid4()), created_at=now, updated_at=now,
                seed=request.seed,
                prompt=request.prompt if request.prompt is not None else CONTINUATION_PROMPT,
                duration_seconds=request.duration_seconds,
                workflow_hash=service.builder.hash_for("bridge"),
                parent_id=parent_id,
                references=references,
                input_info={
                    "mode": "bridge", "operation": "bridge",
                    "continuation": request.model_dump(),
                    "bridge_anchors": anchors,
                    "workflow_provenance": service.builder.provenance("bridge"),
                    "comfy_extra_pnginfo": getattr(service.builder, "extra_pnginfo", {}),
                },
            ), materialize_request=True,
        )
        self._state = replace(self._state, run=run.model_copy(deep=True))
        self._sealed = True
        return run

    async def _anchors(self, parent: Run, target_id: str, identities: list[dict]) -> dict:
        service = self.dispatcher
        if parent.id == target_id:
            raise ValueError("Bridge parent and target must be distinct accepted runs")
        target = service.store.get(target_id)
        if target.state != "accepted":
            raise Conflict("Bridge target must be explicitly accepted")
        keys = ("source", "sha256")
        target_identities = [r for r in target.references if r.get("type") == "image"
                             and r.get("role") in (None, "identity")]
        target_roles = (None, "identity", "initial_frame") + (
            ("target_frame",) if target.input_info.get("operation") == "bridge" else ()
        )
        if (any(r.get("role") not in target_roles
                for r in target.references if r.get("type") == "image")
                or [(r.get("source_root", "assets"), *(r.get(k) for k in keys))
                    for r in target_identities]
                != [(r["source_root"], *(r.get(k) for k in keys)) for r in identities]):
            raise Conflict("Bridge anchors must share the same original identity")
        anchors = {}
        for role, anchor in (("parent", parent), ("target", target)):
            if not anchor.output.get("path"):
                raise ValueError("Bridge anchor has no owned published video")
            video = service.video_path(anchor.id)
            verify_video(await service.media.probe(video), service.frames_for_duration(anchor.duration_seconds))
            anchors[role] = {
                "run_id": anchor.id,
                "video_path": service.store.relative_artifact(anchor.id, "chunk.mp4"),
                "video_sha256": await asyncio.to_thread(owned_sha256, video),
                "manifest_sha256": await asyncio.to_thread(
                    owned_sha256, service.store.directory(anchor.id) / "manifest.json",
                ),
            }
            if service.store.get(anchor.id).model_dump() != anchor.model_dump():
                raise Conflict("Bridge anchor manifest changed while freezing its proof")
        return anchors

    def verify_anchors(self, run: Run) -> None:
        service = self.dispatcher
        identities = [(r["source_root"], r["source"], r["sha256"]) for r in run.references
                      if r.get("role") == "identity"]
        for anchor in run.input_info["bridge_anchors"].values():
            current = service.store.get(anchor["run_id"])
            current_identities = [
                (r.get("source_root", "assets"), r.get("source"), r.get("sha256"))
                for r in current.references if r.get("type") == "image"
                and r.get("role") in (None, "identity")
            ]
            if (current.state != "accepted"
                    or current_identities != identities
                    or owned_sha256(service.store.directory(current.id) / "manifest.json")
                    != anchor["manifest_sha256"]
                    or owned_sha256(service.video_path(current.id)) != anchor["video_sha256"]):
                raise Conflict("Bridge anchor changed after admission")

    async def _prepare(self, run: Run, request: BridgeRequest) -> list[dict]:
        from .v2v import V2VPipe

        service = self.dispatcher
        await asyncio.to_thread(self.verify_anchors, run)
        snapshots = {}
        for role, anchor in run.input_info["bridge_anchors"].items():
            destination = service.store.directory(run.id) / f"bridge_{role}.mp4"
            await await_thread(snapshot_video, service.video_path(anchor["run_id"]), destination,
                               anchor["video_sha256"])
            snapshots[role] = destination
        references = await V2VPipe(service)._prepare(run, request, parent_video=snapshots["parent"])
        frame = contained(service.store.directory(run.id), "target_frame.png")
        frame_info = await service.media.prepare_first_frame(snapshots["target"], frame)
        if (Path(frame_info["path"]).resolve() != frame.resolve() or not frame.is_file()
                or frame_info.get("source_frame_index") != 0):
            raise ValueError("Target preparation must return its exact first decoded frame")
        upload = await service.comfy.upload(frame, f"h3_{run.id}_target_frame.png")
        references.insert(-1, {
            "type": "image", "role": "target_frame", "source_root": "runs",
            "source": service.store.relative_artifact(run.id, "target_frame.png"),
            "target_run_id": request.target_run_id,
            "sha256": await asyncio.to_thread(sha256_file, frame),
            "filename": upload["filename"], "upload": upload,
            "has_audio": False, "input_info": frame_info,
        })
        await asyncio.to_thread(self.verify_anchors, run)
        return references

    async def arun(self) -> None:
        if not self._sealed or self._state.run is None:
            raise Conflict("Pipeline has not been admitted")
        service = self.dispatcher
        run = self._state.run
        if asyncio.current_task() is not service._task or service._active != run.id:
            raise Conflict("Pipeline execution belongs to the central worker only")
        start = monotonic()
        request = self._state.request.model_copy(deep=True)
        references = await self._prepare(run, request)
        service.store.update(run.id, references=references)
        workflow = service.builder.build(
            operation="bridge",
            prompt=run.prompt,
            seed=run.seed,
            duration_seconds=run.duration_seconds,
            references=references,
            filename_prefix=f"h3_backend/{run.id}/chunk",
        )
        workflow_path = service.store.artifact_json(run.id, "workflow_api.json", workflow)
        # Hash persisted bytes: Store serialization is the execution artifact contract.
        workflow_sha256 = await asyncio.to_thread(
            lambda: hashlib.sha256(workflow_path.read_bytes()).hexdigest()
        )
        service.store.artifact_markdown(run.id, run.prompt)
        current = service.store.get(run.id)
        service.store.update(
            run.id,
            input_info={
                **current.input_info,
                "workflow_api_sha256": workflow_sha256,
                "workflow_api": service.store.relative_artifact(run.id, "workflow_api.json"),
                "prompt_markdown": service.store.relative_artifact(run.id, "prompt.md"),
                "telemetry": service.store.relative_artifact(run.id, "telemetry.jsonl"),
                "effective_markdown": run.prompt,
                "slot_map": [
                    {
                        "tag": f"<Picture {index + 1}>",
                        "role": ref["role"], "source": ref["source"],
                        "sha256": ref["sha256"],
                    }
                    for index, ref in enumerate(r for r in references if r["type"] == "image")
                ] + [
                    {
                        "tag": f"<Video {index + 1}>",
                        "role": ref["role"], "source": ref["source"],
                        "sha256": ref["sha256"],
                    }
                    for index, ref in enumerate(r for r in references if r["type"] == "video")
                ],
            },
        )
        self._state = replace(self._state, references=references, workflow=workflow)

        async def submitted(prompt_id):
            service.store.update(run.id, prompt_id=prompt_id)

        async def progress(data):
            service.store.update(run.id, progress=data)

        result = await service.comfy.execute(
            workflow,
            prompt_id=str(uuid4()),
            deadline=service.settings.inference_deadline,
            on_submitted=submitted,
            on_progress=progress,
            extra_pnginfo=getattr(service.builder, "extra_pnginfo", {}),
        )
        source = output_source(result, service.settings.comfy_root)
        info = await service.media.probe(source)
        verify_video(info, service.frames_for_duration(run.duration_seconds))
        destination = contained(service.store.directory(run.id), "chunk.mp4")
        await await_thread(publish, source, destination)
        service.store.update(
            run.id,
            state="ready_for_review",
            publication_mode="atomic_copy_from_comfy_output",
            output={
                "path": service.store.relative_artifact(run.id, "chunk.mp4"),
                "probe": info,
                "source": str(source),
                "node": "34",
            },
            timings={"total_seconds": monotonic() - start},
        )


router = APIRouter()


@router.post("/runs/{parent_id}/bridge", response_model=Run, status_code=202)
async def create_bridge(parent_id: str, request: BridgeRequest, http_request: Request):
    dispatcher = http_request.app.state.service
    pipe = (BridgePipe(dispatcher).have(request).from_parent(parent_id)
            .with_last_frame().with_original_identity().with_motion_tail()
            .with_workflow(BRIDGE_CONFIG).save_chunk())
    return await dispatcher.submit(pipe)
