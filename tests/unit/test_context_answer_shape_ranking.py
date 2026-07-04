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


def test_context_requirement_boost_prefers_exact_count_over_partial_list() -> None:
    query = "How many pets does Gina have?"
    generic = _item(
        "generic",
        score=0.711,
        text="Gina talks about pets and often helps at the local shelter.",
    )
    partial_list = _item(
        "partial_list",
        score=0.705,
        text="Gina has a rescue dog, a cat, and a turtle at home.",
    )
    exact_count = _item(
        "exact_count",
        score=0.7,
        text="Gina has three pets at home.",
    )

    boosted = apply_context_requirement_boosts(
        (generic, partial_list, exact_count),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["exact_count"].score > by_id["partial_list"].score
    assert by_id["exact_count"].score > by_id["generic"].score
    assert by_id["exact_count"].diagnostics["score_signals"][
        "context_requirement_exact_count_cardinality_boost"
    ] > 0
    assert (
        "context_requirement_exact_count_cardinality_boost"
        not in by_id["partial_list"].diagnostics["score_signals"]
    )


    vague_count = _item(
        "vague_count",
        score=0.699,
        text="Gina has several pets at home.",
    )
    vague_boosted = apply_context_requirement_boosts(
        (vague_count,),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )[0]
    assert (
        "context_requirement_exact_count_cardinality_boost"
        not in vague_boosted.diagnostics["score_signals"]
    )


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


def test_context_requirement_boost_prefers_requested_duration_unit() -> None:
    query = "How many years has Maya practiced piano?"
    wrong_unit_count = _item(
        "wrong_unit_count",
        score=0.711,
        text="Maya practiced piano for three recitals during the spring showcase.",
    )
    exact_duration = _item(
        "exact_duration",
        score=0.7,
        text="Maya has practiced piano for three years.",
    )

    boosted = apply_context_requirement_boosts(
        (wrong_unit_count, exact_duration),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["exact_duration"].score > by_id["wrong_unit_count"].score
    assert "duration_year" in by_id["exact_duration"].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ]
    assert by_id["exact_duration"].diagnostics["score_signals"][
        "context_requirement_typed_answer_unit_boost"
    ] > 0
    assert (
        "context_requirement_typed_answer_unit_boost"
        not in by_id["wrong_unit_count"].diagnostics["score_signals"]
    )


def test_context_requirement_boost_prefers_age_unit_over_distance_number() -> None:
    query = "How old is Alex?"
    wrong_unit_number = _item(
        "wrong_unit_number",
        score=0.711,
        text="Alex ran 32 miles during the charity race.",
    )
    exact_age = _item(
        "exact_age",
        score=0.7,
        text="Alex is 32 years old.",
    )

    boosted = apply_context_requirement_boosts(
        (wrong_unit_number, exact_age),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["exact_age"].score > by_id["wrong_unit_number"].score
    assert "age_year" in by_id["exact_age"].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ]
    assert "age_year" not in by_id["wrong_unit_number"].diagnostics.get(
        "provenance",
        {},
    ).get("context_requirement_matched_answer_shapes", [])


def test_context_requirement_boost_prefers_requested_quantity_unit() -> None:
    query = "How many cups of flour did Gina use?"
    wrong_unit_number = _item(
        "wrong_unit_number",
        score=0.711,
        text="Gina baked for two hours before the guests arrived.",
    )
    exact_quantity = _item(
        "exact_quantity",
        score=0.7,
        text="Gina used two cups of flour for the bread.",
    )

    boosted = apply_context_requirement_boosts(
        (wrong_unit_number, exact_quantity),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["exact_quantity"].score > by_id["wrong_unit_number"].score
    assert "quantity_cup" in by_id["exact_quantity"].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ]


def test_context_requirement_boost_prefers_requested_dollar_unit() -> None:
    query = "How many dollars did Nora spend?"
    wrong_unit_number = _item(
        "wrong_unit_number",
        score=0.701,
        text="Nora walked 12 miles after lunch.",
    )
    exact_cost = _item(
        "exact_cost",
        score=0.7,
        text="Nora spent $12 on the museum ticket.",
    )

    boosted = apply_context_requirement_boosts(
        (wrong_unit_number, exact_cost),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["exact_cost"].score > by_id["wrong_unit_number"].score
    assert "quantity_dollar" in by_id["exact_cost"].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ]


def test_context_requirement_penalizes_nearby_wrong_unit_for_price_query() -> None:
    query = "What was the deposit amount for Mia's ceramics class?"
    nearby_wrong_unit = _item(
        "nearby_wrong_unit",
        score=0.722,
        text="Mia spent 45 minutes at the ceramics class after paying the deposit.",
    )
    exact_price = _item(
        "exact_price",
        score=0.7,
        text="Mia said the ceramics class deposit was $45.",
    )

    boosted = apply_context_requirement_boosts(
        (nearby_wrong_unit, exact_price),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["exact_price"].score > by_id["nearby_wrong_unit"].score
    assert "quantity_dollar" in by_id["exact_price"].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ]
    assert by_id["nearby_wrong_unit"].diagnostics["score_signals"][
        "context_requirement_typed_answer_unit_mismatch_penalty"
    ] > 0
    assert by_id["nearby_wrong_unit"].diagnostics["provenance"][
        "context_requirement_mismatched_answer_unit_shapes"
    ] == ["duration_minute"]


def test_context_requirement_does_not_penalize_exact_unit_with_nearby_number() -> None:
    query = "What was the deposit amount for Mia's ceramics class?"
    exact_price_with_context = _item(
        "exact_price_with_context",
        score=0.7,
        text="Mia paid the $45 ceramics deposit 20 minutes before registration closed.",
    )

    (boosted,) = apply_context_requirement_boosts(
        (exact_price_with_context,),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert "quantity_dollar" in boosted.diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ]
    assert (
        "context_requirement_typed_answer_unit_mismatch_penalty"
        not in boosted.diagnostics["score_signals"]
    )


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
