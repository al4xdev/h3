import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from test_media import fixture_video
from test_service import Builder, make_service

from h3_backend.generation.bridge import BridgePipe, owned_sha256, router, snapshot_video
from h3_backend.generation.dispatcher import Conflict
from h3_backend.generation.models import BridgeRequest, ContinueRequest, RunRequest
from h3_backend.generation.workflow import WorkflowBuilder
from h3_backend.infrastructure import media
from h3_backend.infrastructure.store import Store

ROOT = Path(__file__).resolve().parents[1]


class BridgeBuilder(Builder):
    def hash_for(self, operation):
        return "bridge-sha" if operation == "bridge" else super().hash_for(operation)

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {"operation": kwargs["operation"], "seed": kwargs["seed"]}


def bridge_service(tmp_path):
    service = make_service(tmp_path)
    service.builder = BridgeBuilder()

    async def first_frame(source, destination):
        assert source.name == "bridge_target.mp4"
        destination.write_bytes(b"exact-first-frame")
        return {"path": str(destination), "source_frame_index": 0, "format": "PNG"}

    service.media.prepare_first_frame = first_frame
    return service


async def anchors(service):
    parent = await service.create(RunRequest(seed=1, duration_seconds=2.3))
    await service._task
    await service.decide(parent.id, True)
    target = await service.continue_run(parent.id, ContinueRequest(seed=2, duration_seconds=2.3))
    await service._task
    await service.decide(target.id, True)
    return parent, target


def request(target, **options):
    return BridgeRequest(seed=3, duration_seconds=2.3, target_run_id=target.id, **options)


def references(count=1):
    images = [("initial_frame", "initial.png")]
    images += [("identity", f"identity-{i}.png") for i in range(count)]
    images += [("target_frame", "target.png")]
    return [{"type": "image", "role": role, "filename": f"h3/{name} [input]"}
            for role, name in images] + [
        {"type": "video", "role": "motion_video", "filename": "h3/tail.mp4 [input]",
         "has_audio": True},
    ]


def object_info(builder):
    baseline = builder.effective_baseline_for("bridge")
    info = {node["class_type"]: {"input": {"required": {}}} for node in baseline.values()}
    for node_id, field in (("171:4", "unet_name"), ("171:3", "clip_name"),
                           ("171:2", "vae_name"), ("171:1", "vae_name"),
                           ("22:6", "sampler_name"), ("22:7", "scheduler"),
                           ("18", "format"), ("34", "format")):
        if node_id not in baseline:
            continue
        node = baseline[node_id]
        required = info[node["class_type"]]["input"]["required"]
        required.setdefault(field, [[]])[0].append(node["inputs"][field])
    info["MiniMaxH3AddGuide"]["input"]["required"]["frame_idx"] = [
        "INT", {"min": -9999, "max": 9999}]
    return info


def test_bridge_requires_installed_negative_guide_support():
    builder = WorkflowBuilder(ROOT)
    info = object_info(builder)
    builder.validate_object_info(info, "bridge")
    info["MiniMaxH3AddGuide"]["input"]["required"]["frame_idx"][1]["min"] = 0
    with pytest.raises(ValueError, match="first and last"):
        builder.validate_object_info(info, "bridge")
    builder.validate_object_info(info, "v2v")


@pytest.mark.parametrize("profile", ["baseline", "final_only"])
@pytest.mark.parametrize("identities", [1, 7])
def test_bridge_graph_is_an_exact_native_derivation(profile, identities):
    builder = WorkflowBuilder(ROOT, output_profile=profile)
    arguments = {"prompt": "Move from the parent to the target.", "seed": 4,
                 "duration_seconds": 8.0, "filename_prefix": "h3_backend/test/chunk"}
    refs = references(identities)
    before = builder.effective_baseline_for("v2v")
    native = builder.build(operation="v2v", references=refs[:-2] + refs[-1:], **arguments)
    bridge = builder.build(operation="bridge", references=refs, **arguments)
    assert builder.effective_baseline_for("v2v") == before
    assert set(bridge) - set(native) == {"bridge:guide", "bridge:resize"}
    for key in native:
        if key not in {"416", "125:14"}:
            assert bridge[key] == native[key], key
    assert bridge["125:14"]["inputs"]["conditioning"] == ["bridge:guide", 0]
    assert bridge["bridge:guide"]["inputs"] == {
        "frame_idx": -1, "positive": ["272", 0], "latent": ["520", 0],
        "vae": ["171:2", 0], "audio_vae": ["171:1", 0], "image": ["bridge:resize", 0],
    }
    assert bridge["bridge:resize"]["inputs"]["image"] == ["417", identities + 1]
    assert bridge["272"]["inputs"]["frame_idx"] == 0
    proof = builder.provenance("bridge")
    assert proof["target_guide_frame"] == -1
    assert proof["derived_from_workflow_hash"] == builder.hash_for("v2v")
    assert proof["effective_baseline_hash"] == builder.payload_hash(
        builder.effective_baseline_for("bridge"))
    assert builder.hash_for("bridge") not in {builder.hash_for("i2v"), builder.hash_for("v2v")}
    builder.verify_changes(bridge, "bridge")
    broken = deepcopy(bridge)
    broken["bridge:resize"]["inputs"]["image"] = ["417", 0]
    with pytest.raises(ValueError, match="target"):
        builder.verify_changes(broken, "bridge")
    broken = deepcopy(bridge)
    broken["bridge:guide"]["inputs"]["frame_idx"] = 0
    with pytest.raises(ValueError, match="Frozen"):
        builder.verify_changes(broken, "bridge")


@pytest.mark.parametrize("mutation", ["order", "role", "no_target", "excess"])
def test_bridge_graph_rejects_invalid_reference_roles(mutation):
    refs = references(8 if mutation == "excess" else 1)
    if mutation == "order":
        refs[0], refs[-2] = refs[-2], refs[0]
    elif mutation == "role":
        refs[-2]["role"] = "identity"
    elif mutation == "no_target":
        refs.pop(-2)
    with pytest.raises(ValueError, match="Bridge"):
        WorkflowBuilder(ROOT).build(operation="bridge", prompt="Bridge", seed=1,
                                    duration_seconds=2.3, references=refs,
                                    filename_prefix="h3_backend/test/chunk")


@pytest.mark.asyncio
async def test_bridge_freezes_both_anchors_and_can_be_next_parent(tmp_path):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    previous = {r.id: (service.store.directory(r.id) / "manifest.json").read_bytes()
                for r in (parent, target)}
    identifier = str(uuid4())
    identity = service.store.get(parent.id).references[0]
    pipe = (BridgePipe(service).have(request(target, prompt="Literal improved bridge prompt"))
            .from_parent(parent.id).with_run_id(identifier).with_identity_proof(
                identity["source_root"], identity["source"], identity["sha256"]))
    assert len(service.comfy.submitted) == 2
    admitted = await pipe.admit()
    await service._task
    ready = service.store.get(admitted.id)
    assert ready.id == identifier and ready.state == "ready_for_review"
    assert ready.prompt == "Literal improved bridge prompt"
    assert ready.parent_id == parent.id
    assert [r["role"] for r in ready.references] == [
        "initial_frame", "identity", "target_frame", "motion_video"]
    assert ready.references[2]["target_run_id"] == target.id
    assert ready.references[2]["input_info"]["source_frame_index"] == 0
    assert ready.references[2]["sha256"] == hashlib.sha256(b"exact-first-frame").hexdigest()
    assert service.media.tails[-1][0].name == "bridge_parent.mp4"
    for role, anchor in ready.input_info["bridge_anchors"].items():
        snapshot = service.store.directory(ready.id) / f"bridge_{role}.mp4"
        assert media.sha256_file(snapshot) == anchor["video_sha256"]
        assert (service.store.directory(anchor["run_id"]) / "manifest.json").read_bytes() == previous[
            anchor["run_id"]]
    frozen = service.store.request(ready.id)
    Store.validate_request(frozen)
    restored = BridgePipe.from_run(service, frozen)
    assert restored.state.request.target_run_id == target.id
    assert restored.state.request.prompt == ready.prompt
    with pytest.raises(Conflict):
        pipe.have(request(target))
    await service.decide(ready.id, True)
    continued = await service.continue_run(ready.id, ContinueRequest(seed=4, duration_seconds=2.3))
    await service._task
    assert service.store.get(continued.id).state == "ready_for_review"
    assert [r["role"] for r in service.store.get(continued.id).references] == [
        "initial_frame", "identity", "motion_video"]
    another = await BridgePipe(service).have(request(target)).from_parent(ready.id).admit()
    await service._task
    assert service.store.get(another.id).state == "ready_for_review"
    assert len(service.comfy.submitted) == 5
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["same", "rejected", "identity", "foreign_video", "symlink"])
async def test_bridge_rejects_unproved_target_without_submitting(tmp_path, invalid):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    if invalid == "same":
        target = parent
    else:
        path = service.store.directory(target.id) / "manifest.json"
        data = json.loads(path.read_text())
        if invalid == "rejected":
            data["state"] = "rejected"
        elif invalid == "identity":
            data["references"][1]["sha256"] = "f" * 64
        elif invalid == "foreign_video":
            data["output"]["path"] = service.store.relative_artifact(parent.id, "chunk.mp4")
        elif invalid == "symlink":
            video = service.video_path(target.id)
            video.rename(video.with_suffix(".bak"))
            video.symlink_to(video.with_suffix(".bak"))
        path.write_text(json.dumps(data))
    with pytest.raises((ValueError, Conflict)):
        await BridgePipe(service).have(request(target)).from_parent(parent.id).admit()
    assert len(service.comfy.submitted) == 2
    await service.shutdown()


@pytest.mark.asyncio
async def test_changed_target_is_not_submitted_or_replayed(tmp_path):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    original_idle = service.comfy.ensure_idle

    async def idle():
        await original_idle()
        service.video_path(target.id).write_bytes(b"changed target encoded bytes")

    service.comfy.ensure_idle = idle
    with pytest.raises(Conflict, match="changed"):
        await BridgePipe(service).have(request(target)).from_parent(parent.id).admit()
    manifests = list(service.store.runs.glob("*/manifest.json"))
    assert len(manifests) == 3
    assert sorted(json.loads(p.read_text())["state"] for p in manifests) == [
        "accepted", "accepted", "failed"]
    assert len(service.comfy.submitted) == 2
    await service.shutdown()


@pytest.mark.asyncio
async def test_bridge_materialized_anchor_proof_cannot_be_rewritten(tmp_path):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    bridge = await BridgePipe(service).have(request(target)).from_parent(parent.id).admit()
    await service._task
    path = service.store.directory(bridge.id) / "manifest.json"
    data = json.loads(path.read_text())
    data["input_info"]["bridge_anchors"]["target"]["video_sha256"] = "f" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="immutable"):
        service.store.request(bridge.id)
    await service.shutdown()


@pytest.mark.asyncio
async def test_bridge_hydration_requires_identity_from_both_frozen_anchors(tmp_path):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    bridge = await BridgePipe(service).have(request(target)).from_parent(parent.id).admit()
    await service._task
    frozen = service.store.request(bridge.id)
    frozen.references[0]["source"] = "another-identity.png"
    with pytest.raises(Conflict, match="changed"):
        service._hydrate(frozen)
    await service.shutdown()


@pytest.mark.asyncio
async def test_bridge_route_has_its_own_explicit_operation(tmp_path):
    service = bridge_service(tmp_path)
    parent, target = await anchors(service)
    app = FastAPI()
    app.state.service = service
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(f"/runs/{parent.id}/bridge", json=request(target).model_dump())
        assert response.status_code == 202
        await service._task
        assert service.store.get(response.json()["id"]).state == "ready_for_review"
        assert (await client.post(f"/runs/{parent.id}/v2v", json=request(target).model_dump())).status_code == 404
    await service.shutdown()


@pytest.mark.asyncio
async def test_bridge_native_graph_executes_with_fake_gpu_and_unchanged_outputs(tmp_path):
    service = bridge_service(tmp_path)
    service.builder = WorkflowBuilder(ROOT)

    async def info():
        return object_info(service.builder)

    service.comfy.object_info = info
    parent, target = await anchors(service)
    bridge = await BridgePipe(service).have(request(target)).from_parent(parent.id).admit()
    await service._task
    ready = service.store.get(bridge.id)
    assert ready.state == "ready_for_review"
    graph = json.loads((service.store.directory(bridge.id) / "workflow_api.json").read_text())
    assert graph["bridge:guide"]["inputs"]["frame_idx"] == -1
    assert graph["bridge:resize"]["inputs"]["image"] == ["417", 2]
    state = json.loads(graph["416"]["inputs"]["media_state"])
    assert state[2]["file"] == ready.references[2]["filename"]
    assert graph["5"]["inputs"] == service.builder.baseline_for("v2v")["5"]["inputs"]
    assert ready.input_info["workflow_provenance"] == service.store.request(bridge.id).input_info[
        "workflow_provenance"]
    await service.shutdown()


@pytest.mark.parametrize("target", ["../video", "https://example.com/video", str(uuid4()).upper()])
def test_bridge_requires_canonical_target_uuid(target):
    with pytest.raises(ValidationError):
        BridgeRequest(seed=1, target_run_id=target)


@pytest.mark.asyncio
async def test_exact_first_frame_is_decoded_without_python_pixels(tmp_path):
    source = tmp_path / "target.mp4"
    await fixture_video(source, True)
    destination = tmp_path / "target_frame.png"
    info = await media.prepare_first_frame(source, destination)
    assert info["source_frame_index"] == 0
    assert info["source_frame_count"] == 56
    assert (info["width"], info["height"]) == (64, 96)

    async def rgb_hash(path):
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-frames:v", "1",
            "-vf", "format=rgb24", "-an", "-f", "hash", "-hash", "sha256", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        output, error = await process.communicate()
        assert process.returncode == 0, error.decode()
        return output

    assert await rgb_hash(source) == await rgb_hash(destination)
    with pytest.raises(ValueError, match="overwrite"):
        await media.prepare_first_frame(source, destination)


def test_encoded_snapshot_is_bounded_owned_and_refuses_overwrite(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"encoded bytes" * 200000)
    digest = media.sha256_file(source)

    def no_whole_file(*arguments):
        pytest.fail("Bridge hashes and snapshots must use bounded reads")

    monkeypatch.setattr(Path, "read_bytes", no_whole_file)
    assert owned_sha256(source) == digest
    destination = tmp_path / "snapshot.mp4"
    snapshot_video(source, destination, digest)
    assert owned_sha256(destination) == digest
    with pytest.raises(FileExistsError):
        snapshot_video(source, destination, digest)
    with pytest.raises(Conflict, match="changed"):
        snapshot_video(source, tmp_path / "bad.mp4", "f" * 64)
    assert not (tmp_path / "bad.mp4").exists()
