"""Explicit, external three-chunk benchmark; importing this file never starts a job."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "dance_reference.png"


@dataclass(frozen=True)
class Stage:
    operation: str
    seed: int
    prompt: str

    def request(self) -> dict:
        common = {"seed": self.seed, "prompt": self.prompt, "duration_seconds": 2.3}
        if self.operation == "i2v":
            return {**common, "image": REFERENCE}
        return {**common, "reference_tail_seconds": 3, "include_audio": True}


STAGES = (
    Stage("i2v", 2026101205, """# Scene — gentle dance, original black dress

## Reference
- <Picture 1> is the ORIGINAL identity and appearance reference, wearing a BLACK dress.

## Action and ending
The fully clothed adult woman performs a gentle, coordinated, non-sexual dance with small side steps and natural arm and hand movements. Keep her original BLACK dress throughout this first clip. Preserve her face, hair, visible anatomy, body proportions, realistic hands and joints.

## Camera and sound
Stable camera, unchanged framing and geometric wall. Quiet room ambience, no dialogue. No clothing removal, no red scene filter, no changes to the reference photograph.
"""),
    Stage("v2v", 2026101206, """# Scene — controlled jump, black-to-red dress, end facing away

## Native references
- <Picture 1> is the exact last decoded frame of the approved parent. Start from this pose and its BLACK dress, anchored at frame zero.
- <Picture 2> is the ORIGINAL identity and facial appearance reference in a BLACK dress. It is not a new starting pose and must not prevent the requested clothing-color change.
- <Video 1> is the recent parent motion context, with paired audio when available.

## Action and required ending
The fully clothed adult woman continues naturally, performs one small controlled jump, and lands with realistic anatomy and balance. During THIS clip, change only her dress color from BLACK to RED while keeping its shape and coverage. Turn her body smoothly away from the camera. END this clip with her BACK facing the camera and her dress RED, so the next clip starts from a back-facing red-dress pose. Do not finish facing the camera. Preserve her identity, hair, body proportions, hands and joints. No nudity or clothing removal; the scene itself is not tinted red.

## Camera and sound
Stable camera, unchanged framing and geometric wall. Quiet room ambience, no dialogue.
"""),
    Stage("v2v", 2026101207, """# Scene — start facing away, turn to front, recover original face

## Native references
- <Picture 1> is the exact last decoded frame of the approved parent. Begin BACK-FACING in its RED dress, anchored at frame zero. Do not reset the pose to the identity photograph.
- <Picture 2> is the ORIGINAL identity and face reference, still in its original BLACK dress. Recover this woman's facial appearance when she turns to face the camera, but do NOT restore the black dress.
- <Video 1> is the recent parent motion context, with paired audio when available.

## Action and required ending
Starting with her back to the camera, the fully clothed adult woman turns smoothly to face FRONT. Reveal her original face clearly toward the end of the clip so it can be compared visually with the original photograph. Keep her dress RED throughout. Preserve identity, hair, clothing coverage, body proportions, visible anatomy, realistic hands and joints. Do not start front-facing or merely look over the shoulder; turn the body from back to front. No nudity, no scene-wide red filter.

## Camera and sound
Stable camera, unchanged framing and geometric wall. Quiet room ambience, no dialogue.
"""),
)


class BenchmarkError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise BenchmarkError(f"Expected a regular file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def canonical_id(value) -> str:
    try:
        result = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BenchmarkError("Invalid run/prompt UUID") from exc
    if result != value:
        raise BenchmarkError("Noncanonical run/prompt UUID")
    return result


def check_probe(details: dict, frames: int) -> dict:
    videos = [s for s in details.get("streams", []) if s.get("codec_type") == "video"]
    if len(videos) != 1:
        raise BenchmarkError("Expected exactly one video stream")
    video = videos[0]
    try:
        valid = (
            (video["width"], video["height"]) == (480, 864)
            and Fraction(video["avg_frame_rate"]) == 24
            and int(video["nb_read_frames"]) == frames
            and abs(float(video["duration"]) - frames / 24) < 0.0001
        )
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise BenchmarkError("Malformed media probe") from exc
    if not valid:
        raise BenchmarkError("Video geometry, frame count, FPS or duration changed")
    return video


def check_audio(details: dict, *, duration: float | None = None) -> None:
    audio = [s for s in details.get("streams", []) if s.get("codec_type") == "audio"]
    if len(audio) != 1 or audio[0].get("codec_name") != "aac" or (
        str(audio[0].get("sample_rate")) != "32000" or audio[0].get("channels") != 2
    ):
        raise BenchmarkError("Baseline AAC stereo32kHz audio is missing or changed")
    if duration is not None:
        try:
            actual = float(audio[0]["duration"])
        except (KeyError, ValueError, TypeError) as exc:
            raise BenchmarkError("Malformed assembly audio duration") from exc
        if not math.isfinite(actual) or abs(actual - duration) > 0.05:
            raise BenchmarkError("Assembly audio does not reach the full padded video boundary")


def summarize_telemetry(path: Path) -> dict:
    result = {"path": str(path), "sample_interval_seconds": 5, "sampled_not_exact_peaks": True,
              "io_counters": None, "io_limitation": "Existing backend telemetry has no IO counters"}
    if not path.is_file() or path.is_symlink():
        return {**result, "available": False, "reason": "Telemetry file unavailable"}
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (ValueError, OSError) as exc:
        return {**result, "available": False, "reason": f"{type(exc).__name__}: {exc}"}

    malformed_samples = sum(not isinstance(row, dict) for row in rows)
    rows = [row for row in rows if isinstance(row, dict)]
    malformed_devices = sum(not isinstance(row.get("devices", []), list) for row in rows)

    def extrema(section, key, mode=max):
        values = [row.get(section, {}).get(key) for row in rows
                  if isinstance(row.get(section), dict)]
        values = [v for v in values if isinstance(v, (int, float))
                  and not isinstance(v, bool) and math.isfinite(v)]
        return mode(values) if values else None

    device_usage = [device["vram_total"] - device["vram_free"] for row in rows
                    for device in (row.get("devices", []) if isinstance(row.get("devices", []), list) else [])
                    if isinstance(device, dict) and isinstance(device.get("vram_total"), int)
                    and isinstance(device.get("vram_free"), int)]
    return {**result, "available": bool(rows), "samples": len(rows),
            "malformed_samples_ignored": malformed_samples,
            "malformed_device_rows_ignored": malformed_devices,
            "min_host_available_bytes": extrema("host", "available_bytes", min),
            "max_host_total_minus_available_bytes": extrema("host", "total_minus_available_bytes"),
            "max_host_swap_used_bytes": extrema("host", "swap_used_bytes"),
            "max_comfy_rss_bytes": extrema("comfyui", "rss_bytes"),
            "max_comfy_swap_bytes": extrema("comfyui", "swap_bytes"),
            "max_backend_rss_bytes": extrema("backend", "rss_bytes"),
            "max_global_vram_used_bytes": max(device_usage) if device_usage else None}


async def media_probe(path: Path) -> dict:
    # Lazy imports keep CLI parsing/composition independent of core resource loading.
    from h3_backend.infrastructure.media import probe
    return await probe(path)


async def assemble(chunks: list[Path], destination: Path) -> dict:
    from h3_backend.infrastructure.media import concatenate
    return await concatenate(chunks, destination)


async def verify_anchor(parent: Path, anchor: Path) -> None:
    from PIL import Image
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", str(parent), "-map", "0:v:0",
        "-vf", "select=eq(n\\,55),format=rgb24,setsar=0", "-fps_mode", "passthrough",
        "-frames:v", "1", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        pixels, error = await process.communicate()
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise BenchmarkError(f"Anchor decode failed: {error.decode(errors='replace')}")
    with Image.open(anchor) as image:
        if image.mode != "RGB" or image.size != (480, 864) or image.tobytes() != pixels:
            raise BenchmarkError("Anchor differs from independently decoded parent frame55")


class BenchmarkPipe:
    """One explicit sequential benchmark; technical acceptance never leaks into the API."""

    def __init__(self, api_url: str, output_dir: Path, *, technical_acceptance: bool,
                 project_root: Path = PROJECT_ROOT, http=None, probe=None, assembler=None,
                 anchor_verifier=None):
        self.api_url = api_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.project_root = Path(project_root)
        self.technical_acceptance = technical_acceptance
        self.http = http
        self.probe = probe or media_probe
        self.assembler = assembler or assemble
        self.anchor_verifier = anchor_verifier or verify_anchor
        self.state = {}

    def _configure(self):
        if self.technical_acceptance is not True:
            raise BenchmarkError("--technical-acceptance is required before any submission")
        parsed = urlsplit(self.api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or (
            parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise BenchmarkError("API URL must be an HTTP(S) base URL without credentials/query")
        self.root = self.project_root.resolve(strict=True)
        dumps = self.root / ".dumps"
        base = dumps / "benchmarks"
        original = self.output_dir if self.output_dir.is_absolute() else self.root / self.output_dir
        self.output = original.resolve()
        if dumps.is_symlink() or base.is_symlink() or original.is_symlink() or (
            not self.output.is_relative_to(base.resolve()) or self.output == base.resolve()
        ):
            raise BenchmarkError("Output directory must be contained below .dumps/benchmarks/")
        if self.output.exists():
            raise BenchmarkError("Output directory already exists; inspect ledger, never replay it")
        self.reference_hash = sha256(self.root / "assets" / REFERENCE)
        self.golden = json.loads((self.root / "workflows/continuation_api.json").read_text())
        self.expected_hashes = {
            "i2v": json.loads((self.root / "workflows/baseline_manifest.json").read_text())["api_sha256"],
            "v2v": json.loads((self.root / "workflows/continuation_manifest.json").read_text())["api_sha256"],
        }
        scenario = {"version": 1, "name": "black_dance_red_jump_back_to_front",
                    "reference": REFERENCE, "reference_sha256": self.reference_hash,
                    "frames_per_chunk": 56, "fps": 24, "width": 480, "height": 864,
                    "requests": [stage.request() for stage in STAGES]}
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(exist_ok=False)
        self.ledger = self.output / "report.json"
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root,
                             capture_output=True, text=True, check=False)
        self.state = {"phase": "configured", "scenario": scenario,
                      "scenario_sha256": json_hash(scenario),
                      "source_commit": git.stdout.strip() if git.returncode == 0 else None,
                      "api_url": self.api_url, "steps": [],
                      "technical_acceptance": {"explicit_opt_in": True,
                                               "scope": "first_two_new_benchmark_parents_only",
                                               "artistic_approval": False},
                      "cache_policy": "Unchanged; warm/cold unknown; no cache/model controls",
                      "measurement_limits": "5s sampled telemetry, not exact peaks; no SSD offload inference",
                      "visual_review": "pending: second ends back/red; third reveals original face/red"}
        self._save()

    def _save(self):
        # Only the freshly reserved benchmark directory is owned by this invocation.
        fd, temporary = tempfile.mkstemp(prefix=".report-", dir=self.output)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            assert Path(temporary).resolve().parent == self.output.resolve()
            assert self.ledger.resolve().parent == self.output.resolve()
            os.replace(temporary, self.ledger)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()

    def _file(self, relative: str, expected: Path) -> Path:
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise BenchmarkError("Artifact path must be relative and contained")
        candidate = self.root / relative
        if candidate.is_symlink():
            raise BenchmarkError("Artifact must not be a symlink")
        path = candidate.resolve()
        if path != expected.resolve() or not path.is_relative_to(self.root):
            raise BenchmarkError("Artifact is not the run's own expected path")
        sha256(path)
        return path

    async def _verify(self, run: dict, stage: Stage, parent: dict | None) -> dict:
        run_id = canonical_id(run.get("id"))
        prompt_id = canonical_id(run.get("prompt_id"))
        if run.get("state") != "ready_for_review" or run.get("error") or run.get("decision"):
            raise BenchmarkError(f"Run is not a successful undecided output: {run.get('error')}")
        if run.get("seed") != stage.seed or run.get("prompt") != stage.prompt or (
            run.get("duration_seconds") != 2.3 or run.get("parent_id") != (
                parent["id"] if parent else None
            )
        ):
            raise BenchmarkError("Returned request/lineage differs from frozen benchmark")
        directory = self.root / "runs" / run_id
        video = self._file(run["output"]["path"], directory / "chunk.mp4")
        details = await self.probe(video)
        check_probe(details, 56)
        check_audio(details)
        if run.get("workflow_hash") != self.expected_hashes[stage.operation]:
            raise BenchmarkError("Operation golden workflow hash changed")
        payload = self._file(run["input_info"]["workflow_api"], directory / "workflow_api.json")
        payload_sha = sha256(payload)
        if payload_sha != run["input_info"]["workflow_api_sha256"]:
            raise BenchmarkError("Persisted workflow checksum mismatch")
        graph = json.loads(payload.read_text())
        if graph["365"]["inputs"]["prompt"] != stage.prompt or (
            graph["16"]["inputs"]["seed"] != stage.seed
        ) or graph["22:23"]["inputs"]["value"] != 2.3:
            raise BenchmarkError("Workflow literal prompt/seed/duration mismatch")
        conditioning = ["471", 0] if parent is None else ["272", 0]
        if graph["125:14"]["inputs"]["conditioning"] != conditioning:
            raise BenchmarkError("Native operation conditioning mismatch")
        if run["input_info"]["workflow_provenance"]["operation"] != stage.operation:
            raise BenchmarkError("Operation provenance mismatch")
        # Preview pruning may change node count, never these shared generation settings.
        for node_id in ("171:4", "171:3", "171:2", "171:1", "22:6", "22:7", "542", "125:12"):
            if graph.get(node_id) != self.golden.get(node_id) or node_id not in graph:
                raise BenchmarkError(f"Frozen model/sampler/sigma setting changed: {node_id}")
        refs = run["references"]
        expected_roles = ["identity"] if parent is None else ["initial_frame", "identity", "motion_video"]
        if [item["role"] for item in refs] != expected_roles:
            raise BenchmarkError("Native reference roles/order changed")
        identity = refs[0] if parent is None else refs[1]
        if identity.get("source") != REFERENCE or identity.get("source_root") != "assets" or (
            identity.get("sha256") != self.reference_hash
            or sha256(self.root / "assets" / REFERENCE) != self.reference_hash
        ):
            raise BenchmarkError("Original identity photograph changed")
        if parent:
            anchor, _, motion = refs
            if anchor["parent_id"] != parent["id"] or motion["parent_id"] != parent["id"]:
                raise BenchmarkError("Reference parent mismatch")
            info = anchor["input_info"]
            if info["source_frame_count"] != 56 or info["source_frame_index"] != 55:
                raise BenchmarkError("Anchor is not parent final frame55")
            anchor_path = self._file(anchor["source"], directory / "initial_frame.png")
            if sha256(anchor_path) != anchor["sha256"]:
                raise BenchmarkError("Anchor checksum mismatch")
            await self.anchor_verifier(self.root / parent["output"]["path"], anchor_path)
            tail_path = self._file(motion["source"], directory / "reference_tail.mp4")
            tail = motion["input_info"]
            if sha256(tail_path) != motion["sha256"] or (
                tail["requested_seconds"] != 3 or abs(tail["actual_seconds"] - 56 / 24) > 0.0001
                or tail["loaded_reference_frames"] != 56 or tail["effective_reference_frames"] != 56
                or tail["final_edge_loss_frames"] != 0
            ):
                raise BenchmarkError("Tail contract/checksum changed")
            parent_audio = any(s.get("codec_type") == "audio" for s in parent["output"]["probe"]["streams"])
            if motion.get("has_audio") is not parent_audio:
                raise BenchmarkError("Paired-audio reference differs from parent")
            if graph["272"]["inputs"]["frame_idx"] != 0:
                raise BenchmarkError("Native anchor is not guide frame zero")
            if [item["tag"] for item in run["input_info"]["slot_map"]] != [
                "<Picture 1>", "<Picture 2>", "<Video 1>"
            ]:
                raise BenchmarkError("Native picture/video slots changed")
        return {"run_id": run_id, "prompt_id": prompt_id, "video": str(video),
                "sha256": sha256(video), "probe": details, "payload_sha256": payload_sha,
                "workflow_nodes": len(graph), "preview_nodes_present": [
                    node_id for node_id in ("18", "176", "177") if node_id in graph
                ], "workflow_hash": run["workflow_hash"],
                "workflow_provenance": run["input_info"]["workflow_provenance"],
                "backend_timings": run.get("timings", {}),
                "telemetry": summarize_telemetry(directory / "telemetry.jsonl"),
                "native_anchor_exact": parent is not None}

    async def arun(self) -> dict:
        self._configure()
        started = monotonic()
        own_http = self.http is None
        client = self.http or httpx.AsyncClient(base_url=self.api_url, timeout=30)
        parent, chunks, ids, prompts = None, [], [], set()
        try:
            for index, stage in enumerate(STAGES):
                step = {"index": index + 1, "request": stage.request(), "operation": stage.operation,
                        "phase": "admission_in_progress", "post_attempted": True}
                self.state["steps"].append(step)
                self.state["phase"] = f"chunk_{index + 1}_admission_in_progress"
                self._save()  # An ambiguous response must never make another POST safe.
                endpoint = "/runs/i2v" if parent is None else f"/runs/{parent['id']}/v2v"
                stage_started = monotonic()
                response = await client.post(endpoint, json=step["request"])
                step["admission_http_status"] = response.status_code
                if response.status_code != 202:
                    step["response_error"] = response.text
                    raise BenchmarkError(f"Admission refused: HTTP{response.status_code}")
                admitted = response.json()
                step["admission"] = admitted
                self._save()
                run_id = canonical_id(admitted.get("id"))
                if run_id in ids or admitted.get("parent_id") != (parent["id"] if parent else None):
                    raise BenchmarkError("Admission ID/parent mismatch")
                ids.append(run_id)
                step["phase"] = "waiting_on_own_prompt"
                self.state["phase"] = f"chunk_{index + 1}_waiting_on_own_prompt"
                self._save()
                print(f"ADMITTED chunk{index + 1} {stage.operation}: {run_id}", flush=True)
                response = await client.get(f"/runs/{run_id}", params={"wait": "true"}, timeout=1300)
                response.raise_for_status()
                run = response.json()
                step["result"] = run
                self._save()
                if run.get("id") != run_id:
                    raise BenchmarkError("Long-wait returned a different run")
                verification = await self._verify(run, stage, parent)
                if verification["prompt_id"] in prompts:
                    raise BenchmarkError("Prompt UUID reused across benchmark chunks")
                prompts.add(verification["prompt_id"])
                step["verification"] = verification
                step["end_to_end_seconds"] = monotonic() - stage_started
                step["phase"] = "technically_verified"
                chunks.append(Path(verification["video"]))
                self._save()
                if index < 2:
                    step["phase"] = "technical_acceptance_in_progress"
                    step["acceptance_reason"] = "Explicit benchmark opt-in; not artistic approval"
                    self._save()
                    response = await client.post(f"/runs/{run_id}/accept")
                    response.raise_for_status()
                    accepted = response.json()
                    if accepted.get("id") != run_id or accepted.get("state") != "accepted" or (
                        accepted.get("decision", {}).get("accepted") is not True
                    ):
                        raise BenchmarkError("Technical acceptance was not persisted for own parent")
                    mutable_review_fields = {"state", "decision", "updated_at"}
                    if {k: v for k, v in accepted.items() if k not in mutable_review_fields} != {
                        k: v for k, v in run.items() if k not in mutable_review_fields
                    }:
                        raise BenchmarkError("Acceptance changed verified parent artifacts/request")
                    step["technical_acceptance"] = accepted
                    parent = {**run, "state": "accepted", "decision": accepted["decision"]}
                step["phase"] = "complete"
                self._save()
            response = await client.get(f"/runs/{ids[-1]}/sequence")
            response.raise_for_status()
            sequence = response.json()
            if sequence.get("root_id") != ids[0] or sequence.get("end_run_id") != ids[-1] or (
                [block["id"] for block in sequence.get("blocks", [])] != ids
            ):
                raise BenchmarkError("Sequence does not describe exactly the three benchmark runs")
            if [block["state"] for block in sequence["blocks"]] != ["accepted", "accepted", "ready_for_review"]:
                raise BenchmarkError("Sequence approval states changed")
            self.state["sequence"] = sequence
            self.state["phase"] = "assembling_external_preview"
            self._save()
            assembly_started = monotonic()
            destination = self.output / "benchmark.mp4"
            result = await self.assembler(chunks, destination)
            if result.get("assembly") != "external_concat_no_overlap_trim_no_crossfade":
                raise BenchmarkError("Assembly must preserve full chunks without hidden seam editing")
            details = await self.probe(destination)
            check_probe(details, 168)
            check_audio(details, duration=7.0)
            self.state["assembly"] = {"path": str(destination), "sha256": sha256(destination),
                                      "probe": details, "mechanism": result["assembly"],
                                      "frames": 168, "seam_frames": [56, 112],
                                      "seam_seconds": [56 / 24, 112 / 24],
                                      "seconds": monotonic() - assembly_started}
            self.state["end_to_end_seconds"] = monotonic() - started
            self.state["phase"] = "complete_pending_visual_review"
            self._save()
            print(f"BENCHMARK READY: {destination}", flush=True)
            return self.state
        except BaseException as exc:
            self.state["failure"] = {"type": type(exc).__name__, "message": str(exc),
                                     "phase": self.state["phase"],
                                     "recovery": "Inspect known IDs/ledger; never repeat admission blindly"}
            self.state["phase"] = "failed_no_automatic_replay"
            self._save()
            raise
        finally:
            if own_http:
                await client.aclose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--technical-acceptance", action="store_true")
    args = parser.parse_args(argv)
    if not args.technical_acceptance:
        parser.error("--technical-acceptance is required; only benchmark parents are auto-accepted")
    try:
        asyncio.run(BenchmarkPipe(args.api_url, args.output_dir,
                                  technical_acceptance=True).arun())
    except (BenchmarkError, httpx.HTTPError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Benchmark stopped: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
