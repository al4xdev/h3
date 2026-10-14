"""Parametrize the exported graph without rewriting its model or processing branches."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal


@dataclass(frozen=True)
class WorkflowConfig:
    operation: str
    mode: str
    conditioning: tuple[str, int]
    guide_helpers: tuple[str, ...]
    guide_frame: int | None
    reference_roles: tuple[str, ...]
    max_identities: int
    max_pictures: int
    max_videos: int


I2V_CONFIG = WorkflowConfig("i2v", "normal", ("471", 0), (), None, ("identity",), 9, 9, 3)
V2V_CONFIG = WorkflowConfig(
    "v2v", "continuation", ("272", 0), ("272", "274", "276"), 0,
    ("initial_frame", "identity", "motion_video"), 8, 9, 1,
)
BRIDGE_CONFIG = WorkflowConfig(
    "bridge", "bridge", ("bridge:guide", 0), V2V_CONFIG.guide_helpers, 0,
    ("initial_frame", "identity", "target_frame", "motion_video"), 7, 9, 1,
)

OutputProfile = Literal["baseline", "final_only"]
PREVIEW_NODES = ("18", "176", "177")


DEFAULT_DURATION_SECONDS = 8.0
# Operational request budget, not a checkpoint maximum or proof of GPU/RAM safety.
MAX_DURATION_SECONDS = 10.0
DURATION_FPS = 24
FRAME_BASE = 5
FRAME_STRIDE = 17


def _aligned_frames(seconds: float) -> int:
    # Match the frozen graph exactly, including Python's half-even round.
    requested = max(FRAME_BASE, round(seconds * DURATION_FPS))
    return requested + (FRAME_BASE - requested % FRAME_STRIDE) % FRAME_STRIDE


MAX_DURATION_FRAMES = _aligned_frames(MAX_DURATION_SECONDS)


def frames_for_duration(seconds: float) -> int:
    if not math.isfinite(seconds) or not 0 < seconds <= MAX_DURATION_SECONDS:
        raise ValueError("Requested duration must be finite, positive and at most ten seconds")
    frames = _aligned_frames(seconds)
    if frames > MAX_DURATION_FRAMES:
        raise ValueError("Aligned frame count exceeds the operational duration budget")
    return frames


def duration_capabilities() -> dict[str, Any]:
    return {
        "default_requested_seconds": DEFAULT_DURATION_SECONDS,
        "min_requested_seconds": 0, "min_exclusive": True,
        "max_requested_seconds": MAX_DURATION_SECONDS, "input_step": 0.01,
        "fps": DURATION_FPS, "frame_base": FRAME_BASE, "frame_stride": FRAME_STRIDE,
        "rounding": "half_even", "max_frames": MAX_DURATION_FRAMES,
        "max_actual_seconds": MAX_DURATION_FRAMES / DURATION_FPS,
    }


def _media_entry(reference: dict[str, Any]) -> dict[str, Any]:
    kind = reference.get("type")
    if kind not in ("image", "video"):
        raise ValueError("Only image and video references are enabled in this baseline")
    filename = reference.get("filename", "")
    if not isinstance(filename, str) or not filename.endswith(" [input]"):
        raise ValueError("Reference must be an uploaded ComfyUI input file")
    path = PurePosixPath(filename.removesuffix(" [input]"))
    if path.is_absolute() or ".." in path.parts or "\\" in str(path) or not path.name:
        raise ValueError("Unsafe uploaded filename")
    audio = bool(reference.get("has_audio", False)) and kind == "video"
    entry: dict[str, Any] = {
        "kind": "picture" if kind == "image" else "video",
        "file": filename,
        "name": path.name,
        "has_audio": audio,
        "audio_mode": "paired" if audio else "off",
        "enabled": True,
    }
    info = reference.get("input_info", {})
    for key in ("width", "height", "duration"):
        value = reference.get(key, info.get(key))
        if key == "duration" and value is None:
            value = info.get("actual_seconds")
        if value is not None:
            entry[key] = value
    return entry


class WorkflowBuilder:
    def __init__(
        self, project_root: Path, mode: str = "normal", *, output_profile: OutputProfile = "baseline",
    ):
        if output_profile not in ("baseline", "final_only"):
            raise ValueError("Workflow output profile must be baseline or final_only")
        self._output_profile = output_profile
        # Constructor aliases are for old callers; production dispatches per build.
        aliases = {"normal": "i2v", "continuation": "v2v", "i2v": "i2v", "v2v": "v2v",
                   "bridge": "bridge"}
        if mode not in aliases:
            raise ValueError("Workflow mode must be normal, continuation, i2v, v2v or bridge")
        self._default_operation = aliases[mode]
        self.mode = self.config_for(self._default_operation).mode
        directory = project_root / "workflows"
        raw = (directory / "continuation_api.json").read_bytes()
        manifest = json.loads((directory / "continuation_manifest.json").read_text())
        self.canonical_template_hash = hashlib.sha256(raw).hexdigest()
        if self.canonical_template_hash != manifest["api_sha256"]:
            raise ValueError("Frozen workflow checksum mismatch; review the new baseline first")
        self._canonical = json.loads(raw)
        self._manifests = {
            "i2v": json.loads((directory / "baseline_manifest.json").read_text()),
            "v2v": manifest,
        }
        self.allowed_inputs = manifest["allowed_inputs"]
        self.extra_pnginfo = copy.deepcopy(manifest["extra_pnginfo"])
        for operation in ("i2v", "v2v", "bridge"):
            self._verify_links(self.effective_baseline_for(operation), operation)

    @staticmethod
    def config_for(operation: str) -> WorkflowConfig:
        if operation == "i2v":
            return I2V_CONFIG
        if operation == "v2v":
            return V2V_CONFIG
        if operation == "bridge":
            return BRIDGE_CONFIG
        raise ValueError("Workflow operation must be i2v, v2v or bridge")

    def baseline_for(self, operation: str) -> dict[str, Any]:
        config = self.config_for(operation)
        graph = copy.deepcopy(self._canonical)
        # This is the complete routing allowlist, matching the two native exports.
        for node_id in V2V_CONFIG.guide_helpers:
            if node_id not in config.guide_helpers:
                del graph[node_id]
        graph["125:14"]["inputs"]["conditioning"] = list(config.conditioning)
        if operation == "bridge":
            graph["bridge:guide"] = copy.deepcopy(graph["272"])
            graph["bridge:guide"]["inputs"].update(
                frame_idx=-1, positive=["272", 0], image=["bridge:resize", 0],
            )
            graph["bridge:resize"] = copy.deepcopy(graph["274"])
            graph["bridge:resize"]["inputs"]["image"] = ["417", 2]
        return graph

    @property
    def output_profile(self) -> OutputProfile:
        return self._output_profile

    def effective_baseline_for(self, operation: str) -> dict[str, Any]:
        """Project the native operation without changing any surviving node or link."""
        graph = self.baseline_for(operation)
        if self.output_profile == "final_only":
            for node_id in PREVIEW_NODES:
                del graph[node_id]
        return graph

    @property
    def baseline(self) -> dict[str, Any]:
        return self.baseline_for(self._default_operation)

    @property
    def hash(self) -> str:
        return self.hash_for(self._default_operation)

    def hash_for(self, operation: str) -> str:
        self.config_for(operation)
        if operation == "bridge":
            return self.payload_hash(self.baseline_for(operation))
        # Legacy workflow_hash identifies the raw golden export, not a run payload.
        return self._manifests[operation]["api_sha256"]

    def provenance(self, operation: str) -> dict[str, Any]:
        proof = {
            "canonical_template_hash": self.canonical_template_hash,
            "workflow_hash": self.hash_for(operation),
            "operation": operation,
            "config": asdict(self.config_for(operation)),
            "output_profile": self.output_profile,
            "removed_preview_nodes": list(PREVIEW_NODES) if self.output_profile == "final_only" else [],
            "effective_baseline_hash": self.payload_hash(self.effective_baseline_for(operation)),
        }
        if operation == "bridge":
            proof["derived_from_operation"] = "v2v"
            proof["derived_from_workflow_hash"] = self.hash_for("v2v")
            proof["added_nodes"] = ["bridge:guide", "bridge:resize"]
            proof["target_guide_frame"] = -1
        return proof

    @staticmethod
    def payload_hash(graph: dict[str, Any]) -> str:
        raw = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _verify_links(self, graph: dict[str, Any], operation: str | None = None) -> None:
        config = self.config_for(self._default_operation if operation is None else operation)
        for node_id, field, expected in (
            ("5", "vae", ["171:2", 0]),
            ("176", "vae", ["171:2", 0]),
            ("259", "vae", ["171:2", 0]),
            ("125:12", "sampler", ["22:6", 0]),
            ("125:12", "sigmas", ["542", 0]),
        ):
            if node_id == "176" and self.output_profile == "final_only":
                continue
            if graph[node_id]["inputs"].get(field) != expected:
                raise ValueError(f"Missing or changed virtual link {node_id}.{field}")
        if any(node in graph for node in ("279", "296", "368")):
            raise ValueError("This baseline must use normal references, not final/seamless assembly")
        links = [
            ("417", "references", ["416", 0]),
            ("471", "any_02", ["5", 0]),
            ("520", "any_01", ["5", 1]),
            ("125:12", "latent_image", ["520", 0]),
            ("125:12", "guider", ["125:14", 0]),
            ("125:14", "conditioning", list(config.conditioning)),
            ("511", "any_01", ["417", 9]),
            ("510", "any_01", ["417", 12]),
            ("5", "ref_videos.ref_video_0", ["511", 0]),
            ("5", "ref_video_audios.ref_video_audio_0", ["510", 0]),
            ("418", "videos.<Video 1>", ["417", 9]),
        ]
        for index in range(9):
            links.extend([
                ("5", f"ref_images.ref_image_{index}", ["417", index]),
                ("418", f"pictures.<Picture {index + 1}>", ["417", index]),
            ])
        if config.guide_helpers:
            for node_id, class_type in (
                ("272", "MiniMaxH3AddGuide"), ("274", "ImageResizeKJv2"), ("276", "GetImageSize")
            ):
                if graph.get(node_id, {}).get("class_type") != class_type:
                    raise ValueError(f"Missing native guide helper {node_id}")
            links.extend([
                ("272", "frame_idx", config.guide_frame),
                ("272", "positive", ["471", 0]),
                ("272", "latent", ["520", 0]),
                ("272", "vae", ["171:2", 0]),
                ("272", "audio_vae", ["171:1", 0]),
                ("272", "image", ["274", 0]),
                ("274", "image", ["417", 0]),
                ("276", "image", ["417", 0]),
                ("274", "width", ["276", 0]),
                ("274", "height", ["276", 1]),
            ])
        elif any(node in graph for node in ("272", "274", "276")):
            raise ValueError("Initial workflow must not activate first-frame guide")
        if config.operation == "bridge":
            for node_id, native in (("bridge:guide", "272"), ("bridge:resize", "274")):
                if graph.get(node_id, {}).get("class_type") != self._canonical[native]["class_type"]:
                    raise ValueError(f"Missing native bridge helper {node_id}")
            links.extend([
                ("bridge:guide", "frame_idx", -1),
                ("bridge:guide", "positive", ["272", 0]),
                ("bridge:guide", "latent", ["520", 0]),
                ("bridge:guide", "vae", ["171:2", 0]),
                ("bridge:guide", "audio_vae", ["171:1", 0]),
                ("bridge:guide", "image", ["bridge:resize", 0]),
                ("bridge:resize", "width", ["276", 0]),
                ("bridge:resize", "height", ["276", 1]),
            ])
            slot = graph["bridge:resize"]["inputs"].get("image")
            if (not isinstance(slot, list) or len(slot) != 2 or slot[0] != "417"
                    or type(slot[1]) is not int or not 2 <= slot[1] <= 8):
                raise ValueError("Bridge target must use its dedicated native picture slot")
        for node_id, field, expected in links:
            if graph.get(node_id, {}).get("inputs", {}).get(field) != expected:
                raise ValueError(f"Missing or changed native link {node_id}.{field}")

    @staticmethod
    def _verify_continuation_roles(
        references: list[dict[str, Any]], config: WorkflowConfig = V2V_CONFIG,
    ) -> None:
        # The native splitter preserves image order within categories: never silently reorder.
        if not 3 <= len(references) <= config.max_identities + 2:
            raise ValueError("Continuation requires initial_frame, one to eight identities, motion_video")
        initial_role, identity_role, motion_role = config.reference_roles
        expected = [("image", initial_role)]
        expected += [("image", identity_role)] * (len(references) - 2)
        expected += [("video", motion_role)]
        if [(ref.get("type"), ref.get("role")) for ref in references] != expected:
            raise ValueError("Continuation references must be ordered initial_frame, identity, motion_video")
        initial = references[0]
        for identity in references[1:-1]:
            if identity.get("filename") == initial.get("filename") or (
                initial.get("sha256") and identity.get("sha256") == initial["sha256"]
            ):
                raise ValueError("Initial frame must be distinct from identity")

    def build(
        self,
        *,
        prompt: str,
        seed: int,
        duration_seconds: float,
        references: list[dict[str, Any]],
        filename_prefix: str,
        operation: str | None = None,
    ) -> dict[str, Any]:
        operation = self._default_operation if operation is None else operation
        config = self.config_for(operation)
        frames_for_duration(duration_seconds)
        if not prompt.strip() or len(prompt) > 12000:
            raise ValueError("Prompt must contain between 1 and 12000 characters")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**53 - 1:
            raise ValueError("Seed must be an integer between zero and 2**53-1")
        prefix = PurePosixPath(filename_prefix)
        if (
            prefix.is_absolute()
            or ".." in prefix.parts
            or "\\" in filename_prefix
            or not filename_prefix.startswith("h3_backend/")
            or "%" in filename_prefix
        ):
            raise ValueError("Saver prefix must be a safe relative path under h3_backend/")
        if operation == "bridge":
            if not 4 <= len(references) <= config.max_identities + 3:
                raise ValueError("Bridge requires initial frame, one to seven identities, target and motion")
            expected = [("image", "initial_frame")]
            expected += [("image", "identity")] * (len(references) - 3)
            expected += [("image", "target_frame"), ("video", "motion_video")]
            if [(r.get("type"), r.get("role")) for r in references] != expected:
                raise ValueError("Bridge references must be ordered initial, identity, target, motion")
            self._verify_continuation_roles(references[:-2] + references[-1:])
        elif config.guide_helpers:
            self._verify_continuation_roles(references, config)
        elif any(
            ref.get("role") is not None and (
                ref["role"] not in config.reference_roles or ref.get("type") != "image"
            )
            for ref in references
        ):
            # Untyped references remain compatible; explicit continuation roles never leak into i2v.
            raise ValueError("Initial workflow only accepts explicit identity image roles")
        entries = [_media_entry(reference) for reference in references]
        pictures = sum(entry["kind"] == "picture" for entry in entries)
        videos = sum(entry["kind"] == "video" for entry in entries)
        if not 1 <= pictures <= config.max_pictures or videos > config.max_videos:
            raise ValueError("Supply one to nine identity images and at most three videos")
        graph = self.effective_baseline_for(operation)
        graph["365"]["inputs"]["prompt"] = prompt
        graph["16"]["inputs"]["seed"] = seed
        graph["22:23"]["inputs"]["value"] = duration_seconds
        graph["416"]["inputs"]["media_state"] = json.dumps(entries)
        if operation == "bridge":
            graph["bridge:resize"]["inputs"]["image"] = ["417", pictures - 1]
        graph["34"]["inputs"]["filename_prefix"] = filename_prefix
        if self.output_profile == "baseline":
            graph["18"]["inputs"]["filename_prefix"] = str(prefix.with_name("preview"))
        self.verify_changes(graph, operation)
        return graph

    def verify_changes(self, graph: dict[str, Any], operation: str | None = None) -> None:
        operation = self._default_operation if operation is None else operation
        baseline = self.effective_baseline_for(operation)
        if graph.keys() != baseline.keys():
            raise ValueError("The frozen graph's nodes cannot change")
        for node_id, original in baseline.items():
            node = graph[node_id]
            if node.keys() != original.keys():
                raise ValueError(f"Unexpected node structure change: {node_id}")
            if {k: v for k, v in node.items() if k != "inputs"} != {
                k: v for k, v in original.items() if k != "inputs"
            }:
                raise ValueError(f"Node type/metadata changed: {node_id}")
            if node["inputs"].keys() != original["inputs"].keys():
                raise ValueError(f"Unexpected input change: {node_id}")
            allowed = self.allowed_inputs.get(node_id, [])
            if operation == "bridge" and node_id == "bridge:resize":
                allowed = ["image"]
            for field, value in original["inputs"].items():
                if field not in allowed and node["inputs"][field] != value:
                    raise ValueError(f"Frozen input changed: {node_id}.{field}")
        self._verify_links(graph, operation)
        if operation == "bridge":
            entries = json.loads(graph["416"]["inputs"]["media_state"])
            pictures = sum(entry.get("kind") == "picture" for entry in entries)
            if graph["bridge:resize"]["inputs"]["image"] != ["417", pictures - 1]:
                raise ValueError("Bridge target guide must anchor the last native picture slot")

    def validate_object_info(
        self, object_info: dict[str, Any], operation: str | None = None,
    ) -> None:
        operation = self._default_operation if operation is None else operation
        baseline = self.effective_baseline_for(
            self._default_operation if operation is None else operation,
        )
        for node_id, node in baseline.items():
            if node["class_type"] not in object_info:
                raise ValueError(f"Missing ComfyUI class {node['class_type']} ({node_id})")
        # These are the selected, not subgraph-default, model names. Never silently substitute.
        for node_id, field in (
            ("171:4", "unet_name"),
            ("171:3", "clip_name"),
            ("171:2", "vae_name"),
            ("171:1", "vae_name"),
        ):
            node = baseline[node_id]
            schema = object_info[node["class_type"]]["input"]["required"][field]
            choices = schema[0]
            if not isinstance(choices, list) or node["inputs"][field] not in choices:
                raise ValueError(f"Selected model unavailable: {node['inputs'][field]}")
        for node_id, field in (
            ("22:6", "sampler_name"),
            ("22:7", "scheduler"),
            ("18", "format"),
            ("34", "format"),
        ):
            if node_id == "18" and self.output_profile == "final_only":
                continue
            node = baseline[node_id]
            schema = object_info[node["class_type"]]["input"]["required"][field]
            choices = schema[0]
            if isinstance(choices, list) and node["inputs"][field] not in choices:
                raise ValueError(f"Unavailable workflow option: {node_id}.{field}")
        if operation == "bridge":
            frame_schema = object_info["MiniMaxH3AddGuide"].get("input", {}).get("required", {}).get(
                "frame_idx", [],
            )
            if (len(frame_schema) < 2 or not isinstance(frame_schema[1], dict)
                    or frame_schema[1].get("min", 0) > -1
                    or frame_schema[1].get("max", -2) < 0):
                raise ValueError("Installed MiniMax H3 guide must support first and last frame indices")
