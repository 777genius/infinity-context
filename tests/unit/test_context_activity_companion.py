from infinity_context_core.application.context_activity_companion import (
    activity_companion_signal,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_activity_companion_signal_accepts_class_with_colleague() -> None:
    query = "Who did Riley go to yoga with?"
    boost, penalty, reason = activity_companion_signal(
        query=query,
        item=_item(
            "D4:2 Riley: I started a weekend yoga class with a colleague, "
            "and it has helped my flexibility."
        ),
        query_anchor_intent=build_query_anchor_intent(query),
    )

    assert boost > 0
    assert penalty == 0
    assert reason == "activity_companion_positive_match"


def test_activity_companion_signal_accepts_colleague_invitation_to_class() -> None:
    query = "Who did Riley go to yoga with?"
    boost, penalty, reason = activity_companion_signal(
        query=query,
        item=_item(
            "D4:3 Riley: My colleague Alex invited me to a beginner yoga class "
            "after work."
        ),
        query_anchor_intent=build_query_anchor_intent(query),
    )

    assert boost > 0
    assert penalty == 0
    assert reason == "activity_companion_positive_match"


def test_activity_companion_signal_rejects_activity_without_companion() -> None:
    query = "Who did Riley go to yoga with?"
    boost, penalty, reason = activity_companion_signal(
        query=query,
        item=_item("D4:4 Riley: Yoga helps my flexibility, so I practice daily."),
        query_anchor_intent=build_query_anchor_intent(query),
    )

    assert boost == 0
    assert penalty > 0
    assert reason == "activity_companion_missing_evidence"


def _item(text: str) -> ContextItem:
    return ContextItem(
        item_id="item",
        item_type="chunk",
        text=text,
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics=None,
    )
