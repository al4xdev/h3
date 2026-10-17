# H3 benchmark MCP — local adapter, not another generator

The MCP reuses **a single invocation** of `tools/benchmark_h3.py`. The scenario, seeds, validation, technical review, and assembly remain defined exclusively in that CLI. The adapter does not start an API, does not call ComfyUI, and does not alter models, caches, or parameters.

## Actual host registration

The installed plugin `dsh-customs/plugins/project-mcp` reads `<Git root>/.agents/mcp.json` when an Agent is created or resumed. The registration for this project is:

```json
{"mcpServers":{"h3_benchmark":{"builtin":true,"toolsDir":".agents/tools","timeoutMs":30000,"failOnStartupError":true}}}
```

The shim `.agents/tools/benchmark.mjs` exports the adapter `tools/benchmark_mcp.mjs`. **Do not** point `toolsDir` to `tools/`: the loader imports all immediate `.mjs` files, which would include the executable exporter. The registry is trusted executable configuration, not a sandbox.

The generic plugin server uses the installed official SDK `@modelcontextprotocol/server` **2.3.1**; the native DSH client uses `@modelcontextprotocol/client` **2.0.0**. There is no manual JSON-RPC protocol, no new Python dependencies, and no modification of global plugins or configuration. `.agents/config.json` and `dshCustoms.managedPlans.autoApprove=true` remain intact.

**Discovery requires a newly created or resumed Agent.** Editing these files does not guarantee an update to the catalog of an already active Agent. Offline testing verifies schema/registration, handshake, and calls by the real client; it is not proof of retroactive availability across all sessions.

## Tools

- `mcp__h3_benchmark__benchmark_info`: contract, command, and CLI hash; no spawn, HTTP, or GPU.
- `mcp__h3_benchmark__benchmark_start`: `{"label":"comparison-one","technical_acceptance":true}`. The API must be active at `http://127.0.0.1:8010`. Consumes **three real GPU generations**; returns its own UUID immediately, not completion.
- `mcp__h3_benchmark__benchmark_status`: `{"job_id":"<returned UUID>"}`. Reads only the bounded status/report for that job; no process control, internal polling, or replay.

Start accepts only lowercase labels matching `[a-z][a-z0-9-]{0,63}` and explicit opt-in. It does not permit arbitrary commands, environment variables, paths, external URLs, parent IDs, or scenarios. Only the two new benchmark parents receive technical acceptance to proceed; visual approval remains pending and the last chunk stays ready for review.

The process receives exactly `uv run --no-sync python tools/benchmark_h3.py --api-url http://127.0.0.1:8010 --output-dir .dumps/benchmarks/mcp-<label> --technical-acceptance`, the project cwd, and `PYTHONDONTWRITEBYTECODE=1`. Worker stdout/stderr are redirected to dedicated files, never to protocol stdout. No import, initialize, list, info, or status call generates videos.

## Durable state and honest concurrency

- `.data/benchmark-mcp/jobs/<UUID>/job.json`: intent, command, and hash before spawn; PID and Linux process identity after spawn; terminal state/error when observed.
- In the same directory: private `stdout.log`, `stderr.log`.
- `.data/benchmark-mcp/jobs/active.json`: atomic `O_EXCL` lock shared across the project's MCP servers; release requires the owning UUID.
- `label-<label>.json` in that directory permanently reserves labels: failures do not authorize recycling a test run.
- `.dumps/benchmarks/mcp-<label>/report.json` and `benchmark.mp4`: benchmark scratch, without migrating legacy chunks in `runs/`.

The lock serializes **MCP starts**, not direct CLI/API invocations. The backend's global slot, RAM telemetry, and own-prompt checks remain the generation authority. Existing labels and directories are never overwritten; even two concurrent servers cannot duplicate the same start. There is no automatic resume.

The worker may continue running if the calling server or session terminates: it is asynchronous, detached, with dedicated logs. Upon reconnection, status correlates PID and `/proc` start-time/argv, but does not kill PIDs or release locks based on assumptions. A `running` record with `process_identity_confirmed=false` is an **uncertain result**, not inferred success or failure. A completed CLI report does not automatically promote the server's lost terminal state.

In case of crash or uncertain result: preserve job, lock, and ledger; inspect the UUID, process identity, and known IDs from the report without launching new inference. Only an operator may resolve their own lock after verifying worker absence and terminal outcome; never clear another UUID's lock, delete outputs, or pick a new label to repeat an uncertain POST. The adapter offers no generic cancel/kill tool or automatic recovery.

## Offline verification

```fish
node --test tests/test_benchmark_mcp.mjs
env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run ruff check --no-cache src tests tools/benchmark_h3.py
```

Tests use an EventEmitter / inert worker injected strictly by test code, never via MCP arguments. The handshake uses native SDK/registry wiring without starting the API or running the real CLI. Technical output does not certify facial identity, correct color/pose, or perceptual continuity: reviewing the assembly and contact sheet remains mandatory.
