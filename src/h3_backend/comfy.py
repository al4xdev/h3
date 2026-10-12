"""Comfy transport: no shared queue mutations and no inference polling."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import websockets


class ComfyError(RuntimeError):
    pass


class QueueBusy(ComfyError):
    pass


class ExecutionInterrupted(ComfyError):
    pass


def terminal_event(event: dict, prompt_id: str) -> str | None:
    data = event.get("data", {})
    if data.get("prompt_id") != prompt_id:
        return None
    kind = event.get("type")
    if kind == "execution_error":
        return "failed"
    if kind == "execution_interrupted":
        return "interrupted"
    if kind == "execution_success" or (
        kind == "executing" and "node" in data and data["node"] is None
    ):
        return "success"
    # `executed` describes a single node, including cached/preview outputs.
    return None


def history_terminal(history: dict, prompt_id: str) -> dict | None:
    entry = history.get(prompt_id)
    if not isinstance(entry, dict):
        return None
    status = entry.get("status", {})
    if status.get("status_str") == "error":
        raise ComfyError("History reports execution error")
    if status.get("completed") is True and status.get("status_str") == "success":
        return entry
    return None


class ComfyClient:
    def __init__(self, url: str, *, http: httpx.AsyncClient | None = None, connector=None):
        self.url = url.rstrip("/")
        self.http = http or httpx.AsyncClient(
            base_url=self.url, timeout=httpx.Timeout(60, connect=10)
        )
        self._owns_http = http is None
        self.connector = connector or websockets.connect

    async def close(self):
        if self._owns_http:
            await self.http.aclose()

    async def _get(self, path: str) -> dict:
        response = await self.http.get(path)
        response.raise_for_status()
        return response.json()

    async def system_stats(self) -> dict:
        return await self._get("/system_stats")

    async def object_info(self) -> dict:
        return await self._get("/object_info")

    async def ensure_idle(self) -> None:
        queue = await self._get("/queue")
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise QueueBusy("ComfyUI has an existing job; nothing was submitted")

    async def upload(self, path: Path, name: str) -> dict:
        with path.open("rb") as stream:
            response = await self.http.post(
                "/upload/image",
                files={"image": (name, stream, "application/octet-stream")},
                data={"type": "input", "overwrite": "false"},
            )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result.get("name"), str) or result.get("type", "input") != "input":
            raise ComfyError("Invalid upload response")
        filename = Path(result["name"])
        subfolder = Path(result.get("subfolder", ""))
        if (
            filename.is_absolute()
            or len(filename.parts) != 1
            or ".." in filename.parts
            or subfolder.is_absolute()
            or ".." in subfolder.parts
            or "\\" in str(filename)
            or "\\" in str(subfolder)
        ):
            raise ComfyError("Unsafe uploaded filename")
        return {**result, "filename": (subfolder / filename).as_posix() + " [input]"}

    async def history(self, prompt_id: str) -> dict:
        return await self._get(f"/history/{prompt_id}")

    async def cancel(self, prompt_id: str) -> None:
        response = await self.http.post(f"/api/jobs/{prompt_id}/cancel")
        response.raise_for_status()

    def ws_url(self, client_id: str) -> str:
        parsed = urlsplit(self.url)
        return urlunsplit(
            (
                "wss" if parsed.scheme == "https" else "ws",
                parsed.netloc,
                parsed.path + "/ws",
                urlencode({"clientId": client_id}),
                "",
            )
        )

    @asynccontextmanager
    async def _socket(self, client_id: str):
        async with self.connector(
            self.ws_url(client_id), open_timeout=10, close_timeout=5
        ) as socket:
            yield socket

    async def execute(
        self,
        workflow: dict,
        *,
        prompt_id: str,
        deadline: float,
        on_submitted: Callable[[str], Awaitable[None]],
        on_progress: Callable[[dict], Awaitable[None]],
        extra_pnginfo: dict | None = None,
    ) -> dict:
        client_id = str(uuid4())
        submitted = False
        try:
            async with asyncio.timeout(deadline):
                async with self._socket(client_id) as socket:
                    await self.ensure_idle()
                    # Persist the supplied ID before the HTTP call: a timeout may still enqueue it.
                    await on_submitted(prompt_id)
                    submitted = True
                    payload = {"prompt": workflow, "client_id": client_id, "prompt_id": prompt_id}
                    if extra_pnginfo is not None:
                        payload["extra_data"] = {"extra_pnginfo": extra_pnginfo}
                    response = await self.http.post("/prompt", json=payload)
                    response.raise_for_status()
                    if response.json().get("prompt_id") != prompt_id:
                        raise ComfyError("ComfyUI did not preserve the supplied prompt ID")
                    try:
                        await self._consume(socket, prompt_id, on_progress)
                    except (websockets.exceptions.ConnectionClosed, OSError):
                        # Open the replacement before checking history to close the completion gap.
                        # One recovery history read; subsequent terminal success gets one result read.
                        checked = False
                        for attempt in range(2):
                            try:
                                async with self._socket(client_id) as replacement:
                                    checked = True
                                    entry = history_terminal(
                                        await self.history(prompt_id), prompt_id
                                    )
                                    if entry is not None:
                                        return entry
                                    await self._consume(replacement, prompt_id, on_progress)
                                break
                            except (websockets.exceptions.ConnectionClosed, OSError):
                                if checked or attempt == 1:
                                    raise ExecutionInterrupted(
                                        "WebSocket reconnect exhausted; outcome unknown"
                                    )
                        # A terminal event after the one recovery check authorizes one result read.
                        return self._completed(await self.history(prompt_id), prompt_id)
                    return self._completed(await self.history(prompt_id), prompt_id)
        except BaseException:
            if submitted:
                # Only the caller-supplied UUID is ever canceled, including uncertain HTTP outcomes.
                try:
                    await asyncio.shield(self.cancel(prompt_id))
                except (httpx.HTTPError, OSError, ComfyError) as exc:
                    logging.getLogger(__name__).warning(
                        "Could not cancel own prompt %s: %s", prompt_id, exc
                    )
            raise

    @staticmethod
    def _completed(history: dict, prompt_id: str) -> dict:
        entry = history_terminal(history, prompt_id)
        if entry is None:
            raise ComfyError("Terminal event without confirmed successful history")
        return entry

    async def _consume(self, socket, prompt_id: str, on_progress) -> None:
        while True:
            message = await socket.recv()
            if isinstance(message, bytes):
                continue
            event = json.loads(message)
            terminal = terminal_event(event, prompt_id)
            if terminal == "success":
                return
            if terminal == "failed":
                raise ComfyError(str(event.get("data", {})))
            if terminal == "interrupted":
                raise ExecutionInterrupted("Own prompt was interrupted")
            data = event.get("data", {})
            if data.get("prompt_id") == prompt_id and event.get("type") in {
                "progress",
                "executing",
                "execution_start",
            }:
                await on_progress({"type": event["type"], **data})
