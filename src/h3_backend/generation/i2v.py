"""Image-only fluent configuration and complete sequential pipeline."""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from dataclasses import dataclass, field, replace
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Request

from ..infrastructure.store import contained, timestamp
from .dispatcher import Conflict, output_source, publish, verify_video
from .models import Run, RunRequest
from .workflow import I2V_CONFIG, WorkflowConfig


@dataclass(frozen=True)
class I2VPipeState:
    request: RunRequest | None = None
    workflow_config: WorkflowConfig | None = None
    save_output: bool = False
    run: Run | None = None
    references: list[dict] = field(default_factory=list)
    workflow: dict = field(default_factory=dict)


class I2VPipe:
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self._state = I2VPipeState()
        self._sealed = False
        self._submitting = False

    @property
    def dispatcher(self):
        return self._dispatcher

    @property
    def state(self) -> I2VPipeState:
        # Inspection must not expose mutable worker/config objects to callers.
        return deepcopy(self._state)

    def _configure(self, **changes) -> I2VPipe:
        if self._sealed or self._submitting:
            raise Conflict("Pipeline configuration is immutable after submission")
        self._state = replace(self._state, **changes)
        return self

    def have(self, request: RunRequest) -> I2VPipe:
        if not isinstance(request, RunRequest):
            raise TypeError("Expected RunRequest")
        snapshot = RunRequest.model_validate(request.model_dump())
        return self._configure(request=snapshot)

    def with_workflow(self, config: WorkflowConfig) -> I2VPipe:
        if config != I2V_CONFIG:
            raise ValueError("i2v requires its canonical workflow configuration")
        return self._configure(workflow_config=config)

    def save_chunk(self) -> I2VPipe:
        return self._configure(save_output=True)

    async def admit(self) -> Run:
        return await self.dispatcher.submit(self)

    async def _admit(self) -> Run:
        service = self.dispatcher
        if self._state.request is None or self._state.workflow_config != I2V_CONFIG:
            raise ValueError("Incomplete i2v request/workflow configuration")
        if not self._state.save_output:
            raise ValueError("Pipeline must publish its chunk")
        request = self._state.request.model_copy(deep=True)
        service.frames_for_duration(request.duration_seconds)
        if request.prompt is not None and not request.prompt.strip():
            raise ValueError("Prompt cannot be whitespace")
        references = []
        sources = [request.image, *request.images]
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
            references.append(
                {
                    "type": "image", "role": "identity", "source": source,
                    "source_root": "assets", "sha256": digest, "input_info": info,
                }
            )
        await service.comfy.ensure_idle()
        service.builder.validate_object_info(await service.comfy.object_info(), operation="i2v")
        now = timestamp()
        run = service.store.create(
            Run(
                id=str(uuid4()), created_at=now, updated_at=now,
                seed=request.seed, prompt=request.prompt,
                duration_seconds=request.duration_seconds,
                workflow_hash=service.builder.hash_for("i2v"),
                references=references,
                input_info={
                    "mode": "normal", "operation": "i2v", "continuation": None,
                    "workflow_provenance": service.builder.provenance("i2v"),
                    "comfy_extra_pnginfo": getattr(service.builder, "extra_pnginfo", {}),
                },
            )
        )
        self._state = replace(self._state, run=run.model_copy(deep=True))
        self._sealed = True
        return run

    async def _prepare(self, run: Run) -> list[dict]:
        service = self.dispatcher
        references = []
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
        return references

    async def arun(self) -> None:
        if not self._sealed or self._state.run is None:
            raise Conflict("Pipeline has not been admitted")
        service = self.dispatcher
        run = self._state.run
        if asyncio.current_task() is not service._task or service._active != run.id:
            raise Conflict("Pipeline execution belongs to the central worker only")
        start = monotonic()
        references = await self._prepare(run)
        service.store.update(run.id, references=references)
        workflow = service.builder.build(
            operation="i2v",
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


@router.post("/runs/i2v", response_model=Run, status_code=202)
@router.post("/runs", response_model=Run, status_code=202)
async def create_i2v(request: RunRequest, http_request: Request):
    dispatcher = http_request.app.state.service
    pipe = I2VPipe(dispatcher).have(request).with_workflow(I2V_CONFIG).save_chunk()
    return await dispatcher.submit(pipe)
