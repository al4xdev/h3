"""Exercise the shipped launcher with a real Uvicorn socket and open SSE stream."""

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("stop_signal", "batch_error"), [(signal.SIGTERM, False), (signal.SIGINT, True)])
def test_launcher_drains_sse_and_cleans_active_batch(tmp_path, stop_signal, batch_error):
    root = tmp_path / "project"
    root.mkdir()
    with socket.socket() as lease:
        lease.bind(("127.0.0.1", 0))
        port = lease.getsockname()[1]
    shim = tmp_path / "uv"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[:3] == ['run', '--no-sync', 'uvicorn']\n"
        "assert args[3] == 'h3_backend.api:app'\n"
        "assert args[args.index('--timeout-graceful-shutdown') + 1] == '5'\n"
        "assert args[args.index('--host') + 1] == '0.0.0.0'\n"
        "assert args[args.index('--port') + 1] == '8888'\n"
        "assert os.environ['PYTHONDONTWRITEBYTECODE'] == '1'\n"
        "assert os.getcwd() == os.environ['H3_SHUTDOWN_TEST_PROJECT']\n"
        "args = args[3:]\n"
        "args[0] = 'server_shutdown_fixture:create_fixture'\n"
        "args[args.index('--host') + 1] = '127.0.0.1'\n"
        "args[args.index('--port') + 1] = os.environ['H3_SHUTDOWN_TEST_PORT']\n"
        "os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', *args, '--factory'])\n"
    )
    shim.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": f"{PROJECT / 'tests'}{os.pathsep}{PROJECT / 'src'}",
        "H3_SHUTDOWN_TEST_PROJECT": str(PROJECT),
        "H3_SHUTDOWN_TEST_ROOT": str(root),
        "H3_SHUTDOWN_TEST_PORT": str(port),
        "H3_SHUTDOWN_TEST_BATCH_ERROR": str(int(batch_error)),
    }
    connection = None
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen([str(PROJECT / "start.sh")], cwd=tmp_path, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            url = f"http://127.0.0.1:{port}/shutdown-test-ready"
            deadline = time.monotonic() + 10
            with httpx.Client(timeout=0.5) as client:
                while True:
                    try:
                        response = client.get(url)
                        if response.status_code == 200 and response.json()["active"]:
                            break
                    except httpx.TransportError:
                        pass
                    assert process.poll() is None, "Fixture exited during startup"
                    assert time.monotonic() < deadline, "Fixture startup timed out"
                    time.sleep(0.05)
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request("GET", "/events")
                stream = connection.getresponse()
                assert stream.status == 200
                assert stream.getheader("Content-Type").startswith("text/event-stream")
                assert client.get(url).json()["subscribers"] == 1
                started = time.monotonic()
                process.send_signal(stop_signal)
                process.wait(timeout=12)
                elapsed = time.monotonic() - started
                assert 4.5 <= elapsed < 12
            result = json.loads((root / "cleanup.json").read_text())
            assert result == {
                "watcher_closed": True, "runtime_released": True,
                "observer_done": True, "generation_done": True,
                "run_state": "interrupted", "batch_state": "interrupted",
                "submissions": 1, "enhancements": 1,
                "restart_submissions": 0, "restart_enhancements": 0,
                "restart_batch_task": False, "restart_run_state": "interrupted",
                "restart_batch_state": "interrupted",
            }
            log.seek(0)
            output = log.read()
            assert "timeout graceful shutdown exceeded" in output
            assert "Waiting for application shutdown" in output
            assert ("injected batch cleanup failure" in output) == batch_error
        finally:
            if connection is not None:
                connection.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
