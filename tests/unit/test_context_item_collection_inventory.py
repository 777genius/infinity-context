from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_diversity_family,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance
from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_query_expansion_routes_item_collection_lists_to_item_inventory() -> None:
    plan = build_query_expansion_plan("What items does Riley collect?")

    expansion = _expansion_query(plan, "item_purchase_bridge")

    assert "collection collect collects collecting" in expansion
    assert "sneakers shoes jerseys movies movie dvds dvd" in expansion
    assert "visual query image caption photo" in expansion


def test_item_collection_evidence_accepts_possession_and_visual_collection_shapes() -> None:
    cases = (
        "D1:15 Riley: I love talking about my sneaker collection.",
        "D12:18 Riley: I like to collect jerseys.",
        (
            "D27:20 Riley image caption: a photo of a collection of fantasy "
            "movies and DVDs on a table."
        ),
    )

    for text in cases:
        assert has_item_purchase_object_evidence(text)


def test_best_query_relevance_uses_item_inventory_for_collected_items() -> None:
    plan = build_query_expansion_plan("What items does Riley collect?")
    cases = (
        "D1:15 Riley: I love talking about my sneaker collection.",
        "D12:18 Riley: I like to collect jerseys.",
        (
            "D27:20 Riley image caption: a photo of a collection of fantasy "
            "movies and DVDs on a table."
        ),
    )

    for text in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "item_purchase_bridge"
        assert relevance.distinctive_term_hits >= 3


def test_source_sibling_answer_evidence_accepts_direct_item_collection_turns() -> None:
    expansion_query = _expansion_query(
        build_query_expansion_plan("What items does Riley collect?"),
        "item_purchase_bridge",
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="item_purchase_bridge",
        text="D1:15 Riley: I love talking about my sneaker collection.",
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="item_purchase_bridge",
        text="D12:18 Riley: I like to collect jerseys.",
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="item_purchase_bridge",
        text=(
            "D27:20 Riley image caption: a photo of a collection of fantasy "
            "movies and DVDs on a table."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="item_purchase_bridge",
        text="D8:3 Riley: I bought a snack after the trip.",
    )


def test_item_collection_inventory_splits_slots_and_keeps_exact_turns() -> None:
    sneakers = _answer_support_item(
        "sneakers",
        "D1:15 Riley: I love talking about my sneaker collection.",
        source_id="locomo:conv-fixture:session_1:D1:15:turn",
    )
    jerseys = _answer_support_item(
        "jerseys",
        "D12:18 Riley: I like to collect jerseys.",
        source_id="locomo:conv-fixture:session_12:D12:18:turn",
    )
    movies = _answer_support_item(
        "movies",
        (
            "D27:20 Riley: These fantasy movies are mine.\n"
            "image caption: a photo of a collection of DVDs on a table."
        ),
        source_id="locomo:conv-fixture:session_27:D27:20:turn",
    )
    noise = tuple(
        _answer_support_item(
            f"noise_{index}",
            f"D{index}:1 Riley talked about collectibles without naming an item.",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
        )
        for index in range(30, 36)
    )

    families = {
        _answer_support_diversity_family(item) for item in (sneakers, jerseys, movies)
    }
    result = ContextPacker().pack(
        bundle_id="ctx_item_collections",
        items=(*noise, sneakers, jerseys, movies),
        token_budget=280,
        query="What items does Riley collect?",
        max_rendered_chars=1500,
    )
    rendered = result.bundle.rendered_text

    assert any(":item-purchase-shoes:" in family for family in families)
    assert any(":item-purchase-jerseys:" in family for family in families)
    assert any(":item-purchase-media:" in family for family in families)
    assert "sneaker collection" in rendered
    assert "collect jerseys" in rendered
    assert "collection of DVDs" in rendered


def _expansion_query(plan: QueryExpansionPlan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion {reason}")


def _answer_support_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "source_type": "locomo_turn",
            "source_id": source_id,
            "score_signals": {
                "query_expansion_reason": "item_purchase_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 6,
            },
        },
    )
