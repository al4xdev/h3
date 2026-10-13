# Offline Rich wheels for gen

These are unmodified official PyPI `py3-none-any` wheels, usable through Python's
zip importer on `/usr/bin/python3 >=3.12`. No pip, installation, extraction,
virtualenv, global environment change, or runtime network access is required.

| Distribution | Fixed version | Wheel bytes | License |
| --- | --- | ---: | --- |
| Rich | 15.0.0 | 310654 | MIT |
| markdown-it-py | 4.2.0 | 91687 | MIT |
| mdurl | 0.1.2 | 9979 | MIT |
| Pygments | 2.21.0 | 1250147 | BSD-2-Clause |

Total wheels: **1662467 bytes** (about 1.59 MiB). This is the complete mandatory
runtime dependency closure: Rich → markdown-it-py → mdurl, and Rich → Pygments.
Jupyter, Windows-terminal, testing, documentation, and other extras are excluded.
`typing_extensions` is not required by these releases on the supported Python.

## Loading

Only the human presentation caller loads the resolved wheel paths into
`sys.path`, immediately before importing `rich.console` / `rich.table`. The gen
CLI verifies SHA256 and prepends these exact paths from `manifest.json`, relative
to its own directory rather than cwd, so bundled dependencies win in its normal
fresh CLI process. Already imported modules in an embedding process are not
replaced. Keep headless, controller, launcher and backend imports independent of
Rich. The isolated smoke test below proves bundled use without site packages.
Never download/install missing wheels at runtime; gen falls back to plain text.

## Provenance, verification, and updates

`manifest.json` records filenames, distribution names, versions, exact byte sizes,
SHA256, official wheel URLs, version-specific PyPI JSON URLs, Python requirements,
mandatory runtime requirements, and license locations inside each wheel.
The download was performed with Python stdlib `urllib.request` through
`uv run --no-project --python /usr/bin/python3 python`; each downloaded payload's
SHA256 and byte length were compared to that release's PyPI JSON before saving.

For an intentional update, select fixed compatible releases and inspect each
release's `Requires-Dist` / `Requires-Python`, recursively including mandatory
runtime dependencies only. Fetch `https://pypi.org/pypi/NAME/VERSION/json` using
`urllib.request.urlopen`, choose its non-yanked `py3-none-any.whl` entry, download
that entry's official `https://files.pythonhosted.org/` URL, and compare
`hashlib.sha256(payload).hexdigest()` against `entry['digests']['sha256']` and
`len(payload)` against `entry['size']` **before writing**. Never silently resolve
latest versions or extras. Update this table and the manifest together, preserve
unmodified wheels, then run the offline CPU tests (fish-compatible command):

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run --no-project --python /usr/bin/python3 python -B -m unittest discover -s ~/.config/my_scripts/gen -p test_vendor.py -v
```

Tests validate local hashes/metadata/licenses and start `/usr/bin/python3 -I -S`
with only stdlib plus these wheels, blocking socket operations. No networking,
services, GPU, or package installation occurs during test execution or imports.

## License preservation

Keep each entire original wheel and its `*.dist-info` directory intact when
copying or redistributing this bundle. All copyright, permission, warranty,
attribution, and author notices remain embedded at the exact paths recorded in
`license.files`; markdown-it-py also carries upstream `LICENSE.markdown-it`, and
Pygments includes `AUTHORS`. MIT and BSD-2-Clause require preservation of their
notices; this README is not a substitute for the actual license texts. If wheels
are ever extracted or repackaged elsewhere, carry those complete texts/notices
with the redistributed code. No upstream source or license has been modified.
