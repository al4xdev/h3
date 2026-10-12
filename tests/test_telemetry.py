import asyncio
import json

from h3_backend.telemetry import record_telemetry


async def test_global_and_process_metrics_are_distinct(tmp_path):
    stop = asyncio.Event()

    class FakeComfy:
        async def system_stats(self):
            stop.set()
            return {"devices": [{"vram_total": 100, "vram_free": 40}]}

    path = tmp_path / "telemetry.jsonl"
    await record_telemetry(FakeComfy(), path, stop)
    samples = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(samples) == 1
    sample = samples[0]
    assert sample["host"]["available_bytes"] > 0
    assert sample["backend"]["rss_bytes"] > 0
    assert "comfyui" in sample
    assert sample["devices"][0]["vram_free"] == 40
