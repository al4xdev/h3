# Roteiro — plan the whole sequence and generate in order

**Implemented in accordance with plan 41.** Approved specification: [screens v2](design/roteiro-telas.md), [flow and critique](design/roteiro-fluxo.md), and [JSON contract](design/roteiro-contrato.md). Fake/CPU validation and emulated mobile testing are described below; no new live inference was performed.

## Usage

1. Library → **New script**, or navigate directly to `/roteiro` on the local bridge.
2. Select an owned reference and describe the idea. Name, block count, and initial duration are configured in options; the current 8s default duration is loaded from capabilities.
3. **Propose script with Grok** or **Write blocks manually**. The proposal populates action, duration, and base instructions for all blocks; future videos, parents, and frames do not exist yet.
4. Review/edit directly on the card and choose **Use this script**. This saves the plan on the PC without generating.
5. **Prepare block N**: review identity and, for continuations, the REAL last frame of block N−1's accepted attempt. Base instructions are prefilled. **Detail** is optional; Grok candidates are applied to selected text only via **Use this proposal**.
6. **Generate** saves the chosen draft and submits that exact instruction, duration, seed, and parent. Status tracking and review screens match Freestyle mode.
7. Explicitly accept or reject. Acceptance unlocks the next block, but does not prepare or generate it automatically. Rejected or interrupted attempts offer retry using the literal FINAL prompt and the same original parent; previous attempts remain untouched.
8. All blocks accepted → **Prepare assembly** → explicitly **Assemble**. Assembly stitches the actual accepted chain, not planned cards.

**New freestyle** keeps Freestyle mode available without requiring a script. There is no secondary video engine, dispatcher, queue, or alternate review/assembly implementation. Panels and handlers are shared; only script context and admission logic are added.

## Generate remaining blocks

**Generate remaining blocks** generates all blocks that have never been submitted, in script order, including blocks in the middle of a sequence. Each pending segment continues from the selected accepted version of the preceding block (the first script block runs via I2V). When the block following a segment already has an accepted version, the final block of that segment is generated as a **bridge** targeting its first frame, using Grok's edit context (identity + last frame of parent + first frame of target, configured under `roteiro-edits`). A rejected prior block, a block lacking an accepted version, pending reviews, or uncertain outcomes block batch execution with an informative message.

Confirmation authorizes one Grok call before each block, automatic application of refined text, and technical acceptance of intermediate blocks to chain the next one. Technical acceptance does not certify artistic quality. The final block remains ready for review; assembly remains a separate explicit action.

Batch execution freezes sequential editor instructions and base blocks. For each step, it records editor intent, passes identity and, for continuations, the real last frame of the accepted parent; it stores the response used, updates only the block prompt, and triggers generation with the recorded seed, duration, and parameters. It never falls back to raw text. Intents and responses are stored in `.data/roteiro-batches/` with IDs known prior to submission. Errors, halts, uncertain disconnections, or restarts do not repeat provider calls or GPU execution.

`POST /roteiros/<id>/batches/<UUID>` requires `expected_revision`, `auto_accept_intermediate: true`, and `enhance_with_grok: true`; returns 202. `GET` on the same URL inspects batch progress; `GET /roteiro-batches/current` discovers global state without side effects. SSE broadcasts path updates and the client re-reads those files without polling for completion. Closing the browser does not abort the batch.

## Extend script with Tail

After finishing and accepting all current videos, click **Extend script · Tail** below the blocks. Describe what should happen next, choose block count, duration, and seed, and request a proposal from Grok. Planning receives original identity and the real final frame of the most recently accepted video, returning structured JSON. The current ceiling is 1,000 blocks across the entire script, including existing ones.

Edit, reorder, or remove new blocks, then confirm continuation. This action appends only the new segment: existing blocks, videos, and attempts remain intact, and no generation is started. Next, use **Generate remaining blocks**. Each new block passes through the editor with the updated real frame of its predecessor using the batch workflow described above. The final video requires review; assembly remains explicit.

Proposal and adoption share a UUID established prior to submission, recorded at `.data/roteiros/<id>/tail-<UUID>.json`. Query the same request after connection loss; never re-submit an uncertain intent. Modifications to the script or source video invalidate adopting an older proposal. Planning enforces a 20,000-token ceiling; per-block prompt refinement maintains 12,000 tokens. Two-anchor interpolation remains in the backlog.

`POST /roteiros/<id>/tail/<UUID>` plans; `GET` inspects without executing; `PUT` adopts new blocks referencing the source revision. None of these read operations generate video. Validation uses fake clients and CPU media fixtures without live inference.

## Long scripts (application contract)

- `GET /roteiros/summary` → `{items:[{id, name, idea, adopted, revision, block_count, states:{accepted, ready_for_review, active, failed, planned}, strip:[per-block state], updated_at}], total}`. Block state = selected version (or latest attempt): `queued/running/uncertain` → `active`; `rejected/interrupted/failed/not_admitted` → `failed`; no attempts → `planned`. `updated_at` = maximum between `plan.json` mtime and `updated_at` of observed runs.
- `POST /roteiros/<id>/blocks/<block_id>/remove` `{expected_revision}` → updated script. The block is removed from `blocks` and `selected_runs`; if it has attempts, it moves to `removed_blocks` (videos, attempts, and decisions preserved). Blocked if any attempt is active/uncertain, if the block's video is awaiting review, if a batch is active, or if an edit is pending. Accepted versions subsequently lock into `selected_runs` (editorial mode).
- `PUT /roteiros/<id>`: the subsequence of blocks with attempts must remain identical and in original order; never-submitted blocks can be inserted, edited, reordered, or deleted.
- `POST /roteiros/<id>/segments/<UUID>` `{expected_revision, after_block_id|null, idea, count, duration_seconds, seed}` plans blocks for insertion (without saving the script); `GET` on the same ID retrieves the result. The app adopts by inserting blocks via `PUT`.
- `Generate` accepts optional `target_run_id`: creates a bridge targeting the selected accepted version of the following block.

### Planning (initial proposal, Tail, and segments)

A pipeline of focused calls using the same pinned model. Task and format are specified in message content and JSON schema. The planner does not reuse the legacy system prompt that requested a single JSON object for all blocks:

1. **Script** (`h3_roteiro_script`): one key, one fragment. Events with intent, optional speech, and distinct lists for body movement, facial expression, and delta. No seconds and no video prompt.
2. **Palette** (`h3_roteiro_palette`), only if any list is shorter than slots in that event: one key per short event. Does not copy items across modules. A list holds at most 200 items, so one event covers at most 200 blocks (100–200 fits); above that the proposal stops as `palette_failed` with the required count, before any palette call, instead of asking for a list the model cannot return.
3. Code-driven timing: floor and ceiling per event; remaining duration becomes approach/hold for that event. Total block duration matches requested duration. One speech entry per slot, with hardcoded southern accent placeholder; other slots receive `Sem fala.` ("No speech.").
4. **Cards** (`h3_roteiro_card`): one key per slot, one string fragment. Up to 4 in parallel, single attempt. `run_pos_prompt` is excluded. The resulting instruction feeds prompt enhancement; the enhancer remains unchanged.

The result stores `draft_scenes`, `scenes`, `slices`, and `raw_texts` from executed calls. `vision` remains empty: the prompt enhancer receives no camera blocking rehearsals in this step. If the initial call fails due to network or cancellation, the request remains uncertain; subsequent failures mark it `invalid`. No automatic retry.

Tail and segment candidates also record `planning_prompt` as the literal first request of the chain, so the stored evidence matches what the narrator sent. There is no director/critic/prompt-writer step, no beat slicing and no model-authored clock left in the code.

Two hundred blocks in a single event therefore mean one script answer, one palette answer and 200 card answers, each slot with its own expression, body and delta; the alternative for longer scripts is more events, not a longer list.

## Convert Freestyle to script

Under **Operations → Convert to script**, the source is the complete currently opened sequence, including downstream blocks when an ancestor is selected. Conversion uses prompts actually sent as instructions/actions, copies seeds and durations, inherits original identity, and records provenance for existing runs. It does not copy or re-execute videos, call Grok, or modify native decisions.

`POST /roteiros/from-freestyle/<end>` accepts a `roteiro_id` established by the client. On dropped responses, `GET /roteiros/<roteiro_id>` queries that result; no automatic re-conversion occurs. Only sources backed by immutable native requests, verified chains, and confirmed metadata can be adopted. Legacy data lacking verification, altered identities, replaced media, incompatible parameters, or ownership by another script block conversion with an error. Media verification checks file hashes and filesystem identity without decoding pixels or modifying source files.

## Stop a generation

Library notices and active Freestyle cards provide **Stop** controls. Confirmation occurs directly on the card: a short left-to-right fill animation, **Cancel** in green, and **Confirm stop** in red. Opening or cancelling sends no requests; the second click confirms stopping. Reduced motion preferences and dynamic preference switches cancel the animation without affecting confirmation or request state.

`POST /runs/<UUID>/stop` and `POST /roteiros/<id>/batches/<UUID>/stop` accept `{}`. Only owned worker processes can be interrupted; stopping a batch child terminates the entire batch. The operation tracks shutdown even if the client disconnects. Without a confirmed ID or outcome, the UI preserves uncertainty and queries the same endpoint without repeating POST. It does not flush global queues, models, caches, or external processes.

## State and recovery

- `.data` lives on the PC. Plans reside at `.data/roteiros/<UUID>/plan.json`, candidate proposals in the same directory, and writer configuration at `.data/roteiros/editor.json`.
- `GET` requests never write configuration, call providers, or admit generation jobs. `PUT` for plans or configuration is explicit with expected revisions; conflicts preserve local edits rather than overwriting silently.
- Names, actions, durations, and prompts in plans do not prove visual adherence in video. Acceptance, artistic approval, and pose/attire in actual frames remain concrete decisions and evidence.
- A planned key identifies a slot, not a future Run. Upon clicking Generate, the intent receives a known UUID; the server saves a snapshot and reserves `.data/roteiros/.locks/<UUID>.json` before admission.
- The **same UUID** is admitted by the native pipeline. Connection drops or missed responses retain queryable endpoints: `GET /roteiros/<id>/blocks/<key>/attempts/<intentUUID>`.
- Read operations reconcile lock marker, immutable native request, current manifest, snapshot, and identity/parent/chain proofs. Corrupted or missing data following a persisted intent is treated as **uncertain**, never authorizing a new POST. Duplicate 409 POSTs do not resubmit.
- Any script admission failure, including 400, 404, 409, or 422, maintains the lock until the intent endpoint is queried. HTTP 4xx alone does not prove the absence of execution. **Check submission** queries only when script, block, and intent match current context exactly; it never queries an older UUID from a different block.
- Rejection confirmed via GET and history (`admission: rejected`, `state: not_admitted`, `run: null`) displays **Prepare new submission**. This copies the literal snapshot into an isolated draft, including reference/SHA, seed, duration, and original accepted parent. Querying, reloading, and preparing issue no POST/PUT requests and allocate no UUIDs; only Generate creates a new intent. The rejected record remains intact.
- Submitted prefixes and prior decisions remain frozen. Retry adjustments produce new snapshots rather than rewriting past records. Unsubmitted future blocks can be edited or reorganized without generating; never bypass submitted positions.
- URL `/roteiro?roteiro=<UUID>` retains plan location; block/intent and pending parameters retain intent ownership across navigation and reloads. Do not use browser storage as a secondary authority. Unsaved local drafts remain transient.

## Editor and identity

The full-script writer configuration is retained only as a record: the narrator's system prompt is code-owned, so a stored prompt in `.data/roteiros/editor.json` — including one that still asks for a single JSON of every block — is never sent for a new proposal. The per-block enhancer continues using its current custom system, pinned model, and `/grok` endpoint, passing overall intent, past intents, current, next, and duration. Historical text represents **intent**, not claims of visual ground truth. Continuation sends original identity + accepted parent frame through the existing adapter, without synthetic PNGs, path overrides, or silent fallback to a single image.

In settings, **Sequential videos** and **Full script** are collapsible sections. Sequential videos uses `.data/grok/editor.json` and returns text instructions for a single block, with its own save trigger. Full script displays the stored `.data/roteiros/editor.json` read-only, with a note that it is a record and no longer reaches the model. Default prompts and contextual additions generated by the app are written in English; user ideas, previously submitted instructions, and literal user dialogue are preserved. Responses transport requests `text.format` with `type: json_schema`, `strict: true`, and the script schema, including exact block counts. Local validation remains mandatory; errors or truncated responses do not trigger retries or freeform text fallbacks.

The explicit migration script `tools/migrate_grok_prompts.py` preserves sequential video settings verbatim, verifies expected hashes for both files, and saves private backups before updating only the full script prompt. It does not touch OAuth files, alter models, or call providers. Subsequent user edits prevent migration overwrites; an already migrated configuration is not rewritten.

Reused configurations and transports do not authorize OAuth access, token refreshes, or live inference during startup, SSE, or tests. Model remains pinned to `grok-4.20-0309-non-reasoning`. The live authorization from plan 37 was fully consumed; this implementation relies strictly on fakes.

Prior to materialization, the pipeline verifies the script's projected source_root/path/SHA against newly computed native proof. Byte mismatches between preflight and admission reject execution prior to Store creation or worker dispatch. Fluent setters for UUIDs and proofs are pure, optional, and do not mutate public schemas or parameters of Freestyle blocks.

## Deleting items from the library

Cards for **Scripts** and **Freestyle**, as well as their detail views, provide **Delete** actions. Confirmation initiates real removal of owned media: files are relocated to a new private directory `/tmp/h3-trash-*`, with operation logging. Shared references, versioned assets, legacy data, and ComfyUI files remain untouched. Compact manifests, requests, decisions, and tombstone markers remain in `.data` to preserve provenance and prevent UUID reuse.

`DELETE /runs/<UUID>` accepts no request body; `DELETE /roteiros/<UUID>` requires `{"expected_revision": <current revision>}`. Deleting a script removes media from its confirmed attempts and owned assemblies. Active references by another script, external continuations, or shared assemblies block deletion. Active generation, ongoing assembly, or uncertain admission also block removal. The operation acquires the existing local slot without controlling ComfyUI, logging failure/rollback evidence without auto-retrying. Deleted items disappear from catalogs and public GET endpoints; accessing an older view will not regenerate videos or recycle used IDs.

## Navigation and active sequence

**Local Studio** at the top returns to the library. Reviewing a script attempt returns to the all-blocks view via **Back**. Drafts, active jobs, and uncertain submissions maintain their state records and UI locks across navigation.

The back swipe gesture initiates at the left edge and travels rightward, triggering the same navigation as the button. Vertical scrolling, multi-touch inputs, cancelled gestures, and interactions with input fields, video players, controls, or the continuity line do not trigger navigation.

Selecting an ancestor on the continuity line keeps the active sequence view pinned to its explicit last block: opening block 12 and selecting block 7 keeps all twelve cards visible. This visual context does not override the active selection chain: continuing or assembling uses the selected block and its direct ancestors. Alternate branches must be opened explicitly; there is no automatic selection of downstream children or newer results.

## Operational limits, not quality/performance metrics

- Up to 1,000 blocks per document (batch, Tail, segment, editing, and editorial assembly); Freestyle assembly chain remains capped at 100; catalog listings up to 1,000 scripts; metadata files ≤ 16 MiB including history. Reject excess rather than truncating history.
- Raw planning text capped at ≤ 512 KiB per call. Strict JSON, exact block counts; no parsing Markdown/HTML, clamping values, or accepting arbitrary seeds/IDs from providers.
- Action and instruction fields up to 12,000 characters; manual context up to 12,000 characters, and full batch context up to 100,000 characters. Errors preserve existing text without silent truncation.
- Script original media uses editor-compatible context: owned JPEG/PNG up to 20 MiB / 16 MP. Native Freestyle WebP support continues under prior contracts.
- Per-block duration requested in `(0, 10]`, up to 2 decimal places, 24 fps, `5 + 17k`, `Python half-even`. Default 8s → 192 frames / 8s; frozen benchmark 2.3s → 56 frames / 2.333s remains fixed. Parent tail 3s and audio true remain independent. Does not certify visual quality, VRAM/RAM safety, or long-form generation stability.
- RAM tracking remains observational telemetry. No admissions or cancellations based on free RAM; no intervention into ComfyUI memory, caches, processes, lifecycle, or the user's external script.

## Validation and evidence

Narrator cleanup and settings update on 2026-10-21: **1059 Python tests** (fake/CPU, cache-free) passed, **48 Android JVM unit tests** passed, and Ruff was clean. Validated: the retired director/critic/slicer symbols are gone with their only test, the Tail candidate records the literal first prompt of the narrator, and a stored full-script prompt no longer claims an effect. The clock and palette were exercised at 100, 200 and 201 blocks: one event of 200 slots is completed by a single palette answer with 200 distinct instructions, and 201 stops as `palette_failed` before the palette call. On a headless Android emulator (not physical hardware), the settings card shows the note and the read-only prompt, and the proposal timeline renders a narrator event with intent and micro states; the served payload is the one the real chain (`Roteiro.propose` → `narrate`) wrote with the offline demo planner, so it certifies rendering, not a live Grok proposal. One unintended provider call occurred while the demo backend was serving real `Grok` on the proposal route: it returned 401 `login_required`, consumed no inference, and was not repeated. Local copies in `.dumps/android/` (`RELATORIO.md`, `provider-401.txt`, screenshots).

Notices, favorites, and PWA updates on 2026-10-13: **933 Python tests** (fake/CPU) and **236 Node tests** passed; Ruff and whitespace checks passed. Validated features include reconnect reconciliation on the same request, preservation of uncertain decisions, dismissal without deletion or replay, shared atomic favorites, bounded summaries, lazy pagination (12 items) without dropping SSE updates, PWA service worker with zero caching of API/media/operations, and reconnection preserving URL IDs. List entries display across three lines, and favorite/delete icons have 44px tap targets. The custom icon was generated via native image_gen; original and exported assets reside in `src/h3_backend/web/`, with prompt documented in `icon-provenance.json`. Test outputs recorded in `.dumps/tasks/notices-pwa-library-pytest.txt` and `notices-pwa-library-node-tests.txt`. No live Grok/GPU calls, production server restarts, or automated browser captures were executed. Mobile PWA installation requires trusted HTTPS; fullscreen mode and animated dropdown collapses depend on browser platform support.

Batch, Freestyle, and stop updates on 2026-10-13: **924 Python tests** (fake/CPU) and **209 Node tests** passed; Ruff and whitespace checks passed. Includes mandatory per-block Grok prompt refinement, absence of fallback/replay, passive batch discovery, media proof-checked conversion, back swipe navigation, inline stop confirmations, and clean cancellation with disk publishing completed prior to releasing execution slots. Logs stored in `.dumps/tasks/freestyle-batch-pytest.txt` and `freestyle-batch-node-tests.txt`. No live provider/GPU calls, production server restarts, or new browser visual captures were made.

Library, prompts, and navigation updates on 2026-10-13: **889 Python tests** (fake/CPU) and **185 Node tests** passed; Ruff and whitespace checks passed. Validated script deletion with mock native attempts and assemblies, preservation of source files, restart without replay, shared dependencies, rollbacks, atomic private migrations, JSON Schema payloads, non-truncating 12→7 navigation, sequence tail read failures, delayed responses, and tombstones for deleted items. Local full-script configuration was migrated to English with backup snapshots; sequential configuration hash remained byte-identical. Logs saved in `.dumps/tasks/library-grok-pytest.txt` and `library-grok-node-tests.txt`. Zero provider, GPU, or production server activity. This update did not include new browser visual captures; mobile evidence below is historical.

Prior test suite completed without starting live H3 APIs, external providers, or GPUs:

- **859 pytest cases** (fake/CPU, cache-free); clean Ruff linting. Covered persistence, ownership validation, frozen prefix handling, UUID/proof-based admissions, and bridge contracts. One existing Starlette deprecation warning remains.
- **171 pure Node tests**: 43 frontend unit tests, 84 retry tests, and 44 script tests. Validated that all 4xx script errors remain blocked until queried via intent endpoint, preserving Freestyle behavior.
- **Native browser suite**, headless Chromium, 393×852 (DPR 2, mobile touch emulation), pt-BR locale, dark theme. Normal and reduced motion, touch scrolling, and 320px viewport tests; workbench showed zero horizontal overflow, generation CTA met 48px hit target. This represents emulation, not physical hardware testing of system keyboards or native pickers.
- Independent loopback HTTP fixture with SHA-locked web buffers and allowlisted test media; no live product imports or startup. Final test run evaluated `app.js` SHA `b688d3bc2f5efb24ce40cfc9375aa6b4d196d0d1a6d1e116577b882d90f94da2`.
- End-to-end simulated run: macro populated and adopted → root accepted → continuation 409 blocked → GET/reload/preparation without resubmission → fresh UUID with identical snapshot and parent, without modifying prefix via PUT → accepted → third block with 8.1s / seed 0 → explicit assembly of accepted chain. Covered 4 intents across 3 monitored waits; one intent was rejected without Run creation. Saving writer settings transmitted only `system_prompt`, without issuing PUT to the enhancer.
- A preceding test run verified optional refinement across two contexts, explicit adoption, and retry of rejected attempts: preserved whitespace/newlines in final prompt, generated a new UUID with original parent, and avoided repeated Grok calls during preparation. This preceded the final two query/4xx guards and is not presented as verifying them.

Final inspected visual artifacts: [continuation workbench](design/roteiro-workbench-mobile.png) and [draft settings](design/roteiro-settings-mobile.png), both captured under reduced motion. The black photo represents the original identity; the red frame is an existing real video frame used by the fixture, not output from a new generation run or proof that the planned block completed facing backwards.

**Evidence limits:** the test fixture serves a historical 56-frame clip and a historical 168-frame (7s) video. Simulated metadata entries are not live probes of those files; assembly metrics use a fixed 576 value even during 8.1s test runs. These do not prove live 8s generation, 593 assembled frames, artistic continuity, facial identity, memory bounds, visual quality, or performance. The native screen recorder returned a truncated video marked with `BACKEND_UNAVAILABLE`; it was not promoted as a completed demo/GIF or bypassed via alternate harnesses. Page console errors in the final document: zero. Request logs and JSON dumps are stored locally under `.dumps/tests/ui-roteiro/`.

The current catalog does not expose `advanced.routes` for network interception. The Playwright harness in `tests/frontend_roteiro_browser_mock.mjs` **was not executed** following this protocol update; syntax checks and fixture setups do not constitute browser test passes. Screen captures and interaction tests must rely solely on native tools and read-only fixtures serving selected media assets. Fixture logs and diagnostic files record network traffic; do not claim external session interception or physical device execution.
