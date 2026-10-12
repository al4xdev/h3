"""Single-job orchestration; accepted clips never trigger automatic continuation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import shutil
import tempfile
from fractions import Fraction
from pathlib import Path
from time import monotonic
from uuid import uuid4

from .comfy import ComfyClient, ExecutionInterrupted
from .models import CONTINUATION_PROMPT, ContinueRequest, Run, RunRequest, Settings
from .store import Store, contained, timestamp


class Conflict(ValueError):
    pass


def verify_video(info: dict, expected_frames: int) -> None:
    videos = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if len(videos) != 1:
        raise ValueError("Output must contain exactly one video stream")
    video = videos[0]
    duration = float(video.get("duration", info.get("format", {}).get("duration", "nan")))
    fps = Fraction(video.get("avg_frame_rate", "0"))
    if not math.isfinite(duration) or not 0 < duration <= 3:
        raise ValueError("Output duration exceeds the strict three-second limit")
    if (video.get("width"), video.get("height")) != (480, 864) or fps != 24:
        raise ValueError("Output does not match baseline 480x864 at 24 fps")
    if int(video.get("nb_read_frames", video.get("nb_frames", -1))) != expected_frames:
        raise ValueError("Output frame count does not match aligned requested duration")


def output_source(history: dict, comfy_root: Path) -> Path:
    # Node 18 is a preview; only node 34 is eligible for publication.
    node = history.get("outputs", {}).get("34", {})
    candidates = []
    for collection in ("gifs", "videos"):
        for item in node.get(collection, []):
            if item.get("type") != "output":
                continue
            name = item.get("filename", "")
            if Path(name).suffix.lower() != ".mp4" or len(Path(name).parts) != 1:
                continue
            candidates.append(
                contained(
                    comfy_root / "output", Path(item.get("subfolder", "")) / name, must_exist=True
                )
            )
    if len(candidates) != 1 or not candidates[0].is_file():
        raise ValueError("Expected one final MP4 from output node 34")
    return candidates[0]


def publish(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError("Refusing to overwrite a published clip")
    fd, name = tempfile.mkstemp(prefix=".chunk-", suffix=".mp4", dir=destination.parent)
    try:
        with source.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        # Hard-link publishes without replacing any concurrently created destination.
        os.link(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class RunService:
    """Explicit operation pipelines sharing one admission lock and execution slot.

    Keep the worker boundaries separate so i2v cannot accidentally prepare parent
    media or select continuation routing; only the dispatcher knows graph modes.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        store=None,
        comfy=None,
        builder=None,
        media=None,
        frames_for_duration=None,
        telemetry=None,
        memory_available=None,
    ):
        if builder is None:
            from .workflow import WorkflowBuilder

            builder = WorkflowBuilder(settings.project_root)
        if frames_for_duration is None:
            from .workflow import frames_for_duration as frames

            frames_for_duration = frames
        if media is None:
            from . import media as media_module

            media = media_module
        if telemetry is None:
            from .telemetry import record_telemetry

            telemetry = record_telemetry
        self.settings = settings
        self.store = store or Store(settings.project_root)
        self.comfy = comfy or ComfyClient(settings.comfy_url)
        self.builder = builder
        self.media = media
        self.frames_for_duration = frames_for_duration
        self.telemetry = telemetry
        if memory_available is None:
            import psutil

            memory_available = lambda: psutil.virtual_memory().available
        self.memory_available = memory_available
        self._lock = asyncio.Lock()
        self._active: str | None = None
        self._task: asyncio.Task | None = None
        self._closing = False

    async def startup(self) -> None:
        self.store.restore()

    async def shutdown(self) -> None:
        self._closing = True
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._active:
            pending = self.store.get(self._active)
            if pending.state in {"queued", "running"}:
                self.store.update(
                    pending.id,
                    state="interrupted",
                    error="Backend stopped before execution completed",
                )
            self._active = None
        await self.comfy.close()

    async def wait_run(self, run_id: str) -> Run:
        self.store.get(run_id)
        task = self._task if self._active == run_id else None
        if task and not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise  # A disconnected HTTP waiter must not cancel the execution task.
        return self.store.get(run_id)

    def video_path(self, run_id: str) -> Path:
        run = self.store.get(run_id)
        if run.state not in {"ready_for_review", "accepted", "rejected"}:
            raise Conflict("Run has no reviewed/ready video")
        return contained(self.store.directory(run_id), "chunk.mp4", must_exist=True)

    async def decide(self, run_id: str, accepted: bool) -> Run:
        async with self._lock:
            run = self.store.get(run_id)
            if run.state != "ready_for_review":
                raise Conflict(
                    "Only a ready_for_review run can be decided; decisions are immutable"
                )
            return self.store.update(
                run_id,
                state="accepted" if accepted else "rejected",
                decision={"accepted": accepted, "at": timestamp()},
            )

    async def create(self, request: RunRequest) -> Run:
        return await self._admit_i2v(request)

    async def continue_run(self, parent_id: str, request: ContinueRequest) -> Run:
        return await self._admit_v2v(parent_id, request)

    async def _admit_i2v(self, request: RunRequest) -> Run:
        async with self._lock:
            if self._closing or self._active is not None:
                raise Conflict("Only one backend job may be active")
            if self.memory_available() < self.settings.minimum_available_bytes:
                raise Conflict("Available host RAM is below 1.5 GiB; no job was submitted")
            self.frames_for_duration(request.duration_seconds)
            if request.prompt is not None and not request.prompt.strip():
                raise ValueError("Prompt cannot be whitespace")
            references = []
            sources = [request.image, *request.images]
            assets = contained(self.settings.project_root, "assets", must_exist=True)
            paths = [contained(assets, source, must_exist=True) for source in sources]
            # Compare resolved paths so lexical and symlink aliases cannot consume extra slots.
            if len(set(paths)) != len(paths):
                raise ValueError("Duplicate identity sources are ambiguous")
            for source, path in zip(sources, paths, strict=True):
                if not path.is_file():
                    raise ValueError("Reference must be a regular image file")
                info = await asyncio.to_thread(self.media.verify_image, path)
                digest = await asyncio.to_thread(
                    lambda p=path: hashlib.sha256(p.read_bytes()).hexdigest()
                )
                references.append(
                    {
                        "type": "image", "role": "identity", "source": source,
                        "source_root": "assets", "sha256": digest, "input_info": info,
                    }
                )
            await self.comfy.ensure_idle()
            self.builder.validate_object_info(await self.comfy.object_info(), operation="i2v")
            now = timestamp()
            run = self.store.create(
                Run(
                    id=str(uuid4()), created_at=now, updated_at=now,
                    seed=request.seed, prompt=request.prompt,
                    duration_seconds=request.duration_seconds,
                    workflow_hash=self.builder.hash_for("i2v"),
                    references=references,
                    input_info={
                        "mode": "normal", "operation": "i2v", "continuation": None,
                        "workflow_provenance": self.builder.provenance("i2v"),
                        "comfy_extra_pnginfo": getattr(self.builder, "extra_pnginfo", {}),
                    },
                )
            )
            self._active = run.id
            self._task = asyncio.create_task(self._execute_i2v(run), name=f"h3-{run.id}")
            return run

    async def _admit_v2v(self, parent_id: str, request: ContinueRequest) -> Run:
        async with self._lock:
            if self._closing or self._active is not None:
                raise Conflict("Only one backend job may be active")
            if self.memory_available() < self.settings.minimum_available_bytes:
                raise Conflict("Available host RAM is below 1.5 GiB; no job was submitted")
            self.frames_for_duration(request.duration_seconds)
            if request.prompt is not None and not request.prompt.strip():
                raise ValueError("Prompt cannot be whitespace")
            parent = self.store.get(parent_id)
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
            assets = contained(self.settings.project_root, "assets", must_exist=True)
            paths = [contained(assets, source, must_exist=True) for source in sources]
            # Compare resolved paths so lexical and symlink aliases cannot consume extra slots.
            if len(set(paths)) != len(paths):
                raise ValueError("Duplicate identity sources are ambiguous")
            for source, path in zip(sources, paths, strict=True):
                if not path.is_file():
                    raise ValueError("Reference must be a regular image file")
                info = await asyncio.to_thread(self.media.verify_image, path)
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
            await self.comfy.ensure_idle()
            self.builder.validate_object_info(await self.comfy.object_info(), operation="v2v")
            now = timestamp()
            run = self.store.create(
                Run(
                    id=str(uuid4()), created_at=now, updated_at=now,
                    seed=request.seed,
                    prompt=request.prompt if request.prompt is not None else CONTINUATION_PROMPT,
                    duration_seconds=request.duration_seconds,
                    workflow_hash=self.builder.hash_for("v2v"),
                    parent_id=parent_id,
                    references=references,
                    input_info={
                        "mode": "continuation", "operation": "v2v",
                        "continuation": request.model_dump(),
                        "workflow_provenance": self.builder.provenance("v2v"),
                        "comfy_extra_pnginfo": getattr(self.builder, "extra_pnginfo", {}),
                    },
                )
            )
            self._active = run.id
            self._task = asyncio.create_task(self._execute_v2v(run, request), name=f"h3-{run.id}")
            return run

    async def _prepare_i2v(self, run: Run) -> list[dict]:
        references = []
        for index, reference in enumerate(run.references):
            assets = contained(self.settings.project_root, "assets", must_exist=True)
            source = contained(assets, reference["source"], must_exist=True)
            digest = await asyncio.to_thread(
                lambda p=source: hashlib.sha256(p.read_bytes()).hexdigest()
            )
            if digest != reference["sha256"]:
                raise ValueError("Identity image changed after admission")
            suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(
                reference["input_info"]["format"].upper(), source.suffix
            )
            upload = await self.comfy.upload(source, f"h3_{run.id}_identity_{index}{suffix}")
            references.append(
                {
                    **reference,
                    "filename": upload["filename"],
                    "upload": upload,
                    "has_audio": False,
                }
            )
        return references

    async def _prepare_v2v(self, run: Run, request: ContinueRequest) -> list[dict]:
        references = []
        frame = contained(self.store.directory(run.id), "initial_frame.png")
        frame_info = await self.media.prepare_last_frame(
            self.video_path(run.parent_id), frame
        )
        if Path(frame_info["path"]).resolve() != frame.resolve() or not frame.is_file():
            raise ValueError("Last frame preparation returned an unexpected path")
        upload = await self.comfy.upload(frame, f"h3_{run.id}_initial_frame.png")
        references.append({
            "type": "image", "role": "initial_frame",
            "source": f"runs/{run.id}/initial_frame.png", "source_root": "runs",
            "parent_id": run.parent_id,
            "sha256": await asyncio.to_thread(
                lambda: hashlib.sha256(frame.read_bytes()).hexdigest()
            ),
            "filename": upload["filename"], "upload": upload,
            "has_audio": False, "input_info": frame_info,
        })
        for index, reference in enumerate(run.references):
            assets = contained(self.settings.project_root, "assets", must_exist=True)
            source = contained(assets, reference["source"], must_exist=True)
            digest = await asyncio.to_thread(
                lambda p=source: hashlib.sha256(p.read_bytes()).hexdigest()
            )
            if digest != reference["sha256"]:
                raise ValueError("Identity image changed after admission")
            suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(
                reference["input_info"]["format"].upper(), source.suffix
            )
            upload = await self.comfy.upload(source, f"h3_{run.id}_identity_{index}{suffix}")
            references.append(
                {
                    **reference,
                    "filename": upload["filename"],
                    "upload": upload,
                    "has_audio": False,
                }
            )
        tail = contained(self.store.directory(run.id), "reference_tail.mp4")
        tail_info = await self.media.prepare_tail(
            self.video_path(run.parent_id),
            tail,
            request.reference_tail_seconds,
            include_audio=request.include_audio,
            reference_frame_limit=self.frames_for_duration(run.duration_seconds),
        )
        if Path(tail_info["path"]).resolve() != tail.resolve() or not tail.is_file():
            raise ValueError("Tail preparation returned an unexpected path")
        upload = await self.comfy.upload(tail, f"h3_{run.id}_tail.mp4")
        references.append(
            {
                "type": "video", "role": "motion_video",
                "source": f"runs/{run.id}/reference_tail.mp4",
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

    async def _execute_i2v(self, run: Run):
        start = monotonic()
        stop = asyncio.Event()
        telemetry_task = None
        guard_task = None
        interruption = {"reason": "Backend shutdown; own prompt cancellation requested"}
        owner = asyncio.current_task()
        try:
            self.store.update(run.id, state="running")
            references = await self._prepare_i2v(run)
            self.store.update(run.id, references=references)
            workflow = self.builder.build(
                operation="i2v",
                prompt=run.prompt,
                seed=run.seed,
                duration_seconds=run.duration_seconds,
                references=references,
                filename_prefix=f"h3_backend/{run.id}/chunk",
            )
            workflow_path = self.store.artifact_json(run.id, "workflow_api.json", workflow)
            # Hash persisted bytes: Store serialization is the execution artifact contract.
            workflow_sha256 = await asyncio.to_thread(
                lambda: hashlib.sha256(workflow_path.read_bytes()).hexdigest()
            )
            self.store.artifact_markdown(run.id, run.prompt)
            current = self.store.get(run.id)
            self.store.update(
                run.id,
                input_info={
                    **current.input_info,
                    "workflow_api_sha256": workflow_sha256,
                    "workflow_api": f"runs/{run.id}/workflow_api.json",
                    "prompt_markdown": f"runs/{run.id}/prompt.md",
                    "telemetry": f"runs/{run.id}/telemetry.jsonl",
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
            telemetry_task = asyncio.create_task(self._record_telemetry(run.id, stop))
            guard_task = asyncio.create_task(self._memory_guard(stop, owner, interruption))

            async def submitted(prompt_id):
                self.store.update(run.id, prompt_id=prompt_id)

            async def progress(data):
                self.store.update(run.id, progress=data)

            result = await self.comfy.execute(
                workflow,
                prompt_id=str(uuid4()),
                deadline=self.settings.inference_deadline,
                on_submitted=submitted,
                on_progress=progress,
                extra_pnginfo=getattr(self.builder, "extra_pnginfo", {}),
            )
            source = output_source(result, self.settings.comfy_root)
            info = await self.media.probe(source)
            verify_video(info, self.frames_for_duration(run.duration_seconds))
            destination = contained(self.store.directory(run.id), "chunk.mp4")
            await asyncio.to_thread(publish, source, destination)
            self.store.update(
                run.id,
                state="ready_for_review",
                publication_mode="atomic_copy_from_comfy_output",
                output={
                    "path": f"runs/{run.id}/chunk.mp4",
                    "probe": info,
                    "source": str(source),
                    "node": "34",
                },
                timings={"total_seconds": monotonic() - start},
            )
        except asyncio.CancelledError:
            self.store.update(run.id, state="interrupted", error=interruption["reason"])
            raise
        except Exception as exc:  # noqa: BLE001 - persist all worker/plugin failures at this boundary.
            self.store.update(
                run.id,
                state="interrupted" if isinstance(exc, ExecutionInterrupted) else "failed",
                error=f"{type(exc).__name__}: {exc}",
                timings={"total_seconds": monotonic() - start},
            )
        finally:
            stop.set()
            if guard_task:
                guard_task.cancel()
                await asyncio.gather(guard_task, return_exceptions=True)
            if telemetry_task:
                # The recorder receives stop; bounded cleanup also tolerates a broken stats endpoint.
                try:
                    await asyncio.wait_for(telemetry_task, timeout=10)
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - bounded plugin cleanup.
                    logging.getLogger(__name__).warning(
                        "Telemetry cleanup failed for run %s: %s", run.id, exc
                    )
                    telemetry_task.cancel()
                    await asyncio.gather(telemetry_task, return_exceptions=True)
            self._active = None

    async def _execute_v2v(self, run: Run, request: ContinueRequest):
        start = monotonic()
        stop = asyncio.Event()
        telemetry_task = None
        guard_task = None
        interruption = {"reason": "Backend shutdown; own prompt cancellation requested"}
        owner = asyncio.current_task()
        try:
            self.store.update(run.id, state="running")
            references = await self._prepare_v2v(run, request)
            self.store.update(run.id, references=references)
            workflow = self.builder.build(
                operation="v2v",
                prompt=run.prompt,
                seed=run.seed,
                duration_seconds=run.duration_seconds,
                references=references,
                filename_prefix=f"h3_backend/{run.id}/chunk",
            )
            workflow_path = self.store.artifact_json(run.id, "workflow_api.json", workflow)
            # Hash persisted bytes: Store serialization is the execution artifact contract.
            workflow_sha256 = await asyncio.to_thread(
                lambda: hashlib.sha256(workflow_path.read_bytes()).hexdigest()
            )
            self.store.artifact_markdown(run.id, run.prompt)
            current = self.store.get(run.id)
            self.store.update(
                run.id,
                input_info={
                    **current.input_info,
                    "workflow_api_sha256": workflow_sha256,
                    "workflow_api": f"runs/{run.id}/workflow_api.json",
                    "prompt_markdown": f"runs/{run.id}/prompt.md",
                    "telemetry": f"runs/{run.id}/telemetry.jsonl",
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
            telemetry_task = asyncio.create_task(self._record_telemetry(run.id, stop))
            guard_task = asyncio.create_task(self._memory_guard(stop, owner, interruption))

            async def submitted(prompt_id):
                self.store.update(run.id, prompt_id=prompt_id)

            async def progress(data):
                self.store.update(run.id, progress=data)

            result = await self.comfy.execute(
                workflow,
                prompt_id=str(uuid4()),
                deadline=self.settings.inference_deadline,
                on_submitted=submitted,
                on_progress=progress,
                extra_pnginfo=getattr(self.builder, "extra_pnginfo", {}),
            )
            source = output_source(result, self.settings.comfy_root)
            info = await self.media.probe(source)
            verify_video(info, self.frames_for_duration(run.duration_seconds))
            destination = contained(self.store.directory(run.id), "chunk.mp4")
            await asyncio.to_thread(publish, source, destination)
            self.store.update(
                run.id,
                state="ready_for_review",
                publication_mode="atomic_copy_from_comfy_output",
                output={
                    "path": f"runs/{run.id}/chunk.mp4",
                    "probe": info,
                    "source": str(source),
                    "node": "34",
                },
                timings={"total_seconds": monotonic() - start},
            )
        except asyncio.CancelledError:
            self.store.update(run.id, state="interrupted", error=interruption["reason"])
            raise
        except Exception as exc:  # noqa: BLE001 - persist all worker/plugin failures at this boundary.
            self.store.update(
                run.id,
                state="interrupted" if isinstance(exc, ExecutionInterrupted) else "failed",
                error=f"{type(exc).__name__}: {exc}",
                timings={"total_seconds": monotonic() - start},
            )
        finally:
            stop.set()
            if guard_task:
                guard_task.cancel()
                await asyncio.gather(guard_task, return_exceptions=True)
            if telemetry_task:
                # The recorder receives stop; bounded cleanup also tolerates a broken stats endpoint.
                try:
                    await asyncio.wait_for(telemetry_task, timeout=10)
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - bounded plugin cleanup.
                    logging.getLogger(__name__).warning(
                        "Telemetry cleanup failed for run %s: %s", run.id, exc
                    )
                    telemetry_task.cancel()
                    await asyncio.gather(telemetry_task, return_exceptions=True)
            self._active = None

    async def _memory_guard(self, stop, owner, interruption):
        while not stop.is_set():
            if self.memory_available() < self.settings.minimum_available_bytes:
                interruption["reason"] = (
                    "Available host RAM dropped below 1.5 GiB; own prompt cancellation requested"
                )
                # Cancelling execute invokes only /api/jobs/<our UUID>/cancel, never /interrupt.
                owner.cancel()
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.settings.memory_check_interval)
            except TimeoutError:
                pass

    async def _record_telemetry(self, run_id, stop):
        try:
            await self.telemetry(
                self.comfy,
                contained(self.store.directory(run_id), "telemetry.jsonl"),
                stop,
                comfy_pid=self.settings.comfy_pid,
            )
        except Exception as exc:  # noqa: BLE001 - expose any recorder failure as a diagnostic artifact.
            error = f"{type(exc).__name__}: {exc}"
            self.store.artifact_json(
                run_id, "telemetry_error.json", {"error": error, "at": timestamp()}
            )
            run = self.store.get(run_id)
            if run.state in {"queued", "running", "ready_for_review"}:
                self.store.update(run_id, input_info={**run.input_info, "telemetry_error": error})
