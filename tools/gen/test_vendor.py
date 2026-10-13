"""Offline CPU checks for the unmodified, zip-importable Rich wheel bundle."""

import hashlib
import json
import subprocess
import tempfile
import textwrap
import unittest
import zipfile
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit

VENDOR = Path(__file__).resolve().with_name("vendor")


class VendorTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((VENDOR / "manifest.json").read_text(encoding="utf-8"))
        self.wheels = self.manifest["wheels"]

    def test_manifest_has_only_complete_runtime_bundle(self):
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["python"], ">=3.12")
        self.assertEqual(
            {entry["name"].lower() for entry in self.wheels},
            {"rich", "markdown-it-py", "mdurl", "pygments"},
        )
        filenames = [entry["filename"] for entry in self.wheels]
        self.assertEqual(len(filenames), len(set(filenames)))
        self.assertEqual(len(filenames), 4)
        self.assertEqual(set(filenames), {path.name for path in VENDOR.glob("*.whl")})
        self.assertLess(sum(entry["size"] for entry in self.wheels), 2 * 1024 * 1024)

    def test_official_manifest_hashes_metadata_and_licenses(self):
        for entry in self.wheels:
            with self.subTest(wheel=entry["filename"]):
                filename = entry["filename"]
                self.assertEqual(Path(filename).name, filename)
                self.assertTrue(filename.endswith("-py3-none-any.whl"))
                payload = (VENDOR / filename).read_bytes()
                self.assertEqual(len(payload), entry["size"])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
                source = urlsplit(entry["source"])
                self.assertEqual((source.scheme, source.netloc),
                                 ("https", "files.pythonhosted.org"))
                self.assertEqual(Path(source.path).name, filename)
                metadata_source = urlsplit(entry["metadata_source"])
                self.assertEqual((metadata_source.scheme, metadata_source.netloc),
                                 ("https", "pypi.org"))
                self.assertTrue(metadata_source.path.endswith(f"/{entry['version']}/json"))
                self.assertIn(entry["license"]["expression"], {"MIT", "BSD-2-Clause"})
                with zipfile.ZipFile(VENDOR / filename) as archive:
                    metadata_path, = [
                        name for name in archive.namelist()
                        if name.endswith(".dist-info/METADATA")
                    ]
                    metadata = BytesParser().parsebytes(archive.read(metadata_path))
                    self.assertEqual(metadata["Name"], entry["name"])
                    self.assertEqual(metadata["Version"], entry["version"])
                    self.assertEqual(metadata["Requires-Python"], entry["requires_python"])
                    mandatory = [
                        requirement for requirement in metadata.get_all("Requires-Dist", [])
                        if ";" not in requirement
                    ]
                    # Selected releases have only extra-gated conditional dependencies.
                    def normalize(value):
                        return value.replace(" ", "").replace("(", "").replace(")", "")
                    self.assertEqual(
                        {normalize(value) for value in mandatory},
                        {normalize(value) for value in entry["runtime_requires"]},
                    )
                    wheel_path, = [
                        name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")
                    ]
                    wheel_metadata = BytesParser().parsebytes(archive.read(wheel_path))
                    self.assertEqual(wheel_metadata["Root-Is-Purelib"], "true")
                    self.assertIn("py3-none-any", wheel_metadata.get_all("Tag", []))
                    self.assertFalse(any(
                        name.endswith((".so", ".pyd", ".dll")) for name in archive.namelist()
                    ))
                    self.assertTrue(entry["license"]["files"])
                    for license_path in entry["license"]["files"]:
                        self.assertIn(".dist-info/", license_path)
                        self.assertTrue(archive.read(license_path).strip())

    def test_system_python_without_site_imports_only_bundled_rich(self):
        paths = [str(VENDOR / entry["filename"]) for entry in self.wheels]
        script = textwrap.dedent("""\
            import io
            import json
            import sys

            assert sys.version_info >= (3, 12)
            assert sys.flags.no_site and sys.flags.isolated
            assert 'site' not in sys.modules
            assert not any('site-packages' in path or 'dist-packages' in path
                           for path in sys.path)

            def forbid_network(event, args):
                if event.startswith('socket.'):
                    raise AssertionError('network forbidden in vendor smoke test')

            sys.addaudithook(forbid_network)
            paths = json.loads(sys.argv[1])
            sys.path.extend(paths)
            import rich.console
            import rich.table
            import rich.markdown
            import markdown_it
            import mdurl
            import pygments

            modules = [rich.console, rich.table, markdown_it, mdurl, pygments]
            for module in modules:
                assert any(module.__file__.startswith(path + '/') for path in paths)
            output = io.StringIO()
            console = rich.console.Console(file=output, color_system=None, width=60)
            table = rich.table.Table('State')
            table.add_row('offline')
            console.print(table)
            console.print(rich.markdown.Markdown('**bundled** [link](https://example.com)'))
            assert 'offline' in output.getvalue() and 'bundled' in output.getvalue()
            print(json.dumps([module.__file__ for module in modules]))
        """)
        # Isolated mode ignores PYTHONPATH and cwd; -S excludes system site packages.
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run(
                ["/usr/bin/python3", "-I", "-S", "-B", "-c", script, json.dumps(paths)],
                cwd=cwd, env={}, capture_output=True, text=True, timeout=30, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(json.loads(result.stdout)), 5)


if __name__ == "__main__":
    unittest.main()
