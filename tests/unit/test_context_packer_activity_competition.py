from infinity_context_core.application.context_packer import (
    _answer_support_diversity_candidates,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _competition_item(item_id: str, text: str, source_id: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.99,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "score_signals": {
                "query_expansion_reason": "activity_competition_evidence_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 5,
            },
        },
    )


def test_activity_competition_visual_answer_wins_same_source_group_family() -> None:
    generic_history = _competition_item(
        "generic_history",
        (
            "D1:17 Gina image caption: a photo from a dance competition. "
            "D1:20 Gina: My team won first place at regionals."
        ),
        "locomo:conv-fixture:session_1:D1:20:turn",
    )
    visual_answer = _competition_item(
        "visual_answer",
        (
            "D1:24 Jon: I rehearsed with a small group of dancers for a festival. "
            "D1:26 Jon: They are performing at the festival and will impress "
            "with their grace and skill."
        ),
        "locomo:conv-fixture:session_1:D1:26:turn",
    )

    candidates = _answer_support_diversity_candidates(
        [generic_history, visual_answer],
        query="What does Gina say about the dancers in the photo?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What does Gina say about the dancers in the photo?",
    )

    assert candidates[ordered[0]].item_id == "visual_answer"


def test_activity_competition_attitude_reply_wins_same_source_group_family() -> None:
    generic_festival = _competition_item(
        "generic_festival",
        "D1:24 Jon: I rehearsed with a small group of dancers for a festival.",
        "locomo:conv-fixture:session_1:D1:24:turn",
    )
    attitude_reply = _competition_item(
        "attitude_reply",
        "D1:28 Jon: Yeah, awesome! Glad to be part of it.",
        "locomo:conv-fixture:session_1:D1:28:turn",
    )

    candidates = _answer_support_diversity_candidates(
        [generic_festival, attitude_reply],
        query="What is Jon's attitude towards being part of the dance festival?",
    )
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What is Jon's attitude towards being part of the dance festival?",
    )

    assert candidates[ordered[0]].item_id == "attitude_reply"
