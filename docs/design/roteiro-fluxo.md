# H3 · Roteiro — Flow, Actions, and Proposal Limits

**Critical Review v2 — approved and implemented by Plan 41.** Screens and copy in [roteiro-telas.md](roteiro-telas.md); [usage and evidence with limits](../roteiro.md). This critical review records the decisions prior to implementation; it does not replace testing nor does it certify performance by design.

## Critical Review: What Was Found and Corrected

| Problem in initial design | Consequence in usage | Correction in v2 |
| --- | --- | --- |
| Proposal and roteiro repeated the same cards across distinct pages | Adopting felt like switching products without changing the task | A single central screen with proposal/adopted states. |
| Editing action/duration required opening another screen | Too much navigation just to adjust each chunk | In-card editing; organization within disclosure. |
| Preparation, enhancer proposal, and final verification were three pages | Too many steps just to generate an already planned block | A single workbench with context, editor, and explicit adoption of proposal. |
| "Use roteiro instruction" button copied text that was already adopted | Redundant click without a new decision | Field pre-filled; Grok optional. |
| Name/count/duration dominated the entry flow | User had to build a form before sharing the idea | Reference + intent first, division/name under options. |
| Two large stacked contexts pushed the prompt off-screen | Too many folds on mobile before reaching the primary action | Compact contain cards, side by side when legible; expand within document. |
| Three settings editors open at once | Mixed current task with global systems | Clear local section and two systems in separate disclosures. |
| Repeating technical warnings on every card | Plan became hard to read, focused on implementation rather than action | Warnings at points of adoption/Generate and messages only when pertinent. |
| Text describing the past could sound like proof of compliance | Model/user would confuse intent with actual visual output | Label intent of accepted blocks; real frame remains the authoritative visual context. |
| Default 2.3s became outdated after correction 40 | Proposal would start with a different budget than current app | Default 8s sourced from capabilities; benchmark 2.3s remains untouched. |

**What was intentionally kept:** separation of plan/attempts, concrete accepted parent, proposal adoption distinct from Generate, artistic review per block, and explicit assembly. These boundaries do not require redundant pages.

**Risks addressed in implementation:** durable correlation before 202, saving chosen context prior to request, and revision conflicts covered by fake/CPU regressions. Cards/CTAs measured in mobile browser emulated at 393px and 320px, without horizontal overflow. Captures do not certify physical devices, model quality, or performance; see evidence limits.

## 1. What This Evolution Changes

Currently: conceive a block → optionally detail → generate → review → conceive continuation.

Proposed: **conceive the entire video → populate all blocks → work on one block at a time using the existing flow**.

The roteiro is the plan. The Run remains a real attempt. Do not generate all final prompts assuming future frames; do not generate all videos simply because the macro was adopted.

### Primary Flow by Screen

```text
T00 Library
 ├─ New freestyle → existing Freestyle flow
 └─ New roteiro → T01 reference + intent
                       ↓ explicitly propose or write manually
T02 Roteiro
 ├─ Proposal state: populated/editable list → Use this roteiro
 ├─ Adopted state: list + next block/history
 ├─ Edit: expands card, does not navigate away
 └─ Prepare block N
                       ↓
T03 Block Workbench
 ├─ Base instruction pre-filled; real context + duration/seed
 ├─ Optional detailing → candidate in the same editor
 │    └─ Use this proposal OR Keep my instruction
 └─ Explicitly generate block
                       ↓
T04 Order on PC → T05 review after confirmed publication
                       ├─ Reject/interrupted → retry → T03
                       └─ Accept → Prepare next → T03
                                    or last accepted → T06 assembly

T07 Settings returns to origin. T02 is the home of the roteiro.
Back/open/reread/adopt proposal do not generate.
```

## 2. Complete Example: The Roteiro Pre-populates Blocks

Reference: woman in black dress from original image. Idea: dance, small jump with color change to red, finish facing away, then turn to face forward.

| Position | Pre-populated action | Pre-populated duration | What does NOT exist yet |
| --- | --- | --- | --- |
| 1 | Dances maintaining black dress. | 8s | Video, Run ID, final frame, decision. |
| 2 | Small jump; dress turns red; finishes facing away. | 8s | Confirmed parent Run, video, real starting pose. |
| 3 | Turns facing forward; keeps red. | 8s | Confirmed parent Run and real frame facing away. |

Adopting this roteiro prepares three items and their drafts. The first base instruction can be used directly or detailed. After block 1 is accepted, block 2 can be detailed with **original identity + REAL final frame of 1**. The plan for 3 helps contextualize 2, but it is not a known image and must not be executed ahead of time.

If 2 does not end facing away, review must show the real video. Accepting that result does not prove it followed the roteiro. The user can reject it or adjust the future action; do not rewrite history to feign continuity.

## 3. State and Authority: Three Distinct Concepts

### A. Roteiro Plan — Editable

- Dedicated roteiro ID, name, general idea, and OWNED original reference.
- Document revision, item ordering, and stable key for each block.
- Per block: planned action, requested duration, draft seed, base instruction, optional proposal, and chosen instruction.
- Context/version used in detailing, to detect stale response or outdated prompt.
- Saved explicitly on PC under `.data/roteiros/`; not in localStorage, database, or phone memory as authority.
- Stable block key does not become a Run UUID nor change simply because order changed.

### B. Real Attempt — Separate History

- Dedicated submission intent, link with roteiro/block/revision, and the actual Run UUID when admitted.
- Submitted snapshot: literal prompt, seed, duration, identity, and concrete parent, without replacing with old idea.
- Actual state, published media, and decision driven by existing native flow.
- Rejection/interruption preserves the attempt. Retry is another request and another review.
- An attempt is not considered accepted because the roteiro says "block completed". The native decision is authoritative.

### C. Accepted Prefix — Continuation Base

- To generate position N, the chosen attempt of position N−1 must be genuinely accepted and published.
- Each child must point to that exact attempt; it is not enough for it to appear immediately above in a card.
- Reordering future items does not modify the parent of an already submitted child.
- Accepted items and admitted snapshots remain frozen. Revising the planned suffix does not change the already materialized chain.
- Assembly uses the concrete ancestry of the chosen tail, never concatenating arbitrary runs just because they share a block index.

## 4. Action Matrix — No Hidden Side-Effects

| UI Action | Saves plan/config? | Calls Grok? | Generates video? | Changes decision? |
| --- | --- | --- | --- | --- |
| New roteiro / open / Back | No | No | No | No |
| Send reference | Saves dedicated input | No | No | No |
| Propose roteiro with Grok | Records dedicated intent/proposal | Yes, one explicit action | No | No |
| Edit proposal | Draft until save/adopt | No | No | No |
| Use this roteiro | Yes, validated plan | No | No | No |
| Save block changes | Yes, block/revision | No | No | No |
| Prepare block | Prepares dedicated draft/context | No | No | No |
| Detail this block | Records proposal/context | Yes, only that chunk | No | No |
| Use this proposal | Copies candidate to chosen instruction, on same workbench | No | No | No |
| Generate block | Records intent and snapshot/link | No | Yes, one attempt | No |
| Query order / assembly | Read-only / legitimate reconciliation | No | No | No |
| Accept / reject attempt | Maintains native decision | No | No | Yes, explicitly |
| Prepare another attempt | New draft based on snapshot | No | No | No |
| Assemble video | Dedicated intent/assembly | No | No | No |
| Save scriptwriter instructions | Dedicated configuration only | No | No | No |
| Save detailing instructions | Current enhancer configuration only | No | No | No |

Do not confuse upload / save plan / create local UUID with authorization for inference.

## 5. Block Detailing: Reusing the Existing Enhancer

The new proposal provides context to the enhancer without replacing its custom system prompt:

```text
Roteiro: Dance: from black to red
General idea: [user's original intent]

Intent of accepted blocks:
[planned actions and prompts actually submitted from previous chunks]
These texts describe the intent; visual results may differ.

This block:
[planned action for position N]
Requested duration: [draft value]
Aligned frames / time: [current capabilities]

Next planned block:
[action of position N+1, or "This is the last block."]
Do not repeat the previous one or anticipate the action of the next.

Visual context:
1. Original identity.
2. REAL last frame of accepted parent, if available.
```

Only the user clicking **Detail this block** triggers the query. Reuses client/provider/auth/fixed model and the existing CPU preview. Do not read/display OAuth, re-authenticate, renew grant, or modify pin to implement roteiro.

The **macro scriptwriter** has a separate system prompt focused on splitting the idea into blocks. Do not save this system prompt over `.data/grok/editor.json`. Invalid structured response does not result in execution; display error and preserve text/idea. Do not promise that the provider perfectly complies with duration, language, or appearance.

Do not propose new real calls during design/implementation/testing: the single authorization 37 has already been consumed. Future tests will be fake/CPU; real usage only upon explicit action by the owner.

## 6. Isolated Route, Reuse, and Proposed Surface

**Technical proposal to validate after screen review:** a vertical operation `roteiro.py` for plan, proposals, and attempt correlation; same local bridge, without new server/framework/database/queue.

- Dedicated page/context `/roteiros` and `/roteiros/{id}` for the roteiro experience. Can share same shell/styles and current preparation/review screens; do not duplicate entire frontend just to have a separate URL.
- Local plan API: list/create/read/save roteiro and its revision, with bounded locks/atomic writes and explicit conflict handling. Paths are owned; browser cannot pick arbitrary paths.
- Explicit roteiro proposal action separated from block detailing action. Both return editable proposals, never generation callbacks.
- Saving scriptwriter and enhancer systems has separate contracts/scopes. One does not mutate the other.
- Generation/review/continuation/assembly reuse existing pipes, Store, dispatcher, media, and native contracts. Do not copy video validator, frames, review, or generation logic to the scriptwriter.
- Registering/recovering a block's intent must be durable before submission. A link existing only in JS after 202 is insufficient: if the response is lost, "no Run ID in plan" does not mean "did not generate".
- The composition delegating to the native pipe must record the concrete link in the same admission path, with proof/reconciliation of its intent. **Do not** create a second dispatcher, new worker, or "generate all blocks" endpoint. Correlation contract details will be defined in the approved implementation, not faked as already existing.
- GET/SSE/reload reconstitute state and query the same ID. They do not generate or automatically repeat requests.

"Isolated route" means separating the roteiro operation. It does not mean creating another video engine, authentication, state source, or ComfyUI lifecycle.

## 7. UX Edge Cases That Must Be Visible

| Problem | What user sees | What must NOT happen |
| --- | --- | --- |
| Unsaved plan | Unsaved changes; save/discard/continue | Losing text due to Back without choice. |
| Another browser saved new version | Roteiro changed on PC; check version / keep draft | Silently overwriting revision. |
| Macro returned invalid response | Unconvertible response; view text/manual | Inventing duration, clamping, or generating. |
| Stale response | Previous context; explicit adoption | Swapping parent or current edit. |
| Parent lacking acceptance/proof | Open predecessor; prepare blocked | Continuing from rejected run or wrong frame. |
| Missing preview | Reread frame / existing manual flow | Silently sending only identity to Grok. |
| Uncertain submission without Run ID | Query submission intent | Repeating POST because link is absent. |
| Rejected/interrupted attempt | Final prompt + prepare another | Mutating terminal state or querying Grok on its own. |
| Real frame diverges from action | Video/review and real context | Pretending intent was fulfilled. |
| Incomplete assembly / 404 / 5xx | Reread the same ID | New UUID or presumed success. |
| External script terminates ComfyUI | Honest error/uncertainty of attempt | Controlling script, RAM, or caches; replay. |

## 8. Parameters and Limits Not Negotiated by This Design

Preserve configured values: native model, sampler, scheduler, steps, resolution, reference, VAE/decode/export. Duration per block remains requested (0,10], maximum two decimal places, default 8s per correction 40, 24fps, and Python half-even rounding 5+17k. 8s → 192 frames / 8s; three such blocks total 576 frames / 24s, without certifying performance or visual compliance. 2.3s remains explicit in frozen benchmark and historical records. Tail3/audioTrue independent of duration. Aligned totals are the sum of frames, not a promise of exact requested duration for other values.

No RAM policy: do not reject/cancel because free memory dropped. Telemetry remains observational; ComfyUI lifecycle belongs to the owner's script. Single slot and uncertainty/no-replay remain in place.

## 9. Proposals to Decide Together, Not Blocking Doubts

| Decision | My recommendation | Alternative |
| --- | --- | --- |
| Initial input | Reference + idea, initial name/count/duration in options | Desired total duration + proposed division, making alignment explicit. |
| Adopt macro | Pre-populates/saves all blocks, without generating | No presumed automatic alternative. |
| Proceed | Accept → Prepare next explicitly | Automation later, with dedicated scope/authorization. |
| Future planning | Editable even before predecessor exists | Locking everything until generated, less useful. |
| Seed | Copy current preset to draft and preserve | Explicit policy per block; do not select via Grok or increment secretly. |
| Middle-chunk editing | Outside this first evolution | Separate route with preceding/following anchors, still requires dedicated design/workflow. |
| Frontend | Familiar shell + central roteiro screen + reuse of others | Completely separate page; requires extra care with drafts and uncertainties when navigating. |
| Failed result | Display evidence; preserve current retry policy | Include failed retry in a subsequent explicit scope. |

## 10. Criteria to Begin Implementation

1. I critically review the designs and correct course — this v2 already records that first critical review.
2. Owner reviews screens T00–T07 and copy/buttons of this v2.
3. Incorporate feedback into a new Markdown revision.
4. After human approval, finalize technical plan with exclusive files, durable intent/link contract, fake/CPU tests, and frontend integration.
5. Only then implement. Do not interpret manager autoApprove as your review of these screens.

**Prompting you to review these Markdown files is the next action; do not proceed with implementation without your response.**
