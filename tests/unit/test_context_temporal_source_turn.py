from infinity_context_core.application.context_temporal_source_turn import (
    source_turn_refs_from_item,
    source_turn_sequence_boost_signal,
    source_turn_sequence_request,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_source_turn_sequence_request_normalizes_hyphenated_turn_refs() -> None:
    request = source_turn_sequence_request("What did Sam say after D4-3?")

    assert [turn.label() for turn in request.after_turns] == ["D4:3"]
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
