"""Batch orchestration uses CPU fixtures and an inert native-service boundary."""

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_roteiro import fields, setup

from h3_backend.generation.dispatcher import Conflict
from h3_backend.roteiro import CreatePlan
from h3_backend.roteiro_batch import RoteiroBatch, StartBatch, assert_batch_available


class FakeEnhancer:
    def __init__(self):
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        base = request.prompt.split("Chosen instruction: ", 1)[-1].split("\nRequested duration:", 1)[0]
        return {"text": base + " enhanced", "model": request.model}


def consent(revision=1):
    return StartBatch(expected_revision=revision, auto_accept_intermediate=True, enhance_with_grok=True)


@pytest.mark.asyncio
async def test_sequential_native_boundary_and_final_review(tmp_path, monkeypatch):
    service, roteiro = setup(tmp_path)
    doc = await roteiro.create(CreatePlan(**fields(count=3)))
    batch = RoteiroBatch(service, FakeEnhancer())
    calls, outcomes = [], {}
    gate = asyncio.Event()

    async def generate(ident, block, run_id, payload):
        assert_batch_available(service)
        calls.append((block, run_id, payload.parent_id, payload.prompt, payload.seed))
        outcomes[run_id] = {"admission": "admitted", "state": "running"}
        return outcomes[run_id]

    async def wait(run_id):
        await gate.wait()
        outcomes[run_id]["state"] = "ready_for_review"

    async def decide(run_id, accepted):
        assert accepted
        assert_batch_available(service)
        outcomes[run_id]["state"] = "accepted"

    monkeypatch.setattr(batch.roteiro, "generate", generate)
    monkeypatch.setattr(batch, "context", lambda doc, index: f"Chosen instruction: {doc.blocks[index].prompt}\nRequested duration: 2.3")
    monkeypatch.setattr(batch.roteiro, "parent", lambda *args: None)
    monkeypatch.setattr(batch.roteiro, "intent", lambda doc, block, ident: ident)
    monkeypatch.setattr(batch.roteiro, "observed", lambda ident: outcomes[ident])
    monkeypatch.setattr(service, "wait_run", wait)
    monkeypatch.setattr(service, "decide", decide)
    ident = str(uuid4())
    initial = await batch.start(doc["id"], ident, consent())
    assert initial["state"] == "active" and initial["current_run_id"] is None
    with pytest.raises(Conflict):
        assert_batch_available(service)
    with pytest.raises(Conflict):
        await batch.start(doc["id"], str(uuid4()), consent())
    gate.set()
    await batch.task
    result = batch.get(doc["id"], ident)
    assert result["state"] == "ready_for_review"
    assert len(result["completed_block_ids"]) == 3
    assert result["accepted_run_ids"] == [calls[0][1], calls[1][1]]
    assert [c[2] for c in calls] == [None, calls[0][1], calls[1][1]]
    assert [c[3] for c in calls] == [b["prompt"] + " enhanced" for b in doc["blocks"]]
    assert outcomes[calls[-1][1]]["state"] == "ready_for_review"
    assert_batch_available(service)
    with pytest.raises(Conflict):
        await batch.start(doc["id"], ident, consent())
    await service.shutdown()


@pytest.mark.asyncio
async def test_uncertain_admission_stops_without_wait_or_replay(tmp_path, monkeypatch):
    service, roteiro = setup(tmp_path)
    doc = await roteiro.create(CreatePlan(**fields()))
    batch = RoteiroBatch(service, FakeEnhancer())
    calls = []

    async def generate(ident, block, run_id, payload):
        calls.append(run_id)
        return {"admission": "uncertain", "state": "uncertain"}

    async def forbidden(*args):
        pytest.fail("Uncertain admission must not wait, review or resubmit")

    monkeypatch.setattr(batch.roteiro, "generate", generate)
    monkeypatch.setattr(service, "wait_run", forbidden)
    monkeypatch.setattr(service, "decide", forbidden)
    ident = str(uuid4())
    await batch.start(doc["id"], ident, consent())
    await batch.task
    result = batch.get(doc["id"], ident)
    assert result["state"] == "stopped"
    assert result["current_run_id"] == calls[0] and len(calls) == 1
    assert result["completed_block_ids"] == []
    await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_and_startup_never_resume(tmp_path, monkeypatch):
    service, roteiro = setup(tmp_path)
    doc = await roteiro.create(CreatePlan(**fields()))
    batch = RoteiroBatch(service, FakeEnhancer())
    entered = asyncio.Event()

    async def generate(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(batch.roteiro, "generate", generate)
    ident = str(uuid4())
    await batch.start(doc["id"], ident, consent())
    await entered.wait()
    await batch.shutdown()
    result = batch.get(doc["id"], ident)
    assert result["state"] == "interrupted" and result["current_run_id"]
    result["state"] = "active"
    batch.save(result)
    restarted = RoteiroBatch(service, FakeEnhancer())
    await restarted.startup()
    assert restarted.task is None
    assert restarted.get(doc["id"], ident)["state"] == "interrupted"
    await service.shutdown()


def test_explicit_acceptance_consent_required():
    with pytest.raises(ValidationError):
        StartBatch(expected_revision=1, auto_accept_intermediate=False, enhance_with_grok=True)
    with pytest.raises(ValidationError):
        StartBatch(expected_revision=1)
    with pytest.raises(ValidationError):
        StartBatch(expected_revision=1, auto_accept_intermediate=1, enhance_with_grok=True)
    with pytest.raises(ValidationError):
        StartBatch(expected_revision=1, auto_accept_intermediate=True, enhance_with_grok=False)


@pytest.mark.asyncio
async def test_skip_proven_accepted_prefix_and_block_existing_attempt(tmp_path, monkeypatch):
    from h3_backend.roteiro import Generate

    service, roteiro = setup(tmp_path)
    result = await roteiro.create(CreatePlan(**fields(count=3)))
    doc = roteiro.get(result["id"])
    first = doc.blocks[0]
    run_id = str(uuid4())
    roteiro.reserve(doc, first.id, run_id, Generate(
        expected_revision=doc.revision, prompt=first.prompt, seed=first.seed,
        duration_seconds=first.duration_seconds, parent_id=None))
    batch = RoteiroBatch(service, FakeEnhancer())
    monkeypatch.setattr(batch.roteiro, "observed", lambda attempt: {
        "admission": "admitted", "state": "accepted"})
    entered = asyncio.Event()

    async def hold(value):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(batch, "execute", hold)
    ident = str(uuid4())
    initial = await batch.start(doc.id, ident, consent())
    assert initial["initial_parent_id"] == run_id
    assert [b["id"] for b in initial["blocks"]] == [b.id for b in doc.blocks[1:]]
    await batch.shutdown()
    batch.release()
    initial["state"] = "interrupted"
    batch.save(initial)
    other = RoteiroBatch(service, FakeEnhancer())
    monkeypatch.setattr(other.roteiro, "observed", lambda attempt: {
        "admission": "admitted", "state": "interrupted"})
    with pytest.raises(Conflict, match="Resolve every previous attempt"):
        await other.start(doc.id, str(uuid4()), consent())
    assert other.task is None and other.lock_fd is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_current_readonly_and_activation_serializes_admission(tmp_path, monkeypatch):
    service, roteiro = setup(tmp_path)
    result = await roteiro.create(CreatePlan(**fields()))
    batch = RoteiroBatch(service, FakeEnhancer())
    assert batch.current() == {"batch": None}
    assert not (tmp_path / ".data" / "roteiro-batches").exists()
    await service._lock.acquire()
    attempt = asyncio.create_task(batch.start(result["id"], str(uuid4()), consent()))
    for _ in range(30):
        await asyncio.sleep(0.01)
        if batch.lock_fd is not None:
            break
    assert not attempt.done()
    assert batch.current() == {"batch": None}
    service._active = str(uuid4())
    service._lock.release()
    with pytest.raises(Conflict, match="Only one backend job"):
        await attempt
    assert batch.task is None and batch.lock_fd is None
    assert batch.current() == {"batch": None}
    service._active = None

    async def uncertain(*args):
        return {"admission": "uncertain", "state": "uncertain"}

    monkeypatch.setattr(batch.roteiro, "generate", uncertain)
    value = await batch.start(result["id"], str(uuid4()), consent())
    await batch.task
    paths = list((tmp_path / ".data" / "roteiro-batches").iterdir())
    before = {path.name: path.read_bytes() for path in paths}
    current = batch.current()["batch"]
    assert current["id"] == value["id"] and current["state"] == "stopped"
    assert before == {path.name: path.read_bytes() for path in paths}
    await service.shutdown()


@pytest.mark.asyncio
async def test_real_native_service_fake_worker_batch(tmp_path):
    service, roteiro = setup(tmp_path)
    result = await roteiro.create(CreatePlan(**fields(count=3)))
    batch = RoteiroBatch(service, FakeEnhancer())
    ident = str(uuid4())
    await batch.start(result["id"], ident, consent())
    await batch.task
    observed = batch.get(result["id"], ident)
    assert observed["state"] == "ready_for_review", observed["error"]
    assert len(service.comfy.submitted) == 3
    doc = roteiro.get(result["id"])
    runs = [service.store.get(attempt.run_id) for attempt in doc.attempts]
    assert [run.state for run in runs] == ["accepted", "accepted", "ready_for_review"]
    assert [run.parent_id for run in runs] == [None, runs[0].id, runs[1].id]
    assert [run.prompt for run in runs] == [block.prompt for block in doc.blocks]
    assert [run.seed for run in runs] == [block.seed for block in doc.blocks]
    assert [run.duration_seconds for run in runs] == [block.duration_seconds for block in doc.blocks]
    assert observed["accepted_run_ids"] == [runs[0].id, runs[1].id]
    await service.shutdown()


@pytest.mark.asyncio
async def test_enhancer_intent_precedes_call_and_context_tracks_actual_parent(tmp_path):
    import json

    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields(count=3)))

    class CheckedEnhancer(FakeEnhancer):
        async def complete(self, request):
            records = list((tmp_path / ".data" / "roteiro-batches").glob("enhancement-*.json"))
            latest = [json.loads(path.read_text()) for path in records]
            pending = [record for record in latest if record["state"] == "uncertain"]
            assert len(pending) == 1
            assert pending[0]["request"] == request.model_dump()
            assert pending[0]["text"] is None
            if request.continuation_parent_id:
                parent = service.store.get(request.continuation_parent_id)
                assert parent.state == "accepted"
                assert parent.prompt in request.prompt
            assert request.reference.model_dump() == original["reference"]
            assert "Next planned block:" in request.prompt
            return await super().complete(request)

    enhancer = CheckedEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await batch.task
    current = batch.get(original["id"], ident)
    assert current["state"] == "ready_for_review", current["error"]
    doc = roteiro.get(original["id"])
    assert current["expected_current_revision"] == doc.revision == 4
    assert current["source_revision"] == 1
    assert current["blocks"] == original["blocks"]
    assert len(enhancer.calls) == len(current["enhancement_ids"]) == 3
    runs = [service.store.get(attempt.run_id) for attempt in doc.attempts]
    assert [request.continuation_parent_id for request in enhancer.calls] == [None, runs[0].id, runs[1].id]
    for index, enhancement_id in enumerate(current["enhancement_ids"]):
        path = tmp_path / ".data" / "roteiro-batches" / f"enhancement-{enhancement_id}.json"
        record = json.loads(path.read_text())
        assert record["state"] == "adopted"
        assert record["block"]["prompt"] == original["blocks"][index]["prompt"]
        assert record["text"] == runs[index].prompt == doc.blocks[index].prompt
    await service.shutdown()


@pytest.mark.asyncio
async def test_provider_failure_stops_once_without_native_fallback(tmp_path):
    import json

    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields()))

    class BrokenEnhancer(FakeEnhancer):
        async def complete(self, request):
            self.calls.append(request)
            raise OSError("Response unknown")

    enhancer = BrokenEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await batch.task
    current = batch.get(original["id"], ident)
    assert current["state"] == "stopped" and current["phase"] == "improving"
    assert current["current_run_id"] is None
    assert len(enhancer.calls) == 1 and not service.comfy.submitted
    assert roteiro.get(original["id"]).revision == 1
    record = json.loads((tmp_path / ".data" / "roteiro-batches" /
                         f"enhancement-{current['enhancement_ids'][0]}.json").read_text())
    assert record["state"] == "uncertain" and record["text"] is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_explicit_stop_during_provider_does_not_generate(tmp_path):
    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields()))
    entered = asyncio.Event()

    class HoldingEnhancer(FakeEnhancer):
        async def complete(self, request):
            self.calls.append(request)
            entered.set()
            await asyncio.Event().wait()

    enhancer = HoldingEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await entered.wait()
    with pytest.raises(Conflict):
        await batch.stop(original["id"], str(uuid4()))
    current = await batch.stop(original["id"], ident)
    assert current["state"] == "stopped" and current["stop_requested"]
    assert current["phase"] == "improving" and current["current_run_id"] is None
    assert len(enhancer.calls) == 1 and not service.comfy.submitted
    assert batch.lock_fd is None
    with pytest.raises(Conflict):
        await batch.stop(original["id"], ident)
    await service.shutdown()


@pytest.mark.asyncio
async def test_real_native_stop_only_current_run_and_no_next_enhancer(tmp_path):
    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields(count=3)))
    service.comfy.gate = asyncio.Event()
    service.comfy.submitted_event = asyncio.Event()
    enhancer = FakeEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await service.comfy.submitted_event.wait()
    current_id = service._active
    assert current_id and batch.current()["batch"]["phase"] == "generating"
    stopped = await batch.stop(original["id"], ident)
    assert stopped["state"] == "stopped" and stopped["stop_requested"]
    assert stopped["current_run_id"] == current_id
    assert service.store.get(current_id).state == "interrupted"
    assert service._active is None and batch.lock_fd is None
    assert len(service.comfy.submitted) == len(enhancer.calls) == 1
    assert len(roteiro.get(original["id"]).attempts) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_native_mutations_fenced_while_enhancer_active(tmp_path):
    from h3_backend.generation.models import RunRequest

    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields()))
    entered = asyncio.Event()

    class HoldingEnhancer(FakeEnhancer):
        async def complete(self, request):
            entered.set()
            await asyncio.Event().wait()

    batch = RoteiroBatch(service, HoldingEnhancer())
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await entered.wait()
    with pytest.raises(Conflict, match="batch owns"):
        await service.create(RunRequest(seed=7, duration_seconds=2.3))
    with pytest.raises(Conflict, match="batch owns"):
        await service.decide(str(uuid4()), True)
    with pytest.raises(Conflict, match="batch owns"):
        async with service.cpu_slot(str(uuid4())):
            pytest.fail("Assembly must not enter the batch-owned slot")
    assert not service.comfy.submitted and not list((tmp_path / ".data" / "runs").glob("*/run.json"))
    await batch.stop(original["id"], ident)
    await service.shutdown()


@pytest.mark.asyncio
async def test_disconnected_stop_waiter_does_not_cancel_owned_cleanup(tmp_path, monkeypatch):
    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields()))
    service.comfy.gate = asyncio.Event()
    service.comfy.submitted_event = asyncio.Event()
    batch = RoteiroBatch(service, FakeEnhancer())
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await service.comfy.submitted_event.wait()
    own_run = service._active
    native_stop = service.stop_run
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def delayed_stop(run_id):
        assert run_id == own_run
        cleanup_entered.set()
        await cleanup_release.wait()
        return await native_stop(run_id)

    monkeypatch.setattr(service, "stop_run", delayed_stop)
    waiter = asyncio.create_task(batch.stop(original["id"], ident))
    await cleanup_entered.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert batch.stop_task and not batch.stop_task.done()
    assert batch.task and not batch.task.done()
    cleanup_release.set()
    await batch.stop_task
    assert service.store.get(own_run).state == "interrupted"
    assert batch.get(original["id"], ident)["state"] == "stopped"
    assert batch.lock_fd is None and service._active is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_context_over_scene_limit_and_provider_uncertainty_history_fenced(tmp_path):
    service, roteiro = setup(tmp_path)
    data = fields(count=1)
    data["idea"] = "Idea " * 2000
    data["blocks"][0]["prompt"] = "Base " * 1600
    original = await roteiro.create(CreatePlan(**data))

    class BrokenEnhancer(FakeEnhancer):
        async def complete(self, request):
            self.calls.append(request)
            assert 12000 < len(request.prompt) < 100000
            raise OSError("Unknown provider response")

    enhancer = BrokenEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await batch.task
    assert len(enhancer.calls) == 1
    with pytest.raises(Conflict, match="previous text enhancement"):
        await batch.start(original["id"], str(uuid4()), consent())
    assert len(enhancer.calls) == 1 and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_editor_required_and_stop_before_execution_is_terminal(tmp_path):
    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields()))
    unavailable = RoteiroBatch(service)
    with pytest.raises(Conflict, match="editor is unavailable"):
        await unavailable.start(original["id"], str(uuid4()), consent())
    assert unavailable.current() == {"batch": None}
    enhancer = FakeEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    stopped = await batch.stop(original["id"], ident)
    assert stopped["state"] == "stopped" and stopped["stop_requested"]
    assert stopped["current_block_id"] is None and stopped["current_run_id"] is None
    assert batch.lock_fd is None and not enhancer.calls and not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_during_suspended_admission_never_activates(tmp_path):
    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields()))
    enhancer = FakeEnhancer()
    batch = RoteiroBatch(service, enhancer)
    await service._lock.acquire()
    submission = asyncio.create_task(batch.start(original["id"], str(uuid4()), consent()))
    owner_acquired = asyncio.Event()
    acquire = batch.acquire

    def noticed_acquire():
        acquire()
        owner_acquired.set()

    batch.acquire = noticed_acquire
    await owner_acquired.wait()
    assert not submission.done() and batch.task is None
    await batch.shutdown()
    service._lock.release()
    with pytest.raises(Conflict, match="stopped during batch admission"):
        await submission
    assert batch.task is None and batch.lock_fd is None
    assert batch.current() == {"batch": None}
    assert not enhancer.calls and not service.comfy.submitted
    assert not list((tmp_path / ".data" / "roteiro-batches").glob("*.json"))
    await service.shutdown()


@pytest.mark.asyncio
async def test_invalid_provider_scene_is_preserved_without_native_fallback(tmp_path):
    import hashlib
    import json

    service, roteiro = setup(tmp_path)
    original = await roteiro.create(CreatePlan(**fields()))
    returned = "x" * 12001

    class InvalidEnhancer(FakeEnhancer):
        async def complete(self, request):
            self.calls.append(request)
            return {"text": returned, "model": request.model}

    enhancer = InvalidEnhancer()
    batch = RoteiroBatch(service, enhancer)
    ident = str(uuid4())
    await batch.start(original["id"], ident, consent())
    await batch.task
    current = batch.get(original["id"], ident)
    assert current["state"] == "stopped" and current["current_run_id"] is None
    enhancement_id = current["enhancement_ids"][0]
    record = json.loads((tmp_path / ".data" / "roteiro-batches" /
                         f"enhancement-{enhancement_id}.json").read_text())
    assert record["state"] == "invalid_received" and record["text"] == returned
    assert record["response_characters"] == record["response_bytes"] == 12001
    assert record["response_sha256"] == hashlib.sha256(returned.encode()).hexdigest()
    assert not service.comfy.submitted and not roteiro.get(original["id"]).attempts
    assert roteiro.get(original["id"]).revision == 1 and len(enhancer.calls) == 1
    with pytest.raises(Conflict, match="previous text enhancement"):
        await batch.start(original["id"], str(uuid4()), consent())
    await service.shutdown()
