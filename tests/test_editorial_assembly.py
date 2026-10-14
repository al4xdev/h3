"""Editorial ordering keeps native parent history immutable and uses CPU media only."""

import json
from uuid import uuid4

import pytest
import test_assembly as assembly_tests
from pydantic import ValidationError
from test_assembly import bytes_before, chain
from test_grok_multimodal import fixture_image
from test_roteiro import fields

from h3_backend.generation.assembly import (
    AssemblyIntent,
    AssemblyPipe,
    AssemblyRequest,
    assembly_video,
    get_assembly,
)
from h3_backend.generation.dispatcher import Conflict
from h3_backend.infrastructure import media
from h3_backend.roteiro import CreatePlan, Roteiro


@pytest.fixture(scope="session")
def source_clips(tmp_path_factory):
    return assembly_tests.source_clips.__wrapped__(tmp_path_factory)


async def editorial(tmp_path, source_clips, monkeypatch):
    service, runs = chain(tmp_path, source_clips, end_state="accepted")
    encoded = fixture_image(tmp_path / "valid-reference.png")
    (tmp_path / "assets/dance_reference.png").write_bytes(encoded)
    roteiro = Roteiro(service)
    payload = fields(count=3)
    order = [runs[0], runs[2], runs[1]]
    for block, run in zip(payload["blocks"], order, strict=True):
        block["action"] = run.id
    doc = await roteiro.create(CreatePlan(**payload))

    def selected(operation, document):
        result = []
        for block in document.blocks:
            run = operation.service.store.get(block.action)
            if run.state != "accepted" or not run.decision or run.decision.get("accepted") is not True:
                raise Conflict("Selected version is not accepted")
            result.append(run.id)
        return result

    monkeypatch.setattr(Roteiro, "selected_run_ids", selected)
    return service, runs, doc, order


def pipe(service, doc):
    return AssemblyPipe(service).have(str(uuid4())).from_roteiro(doc["id"], doc["revision"]).save_video()


async def test_editorial_concat_inserts_clip_without_rewriting_old_parents(tmp_path, source_clips, monkeypatch):
    service, runs, doc, order = await editorial(tmp_path, source_clips, monkeypatch)
    before = bytes_before(service, runs)
    operation = pipe(service, doc)
    result = await operation.arun()
    assert result["state"] == "completed" and result["mode"] == "accepted_sequence"
    assert result["input_ids"] == [run.id for run in order]
    assert result["frames"] == 15 and result["output"]["boundaries"] == [5, 10]
    assert result["end_run_id"] == runs[1].id
    assert result["roteiro_id"] == doc["id"] and result["roteiro_revision"] == doc["revision"]
    assert len(result["roteiro_sha256"]) == 64
    directory = tmp_path / ".data/assemblies" / result["id"]
    intent = AssemblyIntent.model_validate_json((directory / "request.json").read_text())
    assert intent.roteiro_id == doc["id"] and intent.roteiro_revision == 1
    assert intent.roteiro_sha256 is not None
    assert [clip.parent_id for clip in intent.inputs] == [run.parent_id for run in order]
    assert get_assembly(tmp_path, result["id"]) == result
    output = assembly_video(tmp_path, result["id"])
    decoded = await media._command("ffmpeg", "-v", "error", "-i", str(output), "-vf",
                                   "select=eq(n\\,0)+eq(n\\,5)+eq(n\\,10)", "-fps_mode",
                                   "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-")
    pixels = [decoded[index * 48 * 64 * 3:index * 48 * 64 * 3 + 3] for index in range(3)]
    assert [max(range(3), key=lambda c: pixel[c]) for pixel in pixels] == [0, 2, 1]
    assert bytes_before(service, runs) == before
    assert not service.comfy.submitted and service._cpu_active is None
    await service.shutdown()


@pytest.mark.parametrize("failure", ["revision", "unaccepted", "missing", "duplicate"])
async def test_editorial_admission_refuses_incomplete_versions(tmp_path, source_clips, monkeypatch, failure):
    service, runs, doc, _ = await editorial(tmp_path, source_clips, monkeypatch)
    operation = pipe(service, doc)
    plan = tmp_path / ".data/roteiros" / doc["id"] / "plan.json"
    if failure == "revision":
        operation = AssemblyPipe(service).have(str(uuid4())).from_roteiro(doc["id"], 2).save_video()
    elif failure == "unaccepted":
        manifest = service.store.directory(runs[-1].id) / "manifest.json"
        run = json.loads(manifest.read_text())
        run["state"] = "ready_for_review"
        manifest.write_text(json.dumps(run))
    else:
        document = json.loads(plan.read_text())
        document["blocks"][1]["action"] = str(uuid4()) if failure == "missing" else runs[0].id
        plan.write_text(json.dumps(document))
    with pytest.raises((Conflict, ValueError, FileNotFoundError)):
        await operation.arun()
    assert not (tmp_path / ".data/assemblies" / operation.state.id).exists()
    assert not service.comfy.submitted and service._cpu_active is None
    await service.shutdown()


@pytest.mark.parametrize("failure", ["revision", "selected-order", "same-revision-content", "source"])
async def test_editorial_changed_snapshot_fails_before_publication(tmp_path, source_clips, monkeypatch, failure):
    service, runs, doc, _ = await editorial(tmp_path, source_clips, monkeypatch)
    operation = pipe(service, doc)
    original = service.media.concatenate

    async def changed(sources, destination):
        result = await original(sources, destination)
        plan = tmp_path / ".data/roteiros" / doc["id"] / "plan.json"
        document = json.loads(plan.read_text())
        if failure == "source":
            with (service.store.directory(runs[0].id) / "chunk.mp4").open("ab") as stream:
                stream.write(b"changed source")
        else:
            if failure == "revision":
                document["revision"] += 1
            elif failure == "selected-order":
                document["blocks"] = document["blocks"][::-1]
            else:
                document["name"] = "Changed without revision"
            plan.write_text(json.dumps(document))
        return result

    monkeypatch.setattr(service.media, "concatenate", changed)
    with pytest.raises((Conflict, ValueError)):
        await operation.arun()
    result = get_assembly(tmp_path, operation.state.id)
    assert result["state"] == "failed" and result["video_url"] is None
    assert not (tmp_path / ".data/assemblies" / operation.state.id / "output.json").exists()
    assert service._cpu_active is None and not service.comfy.submitted
    await service.shutdown()


async def test_fluent_editorial_binding_and_legacy_intent_remain_strict(tmp_path, source_clips, monkeypatch):
    service, _, doc, _ = await editorial(tmp_path, source_clips, monkeypatch)
    operation = pipe(service, doc)
    assert operation.state.end_run_id is None
    assert not (tmp_path / ".data/assemblies").exists()
    await operation.arun()
    intent = json.loads((tmp_path / ".data/assemblies" / operation.state.id / "request.json").read_text())
    for key in ("roteiro_id", "roteiro_revision", "roteiro_sha256"):
        intent.pop(key)
    with pytest.raises(ValidationError):
        AssemblyIntent.model_validate(intent)
    with pytest.raises(ValidationError):
        AssemblyRequest(end_run_id=intent["end_run_id"], input_ids=[clip["run_id"] for clip in intent["inputs"]])
    with pytest.raises(Conflict):
        operation.from_end(str(uuid4()))
    with pytest.raises(ValueError):
        AssemblyPipe(service).from_roteiro(doc["id"], True)
    await service.shutdown()


async def test_real_roteiro_proof_rejects_blocks_without_owned_attempts(tmp_path, source_clips, monkeypatch):
    original = Roteiro.selected_run_ids
    service, _, doc, _ = await editorial(tmp_path, source_clips, monkeypatch)
    monkeypatch.setattr(Roteiro, "selected_run_ids", original)
    operation = pipe(service, doc)
    with pytest.raises(Conflict, match="selected version"):
        await operation.arun()
    assert not (tmp_path / ".data/assemblies" / operation.state.id).exists()
    assert service._cpu_active is None and not service.comfy.submitted
    await service.shutdown()
