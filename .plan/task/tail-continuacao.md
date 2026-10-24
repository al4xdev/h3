# Tail — Script Tail Extension

Status: completed and validated with CPU fixtures on 2026-10-13.
Owner request on 2026-10-13.
File maintained directly, outside harness. Interpolation remains in backlog.

## Expected Outcome

Within a script, the user provides a sentence indicating what should happen
next and how many blocks to append. Grok plans the intents in JSON;
subsequently, in a confirmed batch, it refines each block using the real visual
outcome of the previous one before generating. Do not require the user to write
the final prompt or manually click "Improve/Refine" for each block in the batch.

Freestyle remains legacy, with its existing conversion path preserved.

## Baseline Rules

1. Use the confirmed end of the script's accepted sequence, with materialized video,
   proven original identity, and final frame derived from that same parent.
2. If no video exists yet, complete the initial I2V generation before proceeding.
   Parent acceptance remains mandatory; in a confirmed batch it may be technical.
3. Do not proceed over a block pending review, active generation, uncertain
   outcome, or failed/interrupted attempt. These situations require explicit
   review or recovery, without automatic re-inference.
4. Distinguish future unsubmitted plans from an existing video tail.
   The form must clearly indicate where new blocks will be appended; do not
   silently overwrite drafts, candidates, or pending blocks.

## Two Grok Stages

**Planning:** the sentence becomes a structured proposal of new blocks, with valid
actions and requested durations. Use the script context and proven starting state.
Future blocks describe intent, not observed frames or an already guaranteed artistic
chronology. The proposal is editable and its explicit adoption saves the plan, without
initiating generation.

**Refinement during execution:** immediately prior to each block, use the original
identity, the real last frame of the currently accepted parent, and the intents of
neighboring blocks. Store the literal proposal effectively used and its link to that
parent. Following generation and intermediate acceptance, the next refinement receives
the new real frame.

The batch does not use a single frozen frame across all blocks. Grok failure or uncertain
outcome halts execution, without falling back to the raw script.

## Proposed Implementation

- Reuse `roteiro.py`, JSON proposal, and `roteiro_batch.py`; maintain a single vertical
  orchestration, the existing dispatcher, and global slot. Do not create another queue,
  agent framework, or generation engine.
- Add tail flow to the script UI: sentence, count, and proposal staging; editing/adoption;
  explicit batch start with current consents.
- Save intent, source revision, extension point, IDs, and references under `.data`.
  Publish new blocks atomically, without overwriting the accepted prefix or altering
  previous attempts. Delayed proposals must remain bound to the source context and
  require reconciliation if the script changed.
- Preserve distinct prompts/configurations for planning and refinement, fixed model,
  and current limits: 20000 output tokens for script, 12000 for block editor.
  New provider prompts must be written in English.
- Maintain native V2V with real initial frame, identity, and parent video/tail context,
  without altering models, sampler, scheduler, steps, resolution, conditioning, decode,
  audio, or context parameters. Duration follows existing per-block policy: default 8s,
  requested budget up to 10s, 24fps, and 5+17k alignment.
- Reuse Stop, warnings, SSE reading, recovery by same ID, and generic loading.
  Intermediates may be technically accepted in a confirmed batch; the final chunk remains
  for human review. Do not initiate assembly automatically.

## Verification and Completion

Test with fake clients and CPU fixtures: extension after accepted parent; root completed
before V2V; frame updated on each refinement; invalid JSON; concurrent plan/draft;
duration; cancellation; provider failure; crash/restart without replay; history
preserved and final block ready for review. Tests and opening UI do not call provider/GPU.

Run appropriate checks, Node, Ruff, and diff. Record evidence and create local commit.
Do not consider Tail completed merely by re-presenting an already existing batch: the new
sentence must produce an extension bound to the correct script tail. Real generation,
if needed, requires its own explicit intent and is not initiated by this plan.

## Delivery and Evidence

- UI **Continue script · Tail** with sentence, count, duration, and seed; editable proposal,
  frozen prefix, and explicit adoption restricted to the new segment.
- POST/GET/PUT routes by UUID, reservation before provider call, and recovery of same
  request. Revision, identity, accepted chain, and source video bytes are checked;
  invalid output is preserved, without fallback or replay.
- Existing batch refines each new block using the updated final frame and preserves
  prefix files, parameters, and attempts. Final video left for review.
- Proven pre-submission rejection releases the form; unknown outcome remains blocked.
  Delayed reads preserve navigation and local edits.
- Complete Python suite: 949 passed tests before final recovery adjustments.
  Following those adjustments, 70 script/Tail/batch/API tests passed, including three
  new ASGI contracts. Frontend: 256 passed tests.
- Ruff and `git diff --check` passed. Local evidence in `.dumps/tasks/tail-pytest.txt`,
  `tail-final-python.txt`, and `tail-node-tests.txt`.
- No live calls to provider/GPU, restart of production server, or artistic certification
  occurred. Existing total limit: 50 blocks. Interpolation deferred.
