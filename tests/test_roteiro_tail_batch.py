import asyncio
import base64
import json
import subprocess
from uuid import uuid4

import httpx
import pytest
from test_grok import finished
from test_grok_multimodal import FakeManager
from test_roteiro import fields, setup
from test_roteiro_batch import FakeEnhancer, consent

from h3_backend.grok import FIXED_EDITOR_MODEL, Grok
from h3_backend.roteiro import CreatePlan, Generate
from h3_backend.roteiro_batch import RoteiroBatch


def materialize_video(path, color):
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        f"color={color}:size=480x864:rate=24", "-frames:v", "56", "-c:v", "libx264",
        "-threads", "1", "-pix_fmt", "yuv420p", str(path),
    ], capture_output=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr.decode()


async def accepted_root(roteiro, service):
    created = await roteiro.create(CreatePlan(**fields(count=1)))
    doc = roteiro.get(created["id"])
    block = doc.blocks[0]
    run_id = str(uuid4())
    await roteiro.generate(doc.id, block.id, run_id, Generate(
        expected_revision=doc.revision, prompt=block.prompt, seed=block.seed,
        duration_seconds=block.duration_seconds, parent_id=None))
    await service.wait_run(run_id)
    await service.decide(run_id, True)
    return roteiro.get(doc.id), run_id


@pytest.mark.asyncio
async def test_tail_planning_adoption_and_batch_refresh_actual_parent_frames(tmp_path, monkeypatch):
    from h3_backend.roteiro import AdoptTail, Block, TailRequest

    service, roteiro = setup(tmp_path)
    materialize_video(service.comfy.output, "green")
    doc, root_id = await accepted_root(roteiro, service)
    root_directory = service.store.directory(root_id)
    original_files = {path.name: path.read_bytes() for path in root_directory.iterdir()
                      if path.is_file()}
    original_attempts = list(doc.attempts)
    original_blocks = list(doc.blocks)
    identity = (tmp_path / "assets/dance_reference.png").read_bytes()
    idea = "Walk to the window, then wave goodbye"
    wires = []

    enhanced = []

    def provider(request):
        wire = json.loads(request.content)
        wires.append(wire)
        assert int(request.headers["content-length"]) == len(request.content)
        assert wire["model"] == FIXED_EDITOR_MODEL
        if "text" in wire:
            assert wire["max_output_tokens"] == 20000
            assert wire["text"]["format"]["type"] == "json_schema"
            assert wire["text"]["format"]["strict"] is True
            assert idea in wire["input"][-1]["content"][-1]["text"]
            step = wire["text"]["format"]["name"]
            prompt = wire["input"][-1]["content"][-1]["text"]
            marker = "Payload:\n"
            body = json.loads(prompt[prompt.index(marker) + len(marker):])
            if step == "h3_roteiro_script":
                text = json.dumps({
                    "name": "Tail intentions", "summary": "Continua da cauda.",
                    "events": [{
                        "title": "Janela", "kind": "action", "intent": "anda até a janela",
                        "dialogue": None,
                        "anatomy": ["corpo 1", "corpo 2"],
                        "expressions": ["expressão 1", "expressão 2"],
                        "deltas": ["delta 1", "delta 2"],
                        "camera_focus": None, "keeps": ["janela"],
                    }],
                })
            elif step == "h3_roteiro_card":
                text = json.dumps({
                    "id": body["id"], "title": body["title"],
                    "expression": body["expression"], "anatomy": body["anatomy"],
                    "delta": body["delta"], "camera_focus": body["camera_focus"],
                    "dialogue": body["dialogue"],
                    "instruction": (
                        f"Ação: {body['intent']}\nCorpo: {body['anatomy']}\n"
                        f"Expressão: {body['expression']}\n"
                        f"Mudança em relação ao anterior: {body['delta']}\n"
                    ),
                })
            else:
                raise AssertionError(step)
        else:
            assert wire["max_output_tokens"] == 12000
            context = wire["input"][-1]["content"][-1]["text"]
            assert "Janela" in context and "Corpo:" in context
            enhanced.append(wire)
            text = f"Actual enhanced instruction {len(enhanced)}"
        return httpx.Response(200, json=finished(text))

    class RecordedGrok(Grok):
        def __init__(self):
            super().__init__(FakeManager(provider), FIXED_EDITOR_MODEL, root=tmp_path)
            self.calls = []

        async def complete(self, request, **kwargs):
            parent = service.store.get(request.continuation_parent_id)
            assert parent.state == "accepted" and service.video_path(parent.id).is_file()
            self.calls.append(request)
            return await super().complete(request, **kwargs)

    grok = RecordedGrok()
    batch = RoteiroBatch(service, grok)
    try:
        tail_id = str(uuid4())
        proposal = await roteiro.propose_tail(doc.id, tail_id, TailRequest(
            expected_revision=doc.revision, idea=idea, count=2, seed=97, duration_seconds=2.3), grok)
        assert roteiro.get(doc.id) == doc and len(service.comfy.submitted) == 1
        assert proposal["state"] == "proposed", proposal.get("detail")
        adopted = await roteiro.adopt_tail(doc.id, tail_id, AdoptTail(
            expected_revision=doc.revision,
            blocks=[Block.model_validate(block) for block in proposal["blocks"]]))
        assert len(service.comfy.submitted) == 1 and len(grok.calls) == 3
        assert roteiro.get(doc.id).blocks[:1] == original_blocks
        assert roteiro.get(doc.id).attempts == original_attempts
        native_execute = service.comfy.execute

        async def colorful_execute(*args, **kwargs):
            materialize_video(service.comfy.output, "blue" if len(service.comfy.submitted) == 1 else "yellow")
            return await native_execute(*args, **kwargs)

        monkeypatch.setattr(service.comfy, "execute", colorful_execute)
        batch_id = str(uuid4())
        initial = await batch.start(doc.id, batch_id, consent(adopted["revision"]))
        assert initial["initial_parent_id"] == root_id
        assert [block["id"] for block in initial["blocks"]] == [block["id"] for block in proposal["blocks"]]
        await asyncio.wait_for(batch.task, 120)
        result = batch.get(doc.id, batch_id)
        assert result["state"] == "ready_for_review", result["error"]
        final_doc = roteiro.get(doc.id)
        runs = [service.store.get(attempt.run_id) for attempt in final_doc.attempts]
        assert [run.parent_id for run in runs] == [None, root_id, runs[1].id]
        assert [run.state for run in runs] == ["accepted", "accepted", "ready_for_review"]
        assert [request.continuation_parent_id for request in grok.calls] == [root_id] * 4 + [runs[1].id]
        assert [run.prompt for run in runs[1:]] == ["Actual enhanced instruction 1", "Actual enhanced instruction 2"]
        assert [run.seed for run in runs[1:]] == [97, 97]
        assert [run.duration_seconds for run in runs[1:]] == [2.3, 2.3]
        assert result["accepted_run_ids"] == [runs[1].id]
        assert [call["operation"] for call in service.builder.calls] == ["i2v", "v2v", "v2v"]
        images = [[base64.b64decode(part["image_url"].split(",", 1)[1])
                   for part in wire["input"][-1]["content"] if part["type"] == "input_image"]
                  for wire in wires]
        assert all(len(pair) == 2 and pair[0] == identity for pair in images)
        assert images[0][1] == images[3][1] and images[3][1] != images[4][1]
        assert final_doc.blocks[:1] == original_blocks
        assert final_doc.attempts[:1] == original_attempts
        assert {path.name: path.read_bytes() for path in root_directory.iterdir()
                if path.is_file()} == original_files
        assert len(service.comfy.submitted) == 3 and len(wires) == 5
    finally:
        await batch.shutdown()
        await service.shutdown()


@pytest.mark.asyncio
async def test_new_root_finishes_and_is_accepted_before_continuation_enhancement(tmp_path):
    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields(count=2)))
    gate = asyncio.Event()
    submitted = asyncio.Event()
    service.comfy.gate = gate
    service.comfy.submitted_event = submitted

    class CheckedEnhancer(FakeEnhancer):
        async def complete(self, request):
            if self.calls:
                assert gate.is_set()
                parent = service.store.get(request.continuation_parent_id)
                assert parent.state == "accepted"
                assert service.video_path(parent.id).is_file()
            else:
                assert request.continuation_parent_id is None
            return await super().complete(request)

    enhancer = CheckedEnhancer()
    batch = RoteiroBatch(service, enhancer)
    await batch.start(original["id"], str(uuid4()), consent())
    try:
        await asyncio.wait_for(submitted.wait(), 5)
        assert len(enhancer.calls) == len(service.comfy.submitted) == 1
        assert [call["operation"] for call in service.builder.calls] == ["i2v"]
        first = roteiro.get(original["id"]).attempts[0].run_id
        assert service.store.get(first).state != "accepted"
        gate.set()
        await asyncio.wait_for(batch.task, 10)
        assert batch.current()["batch"]["state"] == "ready_for_review"
        assert [call["operation"] for call in service.builder.calls] == ["i2v", "v2v"]
        assert [call.continuation_parent_id for call in enhancer.calls] == [None, first]
    finally:
        gate.set()
        await batch.shutdown()
        await service.shutdown()
