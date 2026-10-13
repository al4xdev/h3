"""Log observer tests: fake controllers and private disposable text files only."""
import importlib.util
import io
import os
import select
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

SPEC = importlib.util.spec_from_file_location("gen_follow", Path(__file__).with_name("gen.py"))
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)
RUN = "a" * 32


class FollowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.directory = self.state / RUN
        gen.private_dir(self.directory)
        gen.write_private(self.directory / "run.json", {"id": RUN, "profile": "video"})
        gen.write_private(self.state / "current.json", {"id": RUN})
        self.log = self.directory / "output.log"
        self.log.write_text("old message\n")
        self.log.chmod(0o600)
        self.controller = gen.Controller(self.state, execute=Mock(side_effect=AssertionError("service command forbidden")))
        self.child = Mock()
        self.child.wait.return_value = 0
        self.child.poll.return_value = 0

    def test_native_tail_argv_private_fd_and_no_extra_controller_io(self):
        for start in (None, 1, 900):
            with self.subTest(start=start), patch.object(gen.subprocess, "Popen", return_value=self.child) as popen, patch.object(self.controller, "current", wraps=self.controller.current) as current:
                self.assertEqual(gen.follow_logs(self.controller, start), 0)
                argv = popen.call_args.args[0]
                kwargs = popen.call_args.kwargs
                fd = kwargs["pass_fds"][0]
                self.assertEqual(argv, ["tail", "--follow=descriptor", "-n", "50" if start is None else f"+{start}", "--", f"/proc/self/fd/{fd}"])
                self.assertEqual(kwargs, {"pass_fds": (fd,), "stderr": subprocess.DEVNULL})
                with self.assertRaises(OSError):
                    os.fstat(fd)
                current.assert_called_once_with()
        self.controller.execute.assert_not_called()

    def test_explicit_run_is_pinned_without_current_lookup(self):
        with patch.object(self.controller, "current") as current, patch.object(self.controller, "run_info", wraps=self.controller.run_info) as run_info, patch.object(gen.subprocess, "Popen", return_value=self.child):
            self.assertEqual(gen.follow_logs(self.controller, run_id=RUN), 0)
        current.assert_not_called()
        run_info.assert_called_once_with(RUN)
        self.controller.execute.assert_not_called()

    def test_no_run_has_no_child_or_service_calls(self):
        with patch.object(self.controller, "current", return_value=None), patch.object(gen.subprocess, "Popen") as popen:
            self.assertEqual(gen.follow_logs(self.controller), 0)
        popen.assert_not_called()
        self.controller.execute.assert_not_called()

    def test_invalid_ranges_rejected_before_any_io(self):
        for start, end in ((None, 2), (1, 10), (0, None), (-1, None)):
            with patch.object(self.controller, "current") as current, patch.object(gen.subprocess, "Popen") as popen, self.assertRaises(gen.Refused):
                gen.follow_logs(self.controller, start, end)
            current.assert_not_called()
            popen.assert_not_called()

    def test_symlink_permissions_and_run_escape_rejected(self):
        with patch.object(gen.subprocess, "Popen") as popen:
            self.log.chmod(0o644)
            with self.assertRaises(gen.Refused):
                gen.follow_logs(self.controller)
            self.log.chmod(0o600)
            self.log.unlink()
            self.log.symlink_to(self.directory / "run.json")
            with self.assertRaises(OSError):
                gen.follow_logs(self.controller)
            with self.assertRaises(gen.Refused):
                gen.follow_logs(self.controller, run_id="../../private")
        popen.assert_not_called()
        self.controller.execute.assert_not_called()

    def test_child_creation_failure_closes_descriptor(self):
        captured = []

        def fail(*args, **kwargs):
            captured.extend(kwargs["pass_fds"])
            raise OSError("PRIVATE")

        with patch.object(gen.subprocess, "Popen", side_effect=fail), self.assertRaises(OSError):
            gen.follow_logs(self.controller)
        with self.assertRaises(OSError):
            os.fstat(captured[0])

    def test_spawn_defers_interrupt_and_restores_previous_signal_mask(self):
        previous = {gen.signal.SIGUSR1}
        for failure in (False, True):
            with self.subTest(failure=failure):
                sequence = Mock()
                sequence.mask.side_effect = [previous, previous]
                sequence.spawn.side_effect = OSError("PRIVATE") if failure else None
                sequence.spawn.return_value = self.child
                with patch.object(gen.signal, "pthread_sigmask", sequence.mask), patch.object(gen.subprocess, "Popen", sequence.spawn):
                    if failure:
                        with self.assertRaises(OSError):
                            gen.follow_logs(self.controller)
                    else:
                        self.assertEqual(gen.follow_logs(self.controller), 0)
                self.assertEqual([entry[0] for entry in sequence.mock_calls if entry[0] in ("mask", "spawn")], ["mask", "spawn", "mask"])
                self.assertEqual(sequence.mask.call_args_list, [call(gen.signal.SIG_BLOCK, {gen.signal.SIGINT}), call(gen.signal.SIG_SETMASK, previous)])

    def test_pending_interrupt_on_mask_restore_reaps_captured_child(self):
        self.child.poll.return_value = None
        with patch.object(gen.signal, "pthread_sigmask", side_effect=[set(), KeyboardInterrupt]) as mask, patch.object(gen.subprocess, "Popen", return_value=self.child):
            self.assertEqual(gen.follow_logs(self.controller), 0)
        self.assertEqual(mask.call_args_list, [call(gen.signal.SIG_BLOCK, {gen.signal.SIGINT}), call(gen.signal.SIG_SETMASK, set())])
        self.assertEqual(self.child.mock_calls, [call.poll(), call.terminate(), call.wait(timeout=5)])
        self.controller.execute.assert_not_called()

    def test_ctrl_c_terminates_and_reaps_only_observer(self):
        self.child.wait.side_effect = [KeyboardInterrupt, 0]
        self.child.poll.return_value = None
        with patch.object(gen.subprocess, "Popen", return_value=self.child):
            self.assertEqual(gen.follow_logs(self.controller), 0)
        self.assertEqual(self.child.mock_calls, [call.wait(), call.poll(), call.terminate(), call.wait(timeout=5)])
        self.controller.execute.assert_not_called()

    def test_interrupt_cleanup_timeout_kills_only_child(self):
        self.child.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired("tail", 5), -9]
        self.child.poll.return_value = None
        with patch.object(gen.subprocess, "Popen", return_value=self.child):
            self.assertEqual(gen.follow_logs(self.controller), 0)
        self.child.kill.assert_called_once_with()
        self.assertEqual(self.child.wait.call_args_list, [call(), call(timeout=5), call()])
        self.controller.execute.assert_not_called()

    def test_interrupt_immediately_after_spawn_still_reaps_child(self):
        original_close = os.close

        def interrupted_close(fd):
            original_close(fd)
            raise KeyboardInterrupt

        self.child.poll.return_value = None
        with patch.object(gen.subprocess, "Popen", return_value=self.child), patch.object(gen.os, "close", side_effect=interrupted_close):
            self.assertEqual(gen.follow_logs(self.controller), 0)
        self.assertEqual(self.child.mock_calls, [call.poll(), call.terminate(), call.wait(timeout=5)])
        self.controller.execute.assert_not_called()

    def test_second_interrupt_during_cleanup_kills_and_reaps_own_child(self):
        self.child.wait.side_effect = [KeyboardInterrupt, KeyboardInterrupt, -9]
        self.child.poll.return_value = None
        with patch.object(gen.subprocess, "Popen", return_value=self.child):
            self.assertEqual(gen.follow_logs(self.controller), 0)
        self.child.terminate.assert_called_once_with()
        self.child.kill.assert_called_once_with()
        self.assertEqual(self.child.wait.call_args_list, [call(), call(timeout=5), call()])
        self.controller.execute.assert_not_called()

    def test_child_failure_is_public_no_retry(self):
        self.child.wait.return_value = 1
        with patch.object(gen.subprocess, "Popen", return_value=self.child) as popen, self.assertRaisesRegex(gen.Refused, "log observer failed; no retry performed"):
            gen.follow_logs(self.controller)
        self.assertEqual(popen.call_count, 1)
        self.child.terminate.assert_not_called()

    def test_cli_follow_dispatch_raw_no_decoration(self):
        for prefix in ([], ["--headless"]):
            for args, expected in ((["logs", "--follow"], (None, None, None)),
                                   (["logs", "1", "--follow", "--run", RUN], (1, None, RUN))):
                stdout, stderr = io.StringIO(), io.StringIO()
                controller = Mock(spec=gen.Controller)
                with patch.object(gen, "Controller", return_value=controller), patch.object(gen, "follow_logs", return_value=0) as follow, redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(gen.main([*prefix, *args]), 0)
                follow.assert_called_once_with(controller, *expected)
                self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))
                self.assertEqual(controller.mock_calls, [])

    def test_cli_follow_finite_end_preserves_error_exit(self):
        for prefix in ([], ["--headless"]):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(gen, "Controller", return_value=self.controller), patch.object(gen.subprocess, "Popen") as popen, redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(gen.main([*prefix, "logs", "1", "20", "--follow"]), 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("follow does not accept an end line" if prefix else "não aceita uma linha final", stderr.getvalue())
            popen.assert_not_called()

    def test_real_tail_append_is_pinned_to_original_private_file(self):
        # Only native tail reads this disposable fixture. Never run a launcher.
        original_popen = subprocess.Popen
        created = threading.Event()
        children, errors = [], []

        def create(argv, **kwargs):
            child = original_popen(argv, **kwargs, stdout=subprocess.PIPE, bufsize=0)
            children.append(child)
            created.set()
            return child

        def observe():
            try:
                gen.follow_logs(self.controller, start=1)
            except gen.Refused as error:
                errors.append(str(error))

        with patch.object(gen.subprocess, "Popen", side_effect=create):
            worker = threading.Thread(target=observe, daemon=True)
            worker.start()
            self.assertTrue(created.wait(5), "tail child was not created")
            child = children[0]
            try:
                descriptor = child.stdout.fileno()
                self.assertTrue(select.select([descriptor], [], [], 5)[0], "initial fixture line missing")
                self.assertEqual(os.read(descriptor, 4096), b"old message\n")
                # Replace the path with a different log: descriptor-follow must
                # keep reading the old inode and never follow current.json anew.
                replacement = self.directory / "replacement.log"
                replacement.write_text("wrong new run\n")
                replacement.chmod(0o600)
                with self.log.open("a") as pinned_writer:
                    os.replace(replacement, self.log)
                    pinned_writer.write("new real message\n")
                    pinned_writer.flush()
                self.assertTrue(select.select([descriptor], [], [], 5)[0], "appended fixture line missing")
                self.assertEqual(os.read(descriptor, 4096), b"new real message\n")
            finally:
                child.terminate()
                child.wait(timeout=5)
                worker.join(timeout=5)
                child.stdout.close()
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["log observer failed; no retry performed"])
        self.controller.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
