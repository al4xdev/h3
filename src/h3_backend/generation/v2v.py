"""Video continuation fluent configuration and complete sequential pipeline."""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Request

from ..infrastructure.store import contained, timestamp
from .dispatcher import Conflict, output_source, publish, verify_video
from .models import CONTINUATION_PROMPT, ContinueRequest, Run
from .workflow import V2V_CONFIG, WorkflowConfig


@dataclass(frozen=True)
class V2VPipeState:
    request: ContinueRequest | None = None
    parent_id: str | None = None
    workflow_config: WorkflowConfig | None = None
    save_output: bool = False
    last_frame: bool = False
    original_identity: bool = False
    motion_tail: bool = False
    run: Run | None = None
    references: list[dict] = field(default_factory=list)
    workflow: dict = field(default_factory=dict)


class V2VPipe:
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self._state = V2VPipeState()
        self._sealed = False
        self._submitting = False

    @property
    def dispatcher(self):
        return self._dispatcher

    @property
    def state(self) -> V2VPipeState:
        # Inspection must not expose mutable worker/config objects to callers.
        return deepcopy(self._state)

    def _configure(self, **changes) -> V2VPipe:
        if self._sealed or self._submitting:
            raise Conflict("Pipeline configuration is immutable after submission")
        self._state = replace(self._state, **changes)
        return self

    def have(self, request: ContinueRequest) -> V2VPipe:
        if not isinstance(request, ContinueRequest):
            raise TypeError("Expected ContinueRequest")
        snapshot = ContinueRequest.model_validate(request.model_dump())
        return self._configure(request=snapshot)

    def with_workflow(self, config: WorkflowConfig) -> V2VPipe:
        if config != V2V_CONFIG:
            raise ValueError("v2v requires its canonical workflow configuration")
        return self._configure(workflow_config=config)

    def save_chunk(self) -> V2VPipe:
        return self._configure(save_output=True)

    async def admit(self) -> Run:
        return await self.dispatcher.submit(self)

    def from_parent(self, parent_id: str) -> V2VPipe:
        if not isinstance(parent_id, str) or not parent_id:
            raise ValueError("Continuation requires a parent id")
        return self._configure(parent_id=parent_id)

    def with_last_frame(self) -> V2VPipe:
        return self._configure(last_frame=True)

    def with_original_identity(self) -> V2VPipe:
        return self._configure(original_identity=True)

    def with_motion_tail(
        self, reference_tail_seconds: int | None = None, include_audio: bool | None = None,
    ) -> V2VPipe:
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
        if self._state.request is None or self._state.workflow_config != V2V_CONFIG:
            raise ValueError("Incomplete v2v request/workflow configuration")
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
            if role == "initial_frame":
                continue
            if role not in (None, "identity"):
                raise ValueError("Ambiguous parent image role")
            if reference.get("source_root", "assets") != "assets":
                raise ValueError("Identity must originate inside assets")
            # Legacy role-less sources must still resolve strictly inside assets below.
            identities.append(reference)
        sources = [reference["source"] for reference in identities]
        if not sources:
            raise ValueError("At least one identity image is required")
        if len(sources) > 8:
            raise ValueError("Continuation permits at most eight identity images")
        assets = contained(service.settings.project_root, "assets", must_exist=True)
        paths = [contained(assets, source, must_exist=True) for source in sources]
        # Compare resolved paths so lexical and symlink aliases cannot consume extra slots.
        if len(set(paths)) != len(paths):
            raise ValueError("Duplicate identity sources are ambiguous")
        for source, path in zip(sources, paths, strict=True):
            if not path.is_file():
                raise ValueError("Reference must be a regular image file")
            info = await asyncio.to_thread(service.media.verify_image, path)
            digest = await asyncio.to_thread(
                lambda p=path: hashlib.sha256(p.read_bytes()).hexdigest()
            )
            original = next(r for r in identities if r.get("source") == source)
            if original["sha256"] != digest:
                raise ValueError("Original identity image changed since parent generation")
            references.append(
                {
                    "type": "image", "role": "identity", "source": source,
                    "source_root": "assets", "sha256": digest, "input_info": info,
                }
            )
        await service.comfy.ensure_idle()
        service.builder.validate_object_info(await service.comfy.object_info(), operation="v2v")
        now = timestamp()
        run = service.store.create(
            Run(
                id=str(uuid4()), created_at=now, updated_at=now,
                seed=request.seed,
                prompt=request.prompt if request.prompt is not None else CONTINUATION_PROMPT,
                duration_seconds=request.duration_seconds,
                workflow_hash=service.builder.hash_for("v2v"),
                parent_id=parent_id,
                references=references,
                input_info={
                    "mode": "continuation", "operation": "v2v",
                    "continuation": request.model_dump(),
                    "workflow_provenance": service.builder.provenance("v2v"),
                    "comfy_extra_pnginfo": getattr(service.builder, "extra_pnginfo", {}),
                },
            )
        )
        self._state = replace(self._state, run=run.model_copy(deep=True))
        self._sealed = True
        return run

    async def _prepare(self, run: Run, request: ContinueRequest) -> list[dict]:
        service = self.dispatcher
        references = []
        frame = contained(service.store.directory(run.id), "initial_frame.png")
        frame_info = await service.media.prepare_last_frame(
            service.video_path(run.parent_id), frame
        )
        if Path(frame_info["path"]).resolve() != frame.resolve() or not frame.is_file():
            raise ValueError("Last frame preparation returned an unexpected path")
        upload = await service.comfy.upload(frame, f"h3_{run.id}_initial_frame.png")
        references.append({
            "type": "image", "role": "initial_frame",
            "source": service.store.relative_artifact(run.id, "initial_frame.png"),
            "source_root": "runs",
            "parent_id": run.parent_id,
            "sha256": await asyncio.to_thread(
                lambda: hashlib.sha256(frame.read_bytes()).hexdigest()
            ),
            "filename": upload["filename"], "upload": upload,
            "has_audio": False, "input_info": frame_info,
        })
        for index, reference in enumerate(run.references):
            assets = contained(service.settings.project_root, "assets", must_exist=True)
            source = contained(assets, reference["source"], must_exist=True)
            digest = await asyncio.to_thread(
                lambda p=source: hashlib.sha256(p.read_bytes()).hexdigest()
            )
            if digest != reference["sha256"]:
                raise ValueError("Identity image changed after admission")
            suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(
                reference["input_info"]["format"].upper(), source.suffix
            )
            upload = await service.comfy.upload(source, f"h3_{run.id}_identity_{index}{suffix}")
            references.append(
                {
                    **reference,
                    "filename": upload["filename"],
                    "upload": upload,
                    "has_audio": False,
                }
            )
        tail = contained(service.store.directory(run.id), "reference_tail.mp4")
        tail_info = await service.media.prepare_tail(
            service.video_path(run.parent_id),
            tail,
            request.reference_tail_seconds,
            include_audio=request.include_audio,
            reference_frame_limit=service.frames_for_duration(run.duration_seconds),
        )
        if Path(tail_info["path"]).resolve() != tail.resolve() or not tail.is_file():
            raise ValueError("Tail preparation returned an unexpected path")
        upload = await service.comfy.upload(tail, f"h3_{run.id}_tail.mp4")
        references.append(
            {
                "type": "video", "role": "motion_video",
                "source": service.store.relative_artifact(run.id, "reference_tail.mp4"),
                "source_root": "runs", "parent_id": run.parent_id,
                "sha256": await asyncio.to_thread(
                    lambda: hashlib.sha256(tail.read_bytes()).hexdigest()
                ),
                "filename": upload["filename"],
                "upload": upload,
                "has_audio": bool(request.include_audio and tail_info["has_audio"]),
                "input_info": tail_info,
            }
        )
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
            operation="v2v",
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
        await asyncio.to_thread(publish, source, destination)
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


@router.post("/runs/{parent_id}/v2v", response_model=Run, status_code=202)
@router.post("/runs/{parent_id}/continue", response_model=Run, status_code=202)
async def create_v2v(parent_id: str, request: ContinueRequest, http_request: Request):
    dispatcher = http_request.app.state.service
    pipe = (V2VPipe(dispatcher).have(request).from_parent(parent_id)
            .with_last_frame().with_original_identity().with_motion_tail()
            .with_workflow(V2V_CONFIG).save_chunk())
    return await dispatcher.submit(pipe)
