from infinity_context_core.application.context_source_sibling_answer_evidence_repair import (
    _source_sibling_answer_continuation_hydration_requests,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_visual_referent_question_requests_next_answer_turn_hydration() -> None:
    question_turn = _answer_support_item(
        "visual_question",
        (
            "D2:8 Riley: Wow, they look impressive. "
            "Are they yours at the festival? They're so graceful."
        ),
        source_id="locomo:conv-fixture:session_2:D2:8:turn",
        reason="activity_competition_evidence_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn,),
        existing_source_ids=frozenset(),
    )

    assert requests == {
        "locomo:conv-fixture:session_2:D2:9:turn": (
            "activity_competition_evidence_bridge"
        )
    }


def test_generic_question_does_not_request_visual_referent_hydration() -> None:
    question_turn = _answer_support_item(
        "generic_question",
        "D2:8 Riley: Are they coming to dinner tonight?",
        source_id="locomo:conv-fixture:session_2:D2:8:turn",
        reason="activity_competition_evidence_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn,),
        existing_source_ids=frozenset(),
    )

    assert requests == {}


def test_broad_existing_chunk_does_not_block_focused_continuation_hydration() -> None:
    question_turn = _answer_support_item(
        "visual_question",
        (
            "D2:8 Riley: Wow, they look impressive. "
            "Are they yours at the festival? They're so graceful."
        ),
        source_id="locomo:conv-fixture:session_2:D2:8:turn",
        reason="activity_competition_evidence_bridge",
    )
    broad_chunk = _answer_support_item(
        "broad_chunk",
        (
            "D2:8 Riley: Are they yours at the festival? "
            "D2:9 Morgan: Yes, they're the ones performing at the festival."
        ),
        source_id="locomo:conv-fixture:session_2",
        reason="activity_competition_evidence_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn, broad_chunk),
        existing_source_ids=frozenset({"locomo:conv-fixture:session_2:D2:9:turn"}),
    )

    assert requests == {
        "locomo:conv-fixture:session_2:D2:9:turn": (
            "activity_competition_evidence_bridge"
        )
    }


def test_existing_focused_turn_blocks_duplicate_continuation_hydration() -> None:
    question_turn = _answer_support_item(
        "visual_question",
        (
            "D2:8 Riley: Wow, they look impressive. "
            "Are they yours at the festival? They're so graceful."
        ),
        source_id="locomo:conv-fixture:session_2:D2:8:turn",
        reason="activity_competition_evidence_bridge",
    )
    exact_answer_turn = _answer_support_item(
        "visual_answer",
        "D2:9 Morgan: Yes, they're the ones performing at the festival.",
        source_id="locomo:conv-fixture:session_2:D2:9:turn",
        reason="activity_competition_evidence_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn, exact_answer_turn),
        existing_source_ids=frozenset(
            {
                "locomo:conv-fixture:session_2:D2:8:turn",
                "locomo:conv-fixture:session_2:D2:9:turn",
            }
        ),
    )

    assert requests == {}


def test_activity_duration_question_requests_next_answer_turn_hydration() -> None:
    question_turn = _answer_support_item(
        "duration_question",
        "D4:6 Jordan: How long have you been creating art?",
        source_id="locomo:conv-fixture:session_4:D4:6:turn",
        reason="original_query",
        answer_evidence=False,
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn,),
        existing_source_ids=frozenset(),
    )

    assert requests == {
        "locomo:conv-fixture:session_4:D4:7:turn": (
            "decomposition_activity_duration"
        )
    }


def test_relationship_duration_question_does_not_request_activity_hydration() -> None:
    question_turn = _answer_support_item(
        "relationship_duration_question",
        "D4:6 Jordan: How long have you known Alex?",
        source_id="locomo:conv-fixture:session_4:D4:6:turn",
        reason="original_query",
        answer_evidence=False,
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn,),
        existing_source_ids=frozenset(),
    )

    assert requests == {}


def test_short_anaphoric_answer_requests_previous_question_context() -> None:
    answer_turn = _answer_support_item(
        "anaphoric_answer",
        "D2:9 Morgan: Yes, they are.",
        source_id="locomo:conv-fixture:session_2:D2:9:turn",
        reason="activity_competition_evidence_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (answer_turn,),
        existing_source_ids=frozenset(),
    )

    assert requests == {
        "locomo:conv-fixture:session_2:D2:8:turn": (
            "activity_competition_evidence_bridge"
        )
    }


def test_existing_focused_question_blocks_duplicate_previous_context() -> None:
    question_turn = _answer_support_item(
        "visual_question",
        "D2:8 Riley: Are they yours at the festival?",
        source_id="locomo:conv-fixture:session_2:D2:8:turn",
        reason="activity_competition_evidence_bridge",
    )
    answer_turn = _answer_support_item(
        "anaphoric_answer",
        "D2:9 Morgan: Yes, they are.",
        source_id="locomo:conv-fixture:session_2:D2:9:turn",
        reason="activity_competition_evidence_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (question_turn, answer_turn),
        existing_source_ids=frozenset(
            {
                "locomo:conv-fixture:session_2:D2:8:turn",
                "locomo:conv-fixture:session_2:D2:9:turn",
            }
        ),
    )

    assert requests == {}


def test_long_direct_answer_does_not_request_previous_question_context() -> None:
    answer_turn = _answer_support_item(
        "direct_answer",
        (
            "D2:9 Morgan: Yes, they are mine and they are performing at the "
            "festival with the group I joined last summer after training for "
            "several months."
        ),
        source_id="locomo:conv-fixture:session_2:D2:9:turn",
        reason="activity_competition_evidence_bridge",
    )

    requests = _source_sibling_answer_continuation_hydration_requests(
        (answer_turn,),
        existing_source_ids=frozenset(),
    )

    assert requests == {}


def _answer_support_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
    reason: str,
    answer_evidence: bool = True,
) -> ContextItem:
    score_signals: dict[str, object] = {
        "query_expansion_reason": reason,
    }
    if answer_evidence:
        score_signals["source_sibling_answer_evidence"] = 1
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": score_signals,
        },
    )
