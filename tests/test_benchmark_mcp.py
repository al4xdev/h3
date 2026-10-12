"""Keep the real SDK/inert worker contracts inside the cache-free Python suite."""

import os
import subprocess
from pathlib import Path


def test_native_project_mcp_offline_contracts():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", str(root / "tests/test_benchmark_mcp.mjs")],
        cwd=root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fail 0" in result.stdout
