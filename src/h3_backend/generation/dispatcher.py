"""Single-job orchestration; accepted clips never trigger automatic continuation."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from fractions import Fraction
from pathlib import Path
from time import monotonic

from ..infrastructure.comfy import ComfyClient, ExecutionInterrupted
from ..infrastructure.store import Store, contained, timestamp
from .models import ContinueRequest, Run, RunRequest, Settings


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
    """One admission lock and worker lifecycle, independent of pipeline business steps."""

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

            builder = WorkflowBuilder(
                settings.project_root, output_profile=settings.workflow_output_profile,
            )
        if frames_for_duration is None:
            from .workflow import frames_for_duration as frames

            frames_for_duration = frames
        if media is None:
            from ..infrastructure import media as media_module

            media = media_module
        if telemetry is None:
            from ..infrastructure.telemetry import record_telemetry

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
        self._cpu_active: str | None = None
        self._cpu_task: asyncio.Task | None = None
        self._closing = False
        self.watcher = None
        self._candidates = asyncio.Queue(maxsize=64)
        self._observer_task: asyncio.Task | None = None

    async def startup(self) -> None:
        from ..infrastructure.watcher import FileWatcher
        from .assembly import restore_interrupted

        self.store.hold_runtime()
        try:
            self.watcher = FileWatcher(self.settings.project_root, on_request=self._request_hint)
            self.watcher.start()
            # Registration precedes restore. Initial scans never submit existing requests.
            self.store.restore()
            restore_interrupted(self.settings.project_root)
            self._observer_task = asyncio.create_task(self._observe_requests(), name="h3-file-hints")
        except Exception:
            if self.watcher:
                self.watcher.close()
            self.store.release_runtime()
            raise

    def _request_hint(self, run_id: str) -> None:
        if self._closing or self._active == run_id:
            return
        try:
            self._candidates.put_nowait((run_id, self._active is not None or self._cpu_active is not None or self._lock.locked()))
        except asyncio.QueueFull:
            self._reject_hint(run_id, "Request hint capacity exceeded; no automatic replay")

    def _reject_hint(self, run_id: str, error: str) -> None:
        try:
            run = self.store.get(run_id)
            if run.state == "queued":
                self.store.update(run_id, state="failed", error=error)
        except (OSError, ValueError):
            logging.getLogger(__name__).warning("Rejected request %s: %s", run_id, error)

    async def _observe_requests(self) -> None:
        while True:
            run_id, busy_at_event = await self._candidates.get()
            try:
                async with self._lock:
                    if busy_at_event:
                        raise Conflict("Global slot was busy when intent arrived; no automatic queue")
                    await self._start_materialized(run_id)
            except (OSError, ValueError) as exc:
                # Only the candidate's live own manifest may receive failure evidence.
                self._reject_hint(run_id, f"{type(exc).__name__}: {exc}")
            finally:
                self._candidates.task_done()

    async def shutdown(self) -> None:
        self._closing = True
        if self.watcher:
            self.watcher.close()
        if self._observer_task:
            self._observer_task.cancel()
            await asyncio.gather(self._observer_task, return_exceptions=True)
        if self._cpu_task and not self._cpu_task.done():
            self._cpu_task.cancel()
            await asyncio.gather(self._cpu_task, return_exceptions=True)
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
        try:
            await self.comfy.close()
        finally:
            self.store.release_runtime()

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
        path = self.store.own_artifact(
            run_id, run.output.get("path", self.store.relative_artifact(run_id, "chunk.mp4")),
            "chunk.mp4",
        )
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    @asynccontextmanager
    async def cpu_slot(self, operation_id: str):
        """One assembly owns the same global budget; this is not another job dispatcher."""
        owner = asyncio.current_task()
        async with self._lock:
            if self._closing or self._active is not None or self._cpu_active is not None:
                raise Conflict("Only one backend job may be active")
            if self.memory_available() < self.settings.minimum_available_bytes:
                raise Conflict("Available host RAM is below 1.5 GiB; no assembly was admitted")
            self._cpu_active, self._cpu_task = operation_id, owner
        stop = asyncio.Event()

        async def guard_ram():
            while not stop.is_set():
                if self.memory_available() < self.settings.minimum_available_bytes:
                    owner.cancel("Available host RAM fell below 1.5 GiB during CPU assembly")
                    return
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.settings.memory_check_interval)
                except TimeoutError:
                    pass

        guard = asyncio.create_task(guard_ram(), name=f"h3-cpu-ram-{operation_id}")
        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(guard, return_exceptions=True)
            async with self._lock:
                if self._cpu_task is owner:
                    self._cpu_active = self._cpu_task = None

    async def decide(self, run_id: str, accepted: bool) -> Run:
        async with self._lock:
            if self._cpu_active is not None:
                raise Conflict("Review is frozen while an assembly owns the global slot")
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
        from .i2v import I2VPipe
        from .workflow import I2V_CONFIG

        return await self.submit(
            I2VPipe(self).have(request).with_workflow(I2V_CONFIG).save_chunk()
        )

    async def continue_run(self, parent_id: str, request: ContinueRequest) -> Run:
        from .v2v import V2VPipe
        from .workflow import V2V_CONFIG

        return await self.submit(
            V2VPipe(self).have(request).from_parent(parent_id)
            .with_last_frame().with_original_identity().with_motion_tail()
            .with_workflow(V2V_CONFIG).save_chunk()
        )

    async def submit(self, pipe) -> Run:
        async with self._lock:
            if pipe.dispatcher is not self:
                raise ValueError("Pipeline belongs to another dispatcher")
            if pipe._sealed or pipe._submitting:
                raise Conflict("Pipeline may only be submitted once")
            if self._closing or self._active is not None or self._cpu_active is not None:
                raise Conflict("Only one backend job may be active")
            if self.memory_available() < self.settings.minimum_available_bytes:
                raise Conflict("Available host RAM is below 1.5 GiB; no job was submitted")
            pipe._submitting = True
            try:
                run = await pipe._admit()
            finally:
                pipe._submitting = False
            # Shutdown must not wait on external admission I/O, so recheck after that await.
            if self._closing:
                self.store.update(
                    run.id,
                    state="interrupted",
                    error="Backend stopped before execution completed",
                )
                raise Conflict("Backend stopped during admission; no job was submitted")
            try:
                await self._start_materialized(run.id)
            except (OSError, ValueError) as exc:
                self.store.update(run.id, state="failed", error=f"{type(exc).__name__}: {exc}")
                raise
            return run

    def _hydrate(self, run: Run):
        # Native verticals remain the only two business routes, not a generic command registry.
        if run.input_info.get("operation") == "i2v":
            from .i2v import I2VPipe

            return I2VPipe.from_run(self, run)
        if run.input_info.get("operation") == "v2v":
            from .v2v import V2VPipe

            pipe = V2VPipe.from_run(self, run)
            parent = self.store.get(run.parent_id)
            identities = [reference for reference in parent.references
                          if reference.get("type") == "image"
                          and reference.get("role") in (None, "identity")]
            keys = ("source", "sha256")
            if (parent.state != "accepted"
                    or [(r.get("source_root", "assets"), *(r.get(k) for k in keys)) for r in identities]
                    != [(r["source_root"], *(r.get(k) for k in keys)) for r in run.references]
                    or any(r.get("role") not in (None, "identity", "initial_frame")
                           for r in parent.references if r.get("type") == "image")):
                raise Conflict("Continuation request no longer matches its accepted original identity")
            return pipe
        raise ValueError("Unsupported materialized operation")

    async def _start_materialized(self, run_id: str) -> bool:
        """Called under the sole admission lock by HTTP's commit kick or filesystem hints."""
        if self._active == run_id:
            return False
        current = self.store.get(run_id)
        if current.state != "queued":
            return False  # Terminal/interrupted records are never replayed, even on duplicate hints.
        if (current.prompt_id is not None or current.progress or current.output or current.timings
                or current.decision is not None or current.error is not None
                or current.publication_mode is not None
                or any(ref.get("role") != "identity" for ref in current.references)):
            raise Conflict("Queued manifest already contains execution evidence; no replay")
        run = self.store.request(run_id)
        self._hydrate(run)
        if self._closing or self._active is not None or self._cpu_active is not None:
            raise Conflict("Only one backend job may be active; request was not queued for replay")
        if self.memory_available() < self.settings.minimum_available_bytes:
            raise Conflict("Available host RAM is below 1.5 GiB; no job was submitted")
        self._active = run_id
        # Registration BEFORE 202 closes the one-GET-wait race. RAM caller pipes are not captured.
        self._task = asyncio.create_task(self._worker(run_id), name=f"h3-{run_id}")
        return True

    async def _worker(self, run_id: str):
        start = monotonic()
        stop = asyncio.Event()
        telemetry_task = None
        guard_task = None
        interruption = {"reason": "Backend shutdown; own prompt cancellation requested"}
        owner = asyncio.current_task()
        try:
            # Re-read after scheduling too: no mutable admission object is execution authority.
            run = self.store.request(run_id)
            pipe = self._hydrate(run)
            self.store.update(run_id, state="running")
            telemetry_task = asyncio.create_task(self._record_telemetry(run.id, stop))
            guard_task = asyncio.create_task(self._memory_guard(stop, owner, interruption))
            # Recheck the external global slot for disk-originated admission as well.
            await self.comfy.ensure_idle()
            await pipe.arun()
        except asyncio.CancelledError:
            self.store.update(run_id, state="interrupted", error=interruption["reason"])
            raise
        except Exception as exc:  # noqa: BLE001 - persist all worker/plugin failures at this boundary.
            self.store.update(
                run_id,
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
                        "Telemetry cleanup failed for run %s: %s", run_id, exc
                    )
                    telemetry_task.cancel()
                    await asyncio.gather(telemetry_task, return_exceptions=True)
            if self._active == run_id:
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
