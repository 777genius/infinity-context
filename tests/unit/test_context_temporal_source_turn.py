from infinity_context_core.application.context_temporal_source_turn import (
    source_turn_refs_from_item,
    source_turn_sequence_boost_signal,
    source_turn_sequence_request,
)
from infinity_context_core.application.context_temporal_source_turn_labels import (
    canonicalize_natural_source_turn_labels,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_source_turn_sequence_request_normalizes_hyphenated_turn_refs() -> None:
    request = source_turn_sequence_request("What did Sam say after D4-3?")

    assert [turn.label() for turn in request.after_turns] == ["D4:3"]
    assert request.before_turns == ()


def test_source_turn_sequence_request_normalizes_natural_turn_refs() -> None:
    assert (
        canonicalize_natural_source_turn_labels("session twelve turn four")
        == "D12:4"
    )
    assert (
        canonicalize_natural_source_turn_labels("turn fifth in session twenty first")
        == "D21:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("the 5th turn in the 12th session")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("turn 3 in the twentieth session")
        == "D20:3"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "the third turn from the thirtieth dialogue"
        )
        == "D30:3"
    )
    assert (
        canonicalize_natural_source_turn_labels("the fifth turn in the twelfth session")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "the fifth turn in the twelfth conversation"
        )
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("conversation twelve turn five")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("locomo conversation twelve turn five")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("turn five from conv twelve")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "turn five from locomo conversation twelve"
        )
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "the fourth source turn from the twelfth dialogue"
        )
        == "D12:4"
    )
    assert (
        canonicalize_natural_source_turn_labels("session twelve, fifth turn")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("dialogue twelve fifth source turn")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("turn five of the twelfth session")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "source turn five from the twelfth dialogue"
        )
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("turn five in dialogue D12")
        == "D12:5"
    )
    assert canonicalize_natural_source_turn_labels("session D12 turn five") == "D12:5"
    assert (
        canonicalize_natural_source_turn_labels("twelfth session fifth turn")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("twelfth dialogue fifth source turn")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "twelfth locomo conversation fifth source turn"
        )
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("session twelve / turn five")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("twelfth session / fifth turn")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("turn five, session twelve")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("#5 source turn, dialogue #12")
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels("fifth turn, twelfth session")
        == "D12:5"
    )
    assert canonicalize_natural_source_turn_labels("D12 T5") == "D12:5"
    assert canonicalize_natural_source_turn_labels("D12-T5") == "D12:5"
    assert canonicalize_natural_source_turn_labels("D12_T5") == "D12:5"
    assert canonicalize_natural_source_turn_labels("D12T5") == "D12:5"
    assert (
        canonicalize_natural_source_turn_labels(
            "session number twelve turn number five"
        )
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "dialogue no. 12 source turn no. 5"
        )
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "locomo conversation no. twelve source turn no. five"
        )
        == "D12:5"
    )
    assert (
        canonicalize_natural_source_turn_labels(
            "the fifth turn from session number twelve"
        )
        == "D12:5"
    )

    request = source_turn_sequence_request(
        "What did Sam say after turn four in session twelve?"
    )

    assert [turn.label() for turn in request.after_turns] == ["D12:4"]
    assert request.before_turns == ()


def test_source_turn_sequence_request_accepts_compact_dialogue_turn_refs() -> None:
    request = source_turn_sequence_request("What did Sam say after D12 T5?")

    assert [turn.label() for turn in request.after_turns] == ["D12:5"]
    assert request.before_turns == ()


def test_source_turn_sequence_boost_accepts_hyphenated_item_turn_refs() -> None:
    request = source_turn_sequence_request("What did Sam say after D4-3?")
    before = _item(
        "before",
        text="D4-2 Sam mentioned the workshop agenda.",
        source_id="locomo:conv-fixture:session_4:D4-2:turn",
    )
    after = _item(
        "after",
        text="D4-5 Sam confirmed the workshop was moved.",
        source_id="locomo:conv-fixture:session_4:D4-5:turn",
    )

    before_signal = source_turn_sequence_boost_signal(before, request=request)
    after_signal = source_turn_sequence_boost_signal(after, request=request)

    assert [turn.label() for turn in source_turn_refs_from_item(after)] == ["D4:5"]
    assert after_signal.code == "after_source_turn_match"
    assert after_signal.boost > 0
    assert before_signal.code == "after_source_turn_conflict"
    assert before_signal.boost < 0


def test_source_turn_sequence_before_accepts_hyphenated_query_turn_refs() -> None:
    request = source_turn_sequence_request("What happened before source turn D4-5?")
    before = _item(
        "before",
        text="D4:3 Sam discussed the workshop agenda.",
        source_id="locomo:conv-fixture:session_4:D4:3:turn",
    )
    after = _item(
        "after",
        text="D4:7 Sam confirmed the workshop was moved.",
        source_id="locomo:conv-fixture:session_4:D4:7:turn",
    )

    before_signal = source_turn_sequence_boost_signal(before, request=request)
    after_signal = source_turn_sequence_boost_signal(after, request=request)

    assert [turn.label() for turn in request.before_turns] == ["D4:5"]
    assert before_signal.code == "before_source_turn_match"
    assert before_signal.boost > 0
    assert after_signal.code == "before_source_turn_conflict"
    assert after_signal.boost < 0


def test_source_turn_sequence_scoped_query_rejects_bare_turn_evidence() -> None:
    request = source_turn_sequence_request(
        "What did Sam say after source ref locomo:conv-fixture:session_4:D4:3:turn?"
    )
    bare_after = _item(
        "bare_after",
        text="D4:5 Sam confirmed the workshop was moved.",
        source_id="manual-note",
    )

    signal = source_turn_sequence_boost_signal(bare_after, request=request)

    assert signal.empty


def test_source_turn_sequence_unscoped_query_accepts_scoped_turn_evidence() -> None:
    request = source_turn_sequence_request("What did Sam say after D4:3?")
    scoped_after = _item(
        "scoped_after",
        text="Sam confirmed the workshop was moved.",
        source_id="locomo:conv-fixture:session_4:D4:5:turn",
    )

    signal = source_turn_sequence_boost_signal(scoped_after, request=request)

    assert signal.code == "after_source_turn_match"
    assert signal.boost > 0


def test_source_turn_refs_from_item_normalize_natural_turn_evidence() -> None:
    item = _item(
        "natural_turn_evidence",
        text="Session twelve turn five: Sam confirmed the workshop was moved.",
        source_id="locomo:conv-fixture:session_12",
    )

    assert [turn.label() for turn in source_turn_refs_from_item(item)] == ["D12:5"]


def test_source_turn_refs_from_item_normalize_numbered_natural_turn_evidence() -> None:
    item = _item(
        "numbered_natural_turn_evidence",
        text="Session no. twelve turn no. five: Sam confirmed the workshop.",
        source_id="locomo:conv-fixture:session_12",
    )

    assert [turn.label() for turn in source_turn_refs_from_item(item)] == ["D12:5"]


def test_source_turn_refs_from_item_normalize_hash_prefixed_turn_evidence() -> None:
    item = _item(
        "hash_prefixed_turn_evidence",
        text="#5 source turn, dialogue #12: Sam confirmed the workshop.",
        source_id="locomo:conv-fixture:session_12",
    )

    assert [turn.label() for turn in source_turn_refs_from_item(item)] == ["D12:5"]


def test_source_turn_refs_from_item_normalize_compact_dialogue_turn_evidence() -> None:
    item = _item(
        "compact_turn_evidence",
        text="D12 T5: Sam confirmed the workshop was moved.",
        source_id="locomo:conv-fixture:session_12",
    )

    assert [turn.label() for turn in source_turn_refs_from_item(item)] == ["D12:5"]


def test_source_turn_refs_from_item_uses_conversation_structured_metadata() -> None:
    item = ContextItem(
        item_id="structured_conversation_turn",
        item_type="chunk",
        text="Sam confirmed the workshop was moved.",
        score=0.7,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="summary"),),
        diagnostics={
            "metadata": {
                "conversation_id": "conv_12",
                "turn_id": 5,
            },
        },
    )

    assert [turn.label() for turn in source_turn_refs_from_item(item)] == ["D12:5"]


def test_source_turn_refs_from_item_uses_written_structured_metadata() -> None:
    item = ContextItem(
        item_id="structured_written_conversation_turn",
        item_type="chunk",
        text="Sam confirmed the workshop was moved.",
        score=0.7,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="summary"),),
        diagnostics={
            "metadata": {
                "conversation_id": "conv twelve",
                "turn_id": "turn fifth",
            },
        },
    )

    assert [turn.label() for turn in source_turn_refs_from_item(item)] == ["D12:5"]


def test_source_turn_refs_from_item_uses_numbered_structured_metadata() -> None:
    item = ContextItem(
        item_id="structured_numbered_dialogue_turn",
        item_type="chunk",
        text="Sam confirmed the workshop was moved.",
        score=0.7,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="summary"),),
        diagnostics={
            "metadata": {
                "dialogue_id": "dialogue no. twelve",
                "turn_id": "turn no. five",
            },
        },
    )

    assert [turn.label() for turn in source_turn_refs_from_item(item)] == ["D12:5"]


def _item(item_id: str, *, text: str, source_id: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.7,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "provenance": {
                "fact_status": "active",
                "source_id": source_id,
            }
        },
    )
