"""Narrator clock and promptnest key shape. No provider and no GPU."""

from h3_backend.roteiro.narrator import (
    NO_SPEECH,
    SOUTHERN_SPEECH,
    BlockSlot,
    assign_counts,
    finish_instruction,
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
