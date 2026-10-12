"""Parametrize the exported graph without rewriting its model or processing branches."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any


def frames_for_duration(seconds: float) -> int:
    if not math.isfinite(seconds) or not 0 < seconds <= 3:
        raise ValueError("Baseline duration must be positive and at most three seconds")
    requested = max(5, round(seconds * 24))
    frames = requested + (5 - requested % 17) % 17
    if frames / 24 > 3:
        raise ValueError("The original graph rounds this duration above three seconds; use 2.3")
    return frames


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
    def __init__(self, project_root: Path, mode: str = "normal"):
        if mode not in ("normal", "continuation"):
            raise ValueError("Workflow mode must be normal or continuation")
        self.mode = mode
        directory = project_root / "workflows"
        raw = (directory / f"{mode}_api.json").read_bytes()
        manifest_name = "baseline_manifest.json" if mode == "normal" else "continuation_manifest.json"
        manifest = json.loads((directory / manifest_name).read_text())
        self.hash = hashlib.sha256(raw).hexdigest()
        if self.hash != manifest["api_sha256"]:
            raise ValueError("Frozen workflow checksum mismatch; review the new baseline first")
        self.baseline = json.loads(raw)
        self.allowed_inputs = manifest["allowed_inputs"]
        self.extra_pnginfo = copy.deepcopy(manifest["extra_pnginfo"])
        self._verify_links(self.baseline)

    def _verify_links(self, graph: dict[str, Any]) -> None:
        for node_id, field, expected in (
            ("5", "vae", ["171:2", 0]),
            ("176", "vae", ["171:2", 0]),
            ("259", "vae", ["171:2", 0]),
            ("125:12", "sampler", ["22:6", 0]),
            ("125:12", "sigmas", ["542", 0]),
        ):
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
            ("125:14", "conditioning", ["272" if self.mode == "continuation" else "471", 0]),
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
        if self.mode == "continuation":
            for node_id, class_type in (
                ("272", "MiniMaxH3AddGuide"), ("274", "ImageResizeKJv2"), ("276", "GetImageSize")
            ):
                if graph.get(node_id, {}).get("class_type") != class_type:
                    raise ValueError(f"Missing native guide helper {node_id}")
            links.extend([
                ("272", "frame_idx", 0),
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
        for node_id, field, expected in links:
            if graph.get(node_id, {}).get("inputs", {}).get(field) != expected:
                raise ValueError(f"Missing or changed native link {node_id}.{field}")

    @staticmethod
    def _verify_continuation_roles(references: list[dict[str, Any]]) -> None:
        # The native splitter preserves image order within categories: never silently reorder.
        if not 3 <= len(references) <= 10:
            raise ValueError("Continuation requires initial_frame, one to eight identities, motion_video")
        expected = [("image", "initial_frame")]
        expected += [("image", "identity")] * (len(references) - 2)
        expected += [("video", "motion_video")]
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
    ) -> dict[str, Any]:
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
        if self.mode == "continuation":
            self._verify_continuation_roles(references)
        entries = [_media_entry(reference) for reference in references]
        pictures = sum(entry["kind"] == "picture" for entry in entries)
        videos = sum(entry["kind"] == "video" for entry in entries)
        if not 1 <= pictures <= 9 or videos > 3:
            raise ValueError("Supply one to nine identity images and at most three videos")
        graph = copy.deepcopy(self.baseline)
        graph["365"]["inputs"]["prompt"] = prompt
        graph["16"]["inputs"]["seed"] = seed
        graph["22:23"]["inputs"]["value"] = duration_seconds
        graph["416"]["inputs"]["media_state"] = json.dumps(entries)
        graph["34"]["inputs"]["filename_prefix"] = filename_prefix
        graph["18"]["inputs"]["filename_prefix"] = str(prefix.with_name("preview"))
        self.verify_changes(graph)
        return graph

    def verify_changes(self, graph: dict[str, Any]) -> None:
        if graph.keys() != self.baseline.keys():
            raise ValueError("The frozen graph's nodes cannot change")
        for node_id, original in self.baseline.items():
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
            for field, value in original["inputs"].items():
                if field not in allowed and node["inputs"][field] != value:
                    raise ValueError(f"Frozen input changed: {node_id}.{field}")
        self._verify_links(graph)

    def validate_object_info(self, object_info: dict[str, Any]) -> None:
        for node_id, node in self.baseline.items():
            if node["class_type"] not in object_info:
                raise ValueError(f"Missing ComfyUI class {node['class_type']} ({node_id})")
        # These are the selected, not subgraph-default, model names. Never silently substitute.
        for node_id, field in (
            ("171:4", "unet_name"),
            ("171:3", "clip_name"),
            ("171:2", "vae_name"),
            ("171:1", "vae_name"),
        ):
            node = self.baseline[node_id]
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
            node = self.baseline[node_id]
            schema = object_info[node["class_type"]]["input"]["required"][field]
            choices = schema[0]
            if isinstance(choices, list) and node["inputs"][field] not in choices:
                raise ValueError(f"Unavailable workflow option: {node_id}.{field}")
