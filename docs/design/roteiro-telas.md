# H3 · Roteiro — Revised Screens, v2

**Design approved and implemented by Plan 41.** This revision replaces the initial 12-screen design. The diagrams below are specifications, not screenshots or generation proof. [Flow and rationale for changes](roteiro-fluxo.md); [usage, captures, and validation limits](../roteiro.md).

## What Changed After Designing

1. **Reviewing proposal and monitoring roteiro are the same screen**, in different states. Do not repeat the entire list upon clicking Use.
2. **Editing an item happens in its own card**, without an additional screen for small changes.
3. **Context, instruction, Grok proposal, and Generate stay on the block screen.** Preserve explicit adoption without forcing three consecutive pages.
4. **Status, review, and assembly reuse the existing flow**, originating from the roteiro; do not build another version of each operation.
5. **Saving a plan is not generating.** Make this distinction clear at two key points, rather than repeating technical warnings on every card.
6. Current app default: **8s per block**, per correction 40. Benchmark 2.3s and earlier records remain historical, not roteiro defaults.

### Short Path

```text
Library → New roteiro → Populated roteiro
                             ↓ pick next
                        Prepare block
                             ↓ generate explicitly
                        Order → Review
                             ↓ accept
                        Prepare next
                             ↓ last accepted
                          Assembly
```

There are **eight screens**, including Library and Settings. Proposal/editing are states within them, not new pages. Do not stack all screens onto one page.

## Visual and Interaction Standards

- Mobile 393×852, single document scroll. Sticky top **Back · title · gear**, hit targets 44px; primary fields/buttons 48px. No global tabs or fixed dock.
- Graphite `#242725`, surfaces `#151816`, paper `#eeeae2`, copper `#c38b62`, secondary `#a7ada7`, borders `#454b46`.
- Current display typography: Arial Narrow/Liberation Sans Narrow/Impact; body system-ui; data ui-monospace. No new fonts/dependencies.
- Title 26px, section 22px, body/fields 16px, captions 14px, data 12px. Margins 16px; spacing 8/16/24px; cards padding 16px / border 1px / radius 3px.
- Primary action: filled copper, dark text, full width. Secondary neutral. Disabled state includes textual reason. Visible focus.
- Vertical sequence is the real plan order. Accepted items show real decisions; Planned items do not show thumbnails for non-existent videos.
- Two visual contexts in side-by-side cards when fitting without overflow, including on mobile; images contain, no cropping. At 320px, stack if labels become illegible. Each `Expand image` expands its figure within document flow, without mandatory modal or new flow.
- Desktop: central reading layout up to 960px. Do not turn the plan into a scrolling horizontal timeline.
- Back preserves draft/origin/scroll/focus. Does not save configuration, call Grok, generate, accept, or assemble. No implicit Enter generates.
- Existing motion / reduced-motion, no autoplay, invented progress, or global gestures.

---

## T00 · Library

**A real choice:** whole roteiro or standalone block.

```text
┌─────────────────────────────────────┐
│ ←      Library                   ⚙ │
├─────────────────────────────────────┤
│ Your videos                         │
│                                     │
│ [ New roteiro ]                     │
│ [ New freestyle ]                   │
│                                     │
│ Roteiros                            │
│ ┌─────────────────────────────────┐ │
│ │ Dance: from black to red        │ │
│ │ 3 blocks · 1 accepted           │ │
│ │ Next: block 2                   │ │
│ │ [ Open roteiro ]                │ │
│ └─────────────────────────────────┘ │
│                                     │
│ Freestyle                           │
│ ┌─────────────────────────────────┐ │
│ │ She turns and looks at camera.  │ │
│ │ Ready for review                │ │
│ │ [ Open block ]                  │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

- New roteiro → T01. New freestyle → existing flow, without mandatory roteiro.
- Open roteiro → T02. Open block → existing review.
- Empty: **"Your first roteiro begins with an idea."** / **"No standalone blocks yet."**
- Loading: **"Reading your videos on PC…"** Error: **"Could not read library."** + `Reread library`.
- A roteiro run remains in history, but do not duplicate each attempt as a new main project. The card summarizes accepted positions, not run count.

## T01 · New Roteiro

**Intent first.** Name and chunk count are secondary controls, not a mandatory technical form before telling the scene.

```text
┌─────────────────────────────────────┐
│ ←      New roteiro               ⚙ │
├─────────────────────────────────────┤
│ Original reference                  │
│ [ Choose image on PC          ▾ ]   │
│ [ Upload image from phone ]         │
│ ┌─────────────────────────────────┐ │
│ │         selected image          │ │
│ └─────────────────────────────────┘ │
│                                     │
│ What happens in the video?          │
│ ┌─────────────────────────────────┐ │
│ │ Starts dancing in black.        │ │
│ │ Takes a jump and changes to     │ │
│ │ red, finishes facing away,      │ │
│ │ then turns to face forward.     │ │
│ └─────────────────────────────────┘ │
│                                     │
│ [ Adjust count and name ▾ ]         │
│                                     │
│ [ Propose roteiro with Grok ]       │
│ [ Write blocks manually ]           │
│ Creates a proposal. Does not        │
│ generate video.                     │
└─────────────────────────────────────┘
```

The disclosure **Adjust count and name** contains exactly:

```text
Name [ Dance: from black to red ]
Initial count [ 3 ] blocks
Initial duration [ 8 ] seconds per block
3 × 8 s = 24 s planned
You can edit each chunk later.
```

- Count 3 is a planning example, not a native parameter. Do not use number chosen by Grok as seed/frames.
- Name is optional on entry; proposal can suggest an editable title. Count/duration remain accessible without cluttering the first task.
- Default duration comes from current capabilities: 8s. Fields are not hardcoded to 8 forever. Requested (0,10], two decimal places; validate, do not clamp.
- Upload uses existing flow, saves input on PC, does not call Grok.
- Propose is an explicit call → T02 in proposal state. Manual creates editable items → same T02. Nothing generates during any of these actions.

## T02 · Roteiro — Proposal, Editing, and Tracking

**This is the home of the project.** The same list works before and after adopting the roteiro.

### State A — Proposal Received, Not Adopted

```text
┌─────────────────────────────────────┐
│ ←      Roteiro                   ⚙ │
├─────────────────────────────────────┤
│ Dance: from black to red            │
│ Proposal · no video generated       │
│ 3 blocks · 24 s planned             │
│                                     │
│ ┌─ 1 · Planned ───────────────────┐ │
│ │ Dances maintaining black dress. │ │
│ │ 8 s · [ Edit ]                  │ │
│ └─────────────────────────────────┘ │
│ ┌─ 2 · Planned ───────────────────┐ │
│ │ Jump; changes to red;           │ │
│ │ finishes facing away.           │ │
│ │ 8 s · [ Edit ]                  │ │
│ └─────────────────────────────────┘ │
│ ┌─ 3 · Planned ───────────────────┐ │
│ │ Turns facing front; keeps red.  │ │
│ │ 8 s · [ Edit ]                  │ │
│ └─────────────────────────────────┘ │
│                                     │
│ [ Add block ]                       │
│ [ Use this roteiro ]                │
│ Saves all blocks. Does not generate.│
└─────────────────────────────────────┘
```

- **All items already have action, duration, and base instruction.** Videos, future frames, and Run IDs do not exist yet.
- Use this roteiro validates/saves. Remains on this screen, transitioning to State B. Do not reproduce list on another page.
- Proposing: **"Dividing your idea into blocks…"** Error: **"Could not get proposal. Your idea remains here."** + `Back to idea` / `Write manually`.
- Invalid: **"Response could not be converted into valid blocks."** + `View response` / `Back to idea`. No executable JSON/HTML, guessing, or silent filler.
- Another proposal only via explicit action `Propose another version` in options. The new one is a separate candidate: do not overwrite existing edit or already adopted sequence.

### State B — Adopted Plan

```text
│ Saved on PC · 1 of 3 blocks accepted │
│ [ Prepare block 2 ]                  │
│                                      │
│ 1 · Accepted                         │
│ Dances maintaining black dress.      │
│ [ Watch block ]                      │
│                                      │
│ 2 · Next                             │
│ Jump; red; finishes facing away.     │
│ 8 s · [ Edit ]                       │
│                                      │
│ 3 · Planned                          │
│ Turns facing front; keeps red.       │
│ Awaits block 2 acceptance.           │
│ 8 s · [ Edit ]                       │
│                                      │
│ [ View idea and reference ▾ ]        │
│ [ Add block ]                        │
```

Primary action for State B:

| Real state | Text/action |
| --- | --- |
| None generated | Prepare block 1 |
| Accepted prefix | Prepare block N |
| Submitted/running | View order for block N |
| Ready | Review block N |
| Rejected/interrupted confirmed | Prepare another attempt |
| Confirmed failure | View attempt |
| Uncertain | Query submission of block N |
| All accepted | Prepare assembly |

No Generate All. An accepted card opens the result, not a retroactive editor. For each position, `View attempts` is available by expanding details, separated from the plan.

### State C — Editing in Card

```text
│ 2 · Editing plan                     │
│ What happens                         │
│ [ Action text, editable.           ] │
│ Duration [ 8 ] s                     │
│ 192 frames → 8.000 s aligned         │
│ [ Save changes ] [ Cancel ]          │
│ [ Organize block ▾ ]                 │
```

- Only one card in edit mode at a time; switching with unsaved changes prompts `Save and continue` / `Discard changes` / `Continue editing`.
- Organize: `Move up`, `Move down`, `Remove block`. These are planning actions, without deleting runs/media. Removal requires confirmation.
- Only unsubmitted suffix can change order; does not bypass an already submitted position. No visual renumbering that alters identity of attempts.
- Modifying action/duration/neighbor marks previous detailed instruction as outdated. Do not call Grok or overwrite chosen prompt.
- Unsaved: **"Unsaved changes."** Save error keeps card in edit mode. Conflict: **"Roteiro changed on PC. Check other version before saving."**
- Adding a block after all are accepted marks project incomplete again; does not invalidate/delete previous assembly.

## T03 · Prepare Block — A Workbench, Not Three Pages

**A single task:** review context and instruction, detail if desired, generate when decided.

```text
┌─────────────────────────────────────┐
│ ←      Prepare block 2           ⚙ │
├─────────────────────────────────────┤
│ Block 2 of 3 · continuation          │
│ ┌──────────────┐ ┌────────────────┐ │
│ │   original   │ │   REAL frame   │ │
│ │    image     │ │   of block 1   │ │
│ └──────────────┘ └────────────────┘ │
│ Identity         Where it ended     │
│ [ Expand ]       [ Expand ]         │
│                                     │
│ Jump; red dress; facing away.       │
│ [ View before and after ▾ ]         │
│                                     │
│ Instruction to be sent              │
│ Origin: roteiro                     │
│ ┌─────────────────────────────────┐ │
│ │ Pre-filled editable text.       │ │
│ └─────────────────────────────────┘ │
│ [ Detail this block with Grok ]     │
│                                     │
│ 8 s requested · 192 frames · 8 s    │
│ Seed: 2026101205                    │
│ [ Adjust this block ]               │
│                                     │
│ [ Generate block ]                  │
│ Sends a new attempt to PC.          │
└─────────────────────────────────────┘
```

- Initial entry pre-fills base instruction: do not require `Use roteiro instruction` to copy something already adopted.
- Block 1 has only identity and **"First block · no prior video."** N>1 uses accepted and published attempt of N−1. Both figures remain visible in proposal mode too.
- Expanded before/after: **Intent of accepted blocks / This block / Next planned block**. Do not label text as "what actually happened"; frame is current visual proof.
- Detail button queries only this chunk with reference+frame/context/duration; does not mutate its custom system prompt. Opening workbench does not call Grok.
- Generate uses exactly the field indicated as chosen instruction; manual/Grok/editing are choices, not requiring further navigation.

### Grok Proposal State Within Same Workbench

```text
│ Grok proposal · not yet used         │
│ [ Received text, editable.         ] │
│ [ Use this proposal ]                │
│ [ Keep my instruction ]              │
│ Check before generating.             │
```

- Editor shows candidate without overwriting previously chosen text. `Use this proposal` copies/adopts and returns to editor **Instruction to be sent**, origin Grok. `Keep my instruction` returns to previous text.
- While candidate is open, do not show Generate as if generating received text: **first choose one of the two paths**. Adopting proposal does not generate.
- If user modified draft during the call, response is marked stale; explicit adoption and visible context. Later submission cannot have its snapshot rewritten by response.
- Pending: **"Detailing this block…"** Error: **"Could not detail. Your instruction was kept."** Do not block manual path due to isolated editor error.
- If plan/neighbor changed: **"Plan changed after this detailing. Check instruction."** + `Use this instruction anyway` / `Return to roteiro text`. Confirmation clarifies intent, does not clear submission uncertainty.
- Frame unavailable: **"Could not display last frame."** + `Reread frame`; Grok with two images unavailable, native manual path continues per existing contract, without silent fallback.
- Invalid predecessor: **"Accept previous block before preparing this continuation."** + `Open previous block`. Do not swap parent.
- Retry arrives here pre-filled with **literal FINAL submitted prompt**, reference/seed/duration/original parent, and notice **"New attempt; previous one remains in history."** Do not recompute from macro.

## T04 · Order on PC — Contextualized Current Screen

```text
┌─────────────────────────────────────┐
│ ←      Block 2 on PC             ⚙ │
├─────────────────────────────────────┤
│ Dance: from black to red            │
│ Generating block 2                  │
│ Awaiting result from PC.            │
│                                     │
│ [ View submitted instruction ▾ ]    │
│ [ Data of this attempt ▾ ]          │
│ [ Back to roteiro ]                 │
│ Back does not cancel or resubmit.   │
└─────────────────────────────────────┘
```

- Submitting: **"Sending order to PC…"**; 202: **"Order received. Awaiting execution."**; running: **"Generating block N."** No false percentages.
- Ready: `Review block`. Uncertain with Run ID: **"Result not yet confirmed."** + `Query order`. Without ID: **"Could not confirm if order was admitted."** + `Query submission`.
- Query reconciles durable intent/link, does not POST again. A missing link in browser does not prove job never existed.
- No concurrent generation/retry while intent remains uncertain. Querying/editing future plans does not clear flags.

## T05 · Review Block — Existing Operation

```text
┌─────────────────────────────────────┐
│ ←      Review block 2             ⚙ │
├─────────────────────────────────────┤
│ Block 2 of 3 · ready for review     │
│ ┌─────────────────────────────────┐ │
│ │ Real video · native controls    │ │
│ └─────────────────────────────────┘ │
│ Requested 8 s · verified 8.000 s    │
│ [ View submitted instruction ▾ ]    │
│ [ View attempts of this block ▾ ]   │
│                                     │
│ [ Accept block ]                    │
│ [ Reject attempt ]                  │
│ Accept does not generate next.      │
└─────────────────────────────────────┘
```

After accepting: **"Block 2 accepted."** + `Prepare block 3` / `Back to roteiro`. Remain on this screen; do not automatically navigate to another editor.

After rejecting / confirmed interruption: **"Block 2 still needs an accepted attempt."** + `Prepare another attempt` / `Back to roteiro`. Retry → T03 directly, without new roteiro/Grok.

Without video: display error/state/prompt, not fictitious player. Failed preserves current policy, without inventing new retry. Accepted results do not edit middle chunks: two-anchor operation is a separate evolution.

## T06 · Assembly — Existing Operation

```text
┌─────────────────────────────────────┐
│ ←      Assembly                  ⚙ │
├─────────────────────────────────────┤
│ Dance: from black to red            │
│ 3 accepted blocks · 24 s verified   │
│ 1 · Dance in black                  │
│ 2 · Jump; red; facing away          │
│ 3 · Turns facing front              │
│                                     │
│ [ Assemble video ]                  │
│ Does not generate new blocks.       │
└─────────────────────────────────────┘
```

Concrete chain of accepted attempts, not any arbitrary three runs. Upon completion, player / `Open video` / `Download video`. Partial: **"Preview: 2 of 3 blocks"**. Uncertain/error: `Reread assembly` for same UUID; Back to roteiro available. Does not re-assemble on accept/reload/SSE.

## T07 · Settings — Explicit Scope, No Three Editors Open

```text
┌─────────────────────────────────────┐
│ ←      Settings                  ⚙ │
├─────────────────────────────────────┤
│ This block · draft                  │
│ Duration [ 8 ] s                    │
│ Seed [ 2026101205 ]                 │
│ Does not alter submitted attempts.  │
│                                     │
│ [ Scriptwriter instructions ▾ ]     │
│ [ Detailing instructions ▾ ]        │
│                                     │
│ [ Done with settings ]              │
└─────────────────────────────────────┘
```

- Local section only for unsubmitted draft. For other origins: **"Open an unsubmitted block to adjust duration and seed."**
- Opening scriptwriter reveals textarea / fixed model / `Save scriptwriter instructions`; opening detailing reveals current system / model / `Save detailing instructions`. Do not overwrite one with the other.
- Done/Back does not implicitly save systems or call provider. Local fields track draft; saving must be confirmed before submitting block intent.
- No controls for RAM / lifecycle / native model / sampler. Preserve scroll/focus and do not open keyboard automatically.

## Quick Review

The proposal is: **idea → populated/editable list → next block workbench → order/review → next**. Technical safety changes do not need to become extra steps for the user.

Mapping from previous design: T02+T03+T04 became T02; T05+T06+T07 became T03; status/review/assembly/settings became T04–T07. Library/creation preserved. Current IDs are those of this v2.

**Await human review before implementing.** The design has been critically reviewed and simplified; this does not mean the proposal has already been validated in a browser.
