"""Presentation tests use mocks only; no user service or launcher is invoked."""
import importlib.util
import io
import json
import os
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
        with patch.object(gen, "Controller", return_value=self.controller), patch.dict(os.environ, {"TERM": "xterm-kitty", **(env or {})}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = gen.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_headless_json_exact_old_schemas_and_only_expected_calls(self):
        for args, result, expected in ((["--headless", "qw"], START, call.start("qw", [])),
                                       (["--headless", "stop"], STOP, call.stop()),
                                       (["--headless", "status"], STATUS, call.status())):
            with self.subTest(args=args):
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
                for text in ("Estado do serviço", "ativo", "video", RUN, "Prontidão não verificada", "gen logs"):
                    self.assertIn(text, stdout)
                self.assertNotIn("modelo pronto", stdout)

    def test_status_state_variants_and_uncertainty_remain_honest(self):
        for state in ("absent", "activating", "deactivating", "inactive", "failed"):
            with self.subTest(state=state):
                self.controller.status.return_value = {**STATUS, "state": state, "owned": False, "uncertain": True}
                code, stdout, _ = self.invoke(["status"])
                self.assertEqual(code, 0)
                self.assertIn("não atribuída", stdout)
                self.assertIn("incerto", stdout)
                self.assertIn("Prontidão não verificada", stdout)
                self.assertEqual(self.controller.mock_calls[-1], call.status())
        self.controller.status.return_value = {**STATUS, "state": "absent", "substate": None, "run": None, "profile": None, "owned": False}
        _, stdout, _ = self.invoke(["status"])
        self.assertIn("gen --help", stdout)
        self.assertNotIn("Perfil", stdout)
        self.assertNotIn("Run", stdout)

    def test_start_stop_result_headings_and_no_extra_io(self):
        for result, heading in (("started", "Início solicitado"), ("already-running", "Perfil já em execução")):
            self.controller.reset_mock()
            self.controller.start.return_value = {**START, "result": result}
            _, stdout, _ = self.invoke(["qw"])
            self.assertIn(heading, stdout)
            self.assertIn("gen logs", stdout)
            self.assertIn("Prontidão não verificada", stdout)
            self.assertEqual(self.controller.mock_calls, [call.start("qw", [])])
        for result, heading in (("stopped", "Parada concluída"), ("not-running", "Nenhum serviço em execução")):
            self.controller.reset_mock()
            self.controller.stop.return_value = {**STOP, "result": result}
            _, stdout, _ = self.invoke(["stop"])
            self.assertIn(heading, stdout)
            self.assertIn("gen status", stdout)
            self.assertEqual(self.controller.mock_calls, [call.stop()])

    def test_logs_verbatim_all_modes_no_metadata_io(self):
        lines = [(3, "\033[31moriginal ANSI\033[0m\n"), (4, ""), (5, "x" * 4096 + " [line truncated]\n"), (6, "partial")]
        self.controller.logs.return_value = lines
        expected = "".join(f"{number}: {line}" + ("" if line.endswith("\n") else "\n") for number, line in lines)
        for prefix in ([], ["--headless"]):
            for tty, env in ((True, {}), (False, {}), (True, {"NO_COLOR": ""}), (True, {"TERM": "dumb"})):
                self.controller.reset_mock()
                code, stdout, stderr = self.invoke([*prefix, "logs", "3", "6", "--run", RUN], tty, env)
                self.assertEqual((code, stdout, stderr), (0, expected, ""))
                self.assertEqual(self.controller.mock_calls, [call.logs(3, 6, RUN)])

    def test_default_logs_empty_and_single_start_preserve_calls(self):
        for args, expected in ((["logs"], call.logs(None, None, None)), (["logs", "100"], call.logs(100, None, None))):
            self.controller.reset_mock()
            self.controller.logs.return_value = []
            self.assertEqual(self.invoke(args), (0, "", ""))
            self.assertEqual(self.controller.mock_calls, [expected])

    def test_headless_public_errors_unchanged_and_generic_errors_private(self):
        for error in (gen.Refused("line range must be positive and increasing"), OSError("SECRET"), ValueError("SECRET"), KeyError("SECRET")):
            self.controller.logs.side_effect = error
            code, stdout, stderr = self.invoke(["--headless", "logs", "0"], tty=True)
            expected = str(error) if isinstance(error, gen.Refused) else "operation failed; no retry performed"
            self.assertEqual((code, stdout, stderr), (1, "", f"gen: {expected}\n"))

    def test_human_safe_error_mapping_no_private_echo(self):
        for error in (gen.Refused("only text profiles accept extra arguments"), gen.Refused("PRIVATE arbitrary diagnostic"), OSError("PRIVATE"), ValueError("PRIVATE"), KeyError("PRIVATE")):
            for tty, env, color in ((True, {}, True), (False, {}, False), (True, {"NO_COLOR": ""}, False), (True, {"TERM": "dumb"}, False)):
                self.controller.start.side_effect = error
                code, stdout, stderr = self.invoke(["video", "PRIVATE"], tty, env)
                self.assertEqual((code, stdout), (1, ""))
                self.assertIn("Operação recusada", stderr)
                self.assertNotIn("PRIVATE", stderr)
                self.assertEqual("\033[" in stderr, color)

    def test_help_never_constructs_controller(self):
        for args in (["--help"], ["--headless", "--help"], ["status", "--help"], ["logs", "--help"]):
            with patch.object(gen, "Controller") as factory, redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                gen.main(args)
            self.assertEqual(caught.exception.code, 0)
            factory.assert_not_called()

    def test_late_root_flag_rejected_on_nonmodel_without_io(self):
        for args in (["status", "--headless"], ["stop", "--headless"], ["logs", "--headless"]):
            with patch.object(gen, "Controller") as factory, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                gen.main(args)
            self.assertEqual(caught.exception.code, 2)
            factory.assert_not_called()

    def test_import_is_inert(self):
        with patch("subprocess.run") as execute, patch("os.execve") as execve:
            module = importlib.util.module_from_spec(SPEC)
            SPEC.loader.exec_module(module)
        execute.assert_not_called()
        execve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
