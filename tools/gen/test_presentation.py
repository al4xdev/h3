"""Presentation tests use mocks only; no user service or launcher is invoked."""
import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

SPEC = importlib.util.spec_from_file_location("gen_presentation", Path(__file__).with_name("gen.py"))
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)
RUN = "cb5f12c5f8b6418e97b5e13a5c369c22"
STATUS = {"unit": "gen.service", "state": "active", "substate": "running", "owned": True,
          "run": RUN, "profile": "video", "uncertain": False, "readiness": "not-verified"}
START = {"result": "started", "run": RUN, "profile": "qw", "readiness": "not-verified"}
STOP = {"result": "stopped", "readiness": "not-verified"}


class Terminal(io.StringIO):
    def __init__(self, tty=False):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.controller = Mock(spec=gen.Controller)
        self.controller.start.return_value = dict(START)
        self.controller.stop.return_value = dict(STOP)
        self.controller.status.return_value = dict(STATUS)
        self.controller.logs.return_value = [(9, "original\n"), (10, "partial")]

    def invoke(self, args, tty=False, env=None):
        stdout, stderr = Terminal(tty), Terminal(tty)
        with patch.object(gen, "Controller", return_value=self.controller) as factory, patch.dict(os.environ, {"TERM": "xterm-kitty", **(env or {})}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = gen.main(args)
            except SystemExit as error:
                code = error.code
            self.factory_calls = factory.call_count
        return code, stdout.getvalue(), stderr.getvalue()

    def test_headless_exact_success_schemas_without_rich(self):
        for args, result, expected in ((["--headless", "qw"], START, call.start("qw", [])),
                                       (["--headless", "stop"], STOP, call.stop()),
                                       (["--headless", "status"], STATUS, call.status())):
            with self.subTest(args=args), patch.object(gen, "rich_console", side_effect=AssertionError("Rich forbidden")):
                self.controller.reset_mock()
                code, stdout, stderr = self.invoke(args, tty=True)
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(stdout, json.dumps(result, sort_keys=True) + "\n")
                self.assertEqual(self.controller.mock_calls, [expected])

    def test_status_json_alias_identical_in_all_terminal_modes(self):
        for tty, env in ((False, {}), (True, {}), (True, {"NO_COLOR": ""}), (True, {"TERM": "dumb"})):
            for args in (["status", "--json"], ["--headless", "status", "--json"]):
                with self.subTest(tty=tty, env=env, args=args):
                    code, stdout, stderr = self.invoke(args, tty, env)
                    self.assertEqual((code, stderr), (0, ""))
                    self.assertEqual(stdout, json.dumps(STATUS, sort_keys=True) + "\n")

    def test_model_arguments_verbatim_in_both_modes(self):
        for profile in gen.PROFILE_COMMANDS:
            for headless in ([], ["--headless"]):
                for args in ([], ["--help"], ["--headless"], ["--", "--headless", "--help"], [""], ["--port=9999", "private ; quote \"", ""]):
                    with self.subTest(profile=profile, headless=headless, args=args):
                        self.controller.reset_mock()
                        code, _, stderr = self.invoke([*headless, profile, *args])
                        self.assertEqual((code, stderr), (0, ""))
                        self.assertEqual(self.controller.mock_calls, [call.start(profile, args)])

    def test_post_profile_headless_is_not_consumed(self):
        code, stdout, stderr = self.invoke(["qw", "--headless"])
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("◆ gen", stdout)
        self.assertNotIn('"result"', stdout)
        self.controller.start.assert_called_once_with("qw", ["--headless"])

    def test_human_status_copper_only_on_eligible_tty(self):
        for tty, env, color in ((True, {}, True), (False, {}, False), (True, {"NO_COLOR": ""}, False),
                                (True, {"NO_COLOR": "1"}, False), (True, {"TERM": "dumb"}, False)):
            with self.subTest(tty=tty, env=env):
                code, stdout, stderr = self.invoke(["status"], tty, env)
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual("\033[" in stdout, color)
                for text in ("Service status", "active", "video", RUN, "Not verified", "gen logs"):
                    self.assertIn(text, stdout)
                self.assertNotIn("model ready", stdout)

    def test_status_state_variants_and_uncertainty_remain_honest(self):
        for state in ("absent", "activating", "deactivating", "inactive", "failed"):
            with self.subTest(state=state):
                self.controller.status.return_value = {**STATUS, "state": state, "owned": False, "uncertain": True}
                code, stdout, _ = self.invoke(["status"])
                self.assertEqual(code, 0)
                self.assertIn("not owned", stdout)
                self.assertIn("uncertain", stdout)
                self.assertIn("Not verified", stdout)
                self.assertEqual(self.controller.mock_calls[-1], call.status())
        self.controller.status.return_value = {**STATUS, "state": "absent", "substate": None, "run": None, "profile": None, "owned": False}
        _, stdout, _ = self.invoke(["status"])
        self.assertIn("gen --help", stdout)
        self.assertNotIn("Profile", stdout)
        self.assertNotIn("Run", stdout)

    def test_start_stop_headings_and_no_extra_io(self):
        for result, heading in (("started", "Start requested"), ("already-running", "Profile already running")):
            self.controller.reset_mock()
            self.controller.start.return_value = {**START, "result": result}
            _, stdout, _ = self.invoke(["qw"])
            self.assertIn(heading, stdout)
            self.assertIn("gen logs", stdout)
            self.assertIn("Not verified", stdout)
            self.assertEqual(self.controller.mock_calls, [call.start("qw", [])])
        for result, heading in (("stopped", "Stop completed"), ("not-running", "No service running")):
            self.controller.reset_mock()
            self.controller.stop.return_value = {**STOP, "result": result}
            _, stdout, _ = self.invoke(["stop"])
            self.assertIn(heading, stdout)
            self.assertIn("gen status", stdout)
            self.assertEqual(self.controller.mock_calls, [call.stop()])

    def test_logs_human_verbatim_headless_json(self):
        lines = [(3, "\033[31moriginal ANSI\033[0m\n"), (4, ""), (5, "x" * 4096 + " [line truncated]\n"), (6, "partial")]
        self.controller.logs.return_value = lines
        raw = "".join(f"{number}: {line}" + ("" if line.endswith("\n") else "\n") for number, line in lines)
        machine = json.dumps({"lines": [{"number": n, "text": line} for n, line in lines]}, sort_keys=True) + "\n"
        for prefix in ([], ["--headless"]):
            for tty, env in ((True, {}), (False, {}), (True, {"NO_COLOR": ""}), (True, {"TERM": "dumb"})):
                self.controller.reset_mock()
                with patch.object(gen, "rich_console", side_effect=AssertionError("Rich forbidden")):
                    code, stdout, stderr = self.invoke([*prefix, "logs", "3", "6", "--run", RUN], tty, env)
                self.assertEqual((code, stdout, stderr), (0, machine if prefix else raw, ""))
                self.assertEqual(self.controller.mock_calls, [call.logs(3, 6, RUN)])

    def test_logs_empty_preserve_calls(self):
        self.controller.logs.return_value = []
        for prefix in ([], ["--headless"]):
            for args, expected in ((["logs"], call.logs(None, None, None)), (["logs", "100"], call.logs(100, None, None))):
                self.controller.reset_mock()
                self.assertEqual(self.invoke([*prefix, *args]), (0, '{"lines": []}\n' if prefix else "", ""))
                self.assertEqual(self.controller.mock_calls, [expected])

    def test_headless_errors_json_and_private_errors_sanitized(self):
        for error in (gen.Refused("line range must be positive and increasing"), gen.Refused("SECRET"), OSError("SECRET"), ValueError("SECRET"), KeyError("SECRET"), TypeError("SECRET"), AttributeError("SECRET")):
            self.controller.logs.side_effect = error
            with patch.object(gen, "rich_console", side_effect=AssertionError("Rich forbidden")):
                code, stdout, stderr = self.invoke(["--headless", "logs", "0"], tty=True)
            public = isinstance(error, gen.Refused) and str(error) in gen.PUBLIC_ERRORS
            expected = {"error": {"code": "refused" if public else "operation-failed", "message": str(error) if public else "operation failed; no retry performed"}}
            self.assertEqual((code, stderr), (1, ""))
            self.assertEqual(json.loads(stdout), expected)
            self.assertNotIn("SECRET", stdout)

    def test_status_json_alias_errors_are_json(self):
        self.controller.status.side_effect = OSError("SECRET")
        code, stdout, stderr = self.invoke(["status", "--json"])
        self.assertEqual((code, stderr), (1, ""))
        self.assertEqual(json.loads(stdout)["error"]["code"], "operation-failed")
        self.assertNotIn("SECRET", stdout)

    def test_human_errors_literal_and_private_safe(self):
        for error in (gen.Refused("only text profiles accept extra arguments"), gen.Refused("PRIVATE arbitrary diagnostic"), OSError("PRIVATE"), ValueError("PRIVATE"), KeyError("PRIVATE")):
            for tty, env, color in ((True, {}, True), (False, {}, False), (True, {"NO_COLOR": ""}, False), (True, {"TERM": "dumb"}, False)):
                self.controller.start.side_effect = error
                code, stdout, stderr = self.invoke(["video", "PRIVATE"], tty, env)
                self.assertEqual((code, stdout), (1, ""))
                self.assertIn("Operation refused", stderr)
                self.assertNotIn("PRIVATE", stderr)
                self.assertEqual("\033[" in stderr, color)

    def test_help_never_constructs_controller_and_headless_help_is_json(self):
        for prefix in ([], ["--headless"]):
            for action in ([], ["status"], ["logs"]):
                self.controller.reset_mock()
                code, stdout, stderr = self.invoke([*prefix, *action, "--help"])
                self.assertEqual(self.factory_calls, 0)
                self.assertEqual(self.controller.mock_calls, [])
                self.assertEqual((code, stderr), (0, ""))
                help_text = json.loads(stdout)["help"] if prefix else stdout
                self.assertIn("usage: gen", help_text)
                self.assertNotIn("saída", help_text)

    def test_invalid_headless_arguments_json_no_io_or_private_echo(self):
        for args in (["--headless"], ["--headless", "SECRET"], ["--headless", "status", "SECRET"], ["--headless", "logs", "SECRET"], ["status", "--json", "SECRET"]):
            self.controller.reset_mock()
            code, stdout, stderr = self.invoke(args)
            self.assertEqual((code, stderr), (2, ""))
            self.assertEqual(json.loads(stdout)["error"]["code"], "invalid-arguments")
            self.assertNotIn("SECRET", stdout)
            self.assertEqual(self.factory_calls, 0)
            self.assertEqual(self.controller.mock_calls, [])

    def test_late_root_flag_rejected_without_io(self):
        for args in (["status", "--headless"], ["stop", "--headless"], ["logs", "--headless"]):
            code, stdout, stderr = self.invoke(args)
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("invalid command", stderr)
            self.assertEqual(self.controller.mock_calls, [])

    def test_headless_follow_refused_before_controller_construction(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(gen, "Controller") as factory, redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(gen.main(["--headless", "logs", "--follow"]), 1)
        factory.assert_not_called()
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("human-only", json.loads(stdout.getvalue())["error"]["message"])

    def test_rich_literal_markup_and_plain_fallback(self):
        self.controller.status.return_value = {**STATUS, "substate": "[red]literal[/red]"}
        _, stdout, _ = self.invoke(["status"])
        self.assertIn("[red]literal[/red]", stdout)
        with patch.object(gen, "rich_console", return_value=None):
            code, stdout, stderr = self.invoke(["qw"])
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("Start requested", stdout)
        self.assertIn("Not verified", stdout)

    def test_render_failure_after_start_is_plain_success(self):
        gen.rich_console(io.StringIO())
        with patch("rich.table.Table.grid", side_effect=RuntimeError("PRIVATE renderer failure")):
            code, stdout, stderr = self.invoke(["qw"])
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("Start requested", stdout)
        self.assertEqual(stdout.count("◆ gen"), 1)
        self.assertNotIn("PRIVATE", stdout)
        self.controller.start.assert_called_once_with("qw", [])

    def test_import_is_inert_and_does_not_load_rich(self):
        before = set(sys.modules)
        with patch("subprocess.run") as execute, patch("os.execve") as execve:
            module = importlib.util.module_from_spec(SPEC)
            SPEC.loader.exec_module(module)
        execute.assert_not_called()
        execve.assert_not_called()
        self.assertFalse(any(name == "rich" or name.startswith("rich.") for name in set(sys.modules) - before))


if __name__ == "__main__":
    unittest.main()
