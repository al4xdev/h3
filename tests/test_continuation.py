import pytest
from test_service import make_service

from h3_backend.generation.models import ContinueRequest, RunRequest


@pytest.mark.asyncio
async def test_workflow_selection_and_literal_prompt(tmp_path):
    service = make_service(tmp_path)
    parent = await service.create(RunRequest(seed=1, duration_seconds=2.3))
    await service._task
    await service.decide(parent.id, True)
    markdown = "# Exact\n\n<Picture 1> start  \n<Picture 2> identity\n<Video 1> motion\n"
    child = await service.continue_run(parent.id, ContinueRequest(seed=2, duration_seconds=2.3, prompt=markdown))
    await service._task
    result = service.store.get(child.id)
    assert result.workflow_hash == "anchored-sha"
    assert len(service.builder.calls) == 2
    assert [call["operation"] for call in service.builder.calls] == ["i2v", "v2v"]
    assert service.builder.validations == ["i2v", "v2v"]
    assert service.builder.calls[1]["prompt"] == markdown
    assert result.prompt == result.input_info["effective_markdown"] == markdown
    assert (service.store.directory(child.id) / "prompt.md").read_bytes() == markdown.encode()
    await service.shutdown()


@pytest.mark.asyncio
async def test_nine_initial_identities_cannot_continue(tmp_path):
    service = make_service(tmp_path)
    images = []
    for index in range(8):
        name = f"identity{index}.png"
        (tmp_path / "assets" / name).write_bytes(f"image{index}".encode())
        images.append(name)
    parent = await service.create(RunRequest(seed=1, duration_seconds=2.3, images=images))
    await service._task
    await service.decide(parent.id, True)
    with pytest.raises(ValueError, match="eight"):
        await service.continue_run(parent.id, ContinueRequest(seed=2, duration_seconds=2.3))
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,source", [("unknown", "dance_reference.png"),
                                         (None, "../outside.png")])
async def test_ambiguous_or_unsafe_legacy_parent_rejected(tmp_path, role, source):
    service = make_service(tmp_path)
    parent = await service.create(RunRequest(seed=1, duration_seconds=2.3))
    await service._task
    original = service.store.get(parent.id).references[0]
    reference = {**original, "source": source}
    reference.pop("role")
    if role:
        reference["role"] = role
    service.store.update(parent.id, references=[reference])
    await service.decide(parent.id, True)
    with pytest.raises(ValueError):
        await service.continue_run(parent.id, ContinueRequest(seed=2, duration_seconds=2.3))
    assert len(service.comfy.submitted) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_legacy_assets_identity_is_supported(tmp_path):
    service = make_service(tmp_path)
    parent = await service.create(RunRequest(seed=1, duration_seconds=2.3))
    await service._task
    reference = service.store.get(parent.id).references[0]
    reference.pop("role")
    service.store.update(parent.id, references=[reference])
    await service.decide(parent.id, True)
    child = await service.continue_run(parent.id, ContinueRequest(seed=2, duration_seconds=2.3))
    await service._task
    assert service.store.get(child.id).references[1]["role"] == "identity"
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["./dance_reference.png", "alias.png"])
async def test_resolved_identity_aliases_rejected_at_admission_and_inheritance(tmp_path, alias):
    service = make_service(tmp_path)
    if alias == "alias.png":
        (tmp_path / "assets" / alias).symlink_to("dance_reference.png")
    with pytest.raises(ValueError, match="Duplicate|symlinks"):
        await service.create(RunRequest(seed=1, duration_seconds=2.3, images=[alias]))
    assert not service.comfy.submitted
    parent = await service.create(RunRequest(seed=1, duration_seconds=2.3))
    await service._task
    reference = service.store.get(parent.id).references[0]
    service.store.update(parent.id, references=[reference, {**reference, "source": alias}])
    await service.decide(parent.id, True)
    with pytest.raises(ValueError, match="Duplicate|symlinks"):
        await service.continue_run(parent.id, ContinueRequest(seed=2, duration_seconds=2.3))
    assert len(service.comfy.submitted) == 1
    await service.shutdown()
