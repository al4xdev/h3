import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError

from h3_backend.comfy import ComfyClient, QueueBusy, terminal_event


class Socket:
    def __init__(self, events):
        self.events = iter(events)

    async def recv(self):
        event = next(self.events)
        if isinstance(event, BaseException):
            raise event
        return json.dumps(event)


class Connector:
    def __init__(self, sockets, order):
        self.sockets = iter(sockets)
        self.order = order

    @asynccontextmanager
    async def __call__(self, url, **kwargs):
        self.order.append("ws")
        yield next(self.sockets)


async def noop(*args):
    pass


def event(kind, prompt_id, **data):
    return {"type": kind, "data": {"prompt_id": prompt_id, **data}}


def test_wrong_id_and_intermediate_are_not_terminal():
    assert terminal_event(event("execution_success", "other"), "own") is None
    assert terminal_event(event("executed", "own", node="34"), "own") is None
    assert terminal_event(event("executing", "own", node="18"), "own") is None
    assert terminal_event(event("executing", "own", node=None), "own") == "success"


@pytest.mark.asyncio
async def test_ws_before_submit_terminal_history_once_and_actual_id():
    prompt_id = str(uuid4())
    order, histories, progress = [], [], []
    envelope = {"workflow": {"extra": {"VHS_MetadataImage": False, "VHS_KeepIntermediate": False}}}

    def handler(request):
        order.append(request.url.path)
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if request.url.path == "/prompt":
            assert json.loads(request.content)["prompt_id"] == prompt_id
            assert json.loads(request.content)["extra_data"]["extra_pnginfo"] == envelope
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path.startswith("/history/"):
            histories.append(request.url.path)
            return httpx.Response(
                200,
                json={
                    prompt_id: {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"34": {}},
                    }
                },
            )
        raise AssertionError(request.url)

    async def track(data):
        progress.append(data)

    socket = Socket(
        [
            event("execution_success", "other"),
            event("executed", prompt_id, node="18"),
            event("progress", prompt_id, value=1, max=2),
            event("execution_success", prompt_id),
            event("execution_success", prompt_id),
        ]
    )
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector([socket], order))
        result = await client.execute(
            {},
            prompt_id=prompt_id,
            deadline=5,
            on_submitted=noop,
            on_progress=track,
            extra_pnginfo=envelope,
        )
    assert order[0] == "ws"
    assert order.index("ws") < order.index("/prompt")
    assert len(histories) == 1
    assert len(progress) == 1 and progress[0]["prompt_id"] == prompt_id
    assert "34" in result["outputs"]


@pytest.mark.asyncio
async def test_disconnect_completed_history_never_resubmits():
    prompt_id = str(uuid4())
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/queue":
            return httpx.Response(200, json={})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path.startswith("/history/"):
            return httpx.Response(
                200,
                json={
                    prompt_id: {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {},
                    }
                },
            )
        raise AssertionError(request.url)

    connector = Connector([Socket([ConnectionClosedError(None, None)]), Socket([])], [])
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=connector)
        await client.execute(
            {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
        )
    assert calls.count("/prompt") == 1
    assert sum(p.startswith("/history/") for p in calls) == 1


@pytest.mark.asyncio
async def test_external_queue_aborts_without_submission_or_cancel():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"queue_running": [[1, "external"]]})

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector([Socket([])], []))
        with pytest.raises(QueueBusy):
            await client.execute(
                {}, prompt_id=str(uuid4()), deadline=5, on_submitted=noop, on_progress=noop
            )
    assert calls == ["/queue"]


@pytest.mark.asyncio
async def test_shutdown_cancel_targets_only_own_id():
    prompt_id = str(uuid4())
    submitted = asyncio.Event()
    calls = []

    class WaitingSocket:
        async def recv(self):
            await asyncio.Future()

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            submitted.set()
            return httpx.Response(200, json={"prompt_id": prompt_id})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector([WaitingSocket()], []))
        task = asyncio.create_task(
            client.execute({}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop)
        )
        await submitted.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert f"/api/jobs/{prompt_id}/cancel" in calls
    assert not any(p in {"/interrupt", "/free"} for p in calls)


@pytest.mark.asyncio
async def test_recovery_reads_history_after_replacement_is_open():
    prompt_id = str(uuid4())
    order = []
    connector = Connector([Socket([ConnectionClosedError(None, None)]), Socket([])], order)

    def handler(request):
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path.startswith("/history/"):
            # Completion occurs in the disconnect/reconnect gap. No event is replayed.
            assert order.count("ws") == 2
            order.append("history")
            return httpx.Response(
                200,
                json={
                    prompt_id: {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {},
                    }
                },
            )
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=connector)
        await client.execute(
            {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
        )
    assert order == ["ws", "ws", "history"]


@pytest.mark.asyncio
async def test_reconnect_pending_then_terminal_gets_result_without_resubmit():
    prompt_id = str(uuid4())
    calls = []
    history_count = 0

    def handler(request):
        nonlocal history_count
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path.startswith("/history/"):
            history_count += 1
            return httpx.Response(
                200,
                json={}
                if history_count == 1
                else {
                    prompt_id: {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {},
                    }
                },
            )
        return httpx.Response(200, json={})

    events = [
        event("execution_success", "external"),
        event("executed", prompt_id, node="34"),
        event("executing", prompt_id, node=None),
        event("execution_success", prompt_id),
    ]
    connector = Connector([Socket([ConnectionClosedError(None, None)]), Socket(events)], [])
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=connector)
        await client.execute(
            {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
        )
    assert calls.count("/prompt") == 1
    assert history_count == 2  # one recovery check, one terminal output read
    assert not any("cancel" in path for path in calls)
