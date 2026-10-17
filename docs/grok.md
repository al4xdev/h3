# Grok: visual context, text-only output

`src/h3_backend/grok.py` operates independently of video generation. It accepts an idea, a system prompt, and an optional self-owned reference; it returns editable text. It does not generate or edit images, create runs, accept reviews, continue sequences, or assemble videos. Using the proposal and clicking **Generate** remain separate, explicit actions. The frontend must preserve the reference with the draft and isolate delayed responses, never overwriting a newly entered idea. Model text output is untrusted: use `.value` or `textContent`, not HTML.

## Pinned model and local PC configuration

Approved pin: **`grok-4.20-0309-non-reasoning`**, without the `latest` alias. The [official model card](https://docs.x.ai/developers/models/grok-4.20-non-reasoning.md) advertises text+image → text, non-reasoning, and a 1-million-token context window. The card alone **does not certify grant eligibility, vision support, quota, or billing rates**. The implementation was initially validated strictly offline; a subsequent real validation, authorized deliberately in plan 37, is documented below. That one-off success does not guarantee general account eligibility, future quota, or billing terms.

- `.data/grok/editor.json`, located under `H3_PROJECT_ROOT`, stores `{system_prompt, model}`. It is isolated from `oauth.json`; do not store secrets in these fields.
- `seed_editor(root)` is an explicit administrative action, never triggered on import, startup, or GET. It creates the file only if absent, with the default system prompt and the pin above: exclusive temp file 0600 → fsync → no-clobber link → remove temp file → directory fsync. A valid existing configuration is returned intact, even if its model differs; an administrator must review the discrepancy rather than silently replacing it.
- `GET /grok/editor` is inert. If the file is missing, it returns the default system prompt and `H3_GROK_MODEL` without creating directories. File corruption, symlinks, or inaccessibility yield 409.
- `POST /grok` re-reads configuration. A non-empty persisted model is authoritative; any request specifying another model returns `model_fixed` / 409 before network activity. If no pinned model is persisted, it maintains compatibility: request.model → environment captured at startup. If no model is configured anywhere, it returns 400 and never picks the first catalog entry arbitrarily.
- `PUT /grok/editor` preserves an existing non-empty pin. It allows updating the system prompt while omitting the model or passing an identical one; a different or empty model returns 409 without modification. Changing a pin requires an explicit administrative edit in the local JSON, not through the public editor interface. An absent or empty legacy configuration continues to permit its legacy write contract.
- System prompt: 1 to 100,000 characters, non-empty; model: up to 256 characters. JSON payload is capped at 1 MiB and rejects extra fields. An invalid existing configuration is never deleted or replaced to hide evidence. Target directories and files are opened with no-follow descriptors, must be regular files owned by the local user, with a link count of 1. Normal persistence is atomic with fsync.

## HTTP: idea and selected reference

Example body for `POST /grok` (triggered only by an explicit click to expand/detail):

```json
{
  "system_prompt": "Expand the idea in English without inventing actions or parameters.",
  "prompt": "ela dá um salto e o vestido fica vermelho",
  "reference": {"source_root": "assets", "path": "dance_reference.png"}
}
```

`reference` is optional for text-only backwards compatibility. `model` is optional and cannot conflict with the persisted pin. Response format: `{"text":"...","model":"..."}`. The endpoint accepts prompts up to 100,000 characters; the scene field in the UI enforces a 12,000-character limit and rejects larger output without truncation. The default system prompt requests scene instructions in English only, without hallucinating identity or modifying native parameters. Inline code instructions and continuation context labels are also in English; a custom persisted system prompt is forwarded verbatim.

The full roteiro pipeline uses internal `Grok.complete(..., output_schema=...)` calls to request structured JSON. The [xAI Responses API specification](https://docs.x.ai/developers/rest-api-reference/inference/responses) specifies `text.format = {type: "json_schema", name: "h3_roteiro", strict: true, schema: ...}`; this is distinct from Chat Completions `response_format`. The schema originates from the roteiro DTO, with required fields and forbidden extra properties. The same structure applies to plain text or streamed image payloads while respecting the model pin and original references. The public sequential editor does not receive this opt-in and rejects arbitrary schemas.

The [JSON schema documentation](https://docs.x.ai/developers/model-capabilities/text/structured-outputs) supports non-circular references, objects, arrays, and numeric bounds; string bounds above 2,048 characters depend on model adherence. Consequently, roteiro continues to validate JSON structure, content, block count, and durations locally on the PC. Rejections, incomplete responses, or schema violations do not trigger retries, fallback to freeform text, or model changes. This integration was verified with fake clients; schema support under this specific OAuth grant was not certified via live inference.

The helper `infrastructure/grok_image.py` resolves only self-owned, verified public bytes:

- `assets`: public relative path contained within `assets/`, without private path segments.
- `inputs`: `<UUID>/original.png|jpg|jpeg` under `.data/inputs`, with published `metadata.json` and matching id/source_root/path/SHA; `.part` is rejected. Manually placed inputs lacking published proof are not submitted to Grok.
- `runs`: `.data/runs/<UUID>/initial_frame.png|last_frame.png`. Requires a manifest with matching ID and explicit image reference for that path/SHA, or a complete migration inventory. Legacy alias `runs/<UUID>/...` is allowed only with matching receipt/verified.json, root, destination, run_ids, inventory_sha256, and verified frame SHA. It does not import Store, models, dispatcher, or worker, nor does it read decisions to authorize generation. Any frame without explicit proof is rejected, even if present in the legacy library.

All path components are traversed with no-follow descriptors; URLs, absolute paths, traversal, symlinks, FIFOs, and foreign or temporary files are rejected. The target file must be a regular file, owned locally, with link count 1, and size up to **20 MiB**. Copying and SHA hashing use 48 KiB buffers; source and proof file identity, size, mtime, and ctime are re-verified. A private temporary filesystem snapshot under `.dumps/grok-editor/` freezes bytes prior to validation/submission and is cleanly closed and unlinked on error or cancellation. Original bytes and published metadata are never modified.

External FFprobe/FFmpeg processes verify valid JPEG/PNG formats and confirm a single complete image. An operational ceiling of 16 megapixels is enforced locally; this is not a documented model maximum. WebP files, images larger than 20 MiB, corrupt files, animated images, or missing proofs return `invalid_reference` / 400 **prior to authentication, catalog retrieval, or inference**. The system does not silently convert, resize, or recompress images; the 32 MiB generation limit remains untouched. Python does not decode pixels or buffer full images/base64 strings on the heap.

The [official image documentation](https://docs.x.ai/developers/model-capabilities/images/understanding.md) specifies JPEG/PNG support up to 20 MiB using the Responses schema:

```json
{"role":"user","content":[
  {"type":"input_image","image_url":"data:image/png;base64,..."},
  {"type":"input_text","text":"ideia"}
]}
```

`image_url` is a **flat string**, not the Chat Completions `{url:...}` object. It neither exposes media publicly to the Internet nor expects xAI to resolve localhost URLs. The request body is sent via `httpx content=` using an asynchronous JSON stream with bounded prefix/suffix overhead and incremental base64 encoding over chunks divisible by 3. `Content-Length` accounts for base64 expansion via `4*ceil(bytes/3)`; a 20 MiB image consumes 27,962,028 base64 bytes in addition to envelope framing. It avoids `read_bytes`, full-image base64 buffering, and `json=` arguments containing complete media.

## Continuation: original identity + actual last frame

`POST /grok` accepts an optional `continuation_parent_id`, formatted as a **canonical UUID string**, alongside the mandatory original `reference`. When omitted, text-only and single-image requests retain their standard contract. An invalid parent ID halts the process without falling back to single-image mode or initiating authentication.

```json
{
  "system_prompt": "Meu sistema customizado, sem alteração.",
  "prompt": "ela vira de frente e mantém o vestido vermelho",
  "reference": {"source_root": "assets", "path": "dance_reference.png"},
  "continuation_parent_id": "00000000-0000-0000-0000-000000000001"
}
```

The technical adapter reads only its own manifest, bounded at 1 MiB. It enforces `id` matching the directory, `state: accepted`, `decision.accepted: true`, `error: null`, `publication_mode: atomic_copy_from_comfy_output`, and `output.path: .data/runs/<UUID>/chunk.mp4`. It ignores `output.source` entirely (internal to Comfy). The exact legacy alias `runs/<UUID>/chunk.mp4` is allowed only when backed by consistent receipt/verified migration artifacts and verified video SHA in the inventory; the actual file read remains the canonical target under `.data/runs`. Missing or ambiguous states/decisions block execution, including on legacy data.

It requires exactly one reference with `type: image, role: identity`, matching the selected `source_root`, `source`, and `sha256`. Multiple identity references are unsupported. Other native roles (`image/initial_frame` and `video/motion_video`) are recognized but never substituted as identity. Assets without standard publication proof must still match the SHA recorded by the parent in this mode. Manifests, source files, and identities are re-verified after copying and prior to submission; any inode or content alteration in manifest or video during preparation rejects the request.

`GET /grok/continuation/<UUID>/last-frame` is a **CPU-only preview**. It does not invoke OAuth, catalog discovery, providers, Store, workers, Comfy, jobs, or decisions, and creates no generation UUIDs. A pre-existing `last_frame.png` is not required: it locks the verified `chunk.mp4` into an anonymous disk snapshot under `.dumps/grok-editor`, inspects decoded frame counts via FFprobe, and extracts `select=eq(n,count-1),format=rgb24,setsar=0` via FFmpeg. Native RGB geometry and `map_metadata -1` are preserved, mirroring the native helper; Python never decodes pixels directly. The image is validated **prior to sending headers**, and encoded bytes stream in chunks up to 48 KiB; client disconnection or cancellation tears down snapshots and reaps child processes. It never writes frames, manifests, or decisions to the run directory, nor does it read private outputs.

Editor operational constraints: videos up to **256 MiB**, up to **3,600 decoded frames**, frame geometry up to **16 megapixels**, individual JPEG/PNG files up to **20 MiB** (40 MiB maximum encoded input for the image pair), subprocess timeout up to **120 s**, and bounded stdout/stderr buffers. These do not represent model limits, performance guarantees, or generation tuning parameters. Scratch space is privately owned by the user; inputs and metadata must be regular files with link count 1, owned locally, accessed via no-follow descriptors. Anonymous snapshots maintain 0 hard links and are closed on success, error, or cancellation; no persistent cache is kept.

The explicit trigger locks and validates **both** images prior to authentication or provider calls. The Responses payload prepends a distinct label instructing the model to evaluate BOTH images, followed by two flat `input_image` blocks: first the original identity, then the last frame (reflecting current pose/attire), followed by the user's literal prompt in an isolated `input_text` block without alteration. Custom system prompts are forwarded verbatim and are never reseeded or overwritten. `Content-Length` includes the base64 expansion of both snapshots plus envelope framing. Reads and SHA hashing use 48 KiB buffers; base64 streaming generates chunks up to 64 KiB with at most a 2-byte carry, keeping the heap free of large image or base64 allocations. The single-image legacy helper remains backwards-compatible.

The UI displays identity and last-frame contexts with separate labels, associates late-arriving responses with the parent ID, and displays preview failures transparently. **Use my instruction** remains accessible: native V2V extracts its own frame during generation, which operates as an independent step and remains untouched. Automated tests use synthetic CPU videos and mock provider factories exclusively. The live test authorized in plan 37 confirmed that the grant accepted this two-image payload, but does not constitute a scientific certification of computer vision capabilities or prompt adherence.

## Provider calls and authentication remain isolated

Explicit actions to edit or confirm a batch call `https://api.x.ai/v1/responses` after validating the model against the grant's catalog through the existing OAuth adapter (short-lived caches may bypass remote GET requests; token refreshes can happen during this click). No remote activity occurs on import, startup, GET requests, config saves, file uploads, SSE events, or page reloads. Enforces `store=false`, `stream=false`, 12,000 output tokens for block edits and 20,000 for full roteiro plans, a 120 s timeout, and a 2 MiB response cap. No inference retries, endpoint/key fallbacks, conversational history tracking, or reasoning parameters are used. Errors are sanitized and preserve existing drafts; ambiguous outcomes are never replayed blindly. Routes return `Cache-Control: no-store`.

In a roteiro batch, authorization covers detailing each block prior to generation. The orchestrator reuses this sequential editor with 12,000 output tokens, original identity, and the actual frame of the accepted parent. It locks system prompt and model, logs intent prior to each call, and records the text actually sent. The overall batch context accepts up to 100,000 characters based on local limits; scene generation output remains capped at 12,000 characters. Invalid or uncertain responses halt the batch without falling back to base prompts or repeating inference. An earlier test authorization does not trigger this workflow: the batch requires a fresh explicit click and confirmation in the UI.

OAuth was ported from Alex Tavern and operates independently of the editor. Credentials reside in `.data/grok/oauth.json`, permissions 0600 (directory 0700), stored as local plaintext: secure both workstation and backups. Do not run both projects concurrently to refresh the same rotating grant. Never inspect, display, or copy credentials into editor configuration. Successful authentication does not guarantee third-party integration rights or inference inclusion within a given subscription tier.

To authenticate explicitly, with the API **already running**, execute via fish:

```fish
curl -sS -X POST http://127.0.0.1:8010/grok/auth/start
```

Open `verification_uri` directly on xAI and enter `user_code`. Never transmit passwords, session cookies, or tokens to H3. Use `POST /grok/auth/flow` with `{"flow_id":"..."}` to poll flow status; `/grok/auth/cancel` cancels the pending flow. `/grok/auth/status` and `/grok/auth/models` are explicit operations, not automatic discovery hooks.

Local API / trusted network: same-origin guarantees do not replace authentication for direct HTTP clients. Automated backend verification uses CPU fakes in temporary roots: model pin precedence, no-clobber seeding, Responses payload structure, base64 streaming, bounds enforcement, ownership, SHA hashes, race conditions, symlink handling, and cancellations without generation imports or replays. These tests never spawned production servers, providers, or GPUs. The deliberate live test below was conducted as a distinct phase; UI integration, text adherence, and account eligibility remain separate validation gates.

## Subsequent live validation: plan 37, authorization consumed

Following explicit owner opt-in, **a single live validation run** of the pinned model `grok-4.20-0309-non-reasoning` was executed: **one GET models/200** and **one POST Responses/200**, supplying original identity and the derived last frame from accepted parent `29699…`. The transport transmitted an exact `Content-Length: 2183776` across **40 chunks**, maximum chunk size **65,536 bytes**; total execution took **8.7403 s**. Local evidence is archived at: `.dumps/tests/grok-real-two-images-20261013-plan37-8d42e6/`.

Final verification confirmed frozen code, model pin, custom system prompt, OAuth grant, identity reference, proof hashes, and source video remained unchanged, with the parent run still accepted. No token refresh, re-authentication, retry, GPU generation, or video creation occurred. Authorization for that test was fully consumed: the outcome grants no permission for new calls or replays.

The model response referenced the red dress and continuity of the rear-facing pose, but also introduced unrequested details and was delivered in English, structured as `Video 1` with an 8 s duration. The custom system prompt was transmitted verbatim; these stylistic variations represent proposed text content only, not adjustments to native generation parameters. This success confirms that the specific payload was accepted under that grant at that moment, **not full semantic adherence**, scientific vision verification, artistic quality, or general entitlement regarding quota and billing.
