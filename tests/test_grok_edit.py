"""Three-image editing uses accepted owned videos and CPU/mock-provider fixtures."""

import base64
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from test_grok_continuation import command, parent_fixture, rgb_hash
from test_grok_multimodal import FakeManager, never, response

from h3_backend.grok import FIXED_EDITOR_MODEL, EditPromptRequest, Grok, PromptRequest
from h3_backend.infrastructure import grok_image
from h3_backend.infrastructure.grok_image import continuation_frame
from h3_backend.infrastructure.grok_oauth import OAuthError


def anchors(root):
    parent, reference, video, marker = parent_fixture(root)
    target, _, target_video, target_marker = parent_fixture(root / "second")
    destination = video.parent.parent / target
    target_video.parent.rename(destination)
    return parent, target, reference, video, marker, destination / target_marker.name


def request(parent, target, reference):
    return EditPromptRequest(prompt='literal "transition"\n', system_prompt="custom editor",
                             reference=reference, continuation_parent_id=parent,
                             target_run_id=target)


async def test_first_frame_is_exact_zero_and_differs_from_last(tmp_path):
    ident, _reference, video, marker = parent_fixture(tmp_path)
    before = marker.read_bytes(), video.read_bytes()
    expected = tmp_path / "expected.png"
    command("ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-vf",
            "select=eq(n\\,0),format=rgb24,setsar=0", "-frames:v", "1", "-threads", "1",
            str(expected))
    async with continuation_frame(tmp_path, ident, edge="first") as (first, _, digest):
        first_bytes = first.read()
        derived = tmp_path / "first.png"
        derived.write_bytes(first_bytes)
        assert rgb_hash(derived) == rgb_hash(expected)
    async with continuation_frame(tmp_path, ident) as (last, _, last_digest):
        assert first_bytes != last.read()
        assert digest == last_digest
    assert (marker.read_bytes(), video.read_bytes()) == before
    assert not list((tmp_path / ".dumps/grok-editor").iterdir())
    with pytest.raises(ValueError):
        async with continuation_frame(tmp_path, ident, edge="middle"):
            pytest.fail("Invalid edge was accepted")


async def test_editing_streams_three_ordered_images_and_labels(tmp_path):
    parent, target, reference, video, _, _ = anchors(tmp_path)
    original = (tmp_path / "assets/original.jpg").read_bytes()
    async with continuation_frame(tmp_path, parent) as (snapshot, _, _):
        previous = snapshot.read()
    async with continuation_frame(tmp_path, target, edge="first") as (snapshot, _, _):
        following = snapshot.read()
    seen = []

    def handler(incoming):
        assert len(incoming.content) == int(incoming.headers["content-length"])
        body = json.loads(incoming.content)
        seen.append(body)
        assert body["input"][0] == {"role": "system", "content": "custom editor"}
        content = body["input"][1]["content"]
        assert content[0] == {"type": "input_text", "text": grok_image.EDIT_LABEL}
        assert "previous last frame" in content[0]["text"]
        assert "following FIRST frame" in content[0]["text"]
        assert content[-1] == {"type": "input_text", "text": 'literal "transition"\n'}
        images = [part["image_url"] for part in content if part["type"] == "input_image"]
        assert [base64.b64decode(value.split(",")[1]) for value in images] == [
            original, previous, following]
        assert body["model"] == FIXED_EDITOR_MODEL and body["max_output_tokens"] == 12000
        assert body["store"] is False and body["stream"] is False
        return httpx.Response(200, json=response())

    manager = FakeManager(handler)
    result = await Grok(manager, FIXED_EDITOR_MODEL, root=tmp_path).complete(
        request(parent, target, reference))
    assert result["text"] == "cena" and len(seen) == manager.catalogues == 1
    assert not (tmp_path / ".data/grok").exists()
    assert not (video.parent / "last_frame.png").exists()


@pytest.mark.parametrize("case", ["missing-target", "rejected-target", "target-identity",
                                 "changed-parent", "changed-target", "root-missing"])
async def test_invalid_edit_context_never_authorizes_or_falls_back(tmp_path, monkeypatch, case):
    parent, target, reference, _, parent_marker, target_marker = anchors(tmp_path)
    if case == "missing-target":
        target = str(uuid4())
    if case in {"rejected-target", "target-identity"}:
        metadata = json.loads(target_marker.read_text())
        if case == "rejected-target":
            metadata["state"] = "rejected"
        else:
            metadata["references"][0]["sha256"] = "0" * 64
        target_marker.write_text(json.dumps(metadata))
    if case in {"changed-parent", "changed-target"}:
        native = grok_image._final_frame

        async def mutate(video, frame, *, edge="last"):
            await native(video, frame, edge=edge)
            if edge == "first":
                marker = parent_marker if case == "changed-parent" else target_marker
                metadata = json.loads(marker.read_text())
                metadata["decision"]["accepted"] = False
                marker.write_text(json.dumps(metadata))

        monkeypatch.setattr(grok_image, "_final_frame", mutate)
    manager = FakeManager(never)
    with pytest.raises(OAuthError) as failure:
        await Grok(manager, FIXED_EDITOR_MODEL,
                   root=None if case == "root-missing" else tmp_path).complete(
                       request(parent, target, reference))
    assert failure.value.code in {"invalid_reference", "invalid_continuation"}
    assert manager.catalogues == 0


def test_edit_contract_does_not_expand_generic_editor_schema():
    parent, target = str(uuid4()), str(uuid4())
    reference = {"source_root": "assets", "path": "original.jpg"}
    valid = request(parent, target, reference)
    assert valid.target_run_id == target
    with pytest.raises(ValidationError):
        PromptRequest(**valid.model_dump())
    assert "target_run_id" not in PromptRequest.model_json_schema()["properties"]
    for change in ({"target_run_id": parent}, {"target_run_id": target.upper()},
                   {"continuation_parent_id": None}, {"reference": None}):
        with pytest.raises(ValidationError):
            EditPromptRequest(**{**valid.model_dump(), **change})


@pytest.mark.parametrize("operation", ["v2v", "bridge"])
async def test_target_frame_role_requires_native_bridge_provenance(tmp_path, operation):
    parent, _reference, _, marker = parent_fixture(tmp_path)
    metadata = json.loads(marker.read_text())
    metadata["input_info"] = {"operation": operation}
    metadata["references"].append({"type": "image", "role": "target_frame"})
    marker.write_text(json.dumps(metadata))
    if operation == "bridge":
        async with continuation_frame(tmp_path, parent) as (frame, _, _):
            assert frame.read().startswith(b"\x89PNG")
    else:
        with pytest.raises(ValueError):
            async with continuation_frame(tmp_path, parent):
                pytest.fail("Unproven bridge role was accepted")
