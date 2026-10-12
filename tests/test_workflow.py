import copy
import json
from pathlib import Path

import pytest

from h3_backend.workflow import WorkflowBuilder, frames_for_duration

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
    for name in ("normal_api.json", "baseline_manifest.json"):
        (destination / name).write_bytes((ROOT / "workflows" / name).read_bytes())
    with (destination / "normal_api.json").open("a") as output:
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


def test_validates_models_without_fallback():
    builder = WorkflowBuilder(ROOT)
    info = {node["class_type"]: {"input": {"required": {}}} for node in builder.baseline.values()}
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
        node = builder.baseline[node_id]
        schema = info[node["class_type"]]["input"]["required"]
        choices = schema.setdefault(field, [[]])[0]
        if node["inputs"][field] not in choices:
            choices.append(node["inputs"][field])
    builder.validate_object_info(info)
    info["UNETLoader"]["input"]["required"]["unet_name"][0] = []
    with pytest.raises(ValueError, match="Selected model"):
        builder.validate_object_info(info)
