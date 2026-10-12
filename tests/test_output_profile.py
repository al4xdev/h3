"""CPU-only contracts for the exact preview projection; no real API or GPU jobs."""

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from h3_backend.generation.dispatcher import RunService
from h3_backend.generation.models import Settings
from h3_backend.generation.workflow import PREVIEW_NODES, WorkflowBuilder

ROOT = Path(__file__).resolve().parents[1]
CRITICAL = ("171:4", "171:3", "171:2", "171:1", "22:6", "22:7", "542", "125:12")


def graph_for(builder, operation):
    refs = [{"type": "image", "filename": "h3/identity.png [input]", "role": "identity"}]
    if operation == "v2v":
        refs.insert(0, {"type": "image", "filename": "h3/anchor.png [input]", "role": "initial_frame"})
        refs.append({"type": "video", "filename": "h3/tail.mp4 [input]", "role": "motion_video", "has_audio": True})
    return builder.build(
        operation=operation, prompt="# Literal\n\nDance, jump and turn.  \n", seed=2026101205,
        duration_seconds=2.3, references=refs, filename_prefix="h3_backend/profile-test/chunk",
    )


def closure(graph, root="34"):
    visited = set()

    def visit(node_id):
        if node_id in visited:
            return
        visited.add(node_id)
        for value in graph[node_id]["inputs"].values():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], str) and value[0] in graph
                    and isinstance(value[1], int)):
                visit(value[0])

    visit(root)
    return {key: graph[key] for key in visited}


@pytest.mark.parametrize("operation,native_count,final_count,ancestors", [
    ("i2v", 75, 72, 41), ("v2v", 78, 75, 44),
])
def test_exact_projection_golden_and_final_ancestry(operation, native_count, final_count, ancestors):
    baseline = WorkflowBuilder(ROOT)
    selected = WorkflowBuilder(ROOT, output_profile="final_only")
    native = baseline.baseline_for(operation)
    golden = json.loads((ROOT / "workflows" / (
        "normal_api.json" if operation == "i2v" else "continuation_api.json"
    )).read_text())
    assert native == golden == selected.baseline_for(operation)
    effective = selected.effective_baseline_for(operation)
    assert len(native) == native_count and len(effective) == final_count
    assert native.keys() - effective.keys() == set(PREVIEW_NODES)
    assert effective == {key: value for key, value in native.items() if key not in PREVIEW_NODES}
    assert closure(native) == closure(effective)
    assert len(closure(effective)) == ancestors
    assert effective["259"]["inputs"]["samples"] == ["125:12", 1]
    assert effective["258"]["inputs"]["samples"] == ["125:12", 1]
    for node in CRITICAL:
        assert native[node] == effective[node]
    old_graph = graph_for(baseline, operation)
    new_graph = graph_for(selected, operation)
    assert new_graph == {key: value for key, value in old_graph.items() if key not in PREVIEW_NODES}
    assert closure(old_graph) == closure(new_graph)
    assert new_graph["365"]["inputs"]["prompt"] == "# Literal\n\nDance, jump and turn.  \n"
    if operation == "v2v":
        assert new_graph["272"]["inputs"]["frame_idx"] == 0
        assert new_graph["125:14"]["inputs"]["conditioning"] == ["272", 0]
        assert json.loads(new_graph["416"]["inputs"]["media_state"])[-1]["audio_mode"] == "paired"
    else:
        assert new_graph["125:14"]["inputs"]["conditioning"] == ["471", 0]


@pytest.mark.parametrize("profile", ["baseline", "final_only"])
@pytest.mark.parametrize("operation", ["i2v", "v2v"])
def test_projection_and_provenance_are_fresh_and_unaliased(profile, operation):
    builder = WorkflowBuilder(ROOT, output_profile=profile)
    before = builder.baseline_for(operation)
    effective = builder.effective_baseline_for(operation)
    first = graph_for(builder, operation)
    second = graph_for(builder, operation)
    assert first == second and first is not second
    first["259"]["inputs"]["samples"][1] = 0
    effective["171:4"]["inputs"]["unet_name"] = "changed"
    assert builder.baseline_for(operation) == before
    assert graph_for(builder, operation) == second
    assert builder.effective_baseline_for(operation)["171:4"] == before["171:4"]
    provenance = builder.provenance(operation)
    assert provenance["output_profile"] == profile
    assert provenance["removed_preview_nodes"] == (list(PREVIEW_NODES) if profile == "final_only" else [])
    assert provenance["effective_baseline_hash"] == builder.payload_hash(builder.effective_baseline_for(operation))
    assert provenance["workflow_hash"] == WorkflowBuilder(ROOT).hash_for(operation)
    assert provenance["canonical_template_hash"] == WorkflowBuilder(ROOT).canonical_template_hash
    assert builder.payload_hash(second) != provenance["effective_baseline_hash"]
    with pytest.raises(AttributeError):
        builder.output_profile = "baseline"


@pytest.mark.parametrize("profile", ["baseline", "final_only"])
@pytest.mark.parametrize("operation", ["i2v", "v2v"])
@pytest.mark.parametrize("mutation", ["extra", "remove", "other_profile", "decode", "metadata", "input"])
def test_strict_guards_reject_graph_or_profile_conflicts(profile, operation, mutation):
    builder = WorkflowBuilder(ROOT, output_profile=profile)
    graph = graph_for(builder, operation)
    if mutation == "extra":
        graph["extra"] = copy.deepcopy(graph["259"])
    elif mutation == "remove":
        del graph["259"]
    elif mutation == "other_profile":
        other = "final_only" if profile == "baseline" else "baseline"
        graph = graph_for(WorkflowBuilder(ROOT, output_profile=other), operation)
    elif mutation == "decode":
        graph["259"]["inputs"]["samples"] = ["125:12", 0]
    elif mutation == "metadata":
        graph["259"]["class_type"] = "OtherDecode"
    else:
        graph["259"]["inputs"]["unexpected"] = 1
    with pytest.raises(ValueError):
        builder.verify_changes(graph, operation)


@pytest.mark.parametrize("node_id", CRITICAL)
def test_final_only_keeps_all_critical_input_guards(node_id):
    builder = WorkflowBuilder(ROOT, output_profile="final_only")
    graph = graph_for(builder, "i2v")
    field = next(iter(graph[node_id]["inputs"]))
    graph[node_id]["inputs"][field] = "forbidden mutation"
    with pytest.raises(ValueError, match="Frozen input"):
        builder.verify_changes(graph, "i2v")


def object_info(graph):
    info = {node["class_type"]: {"input": {"required": {}}} for node in graph.values()}
    for node_id, field in (
        ("171:4", "unet_name"), ("171:3", "clip_name"), ("171:2", "vae_name"),
        ("171:1", "vae_name"), ("22:6", "sampler_name"), ("22:7", "scheduler"),
        ("18", "format"), ("34", "format"),
    ):
        if node_id not in graph:
            continue
        node = graph[node_id]
        choices = info[node["class_type"]]["input"]["required"].setdefault(field, [[]])[0]
        if node["inputs"][field] not in choices:
            choices.append(node["inputs"][field])
    return info


@pytest.mark.parametrize("operation", ["i2v", "v2v"])
@pytest.mark.parametrize("profile", ["baseline", "final_only"])
def test_selected_object_info_preserves_model_and_final_format_guards(operation, profile):
    builder = WorkflowBuilder(ROOT, output_profile=profile)
    graph = builder.effective_baseline_for(operation)
    info = object_info(graph)
    builder.validate_object_info(info, operation)
    model_class = graph["171:4"]["class_type"]
    info[model_class]["input"]["required"]["unet_name"][0] = []
    with pytest.raises(ValueError, match="Selected model"):
        builder.validate_object_info(info, operation)
    info = object_info(graph)
    info[graph["34"]["class_type"]]["input"]["required"]["format"][0] = []
    with pytest.raises(ValueError, match="Unavailable workflow option"):
        builder.validate_object_info(info, operation)


@pytest.mark.parametrize("invalid", ["", "Final_only", "unknown", None, True])
def test_unknown_profiles_fail_before_dispatch_or_submission(monkeypatch, invalid):
    with pytest.raises(ValueError, match="output profile"):
        WorkflowBuilder(ROOT, output_profile=invalid)
    with pytest.raises(ValueError, match="output profile"):
        Settings(workflow_output_profile=invalid)
    if isinstance(invalid, str):
        monkeypatch.setenv("H3_WORKFLOW_OUTPUT_PROFILE", invalid)
        with pytest.raises(ValueError, match="output profile"):
            Settings.from_env()


@pytest.mark.parametrize("profile", ["baseline", "final_only"])
def test_env_dispatcher_wires_profile_without_io_or_inference(monkeypatch, profile):
    monkeypatch.setenv("H3_WORKFLOW_OUTPUT_PROFILE", profile)
    settings = Settings.from_env()
    assert settings.workflow_output_profile == profile
    assert settings.minimum_available_bytes == 1536 * 1024**2
    assert settings.memory_check_interval == 5.0
    with pytest.raises(FrozenInstanceError):
        settings.workflow_output_profile = "baseline"
    service = RunService(
        settings, store=object(), comfy=object(), media=object(), telemetry=object(),
        memory_available=lambda: 2 * 1024**3,
    )
    assert service.builder.output_profile == profile
    assert len(graph_for(service.builder, "i2v")) == (75 if profile == "baseline" else 72)
    assert service._task is None and service._active is None


def test_baseline_settings_default_remains_compatible(monkeypatch):
    monkeypatch.delenv("H3_WORKFLOW_OUTPUT_PROFILE", raising=False)
    assert Settings().workflow_output_profile == Settings.from_env().workflow_output_profile == "baseline"
