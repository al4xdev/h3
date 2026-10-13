"""Native fake dispatcher admission, fixed-ID recovery and immutable histories."""

import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
from test_roteiro import fields, setup, update

from h3_backend.generation.dispatcher import Conflict
from h3_backend.generation.i2v import I2VPipe
from h3_backend.generation.models import ContinueRequest, RunRequest
from h3_backend.generation.v2v import V2VPipe
from h3_backend.generation.workflow import I2V_CONFIG, V2V_CONFIG
from h3_backend.roteiro import CreatePlan, Generate


def request(doc, index=0, parent=None, **changes):
    block = doc.blocks[index]
    return Generate(expected_revision=doc.revision, prompt=changes.get("prompt", block.prompt),
                    seed=changes.get("seed", block.seed),
                    duration_seconds=changes.get("duration_seconds", block.duration_seconds),
                    parent_id=parent)


async def create(op, **kwargs):
    result = await op.create(CreatePlan(**fields(**kwargs)))
    return op.get(result["id"])


@pytest.mark.asyncio
async def test_intent_before_admission_actual_native_uuid_get_and_duplicate_fenced(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    ident = str(uuid4())
    original = service.submit

    async def checked(pipe):
        persisted = op.get(doc.id).attempts[0]
        assert persisted.intent_id == ident == pipe.state.run_id
        assert persisted.snapshot.prompt == doc.blocks[0].prompt
        assert persisted.admission == "uncertain"
        assert persisted.snapshot.reference_sha256 == doc.reference_sha256
        return await original(pipe)

    service.submit = checked
    result = await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    assert result["run_id"] == ident and result["admission"] == "admitted"
    assert result["snapshot"]["reference"]["sha256"] == doc.reference_sha256
    await service._task
    seen = op.observed(op.intent(op.get(doc.id), doc.blocks[0].id, ident))
    assert seen["state"] == "ready_for_review"
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, ident, request(doc, prompt="different"))
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_same_id_recovery_after_unexpected_failure_after_native_admission(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    original = service.submit
    ident = str(uuid4())

    async def lost(pipe):
        await original(pipe)
        raise RuntimeError("Response lost")

    service.submit = lost
    result = await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    assert result["run_id"] == ident and result["admission"] == "admitted"
    await service._task
    assert op.observed(op.get(doc.id).attempts[0])["state"] == "ready_for_review"
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, str(uuid4()), request(doc))
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_missing_run_after_in_flight_is_uncertain_not_permission_to_post(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)

    async def lost(pipe):
        raise OSError("External crash before response; absence is not a retry license")

    service.submit = lost
    ident = str(uuid4())
    result = await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    assert result["admission"] == "uncertain" and result["state"] == "uncertain"
    assert result["run"] is None and result["run_id"] == ident
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, str(uuid4()), request(doc))
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_known_native_slot_rejection_persisted_not_admitted(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    service._active = str(uuid4())
    ident = str(uuid4())
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    attempt = op.intent(op.get(doc.id), doc.blocks[0].id, ident)
    assert op.observed(attempt)["state"] == "not_admitted"
    assert attempt.admission == "rejected"
    service._active = None
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_changed_reference_is_known_preflight_rejected_never_native(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    (tmp_path / "assets" / "dance_reference.png").write_bytes(b"changed")
    ident = str(uuid4())
    with pytest.raises((ValueError, Conflict)):
        await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    assert op.observed(op.get(doc.id).attempts[0])["state"] == "not_admitted"
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_concrete_accepted_predecessor_and_frozen_submitted_prefix(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op, count=3)
    first_id = str(uuid4())
    await op.generate(doc.id, doc.blocks[0].id, first_id, request(doc))
    await service._task
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[1].id, str(uuid4()), request(doc, 1, first_id))
    await service.decide(first_id, True)
    changed = [doc.blocks[0], doc.blocks[2], doc.blocks[1]]
    await op.update(doc.id, update(doc, blocks=changed))
    fresh = op.get(doc.id)
    assert fresh.blocks[0] == doc.blocks[0]
    with pytest.raises(Conflict):
        await op.update(fresh.id, update(fresh, blocks=list(reversed(fresh.blocks))))
    foreign = await service.create(RunRequest(seed=9, duration_seconds=2.3))
    await service._task
    await service.decide(foreign.id, True)
    with pytest.raises(Conflict):
        await op.generate(fresh.id, fresh.blocks[1].id, str(uuid4()), request(fresh, 1, foreign.id))
    child_id = str(uuid4())
    child = await op.generate(fresh.id, fresh.blocks[1].id, child_id, request(fresh, 1, first_id))
    await service._task
    assert child["snapshot"]["parent_id"] == first_id
    assert service.store.request(child_id).input_info["continuation"]["reference_tail_seconds"] == 3
    assert service.store.request(child_id).input_info["continuation"]["include_audio"] is True
    with pytest.raises(Conflict):
        await op.update(fresh.id, update(fresh, blocks=[fresh.blocks[1], fresh.blocks[0], fresh.blocks[2]]))
    await service.shutdown()


@pytest.mark.asyncio
async def test_retry_preserves_history_and_original_parent_with_literal_chosen_prompt(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    first_id = str(uuid4())
    await op.generate(doc.id, doc.blocks[0].id, first_id, request(doc))
    await service._task
    await service.decide(first_id, True)
    rejected = str(uuid4())
    await op.generate(doc.id, doc.blocks[1].id, rejected, request(doc, 1, first_id))
    await service._task
    await service.decide(rejected, False)
    original = service.store.get(rejected).model_dump()
    original_snapshot = op.get(doc.id).attempts[-1].snapshot.model_dump()
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[1].id, str(uuid4()), request(doc, 1, rejected))
    retry = str(uuid4())
    result = await op.generate(doc.id, doc.blocks[1].id, retry,
                               request(doc, 1, first_id, prompt="FINAL literal revised", seed=99))
    await service._task
    assert result["snapshot"]["prompt"] == "FINAL literal revised"
    assert result["snapshot"]["parent_id"] == first_id
    assert service.store.get(rejected).model_dump() == original
    assert op.get(doc.id).attempts[-2].snapshot.model_dump() == original_snapshot
    assert len(service.comfy.submitted) == 3
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("alteration", ["prompt", "seed", "parent", "sha", "marker"])
async def test_read_recovery_requires_exact_owned_native_snapshot(tmp_path, alteration):
    service, op = setup(tmp_path)
    doc = await create(op)
    ident = str(uuid4())
    await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    await service._task
    if alteration == "marker":
        path = tmp_path / ".data" / "roteiros" / ".locks" / f"{ident}.json"
        value = json.loads(path.read_text())
        value["roteiro_id"] = str(uuid4())
        path.write_text(json.dumps(value))
    else:
        for name in ("request.json", "manifest.json"):
            path = service.store.directory(ident) / name
            value = json.loads(path.read_text())
            if alteration == "prompt":
                value["prompt"] = "another"
            elif alteration == "seed":
                value["seed"] += 1
            elif alteration == "parent":
                value["parent_id"] = str(uuid4())
            else:
                value["references"][0]["sha256"] = "0" * 64
            path.write_text(json.dumps(value))
    assert op.observed(op.get(doc.id).attempts[0])["state"] == "uncertain"
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, str(uuid4()), request(doc))
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_low_ram_not_consulted_default8_exact_native_configuration(tmp_path):
    service, op = setup(tmp_path)
    service._memory_available = lambda: pytest.fail("No RAM policy calls permitted")
    payload = fields(count=1)
    payload["blocks"][0]["duration_seconds"] = 8
    doc = op.get((await op.create(CreatePlan(**payload)))["id"])
    ident = str(uuid4())
    result = await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    assert result["run"]["duration_seconds"] == 8
    admitted = service.store.request(ident)
    assert admitted.duration_seconds == 8 and admitted.seed == 2026101205
    assert service.frames_for_duration(admitted.duration_seconds) == 192
    # The fake probe is intentionally 56 frames, so worker failure is honest, not ready/success.
    await service._task
    assert service.store.get(ident).state == "failed"
    await service.shutdown()


@pytest.mark.asyncio
async def test_native_predetermined_setter_pure_strict_and_legacy_default(tmp_path):
    service, _op = setup(tmp_path)
    ident = str(uuid4())
    for pipe in (I2VPipe(service), V2VPipe(service)):
        assert pipe.with_run_id(ident) is pipe
        assert pipe.state.run_id == ident and pipe.state.run is None
        for invalid in (ident.upper(), "../", "", None, 7):
            with pytest.raises((ValueError, TypeError)):
                pipe.with_run_id(invalid)
    assert not list(service.store.runs.iterdir()) and not service.comfy.submitted
    pipe = (I2VPipe(service).have(RunRequest(seed=3, duration_seconds=2.3))
            .with_workflow(I2V_CONFIG).save_chunk().with_run_id(ident))
    run = await service.submit(pipe)
    assert run.id == ident
    with pytest.raises(Conflict):
        pipe.with_run_id(str(uuid4()))
    with pytest.raises(Conflict):
        pipe.with_identity_proof("assets", "dance_reference.png", "a" * 64)
    await service._task
    legacy = await service.create(RunRequest(seed=4, duration_seconds=2.3))
    assert legacy.id != ident
    await service._task
    await service.shutdown()


@pytest.mark.asyncio
async def test_global_uuid_reserved_across_documents_no_foreign_association(tmp_path):
    service, op = setup(tmp_path)
    first = await create(op)
    second = await create(op)
    ident = str(uuid4())

    async def lost(pipe):
        raise OSError("unknown native admission")

    service.submit = lost
    await op.generate(first.id, first.blocks[0].id, ident, request(first))
    with pytest.raises(Conflict):
        await op.generate(second.id, second.blocks[0].id, ident, request(second))
    assert op.observed(op.get(first.id).attempts[0])["state"] == "uncertain"
    assert op.observed(op.get(second.id).attempts[0])["state"] == "not_admitted"
    assert not service.comfy.submitted
    await service.shutdown()


@pytest.mark.asyncio
async def test_cancellation_between_intent_and_native_remains_uncertain_no_replay(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    entered = asyncio.Event()

    async def wait(pipe):
        entered.set()
        await asyncio.Event().wait()

    service.submit = wait
    ident = str(uuid4())
    task = asyncio.create_task(op.generate(doc.id, doc.blocks[0].id, ident, request(doc)))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert op.observed(op.get(doc.id).attempts[0])["state"] == "uncertain"
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, str(uuid4()), request(doc))
    await service.shutdown()


@pytest.mark.asyncio
async def test_partial_native_commit_before_pipe_seal_never_marked_not_admitted(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    original = service.store.create

    def crash_after_commit(run, **kwargs):
        original(run, **kwargs)
        raise ValueError("Crash after native request.json publication, before pipe seal")

    service.store.create = crash_after_commit
    ident = str(uuid4())
    result = await op.generate(doc.id, doc.blocks[0].id, ident, request(doc))
    assert result["run_id"] == ident and result["admission"] == "admitted"
    assert result["state"] == "queued"
    assert op.get(doc.id).attempts[0].admission == "uncertain"
    assert service._task is None and not service.comfy.submitted
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, str(uuid4()), request(doc))
    await service.shutdown()


@pytest.mark.asyncio
async def test_parent_changed_after_intent_before_native_is_known_rejection(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    parent_id = str(uuid4())
    await op.generate(doc.id, doc.blocks[0].id, parent_id, request(doc))
    await service._task
    await service.decide(parent_id, True)
    original = op.reference_digest

    async def changed(reference):
        digest = await original(reference)
        path = service.store.directory(parent_id) / "manifest.json"
        data = json.loads(path.read_text())
        data["state"] = "rejected"
        data["decision"] = {"accepted": False}
        path.write_text(json.dumps(data))
        return digest

    op.reference_digest = changed
    ident = str(uuid4())
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[1].id, ident, request(doc, 1, parent_id))
    assert op.observed(op.get(doc.id).attempts[-1])["state"] == "not_admitted"
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_preexisting_native_run_uuid_not_claimed_by_new_roteiro(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    native = await service.create(RunRequest(seed=3, duration_seconds=2.3))
    await service._task
    with pytest.raises(Conflict):
        await op.generate(doc.id, doc.blocks[0].id, native.id, request(doc))
    assert op.get(doc.id).attempts == []
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_child_get_rechecks_original_accepted_owned_ancestor_proof(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    parent_id = str(uuid4())
    await op.generate(doc.id, doc.blocks[0].id, parent_id, request(doc))
    await service._task
    await service.decide(parent_id, True)
    child_id = str(uuid4())
    await op.generate(doc.id, doc.blocks[1].id, child_id, request(doc, 1, parent_id))
    await service._task
    assert op.observed(op.get(doc.id).attempts[-1])["state"] == "ready_for_review"
    path = service.store.directory(parent_id) / "manifest.json"
    value = json.loads(path.read_text())
    value["decision"] = {"accepted": False}
    path.write_text(json.dumps(value))
    recovered = op.observed(op.get(doc.id).attempts[-1])
    assert recovered["run_id"] == child_id and recovered["state"] == "uncertain"
    assert recovered["run"] is None
    assert len(service.comfy.submitted) == 2
    await service.shutdown()


@pytest.mark.asyncio
async def test_native_await_does_not_hold_plan_lock_or_overwrite_future_edits(tmp_path):
    service, op = setup(tmp_path)
    doc = await create(op)
    gate, entered = asyncio.Event(), asyncio.Event()
    original = service.submit

    async def waiting(pipe):
        entered.set()
        await gate.wait()
        return await original(pipe)

    service.submit = waiting
    ident = str(uuid4())
    task = asyncio.create_task(op.generate(doc.id, doc.blocks[0].id, ident, request(doc)))
    await asyncio.wait_for(entered.wait(), 5)
    future = doc.blocks[1].model_copy(update={"action": "Novo futuro"})
    await op.update(doc.id, update(doc, name="Editado durante envio",
                                   blocks=[doc.blocks[0], future]))
    assert op.observed(op.get(doc.id).attempts[0])["state"] == "uncertain"
    gate.set()
    result = await task
    await service._task
    final = op.get(doc.id)
    assert final.revision == 2 and final.name == "Editado durante envio"
    assert final.blocks[1].action == "Novo futuro"
    assert final.attempts[0].source_revision == 1 and result["run_id"] == ident
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_reference_race_between_roteiro_preflight_and_native_hash_never_admits(tmp_path, kind):
    service, op = setup(tmp_path)
    doc = await create(op)
    parent_id = None
    index = 0
    if kind == "v2v":
        parent_id = str(uuid4())
        await op.generate(doc.id, doc.blocks[0].id, parent_id, request(doc))
        await service._task
        await service.decide(parent_id, True)
        index = 1
    previous_task = service._task
    previous_calls = len(service.comfy.submitted)
    previous_validations = list(service.builder.validations)
    original_verify = service.media.verify_image
    creates = []
    original_create = service.store.create

    def replace_bytes_before_native_hash(path):
        path.write_bytes(path.read_bytes() + b"changed-between-preflight-and-native-hash")
        return original_verify(path)

    def track_create(*args, **kwargs):
        creates.append(args[0].id)
        return original_create(*args, **kwargs)

    async def forbidden_comfy():
        pytest.fail("Changed identity must reject before Comfy idle/schema I/O")

    service.media.verify_image = replace_bytes_before_native_hash
    service.store.create = track_create
    service.comfy.ensure_idle = forbidden_comfy
    ident = str(uuid4())
    with pytest.raises(ValueError):
        await op.generate(doc.id, doc.blocks[index].id, ident, request(doc, index, parent_id))
    assert creates == [] and not service.store.directory(ident).exists()
    assert service._task is previous_task and service._active is None
    assert len(service.comfy.submitted) == previous_calls
    assert service.builder.validations == previous_validations
    assert op.observed(op.get(doc.id).attempts[-1])["state"] == "not_admitted"
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_optional_identity_projection_setter_is_strict_pure_and_single_source(tmp_path, kind):
    service, _op = setup(tmp_path)
    pipe = I2VPipe(service) if kind == "i2v" else V2VPipe(service)
    sha = "a" * 64
    assert pipe.with_identity_proof("assets", "dance_reference.png", sha) is pipe
    assert pipe.state.identity_proof == ("assets", "dance_reference.png", sha)
    for root, path, digest in (("private", "secret.png", sha), ("assets", "../private", sha),
                               ("assets", "x.png", "A" * 64), ("assets", "x.png", "x" * 64),
                               ("assets", "x.png", "a" * 63), ("assets", "x.png", None),
                               ("assets", True, sha)):
        with pytest.raises(ValueError):
            pipe.with_identity_proof(root, path, digest)
    assert not list(service.store.runs.iterdir())
    assert service._task is None and not service.comfy.submitted and not service.builder.validations
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["i2v", "v2v"])
async def test_optional_proof_rejects_extra_native_identities_without_materialization(tmp_path, kind):
    service, _op = setup(tmp_path)
    source = tmp_path / "assets" / "dance_reference.png"
    (tmp_path / "assets" / "second.png").write_bytes(source.read_bytes())
    native = RunRequest(seed=1, duration_seconds=2.3, images=["second.png"])
    if kind == "i2v":
        pipe = I2VPipe(service).have(native).with_workflow(I2V_CONFIG).save_chunk()
    else:
        parent = await service.create(native)
        await service._task
        await service.decide(parent.id, True)
        pipe = (V2VPipe(service).have(ContinueRequest(seed=2, duration_seconds=2.3))
                .from_parent(parent.id).with_last_frame().with_original_identity()
                .with_motion_tail().with_workflow(V2V_CONFIG).save_chunk())
    previous = len(service.comfy.submitted)
    ident = str(uuid4())
    pipe.with_run_id(ident).with_identity_proof("assets", "dance_reference.png",
                                               hashlib.sha256(source.read_bytes()).hexdigest())

    async def forbidden_idle():
        pytest.fail("Exact one-source projection must reject before Comfy I/O")

    service.comfy.ensure_idle = forbidden_idle
    with pytest.raises(Conflict):
        await service.submit(pipe)
    assert not service.store.directory(ident).exists()
    assert len(service.comfy.submitted) == previous
    await service.shutdown()
