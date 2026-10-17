# H3 — standing instructions for agents

## Project objective

Build a lightweight local application that transforms reference material and scene instructions into chained videos: image → first chunk → continuations → review → assembly. Preserve visual continuity and allow intentional changes of action/clothing. Materialized files under `.data` are the authority; HTTP is only the local bridge to the browser. Benchmark and MCP are development and operational instruments, not the end product.

The owner has authorized autonomous work: investigate, propose plans, implement phases, test, run own benchmarks, and create local commits. Do not wait for routine approval at each step within this scope. Follow the task revisions approved by the plan system; this instruction does not replace that authorization or harness rules. Do not edit managed plan files directly.

Explicit owner correction on 2026-10-13: this session does not use the plan harness. Directly create and maintain new backlog files in `.plan/backlog/` and new active plans in `.plan/task/`. Do not rewrite managed historical plans in `.plan/tasks/` or `.plan/closed/`.

Autonomy does not authorize: changing generation parameters to attempt improving the model, sacrificing quality for performance, controlling ComfyUI globally, deleting data, disclosing secrets, pushing commits, or repeating a submission with an uncertain outcome. Under out-of-scope risk or genuine ambiguity, halt the affected operation and record the evidence.

## Current product direction: Tail continuation

- Freestyle is legacy mode, retained for compatibility, inspection, and converting existing sequences to scripts. Do not concentrate new features in it; the script is the primary experience.
- Every continuation requires at least one complete, published, and accepted video block so that a real prior video and its final frame exist. In a new sequence, generate the root block first via I2V; an isolated image or a draft does not replace the parent video. The first generation must finish and be accepted before running V2V. In a confirmed batch, intermediate acceptance may be technical, as in the current workflow.
- Active priority: Tail, or tail extension. Append new blocks to the end of a sequence from a user prompt, reusing existing script, structured JSON, and sequential batching.
- Maintain two distinct Grok stages: block intent planning and per-block prompt refinement immediately prior to generation. Planning does not know the frames yet to be generated and must not be treated as a final prompt already tailored to pose or as a guarantee of exact chronology.
- In refinement, use the original identity and the real last frame of the most recently accepted parent. In V2V generation, preserve the existing native video/tail context. Never use the opening frame of the batch for all continuations, nor fall back to raw text if Grok fails.
- In-between editing across anchors is a distinct mode, separate from Tail, authorized later by the owner: remaking a block creates another version; inserting before/after creates a new block. The initial delivery edits one video per request and requires two accepted neighbors. Without a right neighbor, use Tail; prior to the first root, no parent video exists for this operation.
- The Grok editing route has its own configuration and receives identity + last frame of the previous + first frame of the next, in addition to the prompts effectively sent to both neighbors, labeled in English as historical context. The previous video goes to the native engine, not to Grok. The bridge operation derives V2V with a target guide at frame -1, without altering golden graphs or native parameters. Integration validated with CPU/fake fixtures; artistic continuity requires real human review.
- Versions, media, and historical parents are immutable. The script preserves editorial selection per block; editorial assembly uses that order and its versions without rewriting run ancestry. Adopting an edit requires an accepted video and a script revision that remains compatible. Querying/reloading never generates; explicit retry preserves prompt and both anchors, with another UUID.

## Architecture: Fluent Python and strong verticality

- Each operation concentrates its composition, state, business validations, router, and execution sequence in its own vertical file. Current examples: `generation/i2v.py` and `generation/v2v.py`.
- Fluent composition must be clear and complete; setters only compose state, without hidden I/O or execution. Prefer immutable state/dataclasses and explicit arguments.
- A dispatcher coordinates admission, global slot, worker, and request lifecycle; RAM is purely observational telemetry, not execution policy. A `workflow.py`/builder configures both native modes.
- Do not split an operation into a horizontal collection of small services, handlers, commands, or registries. Do not create a DSL, plugin framework, or class hierarchy for a simple flow.
- `infrastructure/` contains shared technical adapters, not a second business layer.
- Python backend does not import PyTorch or load models; it coordinates ComfyUI. Importing/composing tools does not start jobs.
- Preserve existing HTTP entrypoint and contracts, or migrate them explicitly with compatibility tests.

## Most recent decision: local app and paths as source of truth

- The `.data` folder lives **on the PC**, not on mobile. Upload from mobile via the web page is saved to that folder; selecting media already materialized there must also be supported. No cross-device synchronization or second state source.
- Local Python server is a small bridge: serves JS, reads metadata, receives upload with atomic writes, and delivers own files via streaming/Range requests. Do not build a traditional backend, database, broker, external queue, horizontal layers, or complex messaging protocol.
- Explicit requests live in their own JSON file; `.locks` coordinate local writers/executors. A lock alone, a media change, or opening the page never authorizes generation. Do not automatically repeat uncertain intent or interrupted jobs.
- Worker monitors paths on the PC via filesystem events (Linux/inotify), not front↔back polling. An SSE notification only indicates that a path changed; JS re-reads the corresponding files/metadata. Initial registration and event recovery must avoid dropping changes; reconnection must not re-trigger generation.
- Python does not decode/manipulate pixels or keep entire images, frames, or videos in memory. FFmpeg/ffprobe perform validation, extraction, staging, and assembly outside the Python process. Hashing/copying/streaming encoded bytes use bounded buffers. No Pillow in runtime; JS/Canvas may construct visual comparisons. Historical CPU audit tools remain separate from the application.
- The browser requires the bridge to access the PC folder, especially from mobile; do not promise direct filesystem access without actual permission/support. The bridge does not expose the entire PC tree or allow arbitrary paths.
- Locks/filesystem do not eliminate ComfyUI model/tensor cache or Linux reclaimable file cache. Measure process RSS separately; do not promise gains simply from switching architecture.

## Grok: isolated text editor, not generation engine

The owner added the independent route in commit `041b014` and clarified: they want to describe their idea directly to Grok in simple language, without having to write a detailed prompt. A system prompt explains the task and can be modified in the frontend / persisted in its own configuration under `.data/grok/`.

- Later owner correction: send the selected image TOGETHER with `system_prompt` and `prompt` to the editor. The image is visual context, not output/image edit. Fixed model in `.data/grok/editor.json`: `grok-4.20-0309-non-reasoning`, verified on the official public card as text+image→text; initially untested on the account. Later, opt-in37 authorized ONE inference with two images, completed 200 without refresh/reauth/grant/config changes; authorization consumed, no implicit replay. Limits/quota/billing and full adherence to the proposal remain uncertified. Backend re-reads its own configuration and rejects differing overrides without picking another model automatically.
- In manual editor mode, the result becomes an editable text proposal; using the proposal and generating video remain separate explicit actions. Subsequent owner-authorized exception: confirmed batch automatically uses refinement for each block and technically accepts intermediates to proceed. Do not overwrite idea/draft on navigation or delayed response. Bounded self-reference with technical proof and streaming JSON/base64; Python does not decode pixels or hold the entire image in memory. Arbitrary URLs / private paths / OAuth are never references.
- Grok editor remains isolated from the generation engine. Batch and Tail composition belongs to the vertical orchestration operation, which reuses existing explicit routes/contracts; do not place Store/worker/review in the editor or generate upon page open, SSE, or reconnection. Explicit batch confirmation authorizes the automatic sequence within that request. Grok does not edit images on this route.
- Editor configuration is separate from `.data/grok/oauth.json`. Never read/display/copy credentials or modify the grant imported by the owner; preserve the independent OAuth module.
- No live calls to the provider during tests/import/startup/page open/SSE/reconnection. Models/authentication/inference only via explicit actions; no automatic retry of uncertain outcomes or arbitrary selection of the first model.
- Response is untrusted text: use `.value`/`textContent`, respect scene limit, and preserve draft on error. Do not modify native templates/benchmarks/presets to integrate the editor.

## Generation: streamline workflow, do not retune output

The owner has already configured the parameters. Preserve models, sampler, scheduler, steps, resolution/MP, frame formula, attention, conditioning, references, guides, VAEs, and final decode/export path. Do not experiment with parameters to obtain a "better" generation during streamlining.

Later explicit owner correction: duration must be adjustable PER BLOCK, including beyond 3s. The old cap is superseded. Additional owner correction (plan40): application default is 8s for new root blocks and continuations; 2.3s remains solely as the explicit duration of the frozen benchmark and historical records. Maintain 24fps and formula 5+17k/Python half-even, frozen graphs/benchmark. Plan24 defines requested (0,10] as operational budget, aligned maximum 243 frames / 10.125s; do not claim model maximum, safe RAM/VRAM, or validated long generation without evidence. Installed static schema MiniMaxH3ReferenceToVideo accepts length 5..3600 (step 17), tooltip trained ~124..362; this does not certify checkpoint performance/quality. UI shows requested→frames→effective time; tail context 3 / audio True remains independent. Output/hydration guard must match the chosen duration exactly, never removing validation merely to unblock input.

Investigate dependencies and actual execution before removing nodes. Fewer nodes in JSON does not mean less RAM: nodes outside output ancestry may not execute. Already bypassed branches do not justify promises of gain.

Initial audit proved that only `18`, `176`, `177` belong exclusively to the duplicated active preview. Preview uses latent output0; final uses denoised output1. Removing the preview does not authorize rewiring or reusing its decodes in the final output. Ancestors of final output `34` must remain structurally identical.

Keep golden graphs/manifests, prompts, and original references intact. Implement pruning as exact allowlist transformations and explicit profiles, with guards/provenance per profile; do not permit arbitrary removal. Baseline version must remain reproducible.

## Benchmark is the regression anchor

- Original stable generation: commit `502c13f`. Initial frozen tooling: `990e27a`.
- Reusable CLI: `tools/benchmark_h3.py`. Do not duplicate scenario, generation, or validators in MCP/frontend.
- Scenario: chunk1 original dance/BLACK dress; chunk2 small jump, changes dress to RED during the chunk and finishes BACK TURNED; chunk3 starts from that BACK TURNED frame, turns FACING FRONT / reveals facial appearance using original reference, and keeps RED.
- Original black photo remains unchanged. Seeds: `2026101205`, `2026101206`, `2026101207`. Request 2.3s → 56 frames at 24fps, 480×864 per chunk; three chunks → 168 frames / 7s.
- External assembly uses all frames, without overlap trimming, crossfade, color grading, or hidden corrections. Audio is padded to each boundary. Seams at frames 56/112.
- Opt-in `--technical-acceptance` only authorizes technical acceptance of the two new benchmark parents to proceed. It does not change API review policy or certify artistic approval; the third chunk remains ready for review.
- Save intent before each POST, then IDs/status/payload/probes/hashes/timings/telemetry. No re-inference loops, completion polling, automatic resume, or blind replay. An existing directory cannot be recycled to conceal failures.
- Compare the same scenario/seeds/parameters before/after, using new directories solely for authorized intentional comparisons. Record cache/warm/cold and measurement bounds. Equal seeds do not guarantee identical pixels; memory percentage or isolated IO does not prove SSD offload.
- Inspect assembled video and visual evidence of first/last frames; also inspect internal action/transitions. The benchmark contact sheet allows spotting pose, color, and appearance drift. Frame count, RGB/MAE, and hashes do not certify facial identity or perceptual equivalence. Do not install FaceID/embedding models for this test.
- Initial approved baseline: `.dumps/benchmarks/baseline-three-chunks/benchmark.mp4` and `contact_frames.png`; complete adjacent report. It took 410.259s end-to-end, including 2.057s assembly, with models/cache not restarted. Treat as observation, not an SLA or exact peak.

fish example, with API already running and genuinely new directory:

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/benchmark_h3.py --api-url http://127.0.0.1:8010 --output-dir .dumps/benchmarks/comparison-new --technical-acceptance
```

## Data and provenance

- `.data/` is the destination for durable application state: JSONs, manifests, inputs, videos, and durable assemblies, in dedicated subfolders. It is local/gitignored, not disposable.
- `runs/` contains real legacy data, including audited failures and imports. Do not assume they have already been migrated. Migration to `.data` requires a specific plan, reading/snapshot/hash, path/ID compatibility, publishing without overwrite, and verifiable cutover. Never move/delete merely because they are gitignored.
- `.dumps/` is local scratch/evidence: reports, ad-hoc requests, and test media. It is not a backup. Preserve `.dumps/references/` as long as asset provenance points there.
- Graphs, reference manifests, prompts, and versioned assets are real runtime resources, not disposable examples. Relocation only with a dedicated plan and adjustment/testing of all consumers.
- Preserve terminal states and decisions. Do not mutate failed to ready via manual JSON or private API; specific recoveries require proof, provenance, and legitimate public transitions.

## Local MCP and shared tools

Expose project tools via the host's proven native MCP mechanism: `.agents/mcp.json`, controlled shim directory `.agents/tools/`, and a thin adapter. Do not invent configuration fields; consult real schema/code/documentation. Do not point generic discovery to `tools/` if it imports executable scripts like `export_workflow.mjs`.

Keep `dshCustoms.managedPlans.autoApprove` and global configurations intact. Do not modify global plugins, credentials, or application dependencies to accommodate an adapter without proven necessity.

MCP must reuse existing CLI, with opt-in, bounded paths, anti-replay ledger, logs off protocol stdout, and identifiable own operation. Initialize/list/help/read do not submit GPU work. Smoke tests use an inert fake worker. Document namespaced tool names and whether discovery requires a new session; do not claim availability before verification.

## Git, testing, and operational safety

1. Read actual Git/plans/file state; do not assume prior narration remains current.
2. Snapshot existing resources and data; explicit file scoping, no two agents editing the same file. Capture changes from other agents without including them in own commit.
3. Cache-free CPU/fake tests, Ruff, whitespace/diff, and separate commit prior to real benchmark. No push. Use commits for non-destructive rollback; do not reset history or overwrite others' edits.
4. One global job at a time. Explicit owner correction (plan38) supersedes minimum RAM 1536MiB: the app does not reject admission or abort generation/assembly based on free RAM. The owner controls ComfyUI memory/lifecycle via their own script; do not touch that script/process/caches. Telemetry remains passive. HTTP 202 / admission is not completion. Dedicated prompt WebSocket and post-commit history event; long wait, no polling/replay. Explicit own cancellation / clean shutdown and deadlines remain; external outage does not authorize claiming success, resuming via new inference, or replaying.
5. Track all own jobs/processes. After finishing, collect results and shut down only the API created by the agent if there is no reason to keep it running. Do not restart/flush global ComfyUI caches/models/queues or stop external servers.
6. Failures/timeout/ambiguous result: preserve ledger/IDs/evidence, do not create another directory to blindly repeat the same generation.

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run ruff check --no-cache src tests tools/benchmark_h3.py
```

Use native tools for read/search/edit and `bash` for Git, build/test, and processes. Python via `uv`; user-facing commands in fish. Comments explain non-obvious decisions/constraints, not restating code.

## Final frontend: simple, lightweight, video-first

Simple HTML/CSS/JS, preferably same-origin served by backend; no framework/build/extra service without concrete justification. The page must enable viewing videos, states, and sequence, explicitly reviewing and continuing, with honest errors and loading indicators. Do not present failed/incomplete as ready video.

Intentional design tied to block-based assembly, not a generic dashboard; responsive, visible keyboard focus, clear labels, reduced-motion, and no heavy autoplay. Use existing real media, not placeholders. Follow `frontend-design` before creating UI and `browser-mobile-media` before automating mobile validation/capture with the native `browser` tool. UI tests must not trigger GPU via incidental clicks; real generation remains restricted to deliberate benchmarks.

Later owner correction: mobile must display a SCREEN flow, not all panels stacked. Library → reference/idea → editable Grok proposal → prepare generation/status → review → prepare continuation → assembly. One active main panel, clear Back navigation / focus / touch; preserve drafts by scene/parent/duration/reference and IDs/uncertainties during navigation. Using a proposal does not generate, accepting does not continue/assemble, back/reload/SSE never POST. Screen transient state does not replace `.data`; desktop remains usable. During these corrections do not restart production server or trigger provider/GPU incidentally: owner stopped server to conserve RAM.

Subsequent owner request: site must feel alive, with micro-animations / usage animations especially on mobile, analyzed by subagent interaction by interaction (plan26). Preserve real graphite/copper/filmstrip, one active panel, feedback solely on confirmed decisions/states. Motion is presentation: never issues POST/UUID/provider, alters review/payload/draft, autoplays, or waits for animationend for business logic. Prefer opacity/transform on static leaves, short entry ≤12px, press/feedback without shrinking hit target <44px, real reduced-motion, and safe dynamic preference change / cancellation / hidden handling. Never transform ancestors of position:fixed CTAs, videos, or native controls; no conflicting global gestures, invented progress, gratuitous loops, dependencies, or permanent will-change. Test normal AND reduced-motion contexts, touch during animation, focus/viewport/footer, rapid dedupe/SSE/Back, and invariant requests; capture/inspect real mocked frames before declaring aesthetic/performance quality.

Later owner correction in this session: use a dedicated teal/turquoise palette to differentiate the studio from ha_app. The Coisas de Casa reference remains in motion behavior: progressive loading of cards close to scroll and rubber-band bounce, preserving state and position upon returning. Do not materialize controls/history for the entire list upfront; reduced motion must not disable progressive loading. This color choice supersedes the previous graphite/copper UI requirement.

New owner correction (plan32): flow must feel like a mobile app, not pages with all options visible at once. Back lives at the top beside title and gear; Library/New scene are not global tabs. Settings is a screen with return to source, scroll/focus and draft preserved. Duration/seed belong to the unsubmitted block draft; Grok system/model/save live in a separate settings section, keeping pin/read-only and explicit local PUT. Do not edit duration of an already published result or turn a draft adjustment into a global preset. Remove duplicate fixed footer and internal scrolling from library/lists/panels; actions live in document flow, ancestry breaks into real cards. Do not block native gestures or transform ancestors of media/controls/topbar; reduced-motion remains real. Separate navigation from execution: inspecting/resuming draft under uncertainty does not clear flags or submitted state; Generate / new retry remain fenced, including by uncertain assembly. Opening/reloading assembly by UUID requires Library origin and Back, error/Re-read accessible for same ID, without POST or stale catalog erasing uncertainty.

Rejecting discards only that attempt, preserving media/decision/history. Offer preparing another attempt explicitly, in an isolated draft by ID; never reopen/mutate the rejected run or generate upon clicking prepare. Root uses registered reference and copied parameters; continuation uses the SAME original accepted parent, never the rejected child as parent. Missing/ambiguous metadata, unsupported refs, incompatible precision/tail/audio must block automatic copy with a clear reason, without substituting image/seed/parameters with defaults. Prepare/back/configure/open/navigate/SSE never POST generation; only Generate initiates a new request, and a new attempt again requires review. Do not promise equal bytes/pixels or clear locks/uncertainties to facilitate retry.

Additional owner correction (plan33): when drafting continuation, display and send TWO contexts to Grok — original identity reference and real last frame of accepted parent (current pose/outfit), with distinct labels. Prior to this correction the editor sent only identity; do not claim retroactively that both were sent. Native V2V already extracts the last frame and remains untouched. New I2V may publish only chunk.mp4; do not assume last_frame.png pre-exists. Dedicated CPU preview in editor derives decoded final frame from its own accepted video via FFprobe/FFmpeg, in private disk snapshots and bounded streaming; does not write to parent run, does not generate, or call provider/auth. Editor payload may indicate canonical parent, but never arbitrary frame path/URL. Technical adapter validates manifest/identity/SHA read-only without importing Store/worker/dispatcher or altering review. Grok sends identity + frame only on explicit click, with pin/custom system preserved, without fallback to single image if continuation context is invalid. Draft / delayed response also binds to parent ID. API/provider/GPU/models remain prohibited in tests / incidentally; use CPU fixtures and fake clients.

Retry must also exist for interruptions (plan34), preserving old terminal state. Retrieve literal Run.prompt ACTUALLY SENT — Grok-refined proposal if used, never substitute with raw idea or ask for fresh refinement automatically. Display this prompt on rejected/interrupted blocks and prepare new attempt directly on generation screen with prompt/ref/seed/duration prepopulated, without forcing a return to start. Re-editing or consulting Grok again remains a separate explicit option. Request with still uncertain/busy outcome does not authorize retry; confirmed metadata and admission fences remain mandatory. Prepare does not generate, Generate creates new UUID, and new attempt requires its own review. No resume/replay or mutation of rejected/interrupted.

## Autonomous execution order

1. Versioned instructions/roadmap.
2. Complete isolated MCP adapter.
3. Prune only the exclusive active preview and repeat frozen benchmark; promote only with technical proof and visual inspection. Upon regression, retain/reactivate baseline and record, without modifying presets to compensate.
4. Adopt `.data` via safe migration/compatibility and update consumers/tests.
5. Implement lightweight JS frontend to operate/view videos.
6. Validate data/API/MCP/UI integration, document fish commands, and deliver usable application with evidence. Complete goal only when this entire result is verified, not upon finishing a subphase.
