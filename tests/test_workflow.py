import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path

import pytest

from h3_backend.workflow import I2V_CONFIG, V2V_CONFIG, WorkflowBuilder, frames_for_duration

ROOT = Path(__file__).resolve().parents[1]


def reference(kind="image", **extra):
    return {"type": kind, "filename": "h3/test.png [input]", **extra}


def build(builder, **overrides):
    arguments = {
        "prompt": "A gentle dance using <Picture 1>.",
        "seed": 42,
        "duration_seconds": 2.3,
        "references": [reference()],
        "filename_prefix": "h3_backend/run-1/chunk",
    }
    return builder.build(**(arguments | overrides))


def test_duration_preserves_original_rounding_with_strict_cap():
    assert frames_for_duration(2.3) == 56
    assert frames_for_duration(56 / 24) == 56
    assert frames_for_duration(0.1) == 5
    for seconds in (0, -1, 3, 8, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            frames_for_duration(seconds)


def test_only_whitelisted_fields_change_and_virtual_links_survive():
    builder = WorkflowBuilder(ROOT)
    original = copy.deepcopy(builder.baseline)
    graph = build(builder)
    assert len(graph) == 75
    assert builder.baseline == original
    assert graph["125:12"]["inputs"]["sampler"] == ["22:6", 0]
    assert graph["259"]["inputs"]["vae"] == ["171:2", 0]
    assert graph["16"]["inputs"]["seed"] == 42
    assert graph["22:23"]["inputs"]["value"] == 2.3
    assert graph["18"]["inputs"]["save_output"] is False
    assert "176" in graph and "259" in graph
    assert "296" not in graph and "368" not in graph
    builder.verify_changes(graph)
    graph["22:8"]["inputs"]["value"] = 3
    with pytest.raises(ValueError, match="Frozen input"):
        builder.verify_changes(graph)


def test_video_keeps_pairing_and_identity_image():
    graph = build(
        WorkflowBuilder(ROOT), references=[reference(), reference("video", has_audio=True)]
    )
    state = json.loads(graph["416"]["inputs"]["media_state"])
    assert [entry["kind"] for entry in state] == ["picture", "video"]
    assert state[1]["audio_mode"] == "paired"
    assert state[0]["audio_mode"] == "off"


@pytest.mark.parametrize(
    "filename", ["/tmp/a.png [input]", "../a.png [input]", "a.png [output]", "x\\a.png [input]"]
)
def test_reference_path_safety(filename):
    with pytest.raises(ValueError):
        build(WorkflowBuilder(ROOT), references=[reference(filename=filename)])


@pytest.mark.parametrize(
    "prefix", ["/tmp/chunk", "h3_backend/../chunk", "h3_backend/%date%/chunk", "elsewhere/chunk"]
)
def test_prefix_safety(prefix):
    with pytest.raises(ValueError):
        build(WorkflowBuilder(ROOT), filename_prefix=prefix)


def test_checksum_detects_changed_baseline(tmp_path):
    destination = tmp_path / "workflows"
    destination.mkdir()
    for name in ("continuation_api.json", "continuation_manifest.json", "baseline_manifest.json"):
        (destination / name).write_bytes((ROOT / "workflows" / name).read_bytes())
    with (destination / "continuation_api.json").open("a") as output:
        output.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        WorkflowBuilder(tmp_path)


def test_saver_flags_match_original_ui_envelope():
    builder = WorkflowBuilder(ROOT)
    ui = json.loads((ROOT / "workflows/workflow_h3_normal_sfw_validated.json").read_text())
    flags = builder.extra_pnginfo["workflow"]["extra"]
    assert flags == {key: ui["extra"][key] for key in flags}
    assert flags["VHS_MetadataImage"] is False
    assert flags["VHS_KeepIntermediate"] is False


@pytest.mark.parametrize("operation", ["i2v", "v2v"])
def test_validates_models_without_fallback(operation):
    builder = WorkflowBuilder(ROOT)
    baseline = builder.baseline_for(operation)
    info = {node["class_type"]: {"input": {"required": {}}} for node in baseline.values()}
    for node_id, field in (
        ("171:4", "unet_name"),
        ("171:3", "clip_name"),
        ("171:2", "vae_name"),
        ("171:1", "vae_name"),
        ("22:6", "sampler_name"),
        ("22:7", "scheduler"),
        ("18", "format"),
        ("34", "format"),
    ):
        node = baseline[node_id]
        schema = info[node["class_type"]]["input"]["required"]
        choices = schema.setdefault(field, [[]])[0]
        if node["inputs"][field] not in choices:
            choices.append(node["inputs"][field])
    builder.validate_object_info(info, operation=operation)
    if operation == "i2v":
        assert "MiniMaxH3AddGuide" not in info
        with pytest.raises(ValueError, match="Missing ComfyUI class"):
            builder.validate_object_info(info, operation="v2v")
    else:
        incomplete = {key: value for key, value in info.items() if key != "MiniMaxH3AddGuide"}
        with pytest.raises(ValueError, match="Missing ComfyUI class"):
            builder.validate_object_info(incomplete, operation="v2v")
    info["UNETLoader"]["input"]["required"]["unet_name"][0] = []
    with pytest.raises(ValueError, match="Selected model"):
        builder.validate_object_info(info, operation=operation)


def continuation_references(identities=1):
    return [reference(role="initial_frame", filename="h3/end.png [input]")] + [
        reference(role="identity", filename=f"h3/identity-{index}.png [input]")
        for index in range(identities)
    ] + [reference("video", role="motion_video", filename="h3/tail.mp4 [input]", has_audio=True)]


def test_continuation_native_guide_and_literal_prompt():
    builder = WorkflowBuilder(ROOT, mode="continuation")
    prompt = "# Continue\n\n<Picture 1> starts; <Picture 2> identity.  \n<Video 1> movement.\n"
    graph = build(builder, references=continuation_references(), prompt=prompt)
    assert builder.mode == "continuation"
    assert len(graph) == 78
    assert graph["365"]["inputs"]["prompt"] == prompt
    assert graph["272"]["inputs"] == {
        "frame_idx": 0, "positive": ["471", 0], "latent": ["520", 0],
        "vae": ["171:2", 0], "audio_vae": ["171:1", 0], "image": ["274", 0],
    }
    assert graph["125:14"]["inputs"]["conditioning"] == ["272", 0]
    state = json.loads(graph["416"]["inputs"]["media_state"])
    assert [entry["file"] for entry in state] == [r["filename"] for r in continuation_references()]
    assert state[-1]["audio_mode"] == "paired"
    assert builder.extra_pnginfo == WorkflowBuilder(ROOT).extra_pnginfo
    build(builder, references=continuation_references(8))


@pytest.mark.parametrize("mutation", ["missing", "reorder", "duplicate", "hash_duplicate", "excess", "no_identity", "no_video"])
def test_continuation_rejects_ambiguous_roles(mutation):
    refs = continuation_references()
    if mutation == "missing":
        refs[0].pop("role")
    elif mutation == "reorder":
        refs[0], refs[1] = refs[1], refs[0]
    elif mutation == "duplicate":
        refs[1]["filename"] = refs[0]["filename"]
    elif mutation == "hash_duplicate":
        refs[0]["sha256"] = refs[1]["sha256"] = "a" * 64
    elif mutation == "excess":
        refs = continuation_references(9)
    elif mutation == "no_identity":
        refs.pop(1)
    else:
        refs.pop()
    with pytest.raises(ValueError):
        build(WorkflowBuilder(ROOT, "continuation"), references=refs)


@pytest.mark.parametrize("node,field,value", [
    ("272", "frame_idx", 1), ("272", "vae", ["171:1", 0]),
    ("272", "latent", ["5", 0]), ("274", "image", ["417", 1]),
    ("125:14", "conditioning", ["471", 0]),
    ("418", "pictures.<Picture 2>", ["417", 0]),
])
def test_native_guide_verifier_rejects_broken_ancestry(node, field, value):
    builder = WorkflowBuilder(ROOT, "continuation")
    graph = copy.deepcopy(builder.baseline)
    graph[node]["inputs"][field] = value
    with pytest.raises(ValueError, match="native link"):
        builder._verify_links(graph)


def test_initial_bytes_and_exact_continuation_delta():
    manifest = json.loads((ROOT / "workflows/baseline_manifest.json").read_text())
    assert hashlib.sha256((ROOT / "workflows/normal_api.json").read_bytes()).hexdigest() == manifest["api_sha256"]
    assert hashlib.sha256((ROOT / "workflows" / manifest["source_ui"]).read_bytes()).hexdigest() == manifest["source_ui_sha256"]
    initial = WorkflowBuilder(ROOT).baseline
    continuation = WorkflowBuilder(ROOT, "continuation").baseline
    assert continuation.keys() - initial.keys() == {"272", "274", "276"}
    assert initial.keys() - continuation.keys() == set()
    for node in initial:
        if node != "125:14":
            assert initial[node] == continuation[node]
    ui = json.loads((ROOT / "workflows" / manifest["source_ui"]).read_text())
    new_ui = json.loads((ROOT / "workflows/workflow_h3_continuation_sfw_validated.json").read_text())
    for node in ui["nodes"]:
        if node["id"] in (272, 274, 276):
            assert node["mode"] == 4
            node["mode"] = 0
    assert ui == new_ui


def test_continuation_checksum_and_unknown_mode(tmp_path):
    directory = tmp_path / "workflows"
    directory.mkdir()
    for name in ("continuation_api.json", "continuation_manifest.json"):
        (directory / name).write_bytes((ROOT / "workflows" / name).read_bytes())
    with (directory / "continuation_api.json").open("a") as output:
        output.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        WorkflowBuilder(tmp_path, "continuation")
    with pytest.raises(ValueError, match="mode"):
        WorkflowBuilder(ROOT, "unknown")


@pytest.mark.parametrize("operation,filename", [
    ("i2v", "normal_api.json"), ("v2v", "continuation_api.json"),
])
def test_routed_baseline_is_structurally_identical_to_native_golden(operation, filename):
    builder = WorkflowBuilder(ROOT)
    raw = (ROOT / "workflows" / filename).read_bytes()
    assert builder.baseline_for(operation) == json.loads(raw)
    assert builder.hash_for(operation) == hashlib.sha256(raw).hexdigest()


def test_configs_are_frozen_and_have_an_explicit_field_allowlist():
    expected = {
        "operation", "mode", "conditioning", "guide_helpers", "guide_frame",
        "reference_roles", "max_identities", "max_pictures", "max_videos",
    }
    for config in (I2V_CONFIG, V2V_CONFIG):
        assert is_dataclass(config)
        assert {field.name for field in fields(config)} == expected
        with pytest.raises(FrozenInstanceError):
            config.operation = "other"
        assert isinstance(config.conditioning, tuple)
        assert isinstance(config.guide_helpers, tuple)
        assert isinstance(config.reference_roles, tuple)
    assert V2V_CONFIG.max_identities == 8
    assert V2V_CONFIG.guide_frame == 0
    assert I2V_CONFIG.guide_frame is None


def test_one_instance_dispatches_without_mode_mutation_or_cross_run_leaks():
    builder = WorkflowBuilder(ROOT)
    initial = build(builder)
    continuation = build(builder, operation="v2v", references=continuation_references(8))
    assert len(initial) == 75 and len(continuation) == 78
    assert build(builder, operation="i2v") == initial
    assert builder.mode == "normal"
    continuation["272"]["inputs"]["frame_idx"] = 12
    assert builder.baseline_for("v2v")["272"]["inputs"]["frame_idx"] == 0
    with pytest.raises(ValueError, match="operation"):
        build(builder, operation="")


@pytest.mark.parametrize("role,kind", [
    ("initial_frame", "image"), ("motion_video", "video"), ("identity", "video"),
])
def test_i2v_rejects_explicit_continuation_roles(role, kind):
    with pytest.raises(ValueError, match="identity image roles"):
        build(WorkflowBuilder(ROOT), references=[reference(kind, role=role)])


def test_routing_delta_allowlist_and_no_initial_helper_links():
    builder = WorkflowBuilder(ROOT)
    original = builder.baseline_for("v2v")
    routed = builder.baseline_for("i2v")
    assert original.keys() - routed.keys() == {"272", "274", "276"}
    expected = copy.deepcopy(original)
    for helper in ("272", "274", "276"):
        del expected[helper]
    expected["125:14"]["inputs"]["conditioning"] = ["471", 0]
    assert routed == expected
    for node in routed.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                assert value[0] not in {"272", "274", "276"}
                assert value[0] in routed
    for node, field, value in (
        ("125:14", "conditioning", ["272", 0]),
        ("125:12", "latent_image", ["5", 0]),
    ):
        damaged = copy.deepcopy(routed)
        damaged[node]["inputs"][field] = value
        with pytest.raises(ValueError):
            builder.verify_changes(damaged, "i2v")


def test_only_canonical_graph_is_needed_at_runtime(tmp_path):
    directory = tmp_path / "workflows"
    directory.mkdir()
    for filename in ("continuation_api.json", "continuation_manifest.json", "baseline_manifest.json"):
        (directory / filename).write_bytes((ROOT / "workflows" / filename).read_bytes())
    builder = WorkflowBuilder(tmp_path)
    assert builder.baseline_for("i2v") == WorkflowBuilder(ROOT).baseline
    build(builder, operation="v2v", references=continuation_references())


def test_provenance_distinguishes_canonical_golden_and_execution_hashes():
    builder = WorkflowBuilder(ROOT)
    canonical_hash = hashlib.sha256((ROOT / "workflows/continuation_api.json").read_bytes()).hexdigest()
    for operation in ("i2v", "v2v"):
        provenance = builder.provenance(operation)
        assert provenance["canonical_template_hash"] == canonical_hash
        assert provenance["operation"] == operation
        assert provenance["config"]["operation"] == operation
        assert provenance["workflow_hash"] == builder.hash_for(operation)
        refs = continuation_references() if operation == "v2v" else [reference()]
        graph = build(builder, operation=operation, references=refs)
        expected = hashlib.sha256(json.dumps(
            graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()
        assert builder.payload_hash(graph) == expected
        assert expected != provenance["workflow_hash"]
        assert expected != canonical_hash
        assert builder.payload_hash(build(builder, operation=operation, references=refs, seed=43)) != expected
