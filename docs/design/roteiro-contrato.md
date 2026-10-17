# H3 · Roteiro v2 — Implemented Contract (Plan 41)

Verified in `src/h3_backend/roteiro.py`, `web/app.js`, `api.py`, and native pipes. Frozen identifiers reported by the integrator: backend `ee18b5d`, frontend `b688`. These are not inference results.

## Addresses and Authority

- HTML page: `/roteiro?roteiro=<UUID>&block=<UUID>&intent=<UUID>`. `block`/`intent` only appear when they exist. `/` and `/index` continue serving the same shell.
- JSON API: `/roteiros`. Singular/plural prevents collision with HTML. Configuration announces `roteiro_enabled: true` in `/app/config`.
- PC state: `.data/roteiros/<UUID>/plan.json`, `proposal-<UUID>.json`, and correlation marker in `.data/roteiros/.locks/<intentUUID>.json`. Macro system: `.data/roteiros/editor.json`.
- Canonical UUIDs, dedicated regular files, bounded reads, local locks, and atomic writes. HTTP is a bridge; the browser is not an authority on history or revisions.

## Document and Limits

```json
{
  "id": "Roteiro UUID",
  "revision": 1,
  "name": "Dance",
  "idea": "Original intent",
  "reference": { "source_root": "assets", "path": "dance_reference.png" },
  "reference_sha256": "SHA256 derived by server",
  "adopted": false,
  "blocks": [
    {
      "id": "Stable UUID of planned item",
      "action": "Dance in black.",
      "duration_seconds": 8,
      "seed": 2026101205,
      "prompt": "Dance in black."
    }
  ],
  "attempts": []
}
```

`reference_sha256` and `attempts` are read-only. A planned key is not a future Run. Operational limits, not model/memory guarantees:

| Field/resource | Effective limit |
| --- | --- |
| Blocks per plan/proposal | 50; explicit count from 1 to 50 |
| Listing roteiros | Up to 1000 documents; fails above that, no implicit pagination |
| Request/file JSON | 1 MiB; `plan.json` includes entire history; candidate includes raw and structured blocks within the same budget |
| Raw proposal text | 512 KiB in UTF-8; without truncation |
| Name | 256 characters; proposed name non-empty |
| Idea, action, prompt | 12000 characters each; non-empty/non-whitespace |
| Macro system | 100000 characters; non-empty/non-whitespace |
| Seed | Strict integer from 0 to 2^53−1, no bool/string/coercion |
| Requested duration | (0,10], finite, up to two decimal places; current default 8s per capabilities |
| Identity of roteiro/editor | Dedicated JPEG/PNG, up to 20 MiB and 16 million pixels |

JSON rejects duplicate keys, extra keys, and non-finite numbers. Aggregate budgets may prevent a combination of individually valid fields. Do not fill missing model response fields or clamp. Resolution, sampler, graphs, formula 24fps / 5+17k / Python half-even, and tail3/audioTrue remain native; benchmark 2.3s is explicit/historical.

## Plan: Creation and Modification

| Operation | Body/result |
| --- | --- |
| `GET /roteiros` | 200 `{items:[complete documents],total}` |
| `POST /roteiros` | `{name?,idea,reference,blocks?,adopted?}` → 201 document; defaults name `""`, blocks `[]`, adopted false |
| `GET /roteiros/{ident}` | 200 document with reconciled attempts |
| `PUT /roteiros/{ident}` | `{expected_revision,name,idea,reference,adopted,blocks}` → 200 document revision+1 |

PUT requires all editable fields, without id/revision/attempts/reference_sha256. Adoption requires valid blocks. After any intent: identity/idea/adoption remain frozen, and the prefix up to the last submitted position cannot be modified, removed, or reordered. Only the unsubmitted suffix remains editable. A 409 conflict preserves local edits; do not automatically retry saving with another revision.

JSON responses from the router use `Cache-Control: no-store`. Request bodies exceeding 1 MiB return 413; invalid JSON/DTO returns 422. Shared bridge handlers return 400 for ValueError, 409 for conflict/slot/existing file, and 404 for missing file. These status codes do not replace querying the intent itself after an admission error.

## Separate Macro Proposal

`POST /roteiros/{ident}/proposal`, body `{expected_revision,count,duration_seconds?,seed}`. Omitted duration uses native default 8s. 200 response:

```json
{
  "id": "Candidate UUID",
  "roteiro_id": "Roteiro UUID",
  "source_revision": 1,
  "source": {
    "name": "Source name",
    "idea": "Source idea",
    "reference": { "source_root": "assets", "path": "dance_reference.png" },
    "reference_sha256": "Source SHA256"
  },
  "name": "Proposed title",
  "blocks": [
    {
      "id": "new planned key",
      "action": "Action text",
      "duration_seconds": 8,
      "seed": 2026101205,
      "prompt": "Base instruction"
    }
  ],
  "raw_text": "Literal JSON received",
  "stale": false
}
```

The candidate does not modify the plan's blocks/revision. Adoption is an explicit PUT. `source_revision` and `source` bind the original context; revision changes during the call mark it stale. The provider must return exactly `{name,blocks:[{action,duration_seconds,prompt}]}`, exact count. The application assigns keys and seed, not the provider.

Before the explicit call, saves candidate reservation with state uncertain, request/source; does not hold lock during provider await. Invalid proposal JSON returns 422 with `{error:"invalid_proposal",detail,id,roteiro_id,source_revision,source,raw_text,stale}` and preserves bounded text. OAuth/provider errors use `{error,detail}` with adapter status. There is no automatic replay, adoption of invalid proposals, or public recovery of candidates via dedicated GET.

## Systems and Block Detailing

- `GET /roteiros/editor` → 200 `{system_prompt,model}`; missing uses dedicated macro system. GET does not create files or call auth/provider.
- `PUT /roteiros/editor` accepts only `{system_prompt}` → 200 same shape. Pin read by public editor must be `grok-4.20-0309-non-reasoning`; different yields 409. Do not send model.
- Macro system separated from `.data/grok/editor.json`; reuses `Grok.complete`/`PromptRequest`, without editing custom system, OAuth, or grant.
- Detailing a block uses existing POST `/grok`, click-only. Prompt includes macro, intents of accepted predecessors / submitted prompt, current chunk / duration / frames, and next planned item; text is not proof of visual output. The 12000 prompt limit includes this context, system prompt is separate. Overflow reports error, preserving instructions and manual path, without truncation.
- Continuation sends original identity and real accepted `continuation_parent_id` to obtain the actual last frame. No silent fallback from two images to one. Delayed response becomes candidate tied to draft/context; Use Proposal and Generate remain distinct actions.

## Generation Intent

`POST /roteiros/{ident}/blocks/{key}/attempts/{intent_id}` requires:

```json
{
  "expected_revision": 2,
  "prompt": "Chosen literal text",
  "seed": 2026101205,
  "duration_seconds": 8,
  "parent_id": null
}
```

Root uses null; continuation uses the concrete accepted attempt of predecessor, same identity/chain. First generation requires prompt/seed/duration equal to saved block: clicking Generate saves draft via PUT, confirms revision, and only then submits intent. Invalid/conflicting save aborts before POST.

Already submitted positions remain frozen. Rejected/interrupted retry initially copies literal FINAL Run.prompt, seed/duration/reference, and original parent; explicit adjustments can stay in the new snapshot without PUT over frozen block. New attempt requires new artistic review.

Intent UUID is born only upon clicking Generate, is recorded in URL before POST, and will be the same RunID. Backend saves intent/snapshot/marker prior to admission. Optional pure setters `with_run_id`/`with_identity_proof` compose metadata: proof compares expected source/path/SHA with freshly calculated hash from pipe **before ensure_idle, Store.create, and worker**. They do not change legacy public DTO or parameters. Worker retains its own native checks.

202 returned does not mean completion:

```json
{
  "intent_id": "Known UUID",
  "run_id": "SAME UUID",
  "roteiro_id": "UUID",
  "block_id": "planned key",
  "source_revision": 2,
  "state": "queued",
  "admission": "admitted",
  "snapshot": {
    "prompt": "Literal text",
    "seed": 2026101205,
    "duration_seconds": 8,
    "parent_id": null,
    "reference": {
      "source_root": "assets",
      "path": "dance_reference.png",
      "sha256": "server proof"
    }
  },
  "run": { "id": "SAME UUID", "state": "queued" }
}
```

Run above abbreviated; actual return includes full native Run. Marker, Store.request/snapshot, Store.get/immutable projection, and canonical hydration prove association. Native decision/parent/publication are authoritative. A duplicate intent returns 409, never re-executes. Unexpected failure during admission preserves uncertain result and known UUID, potentially returning 202 without confirmed Run.

## Recovery and Confirmed Resubmission

`GET /roteiros/{ident}/blocks/{key}/attempts/{intent_id}` queries exactly its own intent, without execution. Document contains server-owned attempts flattened by block_id.

1. **Every roteiro admission error, including 4xx/409, retains submitted/statusOnly and uncertainty until querying itself.** HTTP status alone does not prove it was not admitted. Unknown 404, missing or corrupt file/link also does not release Generate/rePOST.
2. Frontend compares current roteiro/block/intent against canonical owner **before GET** and again after response. Old root intent when preparing child does not make HTTP requests nor clears uncertainty from another operation.
3. Absence/corruption of proof after reservation maintains `admission:"uncertain",state:"uncertain",run:null`. If Run confirmed: admission admitted and observed native state. Only uncertainty belonging to that intent can be cleared.
4. Confirmed rejection requires dedicated GET with `admission:"rejected",state:"not_admitted",run:null`; same intent as last attempt of position in history, valid source_revision, and proven snapshot/identity/SHA/duration/seed. For continuation, same original parent still accepted/published and same identity.
5. Only then enables **Prepare new submission**: isolated draft `not-admitted:<intentUUID>`, literal prompt/seed/duration/reference/parent copied from snapshot. Prepare does not perform POST, PUT, or allocate UUID; old history remains. Upload/assembly/busy/independent uncertainty fences continue.
6. Only subsequent click on Generate creates new UUID and POST with chosen draft. Does not PUT over frozen position, nor repeats old intent. Identical initial snapshot does not promise identical bytes/pixels.

After confirmed admission, awaiting the RunID itself and reading/SSE of metadata reuse native mechanism, without completion polling or replay. Accept does not generate next; assembly of accepted chain is explicit. Standalone flow retains previous native semantics, including 4xx handling; conservative rules above apply to roteiro intents.

## Architectural Responsibility and Evidence

`roteiro.py` concentrates plan/configuration/proposal/correlation/router; I2V/V2V execute via existing composition and dispatcher. No secondary worker, broker, queue, RAM policy, or ComfyUI script control. Grok remains an isolated editor; roteiro calls its public contract without coupling Grok to Store/dispatcher.

Final validation reported by integrator: 171 Node tests, 859 pytest, and Ruff passed. Mock protocol `b688`: 409 remained fenced → dedicated GET → reload → Prepare without POST → Generate new UUID / copied snapshot / without PUT. Three accepted positions and explicit assembly also exercised; future edit of the third to 8.1s / seed 0 preserved.

These are protocol/UI fake proofs, not new inference or physical certification: assembly mock maintains constant 576 frames even when aligned requests total 593; do not use this fixture to claim real duration or frame count. No test/provider/GPU/process was executed during this documentation update. Real Grok authorization 37 already consumed, without repetition; do not certify visual compliance, quota, RAM/VRAM, or timeframe.
