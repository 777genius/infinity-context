from __future__ import annotations

from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import apply_context_requirement_boosts
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_context_requirement_boost_uses_russian_count_words() -> None:
    query = "Сколько питомцев у Гины?"
    generic = _item(
        "generic",
        score=0.71,
        text="Гина любит питомцев и часто помогает в приюте.",
    )
    count_evidence = _item(
        "count_evidence",
        score=0.7,
        text="Гина заботится о двух питомцах: собаке и кошке.",
    )

    boosted = apply_context_requirement_boosts(
        (generic, count_evidence),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["count_evidence"].score > by_id["generic"].score
    assert by_id["count_evidence"].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["count"]


def test_context_requirement_boost_treats_who_are_group_queries_as_lists() -> None:
    query = "Who are the collaborators on Project Atlas?"
    generic = _item(
        "generic",
        score=0.71,
        text="Project Atlas collaboration notes mention planning work.",
    )
    list_evidence = _item(
        "list_evidence",
        score=0.7,
        text="Alex, Priya, and Morgan were collaborators on Project Atlas.",
    )

    boosted = apply_context_requirement_boosts(
        (generic, list_evidence),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["list_evidence"].score > by_id["generic"].score
    assert by_id["list_evidence"].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["list"]


def test_context_requirement_coverage_keeps_who_is_summary_out_of_list_shape() -> None:
    query = "Who is Alex?"

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(),
    )

    assert "list" not in coverage["requested_answer_shapes"]


def _item(item_id: str, *, score: float, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )
