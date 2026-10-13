"""CPU-only controller tests: never contact the real user service manager."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("gen_controller", Path(__file__).with_name("gen.py"))
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


class FakeManager:
    def __init__(self):
        self.unit = None
        self.calls = []
        self.start_result = 0
        self.stop_result = 0
        self.stop_state = None
        self.raise_start = False
        self.show_result = None

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        assert kwargs == {"capture_output": True, "text": True, "check": False}
        if argv[0] == "systemd-run":
            if self.raise_start:
                raise OSError("SECRET")
            if not self.start_result:
                self.unit = {
                    "LoadState": "loaded", "ActiveState": "active", "SubState": "running", "Transient": "yes",
                    "Description": next(a.split("=", 1)[1] for a in argv if a.startswith("--description=")),
                    "ExecStart": " ".join(argv[argv.index("--") + 1:]),
                }
            return subprocess.CompletedProcess(argv, self.start_result, "", "PRIVATE ERROR")
        if "stop" in argv:
            if not self.stop_result:
                self.unit = self.stop_state
            return subprocess.CompletedProcess(argv, self.stop_result, "", "PRIVATE ERROR")
        if self.show_result is not None:
            return self.show_result
        values = self.unit or {"LoadState": "not-found"}
        return subprocess.CompletedProcess(argv, 0, "\n".join(f"{k}={v}" for k, v in values.items()), "")


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.manager = FakeManager()
        self.controller = gen.Controller(self.root / "state", self.proc, self.manager)
        self.launcher = self.root / "original.sh"
        self.launcher.write_text("#!/bin/sh\nexit 0\n")
        self.launcher.chmod(0o700)
        self.patcher = patch.dict(gen.LAUNCHERS, {p: self.launcher for p in gen.LAUNCHERS})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def start_argv(self):
        return next(argv for argv in reversed(self.manager.calls) if argv[0] == "systemd-run")

    def process(self, pid, comm, argv):
        directory = self.proc / str(pid)
        directory.mkdir()
        (directory / "comm").write_text(comm)
        (directory / "cmdline").write_bytes(b"\0".join(os.fsencode(a) for a in argv))
        return directory

    def test_video_properties_and_single_transient_unit(self):
        self.controller.start("video")
        argv = self.start_argv()
        for expected in ("--user", "--unit=gen", "--collect", "--service-type=exec", "--property=Restart=no", "--property=MemoryHigh=79%", "--property=MemoryMax=80%"):
            self.assertIn(expected, argv)
        output = next(a.split("append:")[1] for a in argv if "StandardOutput=" in a)
        error = next(a.split("append:")[1] for a in argv if "StandardError=" in a)
        self.assertEqual(output, error)
        self.assertEqual(Path(output).stat().st_mode & 0o777, 0o600)

    def test_image_alias_and_qw_have_no_caps(self):
        for profile in ("image", "imagem", *gen.TEXT_PROFILES):
            with self.subTest(profile=profile):
                self.controller.start(profile)
                self.assertFalse(any("Memory" in a for a in self.start_argv()))
                self.controller.stop()

    def test_full_environment_cwd_private_args(self):
        with patch.dict(os.environ, {"GEN_SECRET": "private-value", "PYTHONUNBUFFERED": "unchanged"}):
            result = self.controller.start("qw", ["--ctx-size", "SECRET ARG", "--port=9000"])
            launch = gen.read_private(self.controller.state / result["run"] / "launch.json")
            self.assertEqual(launch["env"], dict(os.environ))
        self.assertEqual(launch["cwd"], os.getcwd())
        self.assertEqual(launch["script"], str(self.launcher))
        self.assertEqual(launch["args"], ["--ctx-size", "SECRET ARG", "--port=9000"])
        self.assertNotIn("SECRET", " ".join(self.start_argv()))
        self.assertNotIn("private-value", " ".join(self.start_argv()))
        for path in self.controller.state.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_image_and_video_reject_extras_before_tool_calls(self):
        for profile in ("image", "imagem", "video"):
            with self.assertRaises(gen.Refused):
                self.controller.start(profile, ["--listen", "elsewhere"])
        self.assertEqual(self.manager.calls, [])

    def test_same_profile_does_not_restart(self):
        first = self.controller.start("image")
        second = self.controller.start("imagem")
        self.assertEqual(second["run"], first["run"])
        self.assertEqual(second["result"], "already-running")
        self.assertEqual(sum(a[0] == "systemd-run" for a in self.manager.calls), 1)
        self.manager.unit["ActiveState"] = "activating"
        self.assertEqual(self.controller.start("image")["result"], "already-running")

    def test_busy_states_and_other_profiles(self):
        self.controller.start("image")
        for state in ("active", "activating", "deactivating", "inactive", "failed"):
            self.manager.unit["ActiveState"] = state
            with self.subTest(state=state), self.assertRaises(gen.Refused):
                self.controller.start("video")
        self.manager.unit["ActiveState"] = "deactivating"
        with self.assertRaises(gen.Refused):
            self.controller.start("image")

    def test_collisions_never_stopped_or_altered(self):
        self.controller.start("image")
        original = dict(self.manager.unit)
        for property_name, changed in (("Description", "other"), ("Transient", "no"), ("ExecStart", "/elsewhere")):
            self.manager.unit = {**original, property_name: changed}
            for action in (self.controller.stop, lambda: self.controller.start("image")):
                before = len(self.manager.calls)
                with self.assertRaises(gen.Refused):
                    action()
                self.assertEqual(len(self.manager.calls), before + 1)
        self.manager.unit = original
        self.assertTrue(self.controller.status()["owned"])

    def test_existing_unit_without_record_is_collision(self):
        self.manager.unit = dict.fromkeys(gen.PROPERTIES, "")
        self.manager.unit.update(LoadState="loaded", ActiveState="inactive")
        for action in (self.controller.stop, lambda: self.controller.start("image")):
            with self.assertRaises(gen.Refused):
                action()
        self.assertFalse(any("stop" in a for a in self.manager.calls))

    def test_external_comfy_and_llama_never_killed(self):
        for index, (comm, argv) in enumerate((("python", ["python", "/home/alex/comfyui/main.py"]), ("llama-server", ["/model/llama-server"]), ("renamed", ["/model/llama-server"]))):
            self.process(100 + index, comm, argv)
        self.assertEqual(sorted(self.controller.external()), [100, 101, 102])
        with self.assertRaises(gen.Refused):
            self.controller.start("video")
        self.assertEqual(self.controller.stop()["result"], "not-running")
        self.assertFalse(any("stop" in a or a[0] == "systemd-run" for a in self.manager.calls))

    def test_no_shell_string_false_positive_relative_comfy_detected(self):
        self.process(101, "bash", ["bash", "-c", "python /home/alex/comfyui/main.py; echo llama-server"])
        directory = self.process(102, "python", ["python", "main.py"])
        (directory / "cwd").symlink_to("/home/alex/comfyui")
        self.assertEqual(self.controller.external(), [102])

    def test_failed_start_is_uncertain_and_not_replayed(self):
        self.manager.start_result = 1
        with self.assertRaises(gen.Refused):
            self.controller.start("image")
        self.assertTrue(self.controller.status()["uncertain"])
        with self.assertRaises(gen.Refused):
            self.controller.start("image")
        self.assertEqual(sum(a[0] == "systemd-run" for a in self.manager.calls), 1)
        self.controller.stop()
        self.manager.start_result = 0
        self.controller.start("image")

    def test_tool_exception_does_not_expose_secrets(self):
        self.manager.raise_start = True
        with self.assertRaises(gen.Refused) as caught:
            self.controller.start("qw", ["SECRET"])
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertTrue(self.controller.status()["uncertain"])

    def test_bus_error_is_not_treated_as_absent(self):
        self.manager.show_result = subprocess.CompletedProcess([], 1, "", "bus failure")
        with self.assertRaises(gen.Refused):
            self.controller.start("image")
        self.assertFalse(any(a[0] == "systemd-run" for a in self.manager.calls))

    def test_stop_owned_and_failed_stop(self):
        self.controller.start("video")
        self.manager.stop_result = 1
        with self.assertRaises(gen.Refused):
            self.controller.stop()
        self.assertIsNotNone(self.manager.unit)
        self.manager.stop_result = 0
        self.assertEqual(self.controller.stop()["result"], "stopped")
        self.assertEqual(self.controller.stop()["result"], "not-running")

    def test_stop_detects_collection_name_reuse(self):
        self.controller.start("image")
        self.manager.stop_state = {**self.manager.unit, "Description": "external", "ActiveState": "inactive"}
        with self.assertRaises(gen.Refused):
            self.controller.stop()
        self.assertEqual(sum("stop" in a for a in self.manager.calls), 1)

    def test_single_lock_covers_start_and_stop(self):
        with self.controller.locked():
            other = gen.Controller(self.controller.state, self.proc, self.manager)
            for action in (other.stop, lambda: other.start("video")):
                with self.assertRaises(gen.Refused):
                    action()
        self.assertEqual(self.manager.calls, [])

    def test_log_tail_ranges_bounds_current_and_explicit_run(self):
        first = self.controller.start("image")["run"]
        log = self.controller.state / first / "output.log"
        log.write_text("".join(f"line {i}\n" for i in range(1, 701)))
        self.assertEqual([n for n, _ in self.controller.logs()], list(range(651, 701)))
        self.assertEqual([n for n, _ in self.controller.logs(10, 12)], [10, 11, 12])
        self.assertEqual(len(self.controller.logs(1)), 500)
        self.assertEqual(self.controller.logs(800), [])
        for start, end in ((0, None), (-1, 10), (20, 10), (1, 501)):
            with self.assertRaises(gen.Refused):
                self.controller.logs(start, end)
        self.controller.stop()
        self.controller.start("video")
        self.assertEqual(self.controller.logs(), [])
        self.assertEqual(len(self.controller.logs(run_id=first)), 50)
        with self.assertRaises(gen.Refused):
            self.controller.logs(run_id="../../etc/passwd")

    def test_log_partial_and_invalid_utf8_and_no_run(self):
        self.assertEqual(self.controller.logs(), [])
        run = self.controller.start("image")["run"]
        (self.controller.state / run / "output.log").write_bytes(b"one\n\xffpartial")
        self.assertEqual(self.controller.logs(), [(1, "one\n"), (2, "\ufffdpartial")])

    def test_private_file_symlink_and_permissions_rejected(self):
        self.controller.start("image")
        pointer = self.controller.state / "current.json"
        pointer.chmod(0o644)
        with self.assertRaises(gen.Refused):
            self.controller.current()
        pointer.chmod(0o600)
        outside = self.root / "outside"
        outside.write_text("{}")
        link = self.root / "link"
        link.symlink_to(outside)
        with self.assertRaises(OSError):
            gen.read_private(link)

    def test_runner_executes_exact_script_env_cwd_and_removes_secret_file(self):
        launch = self.root / "launch.json"
        gen.write_private(launch, {"script": "/exact/script", "args": ["--x", "secret"], "cwd": "/caller/cwd", "env": {"ONLY": "exact"}, "umask": 0o027})
        with patch.object(gen.os, "chdir") as chdir, patch.object(gen.os, "umask") as umask, patch.object(gen.os, "execve") as execve:
            gen.run_launch(launch)
        chdir.assert_called_once_with("/caller/cwd")
        umask.assert_called_once_with(0o027)
        execve.assert_called_once_with("/exact/script", ["/exact/script", "--x", "secret"], {"ONLY": "exact"})
        self.assertFalse(launch.exists())

    def test_runner_real_fake_launcher_preserves_env_cwd(self):
        # This is a fresh harmless shell script, never an original model launcher.
        fake = self.root / "fake.sh"
        fake.write_text('#!/bin/sh\nprintf "%s\\n%s\\n%s" "$PWD" "$ONLY" "$1" > "$OUTPUT"\n')
        fake.chmod(0o700)
        output = self.root / "result"
        launch = self.root / "launch.json"
        gen.write_private(launch, {"script": str(fake), "args": ["private argument"], "cwd": str(self.root), "env": {"ONLY": "private environment", "OUTPUT": str(output)}, "umask": 0o027})
        result = subprocess.run([os.sys.executable, str(gen.Path(gen.__file__)), "_run", str(launch)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text(), f"{self.root}\nprivate environment\nprivate argument")
        self.assertEqual(result.stdout, "")

    def test_log_long_lines_bounded_and_keep_original_numbering(self):
        run = self.controller.start("image")["run"]
        (self.controller.state / run / "output.log").write_text("x" * 100000 + "\nsecond\n")
        lines = self.controller.logs(1, 2)
        self.assertLess(len(lines[0][1]), 4200)
        self.assertIn("truncated", lines[0][1])
        self.assertEqual(lines[1], (2, "second\n"))

    def test_qw_all_flags_are_passed_verbatim_through_cli(self):
        import io
        from contextlib import redirect_stdout
        for profile in gen.TEXT_PROFILES:
            for args in (["--help"], ["--", "--port", "9999"], [""], ["--ctx-size=4096"], []):
                with self.subTest(profile=profile, args=args):
                    with patch.object(gen, "Controller", return_value=self.controller), redirect_stdout(io.StringIO()):
                        self.assertEqual(gen.main([profile, *args]), 0)
                    run = self.controller.current()
                    launch = gen.read_private(self.controller.state / run["id"] / "launch.json")
                    self.assertEqual(launch["args"], args)
                    self.assertEqual(run["profile"], profile)
                    self.controller.stop()

    def test_every_profile_preserves_context_and_systemd_properties(self):
        for profile in gen.LAUNCHERS:
            with self.subTest(profile=profile):
                args = ["--override", "space ; quote \"", ""] if profile in gen.TEXT_PROFILES else []
                mask = os.umask(0o027)
                try:
                    with patch.dict(os.environ, {"GEN_CONTEXT": "unchanged"}):
                        result = self.controller.start(profile, args)
                        launch = gen.read_private(self.controller.state / result["run"] / "launch.json")
                        self.assertEqual(launch["env"], dict(os.environ))
                finally:
                    os.umask(mask)
                self.assertEqual(launch["cwd"], os.getcwd())
                self.assertEqual(launch["umask"], 0o027)
                self.assertEqual(launch["script"], str(self.launcher))
                self.assertEqual(launch["args"], args)
                argv = self.start_argv()
                for value in ("--user", "--unit=gen", "--collect", "--service-type=exec", "--property=Restart=no", "--property=KillMode=control-group"):
                    self.assertIn(value, argv)
                self.assertEqual(any("Memory" in value for value in argv), profile == "video")
                self.controller.stop()

    def test_status_json_is_machine_readable_no_readiness_claim(self):
        import io
        from contextlib import redirect_stdout
        stream = io.StringIO()
        with patch.object(gen, "Controller", return_value=self.controller), redirect_stdout(stream):
            self.assertEqual(gen.main(["status", "--json"]), 0)
        status = json.loads(stream.getvalue())
        self.assertEqual(status["readiness"], "not-verified")
        self.assertEqual(status["state"], "absent")
        self.assertFalse(self.controller.state.exists())

    def test_log_and_run_symlinks_refused(self):
        run = self.controller.start("image")["run"]
        directory = self.controller.state / run
        log = directory / "output.log"
        log.unlink()
        log.symlink_to(self.launcher)
        with self.assertRaises(OSError):
            self.controller.logs()
        real = self.controller.state / "real-directory"
        directory.rename(real)
        directory.symlink_to(real, target_is_directory=True)
        with self.assertRaises(gen.Refused):
            self.controller.current()

    def test_runner_shebang_path_interpreter_and_bonsai_environment(self):
        interpreter = self.root / "fish"
        interpreter.write_text('#!/bin/sh\nprintf "%s\\n%s\\n%s\\n%s\\n%s" "$1" "$2" "$3" "$BONSAI_CTX" "$BONSAI_PORT" > "$OUTPUT"\n')
        interpreter.chmod(0o700)
        launcher = self.root / "fake-bonsai.fish"
        launcher.write_text("#!/usr/bin/env fish\n# Harmless fake: interpreter records original script and args.\n")
        launcher.chmod(0o700)
        output = self.root / "output"
        launch = self.root / "launch.json"
        gen.write_private(launch, {"script": str(launcher), "args": ["--help", ""], "cwd": str(self.root), "env": {"PATH": str(self.root) + ":/usr/bin:/bin", "BONSAI_CTX": "4096", "BONSAI_PORT": "9999", "OUTPUT": str(output)}, "umask": 0o027})
        result = subprocess.run([os.sys.executable, gen.__file__, "_run", str(launch)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text(), f"{launcher}\n--help\n\n4096\n9999")
        self.assertEqual(output.stat().st_mode & 0o777, 0o640)

    def test_corrupt_metadata_cannot_escape_run_directory(self):
        run = self.controller.start("image")["run"]
        metadata = self.controller.state / run / "run.json"
        for value in ({"id": "../../outside", "profile": "image"}, {"id": run, "profile": "other"}):
            metadata.write_text(json.dumps(value))
            with self.assertRaises(gen.Refused):
                self.controller.stop()
        self.assertFalse(any("stop" in args for args in self.manager.calls))

    def test_ownership_rejects_prefix_paths_and_wrong_invocation(self):
        self.controller.start("image")
        original = self.manager.unit["ExecStart"]
        for bad in (original + "-foreign", original.replace(" _run ", " other "), original.replace(str(self.controller.runner), str(self.controller.runner) + "-foreign")):
            self.manager.unit["ExecStart"] = bad
            self.assertFalse(self.controller.status()["owned"])
            with self.assertRaises(gen.Refused):
                self.controller.stop()
        self.manager.unit["ExecStart"] = "{ path=/usr/bin/python3 ; argv[]=" + original + " ; ignore_errors=no ; }"
        self.assertTrue(self.controller.status()["owned"])

    def test_runner_exec_error_is_generic_and_not_retried(self):
        launch = self.root / "launch.json"
        gen.write_private(launch, {"script": "/SECRET/missing", "args": ["SECRET"], "cwd": str(self.root), "env": {}, "umask": 0o027})
        result = subprocess.run([os.sys.executable, gen.__file__, "_run", str(launch)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("SECRET", result.stderr)
        self.assertIn("no retry", result.stderr)
        self.assertFalse(launch.exists())


if __name__ == "__main__":
    unittest.main()
