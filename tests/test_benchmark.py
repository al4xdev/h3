import asyncio
import copy
import importlib.util
import json
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools/benchmark_h3.py"
SPEC = importlib.util.spec_from_file_location("benchmark_h3", TOOL_PATH)
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def media_probe(frames=56, audio=True):
    result = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 480,
                           "height": 864, "avg_frame_rate": "24/1", "nb_read_frames": str(frames),
                           "duration": str(frames / 24)}]}
    if audio:
        result["streams"].append({"codec_type": "audio", "codec_name": "aac",
                                  "sample_rate": "32000", "channels": 2,
                                  "duration": "7.000" if frames == 168 else "2.304"})
    return result


@pytest.fixture
def root(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/dance_reference.png").write_bytes(b"original-black-dress-photo")
    (tmp_path / "workflows").mkdir()
    core = {node_id: {"class_type": "FrozenCore", "inputs": {"frozen": node_id}}
            for node_id in ("171:4", "171:3", "171:2", "171:1", "22:6", "22:7", "542", "125:12")}
    (tmp_path / "workflows/continuation_api.json").write_text(json.dumps(core))
    (tmp_path / "workflows/baseline_manifest.json").write_text(json.dumps({"api_sha256": "golden-i2v"}))
    (tmp_path / "workflows/continuation_manifest.json").write_text(json.dumps({"api_sha256": "golden-v2v"}))
    return tmp_path


class FakeAPI:
    def __init__(self, root, mutate=None, failure=None):
        self.root, self.mutate, self.failure = root, mutate, failure
        self.calls, self.runs, self.requests, self.anchor_calls, self.concat_calls = [], {}, [], [], []

    def make_run(self, request, parent_id):
        index = len(self.requests)
        run_id = f"00000000-0000-0000-0000-{index:012d}"
        prompt_id = f"10000000-0000-0000-0000-{index:012d}"
        directory = self.root / ".data" / "runs" / run_id
        directory.mkdir(parents=True)
        (directory / "chunk.mp4").write_bytes(f"video{index}".encode())
        graph = json.loads((self.root / "workflows/continuation_api.json").read_text())
        graph.update({"365": {"inputs": {"prompt": request["prompt"]}},
                      "16": {"inputs": {"seed": request["seed"]}},
                      "22:23": {"inputs": {"value": 2.3}},
                      "125:14": {"inputs": {"conditioning": ["272", 0] if parent_id else ["471", 0]}},
                      "18": {}, "176": {}, "177": {}})
        identity = {"role": "identity", "source": "dance_reference.png", "source_root": "assets",
                    "sha256": benchmark.sha256(self.root / "assets/dance_reference.png")}
        references = [identity]
        if parent_id:
            graph["272"] = {"inputs": {"frame_idx": 0}}
            (directory / "initial_frame.png").write_bytes(b"parent-final-frame")
            (directory / "reference_tail.mp4").write_bytes(b"paired-audio-tail")
            references = [
                {"role": "initial_frame", "parent_id": parent_id,
                 "source": f".data/runs/{run_id}/initial_frame.png",
                 "sha256": benchmark.sha256(directory / "initial_frame.png"),
                 "input_info": {"source_frame_count": 56, "source_frame_index": 55}},
                identity,
                {"role": "motion_video", "parent_id": parent_id, "has_audio": True,
                 "source": f".data/runs/{run_id}/reference_tail.mp4",
                 "sha256": benchmark.sha256(directory / "reference_tail.mp4"),
                 "input_info": {"requested_seconds": 3, "actual_seconds": 56 / 24,
                                "loaded_reference_frames": 56, "effective_reference_frames": 56,
                                "final_edge_loss_frames": 0}},
            ]
        (directory / "workflow_api.json").write_text(json.dumps(graph))
        (directory / "telemetry.jsonl").write_text(json.dumps({
            "host": {"available_bytes": 100, "total_minus_available_bytes": 900,
                     "swap_used_bytes": 5}, "comfyui": {"rss_bytes": 800, "swap_bytes": 2},
            "backend": {"rss_bytes": 20}, "devices": [{"vram_total": 1000, "vram_free": 100}],
        }) + "\n")
        run = {"id": run_id, "prompt_id": prompt_id, "parent_id": parent_id,
               "seed": request["seed"], "prompt": request["prompt"], "duration_seconds": 2.3,
               "state": "ready_for_review", "error": None, "decision": None,
               "references": references, "workflow_hash": "golden-v2v" if parent_id else "golden-i2v",
               "input_info": {"workflow_api": f".data/runs/{run_id}/workflow_api.json",
                              "workflow_api_sha256": benchmark.sha256(directory / "workflow_api.json"),
                              "workflow_provenance": {"operation": "v2v" if parent_id else "i2v"},
                              "slot_map": [{"tag": tag} for tag in ("<Picture 1>", "<Picture 2>", "<Video 1>")]},
               "output": {"path": f".data/runs/{run_id}/chunk.mp4", "probe": media_probe()},
               "timings": {"total_seconds": 0.5, "prepare_seconds": 0.1}}
        self.runs[run_id] = run
        return run

    def handler(self, request):
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "POST" and (path == "/runs/i2v" or path.endswith("/v2v")):
            if self.failure == "ambiguous_post":
                raise httpx.ReadTimeout("uncertain submission", request=request)
            if self.failure == "refused":
                return httpx.Response(409, json={"detail": "RAM guard"})
            body = json.loads(request.content)
            self.requests.append(body)
            parent = None if path == "/runs/i2v" else path.split("/")[2]
            run = self.make_run(body, parent)
            return httpx.Response(202, json={"id": run["id"], "parent_id": parent})
        if path.endswith("/accept"):
            run = self.runs[path.split("/")[2]]
            if self.failure == "accept_error":
                return httpx.Response(409, json={"detail": "conflict"})
            run["state"] = "accepted"
            run["decision"] = {"accepted": True}
            if self.failure == "accept_wrong_id":
                return httpx.Response(200, json={**run, "id": str(UUID(int=777))})
            return httpx.Response(200, json=run)
        if path.endswith("/sequence"):
            blocks = [{"id": run["id"], "state": run["state"]} for run in self.runs.values()]
            if self.failure == "sequence":
                blocks.reverse()
            return httpx.Response(200, json={"root_id": blocks[0]["id"],
                                             "end_run_id": blocks[-1]["id"], "blocks": blocks})
        assert request.method == "GET" and request.url.params["wait"] == "true"
        if self.failure == "wait_timeout":
            raise httpx.ReadTimeout("wait timed out", request=request)
        if self.failure == "cancel":
            raise asyncio.CancelledError
        run = copy.deepcopy(self.runs[path.split("/")[2]])
        if self.mutate:
            self.mutate(run, self)
        return httpx.Response(200, json=run)

    async def probe(self, path):
        return media_probe(168 if path.name == "benchmark.mp4" else 56)

    async def anchor(self, parent, anchor):
        self.anchor_calls.append((parent, anchor))

    async def assemble(self, chunks, destination):
        self.concat_calls.append(list(chunks))
        destination.write_bytes(b"full-chunk-assembly")
        return {"assembly": "external_concat_no_overlap_trim_no_crossfade"}

    def pipe(self, client, **kwargs):
        return benchmark.BenchmarkPipe("http://fake", Path(".dumps/benchmarks/frozen"),
                                       technical_acceptance=True, project_root=self.root, http=client,
                                       probe=self.probe, assembler=self.assemble,
                                       anchor_verifier=self.anchor, **kwargs)


@pytest.mark.asyncio
async def test_three_stage_benchmark_exact_calls_and_full_assembly(root):
    api = FakeAPI(root)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        result = await api.pipe(client).arun()
    ids = list(api.runs)
    assert api.calls == [
        ("POST", "/runs/i2v"), ("GET", f"/runs/{ids[0]}"), ("POST", f"/runs/{ids[0]}/accept"),
        ("POST", f"/runs/{ids[0]}/v2v"), ("GET", f"/runs/{ids[1]}"), ("POST", f"/runs/{ids[1]}/accept"),
        ("POST", f"/runs/{ids[1]}/v2v"), ("GET", f"/runs/{ids[2]}"), ("GET", f"/runs/{ids[2]}/sequence"),
    ]
    assert [request["seed"] for request in api.requests] == [2026101205, 2026101206, 2026101207]
    assert result["phase"] == "complete_pending_visual_review"
    assert result["assembly"]["frames"] == 168
    assert result["assembly"]["seam_frames"] == [56, 112]
    assert result["assembly"]["seam_seconds"] == [56 / 24, 112 / 24]
    assert result["technical_acceptance"]["artistic_approval"] is False
    assert result["steps"][2].get("technical_acceptance") is None
    assert len(api.concat_calls) == 1 and len(api.concat_calls[0]) == 3
    assert len(api.anchor_calls) == 2
    assert result["steps"][0]["verification"]["telemetry"]["min_host_available_bytes"] == 100
    assert result["steps"][0]["verification"]["telemetry"]["max_global_vram_used_bytes"] == 900
    assert result["steps"][0]["verification"]["telemetry"]["io_counters"] is None
    ledger = json.loads((root / ".dumps/benchmarks/frozen/report.json").read_text())
    assert ledger["scenario_sha256"] == benchmark.json_hash(ledger["scenario"])
    assert [step["post_attempted"] for step in ledger["steps"]] == [True, True, True]
    assert len(ledger["sequence"]["blocks"]) == 3


def test_scenario_is_frozen_and_middle_changes_only_dress():
    first, second, third = benchmark.STAGES
    assert first.operation == "i2v" and second.operation == third.operation == "v2v"
    assert "BLACK dress throughout" in first.prompt
    assert "During THIS clip" in second.prompt and "from BLACK to RED" in second.prompt
    assert "END this clip with her BACK facing" in second.prompt
    assert "Begin BACK-FACING in its RED dress" in third.prompt
    assert "turn the body from back to front" in third.prompt
    assert "do NOT restore the black dress" in third.prompt
    assert "original face clearly" in third.prompt
    for stage in benchmark.STAGES:
        assert stage.prompt.startswith("# Scene") and "fully clothed adult woman" in stage.prompt
        request = stage.request()
        assert request["duration_seconds"] == 2.3
        request["seed"] = 0
        assert stage.request()["seed"] != 0
    assert "<Picture 2>" not in first.prompt
    assert all(tag in second.prompt and tag in third.prompt for tag in ("<Picture 1>", "<Picture 2>", "<Video 1>"))


def test_import_has_no_core_resource_network_or_execution_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Import attempted execution/I/O")
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(benchmark.subprocess, "run", forbidden)
    spec = importlib.util.spec_from_file_location("benchmark_import_only", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert len(module.STAGES) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("output", ["outside", ".dumps/benchmarks", ".dumps/../outside"])
async def test_output_path_guard_before_any_network(root, output):
    api = FakeAPI(root)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        pipe = api.pipe(client)
        pipe.output_dir = Path(output)
        with pytest.raises(benchmark.BenchmarkError, match="contained"):
            await pipe.arun()
    assert api.calls == []


@pytest.mark.asyncio
async def test_symlink_output_escape_guard(root, tmp_path):
    (root / ".dumps/benchmarks").mkdir(parents=True)
    (root / ".dumps/benchmarks/escape").symlink_to(tmp_path.parent, target_is_directory=True)
    pipe = benchmark.BenchmarkPipe("http://fake", Path(".dumps/benchmarks/escape/new"),
                                   technical_acceptance=True, project_root=root)
    with pytest.raises(benchmark.BenchmarkError, match="contained"):
        await pipe.arun()


@pytest.mark.asyncio
async def test_optin_before_files_or_network(root):
    pipe = benchmark.BenchmarkPipe("http://fake", Path(".dumps/benchmarks/new"),
                                   technical_acceptance=False, project_root=root)
    with pytest.raises(benchmark.BenchmarkError, match="technical-acceptance"):
        await pipe.arun()
    assert not (root / ".dumps").exists()


@pytest.mark.parametrize("url", ["ftp://fake", "http://user:pass@fake", "http://fake?x=y", "http://fake#secret", "not-a-url"])
@pytest.mark.asyncio
async def test_url_guard(root, url):
    pipe = benchmark.BenchmarkPipe(url, Path(".dumps/benchmarks/new"),
                                   technical_acceptance=True, project_root=root)
    with pytest.raises(benchmark.BenchmarkError, match="API URL"):
        await pipe.arun()
    assert not (root / ".dumps").exists()


def test_cli_requires_explicit_technical_acceptance_before_io(root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CLI attempted execution")
    monkeypatch.setattr(benchmark.BenchmarkPipe, "arun", forbidden)
    with pytest.raises(SystemExit) as raised:
        benchmark.main(["--api-url", "http://fake", "--output-dir", ".dumps/benchmarks/cli"])
    assert raised.value.code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["ambiguous_post", "refused", "wait_timeout", "cancel", "accept_error", "accept_wrong_id"])
async def test_failure_does_not_advance_or_allow_replay(root, failure):
    api = FakeAPI(root, failure=failure)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        with pytest.raises((benchmark.BenchmarkError, httpx.HTTPError, asyncio.CancelledError)):
            await api.pipe(client).arun()
        calls_before = list(api.calls)
        with pytest.raises(benchmark.BenchmarkError, match="already exists"):
            await api.pipe(client).arun()
    assert api.calls == calls_before
    assert sum(method == "POST" and (path.endswith("/v2v") or path == "/runs/i2v") for method, path in api.calls) == 1
    assert api.concat_calls == []
    ledger = json.loads((root / ".dumps/benchmarks/frozen/report.json").read_text())
    assert ledger["phase"] == "failed_no_automatic_replay"
    assert ledger["steps"][0]["post_attempted"] is True
    assert "never repeat" in ledger["failure"]["recovery"]


@pytest.mark.asyncio
async def test_intent_is_persisted_before_post(root):
    api = FakeAPI(root)
    original_handler = api.handler
    def handler(request):
        if request.method == "POST" and request.url.path == "/runs/i2v":
            ledger = json.loads((root / ".dumps/benchmarks/frozen/report.json").read_text())
            assert ledger["phase"] == "chunk_1_admission_in_progress"
            assert ledger["steps"][0]["post_attempted"] is True
            raise httpx.ReadTimeout("ambiguous", request=request)
        return original_handler(request)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await api.pipe(client).arun()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["failed", "wrong_id", "wrong_seed", "wrong_prompt", "wrong_duration", "hash", "foreign_video", "identity", "role", "operation", "golden", "sampler"])
async def test_invalid_first_output_never_accepted_or_continued(root, kind):
    def mutate(run, api):
        if kind == "failed":
            run["state"], run["error"] = "failed", "worker failure"
        elif kind == "wrong_id":
            run["id"] = str(UUID(int=555))
        elif kind == "wrong_seed":
            run["seed"] = 42
        elif kind == "wrong_prompt":
            run["prompt"] = "truncated"
        elif kind == "wrong_duration":
            run["duration_seconds"] = 3
        elif kind == "hash":
            run["input_info"]["workflow_api_sha256"] = "bad"
        elif kind == "foreign_video":
            run["output"]["path"] = "assets/dance_reference.png"
        elif kind == "identity":
            run["references"][0]["sha256"] = "recolored"
        elif kind == "role":
            run["references"][0]["role"] = "initial_frame"
        elif kind == "operation":
            run["input_info"]["workflow_provenance"]["operation"] = "v2v"
        elif kind == "golden":
            run["workflow_hash"] = "new-baseline"
        elif kind == "sampler":
            payload = api.root / run["input_info"]["workflow_api"]
            graph = json.loads(payload.read_text())
            graph["22:6"]["inputs"]["frozen"] = "changed"
            payload.write_text(json.dumps(graph))
            run["input_info"]["workflow_api_sha256"] = benchmark.sha256(payload)
    api = FakeAPI(root, mutate=mutate)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        with pytest.raises(benchmark.BenchmarkError):
            await api.pipe(client).arun()
    assert len(api.requests) == 1 and not any(path.endswith("/accept") for _, path in api.calls)
    assert api.concat_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["anchor_index", "anchor_hash", "tail", "tail_hash", "guide", "parent", "slots", "audio", "prompt_reuse"])
async def test_invalid_second_output_stops_before_third(root, kind):
    def mutate(run, api):
        if len(api.requests) != 2:
            return
        if kind == "anchor_index":
            run["references"][0]["input_info"]["source_frame_index"] = 54
        elif kind == "anchor_hash":
            run["references"][0]["sha256"] = "bad"
        elif kind == "tail":
            run["references"][2]["input_info"]["effective_reference_frames"] = 55
        elif kind == "tail_hash":
            run["references"][2]["sha256"] = "bad"
        elif kind == "guide":
            payload = api.root / run["input_info"]["workflow_api"]
            graph = json.loads(payload.read_text())
            graph["272"]["inputs"]["frame_idx"] = 1
            payload.write_text(json.dumps(graph))
            run["input_info"]["workflow_api_sha256"] = benchmark.sha256(payload)
        elif kind == "parent":
            run["parent_id"] = str(UUID(int=777))
        elif kind == "slots":
            run["input_info"]["slot_map"] = []
        elif kind == "audio":
            run["references"][2]["has_audio"] = False
        elif kind == "prompt_reuse":
            run["prompt_id"] = next(iter(api.runs.values()))["prompt_id"]
    api = FakeAPI(root, mutate=mutate)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        with pytest.raises(benchmark.BenchmarkError):
            await api.pipe(client).arun()
    assert len(api.requests) == 2
    assert sum(path.endswith("/accept") for _, path in api.calls) == 1
    assert api.concat_calls == []


@pytest.mark.asyncio
async def test_sequence_mismatch_prevents_concat(root):
    api = FakeAPI(root, failure="sequence")
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        with pytest.raises(benchmark.BenchmarkError, match="Sequence"):
            await api.pipe(client).arun()
    assert len(api.requests) == 3 and api.concat_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [55, 167])
async def test_probe_frame_count_prevents_success(root, frames):
    api = FakeAPI(root)
    async def probe(path):
        return media_probe(frames if (path.name == "benchmark.mp4") == (frames == 167) else 56)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        pipe = api.pipe(client)
        pipe.probe = probe
        with pytest.raises(benchmark.BenchmarkError, match="frame count"):
            await pipe.arun()
    ledger = json.loads((root / ".dumps/benchmarks/frozen/report.json").read_text())
    assert ledger["phase"] == "failed_no_automatic_replay"


@pytest.mark.asyncio
async def test_removed_preview_node_count_is_not_a_quality_assertion(root):
    def mutate(run, api):
        payload = api.root / run["input_info"]["workflow_api"]
        graph = json.loads(payload.read_text())
        for node_id in ("18", "176", "177"):
            graph.pop(node_id)
        payload.write_text(json.dumps(graph))
        run["input_info"]["workflow_api_sha256"] = benchmark.sha256(payload)
        # Mirror the persisted manifest: accepting a run may not change its payload hash.
        api.runs[run["id"]]["input_info"]["workflow_api_sha256"] = benchmark.sha256(payload)
    api = FakeAPI(root, mutate=mutate)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        result = await api.pipe(client).arun()
    assert result["phase"] == "complete_pending_visual_review"
    assert result["steps"][0]["verification"]["preview_nodes_present"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["seed", "references", "output"])
async def test_acceptance_cannot_replace_verified_parent_data(root, field):
    api = FakeAPI(root)
    original = api.handler
    def handler(request):
        response = original(request)
        if request.url.path.endswith("/accept"):
            accepted = response.json()
            accepted[field] = 42 if field == "seed" else {} if field == "output" else []
            return httpx.Response(200, json=accepted)
        return response
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(benchmark.BenchmarkError, match="Acceptance changed"):
            await api.pipe(client).arun()
    assert len(api.requests) == 1 and api.concat_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "short", "wrong_format"])
async def test_assembly_audio_loss_prevents_success(root, kind):
    api = FakeAPI(root)
    async def probe(path):
        details = media_probe(168 if path.name == "benchmark.mp4" else 56)
        if path.name == "benchmark.mp4":
            if kind == "missing":
                details["streams"].pop()
            elif kind == "short":
                details["streams"][1]["duration"] = "6.0"
            else:
                details["streams"][1]["sample_rate"] = "16000"
        return details
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        pipe = api.pipe(client)
        pipe.probe = probe
        with pytest.raises(benchmark.BenchmarkError):
            await pipe.arun()
    assert len(api.requests) == 3


@pytest.mark.asyncio
async def test_finished_benchmark_is_not_replayed(root):
    api = FakeAPI(root)
    async with httpx.AsyncClient(base_url="http://fake", transport=httpx.MockTransport(api.handler)) as client:
        await api.pipe(client).arun()
        calls = list(api.calls)
        with pytest.raises(benchmark.BenchmarkError, match="already exists"):
            await api.pipe(client).arun()
    assert api.calls == calls


def test_telemetry_malformed_samples_are_best_effort(tmp_path):
    path = tmp_path / "telemetry"
    samples = [None, "not-a-sample", {"devices": None}, {"devices": "invalid"},
               {"host": {"available_bytes": 10}, "devices": [None, "invalid"]}]
    path.write_text("\n".join(json.dumps(sample) for sample in samples))
    result = benchmark.summarize_telemetry(path)
    assert result["available"] is True and result["samples"] == 3
    assert result["malformed_samples_ignored"] == 2
    assert result["malformed_device_rows_ignored"] == 2
    assert result["min_host_available_bytes"] == 10
    assert result["max_global_vram_used_bytes"] is None


def test_telemetry_missing_and_partial_are_explicit(tmp_path):
    assert benchmark.summarize_telemetry(tmp_path / "missing")["available"] is False
    path = tmp_path / "telemetry"
    path.write_text("invalid-json")
    assert benchmark.summarize_telemetry(path)["available"] is False
    path.write_text(json.dumps({"host": {"available_bytes": 100}, "comfyui": None}) + "\n")
    result = benchmark.summarize_telemetry(path)
    assert result["min_host_available_bytes"] == 100
    assert result["max_comfy_rss_bytes"] is None and result["max_global_vram_used_bytes"] is None
    assert result["io_counters"] is None
