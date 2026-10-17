# H3 — Local Video Generation Studio

> **Note:** This project was originally built for my personal workflow and video generation setup, but the codebase is open for anyone who wants to use, explore, or build upon it. If you run it locally with your own ComfyUI installation, **we recommend running the project and workflow files through an LLM or coding agent (such as Claude / Claude Code)** to review and pinpoint any custom nodes that your ComfyUI setup might still be missing.

Block-by-block sequential video generation and human review built on top of validated native ComfyUI graphs. `.data` on the host PC is the single source of truth; Python serves the lightweight API/UI bridge, catalogs, uploads, and media, observing paths via inotify/SSE and orchestrating external tools without loading models or raw pixel data in memory. The bridge/worker, isolated Grok prompt enhancer/scripting, and FFmpeg assembly are integrated and verified. Human review remains explicit. See [local architecture](docs/local_architecture.md).

Standing decisions on autonomy, vertical architecture, benchmarks, MCP, data storage, and the Android interface are documented in [`AGENTS.md`](AGENTS.md). The goal is a responsive, local chained video creation app, not merely a generation script.

The Store persists state, JSON metadata, and media under `.data/runs/<UUID>/`. `runs/` is preserved as a legacy anchor; projects with existing data require [verified offline migration](docs/data_storage.md) without rewriting manifests or deleting videos. `.dumps/` remains scratch/ephemeral evidence, while `workflows/`, `prompts/`, and `assets/` reside at the repository root.

## Launching the Local Studio

From the repository root, with FFmpeg, ffprobe, and a working ComfyUI instance available:

```fish
uv sync
env PYTHONDONTWRITEBYTECODE=1 uv run --no-sync uvicorn h3_backend.api:app --host 127.0.0.1 --port 8010 --timeout-graceful-shutdown 5
```

Open `http://127.0.0.1:8010`. To connect from mobile over the same **trusted local network** on port 8888:

```fish
./start.sh
```

The script starts the server on `0.0.0.0:8888`. On the host PC, open `http://127.0.0.1:8888`. On mobile, open `http://<PC-LOCAL-IP>:8888` (check with `hostname -I`). **Do not expose this server to the public internet**: it directly manages local filesystem operations and execution permissions on your host PC. Shutting down the bridge waits up to 5 seconds for open HTTP/SSE connections before teardown; closing the bridge does not unload ComfyUI models (they run as separate processes).

- **Roteiro (Story / Script mode)**: plans consecutive chunks in `/roteiro`: idea + visual reference → structured block proposal → explicit review/adoption → step-by-step block preparation. See [roteiro documentation](docs/roteiro.md).
- **Generate Remaining Blocks**: runs the confirmed script sequentially, refining each block with Grok, technically accepting intermediates to proceed, and halting at the final block for human review. Errors or stops cleanly halt the batch without unverified retries.
- **Tail Continuation**: appends new blocks after the last accepted video. A single user prompt produces an editable structured proposal preserving existing history.
- **Bridge / In-between Editing**: allows inserting blocks or re-doing intermediate chunks between two accepted anchors (previous block's last frame and following block's first frame). Grok receives identity reference, the two anchor frames, and historical prompts as context.
- **FFmpeg Sequence Assembly**: stitches accepted chains into a single video without re-encoding quality degradation, ensuring continuous audio coverage across chunk boundaries.
- **Android Mobile App**: a dedicated native Android client (`mobile_app/`) featuring gesture navigation, live status updates, and push notifications via FCM for completed blocks. Pre-built APKs are available under GitHub Releases.

## Project Structure

```text
src/h3_backend/
├── __init__.py
├── api.py                 # HTTP endpoints, query, review, and notifications
├── roteiro/               # Structured script narrator, timeline, palette & cards
├── generation/            # Vertical generation slice
│   ├── __init__.py
│   ├── i2v.py             # I2VPipe: image-to-video root chunk flow
│   ├── v2v.py             # V2VPipe: video-to-video continuation flow
│   ├── dispatcher.py      # Single-slot worker, job admission and lifecycle
│   ├── workflow.py        # WorkflowConfig builder and ComfyUI graph compiler
│   └── models.py          # Generation requests, settings, and Run data
├── notifications/         # FCM push notifications for Android clients
└── infrastructure/        # Shared adapters
    ├── __init__.py
    ├── comfy.py
    ├── media.py
    ├── store.py
    └── telemetry.py
mobile_app/                # Native Android application (Jetpack Compose / Gradle)
workflows/                 # Native ComfyUI graphs, golden exports, and manifests
prompts/                   # Generation & continuation prompt templates
assets/                    # Normalized reference assets and provenance metadata
tests/                     # Comprehensive pytest regression suite
tools/
├── export_workflow.mjs    # Native workflow exporter
└── benchmark_h3.py        # 3-chunk end-to-end benchmark CLI
pyproject.toml, uv.lock    # Python dependencies and locked resolution
.data/runs/<id>/           # Local runtime: manifest, inputs, and chunk.mp4
.data/roteiros/<id>/       # Local runtime: script plans, candidates, and history
runs/<id>/                 # Preserved legacy anchor
.dumps/                    # Local temporary scratch and evidence
```

## What to Preserve

- **Versioned:** Codebase, `tests/` suite, prompts, normalized assets, `workflows/` graphs/manifests, exporter, and lockfiles.
- **Local Persistent:** `runs/` contains real chunks and inputs required for continuation. Being gitignored does not make them disposable.
- **Local Ephemeral:** Ad-hoc requests, reports, and scratch belong in `.dumps/`, never in Git.
- **Private Provenance:** Keep `.dumps/references/` as long as `assets/reference_manifest.json` points to it.
- **Workspace:** `.plan/` is managed locally and `.agents/config.json` is local config; neither is committed.

## Validation & Testing

Requires `uv`, Python ≥ 3.12, and FFmpeg/ffprobe in your `PATH`. Pillow is a **dev-only dependency** used for test fixtures and historical tooling; the runtime relies exclusively on FFmpeg/ffprobe and bounded buffers.

Run test suite and linters from the root directory:

```fish
uv sync
env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run ruff check --no-cache src tests
```

Tests use mock ComfyUI transport and synthetic CPU media fixtures: no GPU or model execution is triggered during testing.

## Output Profiles (Opt-in)

The default output profile is `baseline`: 75 nodes (I2V) / 78 nodes (V2V), including native video/audio preview decodes. Setting `H3_WORKFLOW_OUTPUT_PROFILE=final_only` prunes only preview nodes (`18`, `176`, `177`), reducing graph complexity to 72/75 nodes while leaving final output node `34` unchanged.

To select the profile:

```fish
env PYTHONDONTWRITEBYTECODE=1 H3_WORKFLOW_OUTPUT_PROFILE=final_only uv run uvicorn h3_backend.api:app --host 127.0.0.1 --port 8010 --timeout-graceful-shutdown 5
```

## Android App & Releases

The native Android application is located in `mobile_app/`. Built debug APKs can be found in `mobile_app/release/` and are published as GitHub Release assets.

To build the APK locally using the containerized Android toolchain:

```bash
./mobile_app/build_apk.sh
```

## Android App Backlog

Items noted for upcoming improvements:

- **Opening chunk and cinematic vision**: ensure the script's visual context is passed cleanly to the opener prompt refinement.
- **Notification registration status**: reflect device registration state in Settings via `GET /notifications/devices`.
- **Backend safeguards**: edge-case handling for large multi-beat plans and long FFmpeg assemblies.
