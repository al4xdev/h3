# Durable state in `.data`

The Store uses **only `.data/runs/<UUID>/`** for manifests, inputs, prompts, executed workflows, telemetry, and videos. `project_root` remains the root for `workflows/`, `prompts/`, and `assets/`; do not configure `H3_PROJECT_ROOT=.data`. URLs remain `/runs/<UUID>` and `/runs/<UUID>/video`.

`runs/` is the preserved legacy anchor, not a second writable Store. The migration copies all files and directories (including hidden and nested diagnostics), without altering JSON, states, decisions, or provenance. A failed run without video is valid. Historical Comfy/probe paths and import telemetry remain historical records, not execution inputs.

## Explicit offline migration (fish)

First stop **only this project's own API** and confirm the absence of other writers. Do not stop or restart ComfyUI. The tool does not perform networking or inference, and does not rely solely on the `--offline` flag: it acquires an exclusive product lock. An active runtime holds a shared lock until shutdown; a separate lease permits only one backend per project. Read-only Stores in the same process remain compatible.

```fish
# Preflight: does not copy or publish media.
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/migrate_state.py

# One intent, verified copy, publication without overwrite, and final receipt.
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/migrate_state.py --execute --offline
```

Preflight reads all of `runs/`, verifies UUIDs/manifests, and rejects queued/running runs, symlinks, special files, destination collisions, and insufficient disk space. Execution creates an immutable intent at `.data/migrations/<UUID>/intent.json`, copies to `staging/runs`, compares source and destination inventory and SHA256 checksums, and publishes **only** the `.data/runs` subtree using Linux `renameat2(RENAME_NOREPLACE)`. It will not overwrite even an empty concurrently created destination. Each file and directory publication is fsynced.

After publication, `.data/migrations/<UUID>/verified.json` and `.data/state/migration.json` record the intent UUID, root, destination, inventory, IDs, and checksum. Startup fails closed if legacy data or an intent exists without a valid receipt, or if proof and receipt diverge. Importing modules does not migrate or resubmit jobs. New projects without legacy data can create `.data/runs` directly.

`.data/benchmark-mcp/` belongs to the MCP adapter and remains untouched. `.dumps/benchmarks/` continues as CLI scratch/evidence, not durable application state.

## Crash and reconciliation

Do not delete staging or receipts, and do not attempt another intent to hide an error. Originals remain untouched and can be inspected as an anchor; the new runtime does not fall back to them as writable targets. Partial staging or a diverging source requires investigation, not automated copying or replay.

With the UUID **already recorded** in an intent file, a complete copy that remains identical to the source can be finalized explicitly:

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/migrate_state.py --execute --offline --reconcile INTENT-UUID
```

Reconciliation does not recopy anything: it verifies all bytes, IDs, and root paths before publishing complete staging or finalizing an already-published step. Divergent sources, partial stages, alternate destinations, or symlinks are rejected. Once a receipt exists, rerunning the tool is idempotent: it recognizes the migration and **does not** compare or restore mutable canonical manifests from legacy data. New decisions and new chunks remain in `.data`.

Do not blindly revert to older code after new decisions are made. Snapshot and preserve `.data`, and use code compatible with this authoritative store. No directory is deleted by the migration.

## Technical contract for consumers

- `Store.root`: project resource root, unchanged.
- `Store.runs` / `Store.directory(UUID)`: canonical physical root/directory in `.data`.
- `Store.relative_artifact(UUID, filename)`: persistable string `.data/runs/<UUID>/<filename>`.
- `Store.own_artifact(UUID, persisted_path, filename)`: validates ownership and returns the canonical physical path. Allows `runs/<SAME_UUID>/<filename>` **only** for IDs present in the copy proof/receipt; does not create symlinks or rewrite manifests.
- Allowlist: `chunk.mp4`, `initial_frame.png`, `last_frame.png`, `reference_tail.mp4`, `workflow_api.json`, `prompt.md`, `telemetry.jsonl`, `telemetry_error.json`. Not an arbitrary file resolver. Rejects mismatched UUIDs, non-canonical prefixes, absolute paths, traversal, and symlink ancestors.
- `source_root: runs` remains a logical category for own references; strings for new references and `slot_map` use `.data/runs/...`. `source_root: assets` and original identity references are preserved.
- `Store.sequence` remains metadata-only and reads solely the selected ancestral chain. `restore` observes only the canonical authority, interrupts queued/running jobs without replay, and preserves terminal states.

The benchmark CLI reuses the ownership resolver; scenario, STAGES, Markdown, seeds, models, and parameters remain identical. No additional generation is required to test the migration: CPU fakes and GET requests for existing videos suffice.
