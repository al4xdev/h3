"""Fish parser regression tests; model paths are exclusively printf arguments."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("gen_launchers", ROOT / "gen.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)
PROVENANCE = json.loads((ROOT / "launchers/provenance.json").read_text())


def fish(script, args=()):
    return subprocess.run(
        ["fish", "--no-config", "-c", script, "--", *args],
        capture_output=True, check=True, timeout=5,
    ).stdout


class LauncherTests(unittest.TestCase):
    def test_registry_and_qw_original_path(self):
        self.assertEqual(set(gen.LAUNCHERS), {"image", "video", "qw", "gmmax", "gmno", "gmmed", "gmrol", "gmlow"})
        self.assertEqual(gen.LAUNCHERS["qw"], Path("/home/alex/Applications/bonsai2/run-bonsai2.fish"))
        self.assertEqual(set(gen.TEXT_PROFILES), set(PROVENANCE["profiles"]))
        for name in gen.TEXT_PROFILES:
            if name != "qw":
                self.assertEqual(gen.LAUNCHERS[name], ROOT.resolve() / "launchers" / f"{name}.fish")

    def test_provenance_reconstructs_true_abbreviation_expansion(self):
        # Only abbr declarations execute; the full personal config never does.
        for name, record in PROVENANCE["profiles"].items():
            with self.subTest(profile=name):
                # This fish version shows all definitions even with a name;
                # isolate each declaration so the captured output is unambiguous.
                shown = fish(record["source_declaration"] + f"\nabbr --show {name}").decode().rstrip("\n")
                self.assertEqual(shown, record["shown_declaration"])
                expansion = fish("function abbr; printf '%s\\0' $argv[-1]; end\n" + shown)
                self.assertEqual(expansion, record["expansion"].encode() + b"\0")
                actual = fish("printf '%s\\0' " + record["expansion"])
                self.assertEqual(actual, b"".join(os.fsencode(a) + b"\0" for a in record["expected_argv"]))

    def test_launchers_byte_exact_with_extra_arguments(self):
        for name, record in PROVENANCE["profiles"].items():
            if name == "qw":
                continue  # The original Bonsai script is neither sourced nor changed.
            launcher = ROOT / "launchers" / f"{name}.fish"
            content = launcher.read_text()
            self.assertEqual(content, "#!/usr/bin/env -S fish --no-config\nexec " + record["expansion"] + " $argv\n")
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o755)
            subprocess.run(["fish", "--no-config", "--no-execute", str(launcher)], check=True, capture_output=True, timeout=5)
            # exec is a reserved fish keyword, not a mockable function. Replace
            # precisely that command with printf in a disposable instrumented copy;
            # the entire original command (including its path) becomes argv data.
            self.assertEqual(content.count("\nexec "), 1)
            instrumented = content.replace("\nexec ", "\nprintf '%s\\0' ", 1)
            with tempfile.TemporaryDirectory() as directory:
                safe = Path(directory) / "capture.fish"
                safe.write_text(instrumented)
                for extras in ([], ["--help"], ["--", "--port", "9999"], ["", "a b", 'literal "quotes"', "semi;colon", "line\nbreak", "--samplers", "override"]):
                    with self.subTest(profile=name, extras=extras):
                        original = fish("printf '%s\\0' " + record["expansion"] + " $argv", extras)
                        generated = fish("source $argv[1] $argv[2..-1]", [str(safe), *extras])
                        expected = b"".join(os.fsencode(a) + b"\0" for a in [*record["expected_argv"], *extras])
                        self.assertEqual(original, expected)
                        self.assertEqual(generated, expected)

    def test_executable_shebang_preserves_exported_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "fish"
            config.mkdir()
            marker = root / "config-loaded"
            (config / "config.fish").write_text(
                f"printf loaded > {marker}\nset -gx EDITOR config-override\nset -gx GEN_ENV config-override\n"
            )
            environment = {**os.environ, "XDG_CONFIG_HOME": directory, "EDITOR": "caller-editor", "GEN_ENV": "caller value"}
            for name in gen.TEXT_PROFILES:
                if name == "qw":
                    continue
                content = (ROOT / "launchers" / f"{name}.fish").read_text()
                self.assertEqual(content.count("\nexec "), 1)
                safe = root / f"{name}.fish"
                safe.write_text(content.replace("\nexec ", "\nprintf '%s\\0' ", 1) + "printf '%s\\0' $EDITOR $GEN_ENV (string join : $PATH)\n")
                safe.chmod(0o755)
                with self.subTest(profile=name):
                    result = subprocess.run([str(safe), "extra argument", ""], env=environment, capture_output=True, check=True, timeout=5)
                    argv = [*PROVENANCE["profiles"][name]["expected_argv"], "extra argument", "", environment["EDITOR"], environment["GEN_ENV"], environment["PATH"]]
                    self.assertEqual(result.stdout, b"".join(os.fsencode(a) + b"\0" for a in argv))
                    self.assertFalse(marker.exists())

    def test_frozen_sampler_context_reasoning_and_paths(self):
        contexts = {"gmmax": "98304", "gmno": "98304", "gmmed": "65536", "gmrol": "65536", "gmlow": "4096"}
        for name, context in contexts.items():
            argv = PROVENANCE["profiles"][name]["expected_argv"]
            with self.subTest(profile=name):
                self.assertEqual(argv[0], "/home/alex/.unsloth/llama.cpp/llama-server")
                for option, value in (("--samplers", "temperature;top_p;top_k"), ("-c", context), ("--fit-ctx", context), ("--reasoning", "on" if name == "gmmax" else "off")):
                    self.assertEqual(argv[argv.index(option) + 1], value)
                self.assertEqual("--mmproj" in argv, name != "gmrol")
                self.assertIn("StyleTune-QK-Heretic" if name == "gmrol" else "UDmerge", argv[argv.index("-m") + 1])
                for option in ("-m", "--model-draft", "--slot-save-path", "--chat-template-file"):
                    self.assertTrue(argv[argv.index(option) + 1].startswith("/home/alex/"))


if __name__ == "__main__":
    unittest.main()
