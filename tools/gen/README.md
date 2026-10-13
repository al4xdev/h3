# gen — personal model controller

Standalone PC tool at `/home/alex/.config/my_scripts/gen`, independent of H3.
Python's standard library controls one transient `gen.service`; systemd supervises
the original launchers. Rich decorates human results only. No pip, virtualenv,
network access, boot service or automatic restart is required.

## Fish commands

The installed function and completions live in `~/.config/fish/`. Reload them in
an existing terminal (new terminals load them automatically):

```fish
source ~/.config/fish/functions/gen.fish
complete --erase --command gen
source ~/.config/fish/completions/gen.fish

gen image                  # 'imagem' remains a compatible alias
gen video
gen qw                     # original isolated Bonsai launcher
gen gmmax                  # original Gemma profile
gen gmno
gen gmmed
gen gmrol
gen gmlow
gen status
gen logs                   # last 50 lines
gen logs 1 100             # inclusive range, at most 500 lines
gen logs 100               # at most 500 lines starting here
gen logs 1 100 --run ID    # previous run
gen logs --follow          # last 50 + incoming raw messages
gen logs 1 --follow        # from line 1 + incoming raw messages
gen stop
```

An active service **does not certify model readiness**. Text profiles preserve
all additional launcher arguments, environment, cwd and umask. Image/video do
not accept extra generation settings. Launchers remain in foreground under
systemd, without interactive stdin; output goes to the private run log.

## Human presentation and offline Rich

Help, diagnostics and completions are in English. Result tables use understated
copper on eligible TTYs; pipes, `NO_COLOR` (even empty) and `TERM=dumb` disable
color. Values are literal, not Rich markup. No TUI, animations or invented
progress. Launcher log content remains unchanged and may use its own language
or ANSI styling.

`vendor/` contains official pure-Python wheels: Rich 15.0.0 and its complete
mandatory dependencies, totaling **1,662,467 bytes (~1.59 MiB)**. They are loaded
through Python's zip importer, lazily for human results only, with SHA256 checks.
They are never installed, extracted or fetched at runtime. See `vendor/README.md`
and `vendor/manifest.json` for provenance, pinned versions and embedded licenses.
Missing or corrupt presentation assets fall back to plain English output; a
successful lifecycle command must never be reported as failed because of Rich.

## Pure JSON contract for tools

```fish
gen --headless status
gen status --json            # status-only compatible alias
gen --headless logs 1 100
gen --headless image
gen --headless stop
gen --headless --help
```

`--headless` must precede the command. Every completed headless invocation
produces one JSON object on stdout and no diagnostic text on stderr:

- start/stop/status: existing public success objects remain unchanged;
- finite logs: `{"lines":[{"number":1,"text":"original message\n"}]}`;
- help: `{"help":"usage: gen ..."}` (no controller constructed);
- errors: `{"error":{"code":"refused","message":"public reason"}}`;
  other codes are `operation-failed` and `invalid-arguments`.
- exits: 0 success/help, 1 refused/failed operation, 2 invalid CLI arguments.

**Contract evolution:** older headless logs were numbered text and errors were
text on stderr. They are now JSON, explicitly preparing for MCP. Original log
characters (including ANSI) are JSON-escaped, not rewritten. Use bounded reads
for agents; `--headless logs --follow` is rejected before any controller I/O.
Human `--follow` pins the original private inode/run, has no total line limit,
and Ctrl+C stops only its tail observer. It never switches models automatically.
Finite reads truncate giant individual lines at 4096 characters and preserve
line numbering; default tail returns the last 50 lines.

After a profile name, every token belongs to its launcher: `gen qw --headless`
does not activate controller headless mode; it forwards that argument verbatim.
Unexpected parser/private OS errors do not echo caller arguments or secret paths.
Import/help never starts models. MCP registration belongs to its caller project,
not this standalone tool; H3 contains a thin native adapter.

## Ownership and safety

State remains in `~/.local/state/gen`; relocation never moves or edits it.
A lock serializes start/stop. A different active profile is not replaced;
request `gen stop` explicitly first. Uncertain start results are retained and
never retried automatically. Stop verifies the service's transient flag, unique
run description and exact controller invocation before touching it. The exact
former H3 runner path is recognized for pre-migration owned services, with the
same run marker and invocation boundaries, without restarting those models.

External recognized ComfyUI/llama-server processes block start and are never
stopped by gen. This is not a universal GPU inventory. Reserve `gen.service`:
the lock coordinates gen clients, not another same-user program manipulating
systemd units. Models/ports/samplers/contexts/CUDA remain unchanged. Video keeps
MemoryHigh=79% and MemoryMax=80%; other profiles receive no extra gen cap.
Parent user-slice limits may still apply. No restart policy or boot enablement.

Original external launchers stay untouched:
- `/home/alex/.config/my_scripts/start.sh`
- `/home/alex/.config/my_scripts/start_video.sh`
- `/home/alex/Applications/bonsai2/run-bonsai2.fish`

The five Gemma launchers and `launchers/provenance.json` accompany this tool.
Their exact argv is derived from the old fish abbreviations; sampler quoting,
reasoning and model/draft settings are frozen. Gemma uses fish without loading
config; the original qw shebang behavior is preserved. Migrated abbreviations
are retired when the function is sourced; other aliases remain untouched.

Private launch files contain the original caller environment and may contain
secrets. Never share them, version them or expose them to MCP. Model logs may
also contain private content; log access is explicit. There is no log rotation,
and finite tail scans the file with bounded memory. A stuck systemd manager may
block the CLI; a caller timeout is not proof that the model did not start.

## Offline CPU validation

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run --no-project --python /usr/bin/python3 python -B -m unittest discover -s ~/.config/my_scripts/gen -p 'test_*.py' -v
uv run --no-project --with ruff ruff check --no-cache ~/.config/my_scripts/gen
fish --no-config --no-execute ~/.config/my_scripts/gen/gen.fish
fish --no-config --no-execute ~/.config/my_scripts/gen/completions.fish
```

Tests use fake service managers, instrumented printf-only launchers and private
temporary text logs. Wheel smoke tests use `/usr/bin/python3 -I -S` without site
packages or networking. No real model load/generation is part of validation.

Historical migration backups/evidence remain local to the H3 checkout under
`.dumps/gen-sacred-backup/`, `.dumps/gen-rich-backup/` and
`.dumps/gen-migration-incident.md`. An earlier abbreviation migration had a test
mock incident that may have reached gmmax; it was cancelled and documented.
Do not retroactively claim that historical delivery never invoked a model.
`.dumps` is not an external backup; preserve elsewhere for disk-loss protection.
