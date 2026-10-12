from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from test_api import Service
from test_store import make_run

from h3_backend.api import create_app
from h3_backend.store import Store


def block(store, parent=None, *, accepted=True, verified=True):
    run = make_run().model_copy(update={
        "parent_id": parent.id if parent else None,
        "state": "accepted" if accepted else "queued",
        "decision": {"accepted": True} if accepted else None,
    })
    if verified:
        run.output = {"path": f"runs/{run.id}/chunk.mp4", "probe": {
            "streams": [{"codec_type": "video", "duration": "2.333333"}]
        }}
    return store.create(run)


def test_sequence_is_ordered_branch_specific_metadata_only(tmp_path, monkeypatch):
    store = Store(tmp_path)
    root = block(store, verified=False)
    child = block(store, root)
    sibling = block(store, root)
    end = block(store, child, accepted=False)
    before = {p: p.read_bytes() for p in tmp_path.glob("runs/*/manifest.json")}
    read_text = Path.read_text

    def only_manifests(path, *args, **kwargs):
        assert path.name == "manifest.json"
        return read_text(path, *args, **kwargs)

    def no_binary_read(*args, **kwargs):
        pytest.fail("Sequence query must not read binary content")

    with monkeypatch.context() as context:
        context.setattr(Path, "read_text", only_manifests)
        context.setattr(Path, "read_bytes", no_binary_read)
        result = store.sequence(end.id)
    assert result["root_id"] == root.id and result["end_run_id"] == end.id
    assert result["schema_version"] == 1
    assert [b["id"] for b in result["blocks"]] == [root.id, child.id, end.id]
    assert [b["index"] for b in result["blocks"]] == [0, 1, 2]
    assert [b["accepted"] for b in result["blocks"]] == [True, True, False]
    assert result["blocks"][0]["duration_source"] == "requested"
    assert result["blocks"][0]["duration_seconds"] == 2.3
    assert result["blocks"][1]["duration_seconds"] == 2.333333
    assert result["blocks"][1]["video_url"] == f"/runs/{child.id}/video"
    assert result["blocks"][-1]["video_url"] is None
    assert [b["id"] for b in store.sequence(sibling.id)["blocks"]] == [root.id, sibling.id]
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("fault", ["cycle", "missing", "invalid_id", "unaccepted", "approval",
                                   "output_escape", "other_chunk", "duration"])
def test_invalid_sequence_rejected(tmp_path, fault):
    store = Store(tmp_path)
    root = block(store)
    run = make_run()
    run.parent_id = root.id
    if fault == "cycle":
        run.parent_id = run.id
    elif fault == "missing":
        run.parent_id = str(uuid4())
    elif fault == "invalid_id":
        run.parent_id = "../outside"
    elif fault == "unaccepted":
        root = block(store, accepted=False)
        run.parent_id = root.id
    elif fault == "approval":
        run.state = "accepted"
        run.decision = {"accepted": False}
    elif fault == "output_escape":
        run.output = {"path": "../secret.mp4"}
    elif fault == "other_chunk":
        run.output = {"path": f"runs/{root.id}/chunk.mp4"}
    else:
        run.output = {"probe": {"streams": [{"codec_type": "video", "duration": "nan"}]}}
    store.create(run)
    with pytest.raises(ValueError):
        store.sequence(run.id)


@pytest.mark.asyncio
async def test_sequence_http_without_inference_or_video_access(tmp_path, monkeypatch):
    service = Service(tmp_path)
    root = block(service.store)
    child = block(service.store, root)

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only sequence must not invoke video operations")

    monkeypatch.setattr(service, "video_path", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(service=service)),
                                 base_url="http://fake") as client:
        response = await client.get(f"/runs/{child.id}/sequence")
        assert response.status_code == 200
        assert [b["id"] for b in response.json()["blocks"]] == [root.id, child.id]
        assert (await client.get(f"/runs/{uuid4()}/sequence")).status_code == 404
        assert (await client.get("/runs/not-a-uuid/sequence")).status_code == 400
    assert not service.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [
    {"path": 7}, {"probe": None}, {"probe": {"streams": None}},
    {"probe": {"streams": [None]}},
    {"probe": {"streams": [{"codec_type": "video", "duration": []}]}},
    {"probe": {"streams": [{"codec_type": "video", "duration": True}]}},
])
async def test_malformed_sequence_metadata_returns_400(tmp_path, output):
    service = Service(tmp_path)
    run = service.store.create(make_run().model_copy(update={"output": output}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(service=service)),
                                 base_url="http://fake") as client:
        assert (await client.get(f"/runs/{run.id}/sequence")).status_code == 400
    assert not service.calls
