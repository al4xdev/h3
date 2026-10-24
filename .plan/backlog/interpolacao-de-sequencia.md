# Sequence Interpolation — Generation Between Two Anchors

Status: promoted to implementation in `.plan/task/edicao-entre-ancoras.md` by
subsequent owner authorization. Initial delivery: one video per edit, insertion
between neighbors or a new version of a block, with dedicated interface and Grok route.
Batch insertion of N blocks remains a future evolution.

## Objective

Insert N new blocks between points in a script, for example ten blocks between
a departure scene and an arrival scene. The preceding scene provides the complete
video and its final frame; the destination scene provides an explicit final visual anchor.
Additional images may provide context, with identified roles.

Mode name: **Sequence Interpolation**. This refers to building a narrative
and visual bridge; the name does not promise mathematical pixel interpolation.

## Separation from Tail

Tail appends blocks to the end and originates from the actual prior outcome, without imposing an
arrival frame. Interpolation has two anchors and must gradually approach
the destination visual state. Do not add this second condition to Tail mode.

Preserve the two stages: plan the blocks and subsequently refine each prompt with the
actual newly generated frame. An initial plan with specified timings does not prove that the
pose, clothing, or final action will be close to the intended anchor.

## Investigation Required Prior to Implementation

- Verify in the installed schema and native graph how to condition the start and
  the destination: identity image, context video, initial frame, and desired final
  frame serve distinct roles. Do not treat the parent's `last_frame` as the destination
  frame.
- Currently, `V2V_CONFIG` uses `initial_frame`, `identity`, and `motion_video`. The initial
  frame is derived from the end of the accepted parent. Integration of a final destination
  image is not proven by this contract.
- Define the source and ownership of each reference, duration of each block,
  the insertion point, and the destination of the new sequence. Preserve earlier runs and
  decisions; insertion must not rewrite history or cause an existing continuation
  to silently point to a new parent.
- Define how to review convergence toward the anchor without presuming artistic success,
  performing blind retries, or modifying sampler/models/parameters to compensate.
- Separate prompts and configuration for this mode if its instructions differ
  from script planning and Tail refinement.

## Future Criteria

A new sequence proves both contexts, maintains original media/history,
generates only upon explicit action, and displays the result for review. Fake/CPU tests
must prove ordering, references, ownership, cancellation, and absence of replay.
Any real validation requires dedicated intent and is not authorized by
this backlog record.
