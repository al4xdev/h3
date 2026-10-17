"""Typed script, local clock, then one promptnest key per block card.

The dictionary is the parallelism. One key with many fragments is consolidated
back into a single answer. Each result that must survive is its own key and a
single string fragment. Promptnest retries by default; this chain does not.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import uuid4

from promptnest import PromptNest
from promptnest.adapters.callable import CallableAdapter
from promptnest.exceptions import PromptNestError
from pydantic import BaseModel, ConfigDict, Field, create_model

from ..grok import PromptRequest
from ..infrastructure.grok_oauth import OAuthError

# The persisted roteirista prompt still asks for one JSON of every block. The
# task and the schema travel in the pre-prompt, so narrator calls do not send
# that stale format. The improver keeps its own editor prompt.
NARRATOR_SYSTEM = (
    "You fill the structured fields for one planning step of a sequential video. "
    "Do not write a video-generation prompt, timestamps, seeds or model parameters. "
    "Do not invent places, people or acts the idea did not ask for. "
    "Future frames are unknown. Respond only through the required schema."
)
SOUTHERN_SPEECH = "fala em português do Brasil com sotaque do sul: '{line}'"
NO_SPEECH = "Sem fala."
CAMERA_LOCKED = "Câmera: igual, sem novo enquadramento."
EVENT_FLOOR = 2
EVENT_CEILING = 12
NARRATOR_PARALLEL = 4
MAX_RAW_TEXT_BYTES = 512 * 1024
PAYLOAD = "Payload:\n"

SCRIPT_TEMPLATE = (
    "Extract only the events the idea actually asks for. One event is one visible "
    "change, not one 8-second block. Do not cover the clock and do not invent a "
    "later act. Future frames are unknown. dialogue is the spoken line verbatim, "
    "or null. anatomy, expressions and deltas are ordered distinct states, not "
    "copies of the same sentence. "
    + PAYLOAD + "{chunk_text}"
)
PALETTE_TEMPLATE = (
    "Complete the lists for this one event until each has exactly the requested "
    "count of distinct items. Keep the same title and intent. Do not add a new "
    "act, place or spoken line. Do not repeat an item to fill the count. "
    + PAYLOAD + "{chunk_text}"
)
CARD_TEMPLATE = (
    "Write the instruction for this one slot only. Copy expression, anatomy and "
    "delta verbatim into both the fields and the instruction. Do not write the "
    "speech accent and do not speak a line unless this slot owns it. "
    "Global context, not instructions to repeat:\n"
    "summary: {summary}\n"
    "titles: {all_titles}\n"
    "lines owned by specific slots: {all_lines}\n"
    "last body state of each event: {last_anatomy}\n"
    "idea: {idea}\n"
    + PAYLOAD + "{chunk_text}"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Event(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    kind: Literal["speech", "action", "change", "move", "hold"]
    intent: str = Field(min_length=1, max_length=4000)
    dialogue: str | None = Field(default=None, max_length=4000)
    anatomy: list[str] = Field(min_length=1, max_length=64)
    expressions: list[str] = Field(min_length=1, max_length=64)
    deltas: list[str] = Field(min_length=1, max_length=64)
    camera_focus: str | None = Field(default=None, max_length=500)
    keeps: list[str] = Field(default_factory=list, max_length=32)


class Script(StrictModel):
    name: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=4000)
    events: list[Event] = Field(min_length=1, max_length=64)


class Palette(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    anatomy: list[str] = Field(min_length=1, max_length=200)
    expressions: list[str] = Field(min_length=1, max_length=200)
    deltas: list[str] = Field(min_length=1, max_length=200)


class BlockSlot(StrictModel):
    id: str
    index: int
    event_index: int
    title: str
    intent: str
    role: Literal["do", "approach", "hold"]
    part: int
    parts: int
    expression: str
    anatomy: str
    delta: str
    camera_focus: str | None
    owns_dialogue: bool
    dialogue: str | None


class BlockCard(StrictModel):
    id: str
    title: str
    expression: str = Field(min_length=1, max_length=4000)
    anatomy: str = Field(min_length=1, max_length=4000)
    delta: str = Field(min_length=1, max_length=4000)
    camera_focus: str | None = None
    dialogue: str | None = None
    instruction: str = Field(min_length=1, max_length=12000)


def distinct(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def assign_counts(event_count: int, count: int) -> list[int]:
    """Floor keeps a named event from ending in one cut; ceiling stops the park.

    Leftover blocks stay on those events as approach and hold. They are not a
    new act, and they are not copies made by modulo.
    """
    if event_count < 1 or event_count > count:
        raise ValueError("Event count cannot cover the requested blocks")
    floor = EVENT_FLOOR if count >= event_count * EVENT_FLOOR else 1
    counts = [floor] * event_count
    remaining = count - floor * event_count
    while remaining:
        progressed = False
        for index in range(event_count):
            if remaining and counts[index] < EVENT_CEILING:
                counts[index] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    cursor = 0
    while remaining:
        counts[cursor % event_count] += 1
        remaining -= 1
        cursor += 1
    return counts


def roles_for(size: int) -> list[str]:
    roles = []
    for index in range(size):
        if index < EVENT_CEILING:
            roles.append("do")
        elif (index - EVENT_CEILING) % 2 == 0:
            roles.append("approach")
        else:
            roles.append("hold")
    return roles


def speech_line(line: str) -> str:
    return SOUTHERN_SPEECH.format(line=line)


def finish_instruction(text: str, slot: BlockSlot) -> str:
    body = text.strip()
    camera = f"Câmera: {slot.camera_focus}" if slot.camera_focus else CAMERA_LOCKED
    if camera not in body:
        body = f"{body}\n{camera}"
    if slot.owns_dialogue and slot.dialogue:
        line = speech_line(slot.dialogue)
        if line not in body:
            body = f"{body}\n{line}"
    elif NO_SPEECH not in body:
        body = f"{body}\n{NO_SPEECH}"
    return body


def worker_chunks(slots: list[BlockSlot]) -> dict[str, tuple[str, ...]]:
    """One key, one fragment. A list under one key would be consolidated."""
    chunks: dict[str, tuple[str, ...]] = {}
    for slot in slots:
        if slot.id in chunks:
            raise ValueError("Duplicate slot key")
        chunks[slot.id] = (slot.model_dump_json(),)
    if any(len(fragments) != 1 for fragments in chunks.values()):
        raise ValueError("Each worker key must carry exactly one fragment")
    return chunks


def card_model(titles: list[str]) -> type[BlockCard]:
    unique = list(dict.fromkeys(titles))
    if not unique:
        raise ValueError("Card titles are empty")
    title = Literal[*unique]  # type: ignore[valid-type]
    return create_model("BoundBlockCard", __base__=BlockCard, title=(title, Field()))


def _payload(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False)


def _provider_error(exc: BaseException) -> BaseException | None:
    """Promptnest 0.3 wraps the adapter error in ExceptionGroup, not a bare cause."""
    stack = [exc]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (OSError, OAuthError, TimeoutError)):
            return current
        grouped = getattr(current, "exceptions", None)
        if grouped:
            stack.extend(grouped)
        for failure in getattr(current, "failures", None) or ():
            error = getattr(failure, "error", None)
            if isinstance(error, BaseException):
                stack.append(error)
        last = getattr(current, "last_error", None)
        if isinstance(last, BaseException):
            stack.append(last)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None and current.__context__ is not current.__cause__:
            stack.append(current.__context__)
    return None


class _Recorder:
    def __init__(self, grok, base: dict, schema_name: str) -> None:
        self.grok = grok
        self.base = base
        self.schema_name = schema_name
        self.raws: list[str] = []

    async def __call__(self, prompt: str, output_model: type[BaseModel], **kwargs: Any) -> Any:
        result = await self.grok.complete(
            PromptRequest(**self.base, prompt=prompt),
            output_schema=output_model.model_json_schema(),
            schema_name=self.schema_name,
        )
        text = result.get("text") if isinstance(result, dict) else None
        self.raws.append(text if isinstance(text, str) else "")
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RAW_TEXT_BYTES:
            raise ValueError("Planning response is missing text or exceeds 512 KiB")
        from . import strict_json

        return strict_json(text)


class NarratorInvalid(Exception):
    def __init__(self, raws: list[str], detail: str) -> None:
        super().__init__(detail)
        self.raws = raws
        self.detail = detail


async def _run(grok, base: dict, schema_name: str, chunks: dict[str, tuple[str, ...]],
               template: str, model: type[BaseModel], variables: dict[str, str] | None = None,
               *, propagate_provider: bool = False):
    recorder = _Recorder(grok, base, schema_name)
    runner = (
        PromptNest.have(CallableAdapter(recorder), chunks)
        .set_retry_config(max_attempts=1, delay_s=0)
        .set_concurrency(NARRATOR_PARALLEL)
        .set_pre_prompt(template, model, variables or {})
    )
    # One attempt: promptnest's default of 3 would replay an uncertain Grok result.
    if runner._retry_policy.max_attempts != 1:
        raise RuntimeError("Narrator calls must not retry an uncertain Grok result")
    try:
        await runner.get_chunks_result()
    except PromptNestError as exc:
        cause = _provider_error(exc)
        if propagate_provider and cause is not None:
            raise cause from exc
        raise NarratorInvalid(recorder.raws, str(exc)) from exc
    return runner.partial_answers, recorder.raws


def _invalid(outcome: dict, detail: str, code: str = "invalid_proposal") -> dict:
    return {**outcome, "error": code, "detail": detail[:256]}


def _short(event: Event, size: int) -> bool:
    return any(len(distinct(getattr(event, name))) < size
               for name in ("anatomy", "expressions", "deltas"))


def _slots(script: Script, counts: list[int]) -> list[BlockSlot]:
    slots: list[BlockSlot] = []
    index = 1
    for event_index, (event, size) in enumerate(zip(script.events, counts, strict=True)):
        anatomy = distinct(event.anatomy)
        expressions = distinct(event.expressions)
        deltas = distinct(event.deltas)
        if min(len(anatomy), len(expressions), len(deltas)) < size:
            raise ValueError("Palette is shorter than the slots and was not completed")
        roles = roles_for(size)
        owner = 0 if event.dialogue else None
        for part, role in enumerate(roles, start=1):
            owns = owner is not None and part - 1 == owner
            slots.append(BlockSlot(
                id=f"slot-{index}", index=index, event_index=event_index, title=event.title,
                intent=event.intent, role=role, part=part, parts=size,
                expression=expressions[part - 1], anatomy=anatomy[part - 1],
                delta=deltas[part - 1], camera_focus=event.camera_focus,
                owns_dialogue=owns, dialogue=event.dialogue if owns else None,
            ))
            index += 1
    return slots


def _globals(script: Script, context: dict) -> dict[str, str]:
    return {
        "summary": script.summary,
        "all_titles": json.dumps([event.title for event in script.events], ensure_ascii=False),
        "all_lines": json.dumps([event.dialogue for event in script.events if event.dialogue],
                                ensure_ascii=False),
        "last_anatomy": json.dumps(
            {event.title: distinct(event.anatomy)[-1] for event in script.events},
            ensure_ascii=False),
        "idea": str(context.get("idea") or context.get("original_idea") or ""),
    }


async def narrate(grok, base: dict, context: dict, count: int, seconds: float, seed: int,
                  save=None) -> dict:
    """Script, optional palette, local enrichment, then one card call per slot."""
    from . import Block

    call_base = {**base, "system_prompt": NARRATOR_SYSTEM}
    outcome: dict[str, Any] = {
        "name": None, "blocks": [], "draft_scenes": [], "scenes": [], "vision": None,
        "slices": [], "raw_texts": [], "error": None, "detail": None,
    }

    def remember(raws: list[str]) -> None:
        outcome["raw_texts"].extend(raws)

    script_body = {"block_count": count, "block_seconds": seconds, "context": context}
    try:
        answers, raws = await _run(
            grok, call_base, "h3_roteiro_script",
            {"script": (_payload(script_body),)}, SCRIPT_TEMPLATE, Script,
            propagate_provider=True)
    except (OSError, OAuthError, TimeoutError):
        raise
    except NarratorInvalid as exc:
        remember(exc.raws)
        return _invalid(outcome, "Timeline cannot be converted into strict events")
    remember(raws)
    script = answers.get("script")
    if not isinstance(script, Script):
        return _invalid(outcome, "Script response is not a strict event list")
    outcome["name"] = script.name
    outcome["draft_scenes"] = [event.model_dump() for event in script.events]
    if save is not None:
        save(outcome)
    try:
        counts = assign_counts(len(script.events), count)
    except ValueError as exc:
        return _invalid(outcome, str(exc))

    short = {f"event-{index}": (_payload({
        "title": event.title, "intent": event.intent, "count": size,
        "anatomy": event.anatomy, "expressions": event.expressions, "deltas": event.deltas,
    }),) for index, (event, size) in enumerate(zip(script.events, counts, strict=True))
        if _short(event, size)}
    if short:
        try:
            palettes, raws = await _run(
                grok, call_base, "h3_roteiro_palette", short, PALETTE_TEMPLATE, Palette)
        except (OSError, OAuthError, TimeoutError):
            raise
        except NarratorInvalid as exc:
            remember(exc.raws)
            return _invalid(outcome, "Palette response cannot complete the event lists",
                            "palette_failed")
        remember(raws)
        events = list(script.events)
        for key, palette in palettes.items():
            index = int(key.removeprefix("event-"))
            size = counts[index]
            if (not isinstance(palette, Palette) or palette.title != events[index].title
                    or any(len(distinct(getattr(palette, name))) < size
                           for name in ("anatomy", "expressions", "deltas"))):
                return _invalid(outcome, "Palette repeated items or changed the event")
            events[index] = events[index].model_copy(update={
                "anatomy": distinct(palette.anatomy)[:size],
                "expressions": distinct(palette.expressions)[:size],
                "deltas": distinct(palette.deltas)[:size],
            })
        script = script.model_copy(update={"events": events})
    outcome["scenes"] = [event.model_dump() for event in script.events]
    if save is not None:
        save(outcome)

    try:
        slots = _slots(script, counts)
        chunks = worker_chunks(slots)
        answers, raws = await _run(
            grok, call_base, "h3_roteiro_card", chunks, CARD_TEMPLATE,
            card_model([event.title for event in script.events]), _globals(script, context))
    except (OSError, OAuthError, TimeoutError):
        raise
    except ValueError as exc:
        return _invalid(outcome, str(exc))
    except NarratorInvalid as exc:
        remember(exc.raws)
        return _invalid(outcome, "Card response cannot be converted into strict block cards",
                        "prompt_failed")
    remember(raws)
    if set(answers) != set(chunks):
        return _invalid(outcome, "Card keys do not match the assigned slots")

    blocks = []
    slice_rows = []
    for slot in slots:
        card = answers[slot.id]
        if (not isinstance(card, BlockCard) or card.id != slot.id or card.title != slot.title
                or card.expression != slot.expression or card.anatomy != slot.anatomy
                or card.delta != slot.delta):
            return _invalid(outcome, "Card changed the assigned expression, body or delta")
        if not all(token in card.instruction for token in
                   (slot.expression, slot.anatomy, slot.delta)):
            return _invalid(outcome, "Instruction dropped an assigned field")
        instruction = finish_instruction(card.instruction, slot)
        if slot.owns_dialogue:
            if speech_line(slot.dialogue or "") not in instruction:
                return _invalid(outcome, "Speech placeholder was not applied")
        elif NO_SPEECH not in instruction:
            return _invalid(outcome, "Silent slot is missing the no-speech mark")
        try:
            block = Block(id=str(uuid4()),
                          action=f"{slot.title} · {slot.role} — parte {slot.part}/{slot.parts}",
                          duration_seconds=seconds, seed=seed, prompt=instruction)
        except ValueError:
            return _invalid(outcome, "Assigned cards cannot form strict planned blocks")
        blocks.append(block.model_dump())
        slice_rows.append({**slot.model_dump(), "block_id": block.id})
    outcome["blocks"] = blocks
    outcome["slices"] = slice_rows
    return outcome
