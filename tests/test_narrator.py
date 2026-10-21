"""Narrator clock, palette bound, promptnest key shape and first request. No provider, no GPU."""

import json

import pytest
from pydantic import ValidationError

from h3_backend.roteiro.narrator import (
    NARRATOR_SYSTEM,
    NO_SPEECH,
    PALETTE_CAPACITY,
    SOUTHERN_SPEECH,
    BlockCard,
    BlockSlot,
    Palette,
    Script,
    _slots,
    assign_counts,
    card_marks_error,
    finish_instruction,
    script_request,
    speech_line,
    worker_chunks,
)


def test_worker_dict_is_one_key_and_one_fragment_per_slot():
    slots = [
        BlockSlot(id=f"slot-{i}", index=i, event_index=0, title="Sala", intent="anda",
                  role="do", part=i, parts=3, expression=f"e{i}", anatomy=f"a{i}",
                  delta=f"d{i}", camera_focus=None, owns_dialogue=False, dialogue=None)
        for i in range(1, 4)
    ]
    chunks = worker_chunks(slots)
    assert list(chunks) == ["slot-1", "slot-2", "slot-3"]
    assert all(len(fragments) == 1 and isinstance(fragments[0], str) for fragments in chunks.values())
    collapsed = {"filme": tuple(fragments[0] for fragments in chunks.values())}
    assert len(collapsed) == 1 and len(collapsed["filme"]) == 3


def test_clock_caps_an_event_and_keeps_requested_duration_budget():
    counts = assign_counts(4, 200)
    assert sum(counts) == 200
    assert all(count >= 2 for count in counts)
    assert max(counts) > 12  # leftover is hold/approach, not a new act


def test_one_event_never_asks_the_palette_for_more_than_a_list_holds():
    # 100-200 blocks stay inside a single palette list; the model rejects more items.
    assert PALETTE_CAPACITY == 200
    assert assign_counts(1, 100) == [100]
    assert assign_counts(1, PALETTE_CAPACITY) == [PALETTE_CAPACITY]
    assert assign_counts(1, PALETTE_CAPACITY + 1) == [PALETTE_CAPACITY + 1]
    with pytest.raises(ValidationError):
        Palette(title="Sala", anatomy=[f"a{n}" for n in range(PALETTE_CAPACITY + 1)],
                expressions=["olhar"], deltas=["peso"])


def test_speech_placeholder_is_code_owned_and_other_slots_stay_silent():
    spoken = BlockSlot(id="slot-1", index=1, event_index=0, title="Sala", intent="fala",
                       role="do", part=1, parts=2, expression="olhar", anatomy="vestido",
                       delta="peso", camera_focus=None, owns_dialogue=True, dialogue="Oi, guris")
    silent = spoken.model_copy(update={"id": "slot-2", "index": 2, "part": 2,
                                       "owns_dialogue": False, "dialogue": None})
    body = "Ação: fala\nCorpo: vestido\nExpressão: olhar\nMudança em relação ao anterior: peso"
    said = finish_instruction(body, spoken)
    quiet = finish_instruction(body, silent)
    assert SOUTHERN_SPEECH.format(line="Oi, guris") in said
    assert NO_SPEECH in quiet and "Oi, guris" not in quiet


def test_script_request_is_the_prompt_the_chain_really_sends():
    context = {"idea": "ela sorri", "name": "live"}
    request = script_request({"system_prompt": "ignored", "model": "pinned"}, context, 16, 8.0)
    assert request.system_prompt == NARRATOR_SYSTEM
    assert request.model == "pinned"
    payload = json.loads(request.prompt.split("Payload:\n", 1)[1])
    assert payload == {"block_count": 16, "block_seconds": 8.0, "context": context}


def test_a_requested_line_is_owned_by_one_slot_even_if_two_events_repeat_it():
    def event(title, dialogue, prefix):
        return {"title": title, "kind": "speech", "intent": "fala", "dialogue": dialogue,
                "anatomy": [f"{prefix} corpo {n}" for n in (1, 2)],
                "expressions": [f"{prefix} olhar {n}" for n in (1, 2)],
                "deltas": [f"{prefix} peso {n}" for n in (1, 2)],
                "camera_focus": None, "keeps": []}

    script = Script.model_validate({"name": "Um", "summary": "eco", "events": [
        event("Sala", "Oi, guris", "a"), event("Varanda", "  Oi, guris  ", "b")]})
    slots = _slots(script, [2, 2])
    owners = [slot for slot in slots if slot.owns_dialogue]
    # The repeated line would otherwise be spoken twice, which is the duplication the owner hears.
    assert [slot.title for slot in owners] == ["Sala"] and owners[0].dialogue == "Oi, guris"
    assert all(slot.dialogue is None for slot in slots if not slot.owns_dialogue)


def test_a_card_cannot_write_the_camera_or_a_speech_line_of_its_own():
    slot = BlockSlot(id="slot-1", index=1, event_index=0, title="Sala", intent="anda",
                     role="do", part=1, parts=2, expression="olhar", anatomy="vestido",
                     delta="peso", camera_focus=None, owns_dialogue=False, dialogue=None)

    def card(text):
        return BlockCard(id="slot-1", title="Sala", expression="olhar", anatomy="vestido",
                         delta="peso", instruction=text)

    body = "Ação: anda\nCorpo: vestido\nExpressão: olhar\nMudança em relação ao anterior: peso"
    assert card_marks_error(card(body), slot) is None
    assert card_marks_error(card(body + "\nCâmera: plano fechado"), slot) == (
        "Card wrote its own camera instead of the assigned one")
    assert card_marks_error(card(body + "\n" + speech_line("bom dia")), slot) == (
        "Card wrote a speech line the code did not assign")
    # The owning slot may reproduce exactly the line the code assigned to it.
    owner = slot.model_copy(update={"owns_dialogue": True, "dialogue": "Oi, guris"})
    assert card_marks_error(card(body + "\n" + speech_line("Oi, guris")), owner) is None
    assert card_marks_error(card(body + "\n" + speech_line("outra fala")), owner) is not None
