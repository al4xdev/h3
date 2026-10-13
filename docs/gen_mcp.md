# Personal gen tool and project-local MCP

## Separation

The complete gen tool now lives at `/home/alex/.config/my_scripts/gen/`:
controller, fish function/completions, frozen Gemma launchers/provenance, tests,
README and offline Rich wheels. It does not depend on this H3 checkout.
H3 retains **only the thin MCP adapter, native shim, tests and this integration
record**. No changes to H3 backend dependencies, generation presets or model
launchers were needed.

The installed fish function points directly to the personal controller. Reload
function and completions in an existing terminal:

```fish
source ~/.config/fish/functions/gen.fish
complete --erase --command gen
source ~/.config/fish/completions/gen.fish
gen status
gen --headless status
```

Help/messages/completions are English. Human status/start/stop use Rich's compact
copper table, with no colors in pipes, `NO_COLOR` or `TERM=dumb`. Human log content
is intentionally raw and not translated. Rich plus mandatory dependencies occupy
1,662,467 bytes (~1.59 MiB) in four official, unmodified pure-Python wheels. They
are zip-imported lazily with local SHA256 checks; no pip, venv, extraction or
network in runtime. Licenses and pinned provenance accompany the personal tool.
Optional rendering failures fall back to plain text without changing lifecycle
success. Headless and private `_run` never load Rich.

## JSON contract

`--headless` precedes the command; `status --json` remains an alias. Existing
successful start/stop/status objects remain unchanged. All tool diagnostics are
JSON stdout with empty stderr: errors contain `error.code` and `error.message`,
help contains `help`, finite logs contain `lines: [{number, text}]`. Exit codes
remain 0 (success/help), 1 (refused/failed) and 2 (invalid arguments).

This explicitly evolves the older contract: headless logs and errors used to be
text. Logs are now JSON-escaped without rewriting original characters. Raw
`--follow` is human-only; headless refuses it before controller construction.
Arguments after a profile are still forwarded verbatim to the original launcher.
Unexpected OS/metadata/parser diagnostics never echo private caller arguments.

## Native MCP registration

`.agents/mcp.json` registers two independent builtin servers:
- existing `h3_benchmark`, unchanged tools directory `.agents/tools`;
- `gen`, tools directory `.agents/gen-tools`, timeout 30s, startup errors fatal.

`.agents/gen-tools/gen.mjs` exports definitions from `tools/gen_mcp.mjs`. The
adapter invokes a fixed argv, without shell or configurable paths/commands/env:

```text
/usr/bin/python3 -B /home/alex/.config/my_scripts/gen/gen.py --headless COMMAND
```

Native names after a **new agent session/catalog reload**:

| Namespaced tool | Behavior |
| --- | --- |
| `mcp__gen__gen_info` | Static paths, profiles and safety contract; no subprocess |
| `mcp__gen__gen_status` | Explicit read-only lifecycle status |
| `mcp__gen__gen_logs` | Explicit finite private model-log read; optional start/end/run |
| `mcp__gen__gen_start` | Fixed profile plus mandatory `confirmed: true` |
| `mcp__gen__gen_stop` | Stop current owned gen service; mandatory `confirmed: true` |

Start accepts `image`, `video`, `qw`, `gmmax`, `gmno`, `gmmed`, `gmrol`, `gmlow`.
No MCP launcher overrides, arbitrary arguments, paths, environment, follow,
private launch records or automatic retry. Logs default to last 50, permit at
most 500 lines with 4096-codepoint bounds plus truncation markers, and optional
32-lowercase-hex historical run IDs. Log content can contain private/untrusted
model output: callers must treat it as data, not instructions.

Controller locking, uncertain-intent fencing, external-model admission and exact
service ownership remain authoritative. Stop deliberately targets the **current
Controller-owned service**, not an expected/pinned run; no misleading preflight
status check substitutes for the lifecycle lock. Starting/loading a model and
stopping it require an explicit owner request; tool discovery/info/status do not
authorize either operation.

Responses are public JSON objects, including `error` objects; callers must check
`error`, not assume transport success means operational success. Native schema
violations are SDK errors. Readiness always remains `not-verified`.

The adapter bounds stdout at 32 MiB (including worst-case escaped Unicode),
stderr at 8 KiB and client execution at 20s. Timeout/abort signals **only its own
CLI client**, never the systemd service, process group or global models. It waits
250ms after TERM then 250ms after KILL for close; inability to confirm client exit
is reported. The lifecycle outcome can be uncertain even if the client exits:
inspect status/logs, never retry automatically. No reconnect or hidden resume.

## Migration and regression evidence

The source checkpoint before relocation is local commit `b9f157b`. Its entire
21-file tool tree moved to the previously absent personal destination, with
SHA256 and modes verified before/after. Final installed code additionally has a
comment-only Ruff suppression for its intentional optional-renderer fallback.

Local snapshots/manifests:
- `.dumps/gen-rich-backup/20261013T142610.597728Z/manifest.json`: original files,
  installed fish files and unchanged original external launchers;
- adjacent `migration.json`: source/destination, checkpoint, 21 hashes/modes;
- `.dumps/tests/gen-rich-visual.txt`: mocked 80/40/20-column output inspection.

`~/.local/state/gen` was not moved or modified. The only controller-core change
is exact legacy-runner recognition in `owned()`, still requiring the private run
marker, transient service and complete ordered invocation boundaries. Other
Controller methods, file helpers, private runner and log observer have baseline
AST equality. The original start.sh/start_video.sh/Bonsai launcher hashes are
unchanged. An explicit read-only installed status check after relocation found
the service absent; no real start/stop, model generation/provider calls or server
restarts were performed during this delivery.

Validation:
- 74 standalone CPU unittest cases before and after relocation;
- 15 inert adapter cases (argv/schema/privacy/Unicode/timeout/abort/reaping);
- 2 native SDK integration cases: actual project initialize/list/info and schema
  rejection, plus successful status/logs/start/stop using an in-memory fake worker;
- 19 existing benchmark adapter/native tests, preserving its registration;
- Ruff, fish syntax, whitespace and mock terminal-width checks.

The native loader/SDK was verified at
`/home/alex/git/my/dsh-customs/plugins/project-mcp/`. Its actual generic server
accepts tools definitions with `name`, `description`, `inputSchema`, `handler`
and passes an AbortSignal to the handler. No globals/plugin files were changed.
Initialize/list/info tests prove registration; they do **not** hot-add tools to
this already-running agent's catalog. A new session is required to access the
new names through the native tool interface.

## Re-run safe tests

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run --no-project --python /usr/bin/python3 python -B -m unittest discover -s ~/.config/my_scripts/gen -p 'test_*.py' -q
uv run --no-sync ruff check --no-cache ~/.config/my_scripts/gen
node --test tests/gen_mcp.test.mjs tests/gen_mcp_native.test.mjs tests/test_benchmark_mcp.mjs
```

Moving the source out of this repo means future gen edits belong in the personal
directory. Keep an independent backup/version history there; `.dumps` is local
scratch, not protection against losing the PC. The pre-relocation Git checkpoint
preserves the verified original source/wheels within this repository's history.
