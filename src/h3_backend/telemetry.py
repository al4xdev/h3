"""Amortized global and per-process measurements, separate from job-completion events."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import psutil


def find_comfy_pid() -> int | None:
    expected = str(Path(os.environ.get("H3_COMFY_ROOT", "/home/alex/comfyui")) / "main.py")
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            if expected in (process.info["cmdline"] or []):
                return process.info["pid"]
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return None


def process_memory(pid: int | None) -> dict[str, Any] | None:
    if pid is None:
        return None
    try:
        process = psutil.Process(pid)
        memory = process.memory_info()
        status = Path(f"/proc/{pid}/status")
        swap = None
        if status.exists():
            for line in status.read_text().splitlines():
                if line.startswith("VmSwap:"):
                    swap = int(line.split()[1]) * 1024
        return {"pid": pid, "rss_bytes": memory.rss, "vms_bytes": memory.vms, "swap_bytes": swap}
    except (psutil.AccessDenied, psutil.NoSuchProcess, FileNotFoundError):
        return None


async def record_telemetry(
    comfy: Any,
    path: Path,
    stop: asyncio.Event,
    comfy_pid: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    pid = comfy_pid if comfy_pid is not None else find_comfy_pid()
    while not stop.is_set():
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        sample: dict[str, Any] = {
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "interval_seconds": 5,
            "host": {
                "total_bytes": memory.total,
                "available_bytes": memory.available,
                "total_minus_available_bytes": memory.total - memory.available,
                "swap_used_bytes": swap.used,
            },
            "backend": process_memory(os.getpid()),
            "comfyui": process_memory(pid),
        }
        try:
            stats = await comfy.system_stats()
            sample["devices"] = stats.get("devices", [])
        except (httpx.HTTPError, OSError, ValueError, RuntimeError) as exc:
            sample["comfy_stats_error"] = f"{type(exc).__name__}: {exc}"
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(sample) + "\n")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
