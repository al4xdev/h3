# In-Between Editing Across Anchors and Block Versions

Status: completed. Implementation authorized by owner in this session.

## Contract

- Dedicated editing screen and dedicated Grok route, with separate system prompt in English.
- Remaking block 2 between 1 and 3 creates an alternative version of block 2.
- Inserting before/after a block creates a new block between the chosen neighbors.
- Historical videos and their parents remain immutable. Editorial selection belongs
  to the script, separate from generation ancestry. Accepted versions are selectable.
- Initial delivery generates one block per edit. Requires two accepted anchors; extension
  without a right neighbor uses Tail. Insertion before the first root lacks a parent video.
- Grok receives identity, real last frame of the previous, real first frame of the
  next, and both prompts effectively sent, marked as historical context.
  The previous video is native context for the video engine, not a video upload to Grok.
- Editable proposal, generation, review, and application to the sequence are explicit actions.
  UUIDs and uncertain states live on disk; GET/startup/SSE never resubmit.
- The native bridge operation derives V2V and adds only the allowed final anchor
  via MiniMaxH3AddGuide(frame_idx=-1), proven in installed code. Preserve
  existing models/parameters, golden graphs, and I2V/V2V behavior.
- Editorial assembly must follow the selected videos in the script, maintaining
  original parents in their provenance, without requiring that the new order be genealogical.

## Validation

Fake/CPU tests covering anchors, prompts, guards, versions, positioning, publication,
assembly, and cancellation; frontend with navigation/drafts without incidental generation.
No real inference/provider/GPU or restart of production server.

Results: complete Python suite with 1028 passed tests; 29 focused tests
following final adjustments to selection/Tail and 4 additional history checks.
Frontend: 299 passed tests. Ruff and git diff --check clean.
Desktop browser flow with mocked API validated under normal and
reduced motion, without POST on reload and with draft preserved across Settings/Back.
Local evidence in `.dumps/tests/edit-ui/` and `.dumps/tasks/edit-full-python.txt`.
No real GPU generation or physical mobile device fluidity validation occurred.
Stable server bf7305a remains isolated to protect owner's batch.

## Parallel Work

Native bridge operation and guards; editing screen; HTTP/SSE termination; vertical
editing/Grok/editorial selection operation and integration by the main session.
