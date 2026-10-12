import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError

from h3_backend.infrastructure.comfy import (
    ComfyClient,
    ComfyError,
    ExecutionInterrupted,
    QueueBusy,
    terminal_event,
)


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


class CommitSocket:
    def __init__(self, events, trace):
        self.events = iter(events)
        self.trace = trace
        self.waiting = asyncio.Event()

    async def recv(self):
        item = next(self.events, None)
        if item is None:
            self.waiting.set()
            await asyncio.Future()
        if isinstance(item, BaseException):
            raise item
        self.trace.append(item)
        return json.dumps(item)


def pending_history(prompt_id):
    return {prompt_id: {"status": {"completed": False, "status_str": "success"}}}


def successful_history(prompt_id):
    return {
        prompt_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {"34": {"videos": [{"filename": "own.mp4"}]}},
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("reconnect", [False, True])
@pytest.mark.parametrize("pending", [{}, "pending"])
async def test_early_success_waits_for_own_post_commit_before_second_read(reconnect, pending):
    prompt_id, foreign_id = str(uuid4()), str(uuid4())
    trace, order, calls, progress = [], [], [], []
    early = {} if pending == {} else pending_history(prompt_id)
    reads = 0
    socket = CommitSocket(
        [
            event("execution_success", prompt_id),
            event("execution_success", prompt_id),
            event("executing", foreign_id, node=None),
            event("execution_error", foreign_id),
            event("execution_interrupted", foreign_id),
            event("executed", prompt_id, node="34"),
            event("executing", prompt_id, node="34"),
            event("progress", prompt_id, value=56, max=56),
            event("executing", prompt_id, node=None),
        ],
        trace,
    )

    def handler(request):
        nonlocal reads
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path == f"/history/{prompt_id}":
            reads += 1
            assert order.count("ws") == (2 if reconnect else 1)
            if reconnect and reads == 1:
                assert not trace  # Replacement is open before its one recovery check.
                return httpx.Response(200, json=early)
            if reads == (2 if reconnect else 1):
                assert trace[-1] == event("execution_success", prompt_id)
                return httpx.Response(200, json=early)
            assert trace[-1] == event("executing", prompt_id, node=None)
            return httpx.Response(200, json=successful_history(prompt_id))
        assert request.url.path == "/queue"
        return httpx.Response(200, json={})

    async def track(data):
        progress.append(data)

    sockets = [Socket([ConnectionClosedError(None, None)]), socket] if reconnect else [socket]
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector(sockets, order))
        result = await client.execute(
            {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=track
        )
    assert result == successful_history(prompt_id)[prompt_id]
    assert calls.count("/prompt") == 1 and reads == (3 if reconnect else 2)
    assert [item["type"] for item in progress] == ["executing", "progress"]
    assert all(item["prompt_id"] == prompt_id for item in progress)
    assert not any("cancel" in path for path in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("reconnect", [False, True])
@pytest.mark.parametrize("failure", ["execution_error", "execution_interrupted", "deadline", "cancel"])
async def test_post_commit_wait_failure_cancels_only_own_without_another_read(reconnect, failure):
    prompt_id, foreign_id = str(uuid4()), str(uuid4())
    calls, trace = [], []
    events = [
        event("execution_success", prompt_id),
        event("executing", foreign_id, node=None),
        event("execution_error", foreign_id),
    ]
    if failure in {"execution_error", "execution_interrupted"}:
        events.append(event(failure, prompt_id, exception_message="own failure"))
    socket = CommitSocket(events, trace)

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        return httpx.Response(200, json={})

    sockets = [Socket([ConnectionClosedError(None, None)]), socket] if reconnect else [socket]
    expected = {
        "execution_error": ComfyError,
        "execution_interrupted": ExecutionInterrupted,
        "deadline": TimeoutError,
        "cancel": asyncio.CancelledError,
    }[failure]
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector(sockets, []))
        if failure == "cancel":
            task = asyncio.create_task(client.execute(
                {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
            ))
            await socket.waiting.wait()
            task.cancel()
            with pytest.raises(expected):
                await task
        else:
            with pytest.raises(expected):
                await client.execute(
                    {}, prompt_id=prompt_id, deadline=0.02 if failure == "deadline" else 5,
                    on_submitted=noop, on_progress=noop,
                )
    assert calls.count("/prompt") == 1
    assert calls.count(f"/history/{prompt_id}") == (2 if reconnect else 1)
    assert calls.count(f"/api/jobs/{prompt_id}/cancel") == 1
    assert all(foreign_id not in path for path in calls)
    assert not any(path in {"/interrupt", "/free"} for path in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("reconnect", [False, True])
@pytest.mark.parametrize("early_success", [False, True])
async def test_post_commit_without_confirmed_history_fails_closed(reconnect, early_success):
    prompt_id = str(uuid4())
    calls, trace = [], []
    events = [event("execution_success", prompt_id)] if early_success else []
    events += [event("executing", prompt_id, node=None)]
    socket = CommitSocket(events, trace)

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        return httpx.Response(200, json={})

    sockets = [Socket([ConnectionClosedError(None, None)]), socket] if reconnect else [socket]
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector(sockets, []))
        with pytest.raises(ComfyError, match="without confirmed successful history"):
            await client.execute(
                {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
            )
    assert calls.count("/prompt") == 1
    assert calls.count(f"/history/{prompt_id}") == 1 + int(reconnect) + int(early_success)
    assert calls.count(f"/api/jobs/{prompt_id}/cancel") == 1
    assert trace[-1] == event("executing", prompt_id, node=None)


@pytest.mark.asyncio
async def test_disconnect_during_commit_wait_rechecks_history_only_after_replacement_open():
    prompt_id = str(uuid4())
    calls, order = [], []
    initial = Socket([event("execution_success", prompt_id), ConnectionClosedError(None, None)])
    replacement = Socket([])

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path == f"/history/{prompt_id}":
            assert order.count("ws") == calls.count(f"/history/{prompt_id}")
            return httpx.Response(200, json={} if len(order) == 1 else successful_history(prompt_id))
        assert request.url.path == "/queue"
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector([initial, replacement], order))
        result = await client.execute(
            {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
        )
    assert result == successful_history(prompt_id)[prompt_id]
    assert calls.count("/prompt") == 1 and calls.count(f"/history/{prompt_id}") == 2
    assert not any("cancel" in path for path in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("reconnect", [False, True])
async def test_disconnect_exhausted_during_commit_wait_cancels_only_own(reconnect):
    prompt_id = str(uuid4())
    calls = []
    waiting = Socket([event("execution_success", prompt_id), ConnectionClosedError(None, None)])
    sockets = (
        [Socket([ConnectionClosedError(None, None)]), waiting]
        if reconnect else [waiting, Socket([ConnectionClosedError(None, None)])]
    )

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"prompt_id": prompt_id} if request.url.path == "/prompt" else {})

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector(sockets, []))
        with pytest.raises(ExecutionInterrupted, match="reconnect exhausted"):
            await client.execute(
                {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
            )
    assert calls.count("/prompt") == 1 and calls.count(f"/history/{prompt_id}") == 2
    assert calls.count(f"/api/jobs/{prompt_id}/cancel") == 1
    assert set(calls) == {"/queue", "/prompt", f"/history/{prompt_id}", f"/api/jobs/{prompt_id}/cancel"}


@pytest.mark.asyncio
@pytest.mark.parametrize("reconnect", [False, True])
@pytest.mark.parametrize("post_commit", [False, True])
async def test_history_error_never_becomes_success_during_commit_wait(reconnect, post_commit):
    prompt_id = str(uuid4())
    calls, trace = [], []
    reads = 0
    events = [event("execution_success", prompt_id), event("executing", prompt_id, node=None)]
    socket = CommitSocket(events, trace)

    def handler(request):
        nonlocal reads
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path == f"/history/{prompt_id}":
            reads += 1
            error_at = 1 + int(reconnect) + int(post_commit)
            value = {} if reads < error_at else {
                prompt_id: {"status": {"completed": True, "status_str": "error"}, "outputs": {"34": {}}}
            }
            return httpx.Response(200, json=value)
        return httpx.Response(200, json={})

    sockets = [Socket([ConnectionClosedError(None, None)]), socket] if reconnect else [socket]
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector(sockets, []))
        with pytest.raises(ComfyError, match="History reports execution error"):
            await client.execute(
                {}, prompt_id=prompt_id, deadline=5, on_submitted=noop, on_progress=noop
            )
    assert reads == 1 + int(reconnect) + int(post_commit)
    assert calls.count("/prompt") == 1 and calls.count(f"/api/jobs/{prompt_id}/cancel") == 1
    assert trace[-1] == events[-1 if post_commit else 0]


@pytest.mark.asyncio
async def test_reconnect_early_success_already_committed_does_not_wait_for_extra_event():
    prompt_id = str(uuid4())
    calls, trace, order = [], [], []
    socket = CommitSocket([event("execution_success", prompt_id)], trace)

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if request.url.path == f"/history/{prompt_id}":
            assert order.count("ws") == 2
            history = {} if calls.count(request.url.path) == 1 else successful_history(prompt_id)
            return httpx.Response(200, json=history)
        assert request.url.path == "/queue"
        return httpx.Response(200, json={})

    sockets = [Socket([ConnectionClosedError(None, None)]), socket]
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as http:
        client = ComfyClient("http://fake", http=http, connector=Connector(sockets, order))
        result = await client.execute(
            {}, prompt_id=prompt_id, deadline=0.1, on_submitted=noop, on_progress=noop
        )
    assert result == successful_history(prompt_id)[prompt_id]
    assert not socket.waiting.is_set()
    assert calls.count("/prompt") == 1 and calls.count(f"/history/{prompt_id}") == 2
    assert not any("cancel" in path for path in calls)
