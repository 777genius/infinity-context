from dataclasses import replace

import infinity_context_core.application.context_ranking as context_ranking_module
from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_bm25_lexical_boosts,
    apply_context_requirement_boosts,
    apply_deterministic_rerank_adjustments,
    apply_keyword_chunk_source_score_boost,
    apply_query_anchor_intent_boosts,
    apply_query_plan_bm25_lexical_boosts,
    apply_rank_fusion_boosts,
    best_query_relevance,
    dedupe_rank_items,
    keyword_chunk_score,
    keyword_chunk_source_score_boost,
    query_expansion_reason_priority,
    reciprocal_rank_fusion_scores,
)
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_reciprocal_rank_fusion_scores_combine_ordered_sources() -> None:
    top = _item("top", score=0.8, retrieval_source="keyword_chunks")
    mid = _item("mid", score=0.7, retrieval_source="keyword_chunks")
    low = _item("low", score=0.6, retrieval_source="keyword_chunks")

    scores = reciprocal_rank_fusion_scores(
        {
            "keyword_chunks": (top, mid, low),
            "vector_chunks": (top, low, mid),
        }
    )

    assert scores[("chunk", "top")] > scores[("chunk", "mid")]
    assert scores[("chunk", "top")] > scores[("chunk", "low")]


def test_reciprocal_rank_fusion_deduplicates_within_source() -> None:
    top = _item("top", score=0.8, retrieval_source="keyword_chunks")
    low = _item("low", score=0.6, retrieval_source="keyword_chunks")

    duplicate_scores = reciprocal_rank_fusion_scores({"keyword_chunks": (top, top, low)})
    unique_scores = reciprocal_rank_fusion_scores({"keyword_chunks": (top, low)})

    assert duplicate_scores[("chunk", "top")] == unique_scores[("chunk", "top")]


def test_rank_fusion_boost_requires_multiple_retrieval_sources() -> None:
    only_keyword = (
        _item("top", score=0.8, retrieval_source="keyword_chunks"),
        _item("low", score=0.6, retrieval_source="keyword_chunks"),
    )

    boosted = apply_rank_fusion_boosts(only_keyword)

    assert boosted == only_keyword


def test_rank_fusion_boosts_multi_source_candidates_with_diagnostics() -> None:
    keyword_top = _item("shared", score=0.8, retrieval_source="keyword_chunks")
    keyword_low = _item("keyword_low", score=0.6, retrieval_source="keyword_chunks")
    vector_top = _item("shared", score=0.82, retrieval_source="vector_chunks")
    vector_low = _item("vector_low", score=0.61, retrieval_source="vector_chunks")

    boosted = apply_rank_fusion_boosts(
        (keyword_top, keyword_low, vector_top, vector_low),
        max_boost=0.04,
    )

    shared_keyword = boosted[0]
    shared_vector = boosted[2]
    assert shared_keyword.score > keyword_top.score
    assert shared_vector.score > vector_top.score
    assert shared_keyword.score <= keyword_top.score + 0.04
    assert shared_keyword.diagnostics["score_signals"]["rank_fusion_boost"] <= 0.04
    assert shared_keyword.diagnostics["provenance"]["rank_fusion_applied"] is True


def test_rank_fusion_weights_evidence_sources_by_default() -> None:
    artifact = _item("artifact", score=0.7, retrieval_source="artifact_evidence")
    keyword = _item("keyword", score=0.7, retrieval_source="keyword_chunks")

    boosted = apply_rank_fusion_boosts((artifact, keyword), max_boost=0.04)

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["score_signals"]["rank_fusion_source_weighted"] is True
    assert boosted[0].diagnostics["provenance"]["rank_fusion_source_weighted"] is True


def test_rank_fusion_counts_all_sources_on_hybrid_candidate() -> None:
    hybrid = _item(
        "hybrid",
        score=0.7,
        retrieval_source="keyword_chunks",
        retrieval_sources=("keyword_chunks", "vector_chunks"),
    )
    keyword = _item("keyword", score=0.69, retrieval_source="keyword_chunks")

    boosted = apply_rank_fusion_boosts((hybrid, keyword), max_boost=0.04)

    assert boosted[0].score > hybrid.score
    assert boosted[0].diagnostics["score_signals"]["rank_fusion_source_count"] == 2
    assert boosted[0].diagnostics["provenance"]["rank_fusion_source_count"] == 2


def test_rank_fusion_prefers_multi_signal_entity_temporal_evidence() -> None:
    hybrid = _item(
        "hybrid",
        score=0.7,
        retrieval_source="keyword_chunks",
        retrieval_sources=("keyword_chunks", "vector_chunks", "canonical_anchors"),
        text="Alex discussed Atlas after the launch review.",
    )
    lexical_only = _item(
        "lexical_only",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="Alex mentioned Atlas in a broad note.",
    )

    boosted = apply_rank_fusion_boosts((hybrid, lexical_only), max_boost=0.045)

    assert boosted[0].score > boosted[1].score
    assert (
        boosted[0].diagnostics["score_signals"]["rank_fusion_boost"]
        > boosted[1].diagnostics["score_signals"]["rank_fusion_boost"]
    )
    assert boosted[0].diagnostics["score_signals"]["rank_fusion_source_weighted"] is True
    assert boosted[0].diagnostics["provenance"]["rank_fusion_source_weighted"] is True


def test_rank_fusion_does_not_apply_twice_to_same_candidate() -> None:
    keyword_top = _item("shared", score=0.8, retrieval_source="keyword_chunks")
    keyword_low = _item("keyword_low", score=0.6, retrieval_source="keyword_chunks")
    vector_top = _item("shared", score=0.82, retrieval_source="vector_chunks")

    first_pass = apply_rank_fusion_boosts(
        (keyword_top, keyword_low, vector_top),
        max_boost=0.04,
    )
    second_pass = apply_rank_fusion_boosts(first_pass, max_boost=0.04)

    assert second_pass[0].score == first_pass[0].score
    assert second_pass[2].score == first_pass[2].score


def test_bm25_lexical_boost_prefers_precise_multi_term_candidate() -> None:
    precise = _item(
        "precise",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex approved the Atlas launch checklist.",
    )
    loose = _item(
        "loose",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Alex discussed many unrelated launch ideas and launch notes, "
            "but there was no checklist reference."
        ),
    )

    boosted = apply_bm25_lexical_boosts(
        (precise, loose),
        query="Alex Atlas launch checklist",
        max_boost=0.04,
    )

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["score_signals"]["bm25_lexical_boost"] <= 0.04
    assert boosted[0].diagnostics["score_signals"]["bm25_lexical_matched_term_count"] == 4
    assert boosted[0].diagnostics["provenance"]["bm25_lexical_applied"] is True


def test_bm25_lexical_boost_skips_queries_without_terms() -> None:
    item = _item("only", score=0.7, retrieval_source="keyword_chunks")

    boosted = apply_bm25_lexical_boosts((item,), query="what and where")

    assert boosted == (item,)


def test_bm25_lexical_boost_does_not_apply_twice() -> None:
    first = _item(
        "first",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex approved the Atlas launch checklist.",
    )
    second = _item(
        "second",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="The billing export finished after lunch.",
    )

    first_pass = apply_bm25_lexical_boosts(
        (first, second),
        query="Alex Atlas launch checklist",
    )
    second_pass = apply_bm25_lexical_boosts(
        first_pass,
        query="Alex Atlas launch checklist",
    )

    assert second_pass[0].score == first_pass[0].score


def test_query_plan_bm25_lexical_boost_uses_best_decomposed_query() -> None:
    artifact = _item(
        "artifact",
        score=0.7,
        retrieval_source="artifact_evidence",
        text="Screenshot OCR detected text: Atlas launch deadline moved after Alex call.",
    )
    decoy = _item(
        "decoy",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex and Atlas were mentioned in a broad planning note.",
    )
    plan = build_query_expansion_plan(
        "What changed after the call with Alex about Atlas and what was written in the screenshot?"
    )

    boosted = apply_query_plan_bm25_lexical_boosts(
        (artifact, decoy),
        plan=plan,
        max_boost=0.04,
    )

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["score_signals"]["bm25_lexical_query_reason"] == (
        "decomposition_artifact_evidence"
    )
    assert boosted[0].diagnostics["provenance"]["bm25_lexical_query_reason"] == (
        "decomposition_artifact_evidence"
    )


def test_query_plan_bm25_lexical_boost_reuses_shared_term_frequencies(
    monkeypatch,
) -> None:
    items = (
        _item(
            "first",
            score=0.7,
            retrieval_source="keyword_chunks",
            text="Alex moved the Atlas launch deadline after the call.",
        ),
        _item(
            "second",
            score=0.7,
            retrieval_source="keyword_chunks",
            text="Alex wrote a broad planning note about Atlas.",
        ),
    )
    plan = QueryExpansionPlan(
        original_query="Alex Atlas",
        decompositions=(
            QueryExpansion(query="Alex launch deadline", reason="decomposition_temporal_answer"),
        ),
        expansions=(
            QueryExpansion(query="Alex call notes", reason="meeting_evidence_bridge"),
            QueryExpansion(query="Alex Atlas project", reason="project_summary_bridge"),
        ),
    )
    real_query_term_frequency = context_ranking_module.query_term_frequency
    calls: list[str] = []

    def counting_query_term_frequency(term, text_counts):
        calls.append(term.raw)
        return real_query_term_frequency(term, text_counts)

    monkeypatch.setattr(
        context_ranking_module,
        "query_term_frequency",
        counting_query_term_frequency,
    )

    apply_query_plan_bm25_lexical_boosts(
        items,
        plan=plan,
        bm25_text_stats_cache={},
    )

    assert calls.count("alex") == len(items)


def test_query_plan_bm25_and_relevance_share_cached_expansion_terms(monkeypatch) -> None:
    items = (
        _item(
            "first",
            score=0.7,
            retrieval_source="keyword_chunks",
            text="Alex moved the Atlas launch deadline after the call.",
        ),
        _item(
            "second",
            score=0.7,
            retrieval_source="keyword_chunks",
            text="Alex wrote a broad planning note about Atlas.",
        ),
    )
    plan = QueryExpansionPlan(
        original_query="Alex Atlas",
        decompositions=(
            QueryExpansion(query="Alex launch deadline", reason="decomposition_temporal_answer"),
        ),
        expansions=(
            QueryExpansion(query="Alex call notes", reason="meeting_evidence_bridge"),
            QueryExpansion(query="Alex Atlas project", reason="project_summary_bridge"),
        ),
    )
    real_query_terms = context_ranking_module.query_terms
    calls: list[str] = []

    def counting_query_terms(query: str, *, min_chars: int = 2):
        calls.append(query)
        return real_query_terms(query, min_chars=min_chars)

    context_ranking_module._query_expansion_terms_for_signature.cache_clear()
    monkeypatch.setattr(context_ranking_module, "query_terms", counting_query_terms)

    try:
        apply_query_plan_bm25_lexical_boosts(
            items,
            plan=plan,
            bm25_text_stats_cache={},
        )
        _, _, relevance = best_query_relevance(
            plan,
            text="Alex moved the Atlas launch deadline after the call.",
        )
    finally:
        context_ranking_module._query_expansion_terms_for_signature.cache_clear()

    assert calls == [expansion.query for expansion in plan.retrieval_queries]
    assert relevance.unique_term_hits >= 2


def test_best_query_relevance_reuses_text_variant_profile(monkeypatch) -> None:
    text = "Alex moved the Atlas launch deadline after the call."
    plan = QueryExpansionPlan(
        original_query="Alex Atlas",
        decompositions=(
            QueryExpansion(query="Alex launch deadline", reason="decomposition_temporal_answer"),
        ),
        expansions=(
            QueryExpansion(query="Alex call notes", reason="meeting_evidence_bridge"),
            QueryExpansion(query="Alex Atlas project", reason="project_summary_bridge"),
        ),
    )
    real_text_variant_profile = context_ranking_module.text_variant_profile
    calls: list[str] = []

    def counting_text_variant_profile(value: str, *, min_chars: int = 2):
        calls.append(value)
        return real_text_variant_profile(value, min_chars=min_chars)

    monkeypatch.setattr(
        context_ranking_module,
        "text_variant_profile",
        counting_text_variant_profile,
    )

    _, _, relevance = best_query_relevance(plan, text=text)

    assert calls == [text]
    assert relevance.unique_term_hits >= 2


def test_best_query_relevance_reuses_query_terms_for_plan(monkeypatch) -> None:
    plan = QueryExpansionPlan(
        original_query="Alex Atlas",
        decompositions=(
            QueryExpansion(query="Alex launch deadline", reason="decomposition_temporal_answer"),
        ),
        expansions=(
            QueryExpansion(query="Alex call notes", reason="meeting_evidence_bridge"),
            QueryExpansion(query="Alex Atlas project", reason="project_summary_bridge"),
        ),
    )
    real_query_terms = context_ranking_module.query_terms
    calls: list[str] = []

    def counting_query_terms(query: str, *, min_chars: int = 2):
        calls.append(query)
        return real_query_terms(query, min_chars=min_chars)

    context_ranking_module._query_expansion_terms_for_signature.cache_clear()
    monkeypatch.setattr(context_ranking_module, "query_terms", counting_query_terms)

    try:
        first = best_query_relevance(
            plan,
            text="Alex moved the Atlas launch deadline after the call.",
        )
        second = best_query_relevance(
            plan,
            text="Alex wrote separate Atlas project notes yesterday.",
        )
    finally:
        context_ranking_module._query_expansion_terms_for_signature.cache_clear()

    assert calls == [expansion.query for expansion in plan.retrieval_queries]
    assert first[2].unique_term_hits >= 2
    assert second[2].unique_term_hits >= 2


def test_keyword_chunk_score_boosts_item_purchase_reason() -> None:
    plan = build_query_expansion_plan("What items has Melanie bought?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D19:2 Melanie bought family figurines yesterday and D7:18 Melanie got some new shoes."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "item_purchase_bridge"
    assert score >= 0.88


def test_keyword_chunk_score_boosts_temporal_figurine_purchase_reason() -> None:
    plan = build_query_expansion_plan("When did Melanie buy the figurines?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D19:2 Melanie: These figurines I bought yesterday remind me of "
            "family love. image caption: wooden dolls on a shelf."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "item_purchase_bridge"
    assert score >= 0.88


def test_deterministic_rerank_prefers_item_purchase_object_over_temporal_visual_noise() -> None:
    query = "When did Melanie buy the figurines?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    purchase_evidence = _item(
        "figurine_purchase",
        score=0.8914,
        retrieval_source="keyword_chunks",
        text=(
            "D19:2 Melanie: These figurines I bought yesterday remind me of "
            "family love. image caption: wooden dolls on a shelf."
        ),
        score_signals={"query_expansion_reason": "item_purchase_bridge"},
    )
    temporal_visual_noise = _item(
        "temporal_visual_noise",
        score=0.99,
        retrieval_source="keyword_chunks",
        text=(
            "D14:3 Caroline talked yesterday. image caption: people smiling "
            "near a family picture."
        ),
        score_signals={"query_expansion_reason": "item_purchase_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (temporal_visual_noise, purchase_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["figurine_purchase"].score > by_id["temporal_visual_noise"].score
    assert (
        "item_purchase_object_evidence"
        in by_id["figurine_purchase"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "item_purchase_temporal_weak_evidence"
        in by_id["temporal_visual_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_context_rank_key_prefers_item_purchase_object_signal() -> None:
    purchase_evidence = _item(
        "figurine_purchase",
        score=0.99,
        retrieval_source="keyword_chunks",
        text="D19:2 Melanie bought family figurines yesterday.",
        score_signals={"item_purchase_object_evidence": 3.0},
    )
    temporal_visual_noise = _item(
        "temporal_visual_noise",
        score=0.99,
        retrieval_source="keyword_chunks",
        text="D14:3 Caroline talked yesterday beside a family picture.",
    )

    assert context_rank_key(purchase_evidence) < context_rank_key(temporal_visual_noise)


def test_keyword_chunk_score_boosts_event_participation_bridge() -> None:
    plan = build_query_expansion_plan("What events has Caroline participated in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline participated in LGBTQ community advocacy campaigns and "
            "joined a youth mentorship program."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "event_participation_bridge"
    assert score >= 0.88


def test_keyword_chunk_score_boosts_lgbtq_pride_event_slot() -> None:
    plan = build_query_expansion_plan("What LGBTQ+ events has Caroline participated in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D5:1 Caroline went to an LGBTQ pride parade, felt happy, and "
            "belonged in the community."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "decomposition_lgbtq_pride_event"
    assert score >= 0.89


def test_keyword_chunk_score_boosts_lgbtq_support_group_event_slot() -> None:
    plan = build_query_expansion_plan("What LGBTQ+ events has Caroline participated in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D1:3 Caroline attended an LGBTQ support group and found the "
            "transgender stories powerful."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "decomposition_lgbtq_support_group_event"
    assert score >= 0.89


def test_keyword_chunk_score_boosts_hike_count_activity_bridge() -> None:
    plan = build_query_expansion_plan("How many hikes has Joanna been on?")

    for text in (
        "D7:6 Joanna saw a gorgeous sunset while hiking the other day.",
        "D11:5 Joanna loved this spot on the hike. The rush of the waterfall was soothing.",
        "D14:19 Joanna is hiking with buddies this weekend on a new trail with a waterfall.",
        "D28:22 Joanna took that pic on a hike last summer near Fort Wayne.",
    ):
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == "hike_count_activity_bridge"
        assert score >= 0.865


def test_keyword_chunk_score_boosts_beach_count_activity_bridge() -> None:
    plan = build_query_expansion_plan("How many times has Melanie gone to the beach in 2023?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D10:8 Melanie image query: beach family playing frisbee sandy shore. "
            "Melanie: We went to the beach recently and the kids had a blast."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "beach_count_activity_bridge"
    assert score >= 0.9


def test_deterministic_rerank_prefers_count_aggregation_over_single_mention() -> None:
    query = "How many times has Melanie gone to the beach in 2023?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    single_mention = _item(
        "single_beach",
        score=0.81,
        retrieval_source="keyword_chunks",
        text="Melanie went to the beach recently and the kids had a blast.",
    )
    aggregation = _item(
        "aggregation_beach",
        score=0.7,
        retrieval_source="keyword_aggregation_chunks",
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id="doc:session_1:D1:2:turn"),
            SourceRef(source_type="locomo_turn", source_id="doc:session_4:D4:7:turn"),
            SourceRef(source_type="locomo_turn", source_id="doc:session_8:D8:3:turn"),
        ),
        text=(
            "D1:2 Melanie went to the beach in March. "
            "D4:7 Melanie went to the beach again in July. "
            "D8:3 She visited the beach one more time in September."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (single_mention, aggregation),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["aggregation_beach"].score > by_id["single_beach"].score
    assert (
        "aggregation_multi_evidence"
        in by_id["aggregation_beach"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "aggregation_single_evidence_noise"
        in by_id["single_beach"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_business_commonality_origin_evidence() -> None:
    query = "What do Jon and Gina both have in common?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    origin = _item(
        "gina_business_origin",
        score=0.94,
        retrieval_source="keyword_chunks",
        score_signals={"query_expansion_reason": "business_commonality_bridge"},
        text=(
            "D2:1 Gina launched an ad campaign for her clothing store in hopes "
            "of growing the business. Starting my own store and taking risks is "
            "both scary and rewarding."
        ),
    )
    late_update = _item(
        "late_business_update",
        score=0.96,
        retrieval_source="keyword_source_sibling_chunks",
        score_signals={"query_expansion_reason": "business_commonality_bridge"},
        text=(
            "D18:2 Jon: Hey Gina, congrats on the clothing store! The dance "
            "studio is on tenuous grounds right now, but I'm staying positive."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (late_update, origin),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["gina_business_origin"].score > by_id["late_business_update"].score
    assert (
        "business_commonality_origin_evidence"
        in by_id["gina_business_origin"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "business_commonality_weak_update"
        in by_id["late_business_update"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_treats_charity_brand_deals_as_exact_evidence() -> None:
    query = "What prominent charity organization might Jordan work with and why?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    brand_deals = _item(
        "brand_deals",
        score=0.92,
        retrieval_source="keyword_chunks",
        score_signals={"query_expansion_reason": "charity_brand_sponsorship_bridge"},
        text=(
            "D3:13 Jordan signed up TrailCore for a basketball shoe and gear deal "
            "and is in talks with HydraFuel about a potential sponsorship. "
            "D3:15 Jordan has always liked SummitGear and working with them "
            "would be really cool."
        ),
    )
    weak_update = _item(
        "weak_update",
        score=0.93,
        retrieval_source="keyword_chunks",
        score_signals={"query_expansion_reason": "charity_brand_sponsorship_bridge"},
        text="Jordan mentioned a general planning update about basketball brands.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (weak_update, brand_deals),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["brand_deals"].score > by_id["weak_update"].score
    assert (
        "causal_reason_exact_evidence"
        in by_id["brand_deals"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_list_aggregation_over_single_mention() -> None:
    query = "What shelters does Maria volunteer at?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    single_mention = _item(
        "single_shelter",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="D2:1 Maria volunteers at the homeless shelter every weekend.",
        score_signals={"query_expansion_reason": "decomposition_inventory_list"},
    )
    aggregation = _item(
        "aggregation_shelters",
        score=0.71,
        retrieval_source="keyword_aggregation_chunks",
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id="doc:session_2:D2:1:turn"),
            SourceRef(source_type="locomo_turn", source_id="doc:session_11:D11:10:turn"),
        ),
        text=(
            "D2:1 Maria volunteers at the homeless shelter. "
            "D11:10 Maria also started volunteering at the dog shelter."
        ),
        score_signals={"query_expansion_reason": "decomposition_inventory_list"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (single_mention, aggregation),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["aggregation_shelters"].score > by_id["single_shelter"].score
    assert (
        "aggregation_list_slot_diverse_evidence"
        in by_id["aggregation_shelters"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "aggregation_list_single_evidence_incomplete"
        in by_id["single_shelter"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_keeps_direct_numeric_count_answer() -> None:
    query = "How many children does Melanie have?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    direct_count = _item(
        "children_count",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie has three children.",
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (direct_count,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert "aggregation_single_evidence_noise" not in reranked.diagnostics[
        "provenance"
    ].get("deterministic_rerank_reasons", [])


def test_keyword_chunk_score_boosts_allergy_inventory_equivalents() -> None:
    plan = build_query_expansion_plan("What is Joanna allergic to?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:4 Joanna: Unfortunately, I can't have dairy, so no ice cream "
            "for me. Do you have a dairy-free recipe?"
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "allergy_inventory_bridge"
    assert score >= 0.86


def test_keyword_chunk_score_boosts_children_count_event_bridge() -> None:
    plan = build_query_expansion_plan("How many children does Melanie have?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D18:1 Melanie: We were all freaked when my son got into an "
            "accident during the roadtrip. We were lucky he was okay."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "children_count_event_bridge"
    assert score >= 0.88


def test_keyword_chunk_score_boosts_pottery_project_type_summary() -> None:
    plan = build_query_expansion_plan("What types of pottery have Melanie and her kids made?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D12:2 D12:4 Melanie finished another pottery project and was proud "
            "of the ceramic bowl she made in class."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "pottery_type_bridge"
    assert score >= 0.87


def test_pottery_type_bridge_beats_generic_inventory_for_visual_cup_evidence() -> None:
    plan = build_query_expansion_plan("What types of pottery have Melanie and her kids made?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D8:4 Melanie: The kids loved it! They were excited to get their "
            "hands dirty and make something with clay. blip_caption: a photo "
            "of a cup with a dog face on it. query: kids pottery finished pieces."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "pottery_type_bridge"
    assert relevance.distinctive_term_hits >= 7
    assert score >= 0.87


def test_transgender_youth_center_bridge_scores_talent_show_visual_evidence() -> None:
    plan = build_query_expansion_plan("What transgender-specific events has Caroline attended?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D15:13 Caroline: Wow! Did you see that band? D15:12 blip_caption: "
            "a photo of a band playing on a stage in a park. query: talent "
            "show stage colorful lights microphone."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "transgender_youth_center_event_bridge"
    assert relevance.distinctive_term_hits >= 7
    assert score >= 0.91


def test_keyword_chunk_score_boosts_adoption_current_goal_bridge() -> None:
    plan = build_query_expansion_plan("Would Caroline want to move back to her home country soon?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D19:3 Caroline hopes to build her own family and put a roof "
            "over kids who have not had that before. Adoption is a way of "
            "giving back."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "adoption_current_goal_bridge"
    assert score >= 0.92


def test_keyword_chunk_score_boosts_adoption_current_milestone_bridge() -> None:
    plan = build_query_expansion_plan("Would Caroline want to move back to her home country soon?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D19:1 Caroline passed the adoption agency interviews last Friday. "
            "This is a big move towards her goal of having a family."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "adoption_current_milestone_bridge"
    assert score >= 0.95


def test_query_relevance_priority_requires_specific_adoption_goal_hits() -> None:
    plan = build_query_expansion_plan("Would Caroline want to move back to her home country soon?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="D7:1 Caroline moved from Sweden four years ago and misses home sometimes.",
    )

    assert reason == "decomposition_relocation_context"
    assert relevance.distinctive_term_hits >= 5


def test_keyword_chunk_score_boosts_specific_book_suggestion_bridge() -> None:
    plan = build_query_expansion_plan("What book did Melanie read from Caroline's suggestion?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline recommended Becoming Nicole by Amy Ellis Nutt, a true "
            "story about a trans girl and family."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "book_suggestion_bridge"
    assert relevance.distinctive_term_hits >= 8
    assert score >= 0.94


def test_keyword_chunk_score_boosts_book_recommendation_wording() -> None:
    for query, text in (
        (
            "What book did Melanie read after Caroline recommended it?",
            (
                "Caroline recommended Becoming Nicole by Amy Ellis Nutt, a true "
                "story about a trans girl and family, to Melanie."
            ),
        ),
        (
            "What book did Melanie read after Caroline suggested it?",
            (
                "Caroline suggested Becoming Nicole by Amy Ellis Nutt, a true "
                "story about a trans girl and family, to Melanie."
            ),
        ),
    ):
        plan = build_query_expansion_plan(query)

        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == "book_suggestion_bridge"
        assert relevance.distinctive_term_hits >= 8
        assert score >= 0.94


def test_book_suggestion_bridge_does_not_prioritize_generic_project_suggestion() -> None:
    plan = build_query_expansion_plan("What book did Melanie read from Caroline's suggestion?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Melanie read a project suggestion from Caroline about launch planning.",
    )

    assert reason == "original_query"
    assert relevance.distinctive_term_hits < 5


def test_deterministic_rerank_prefers_book_recommendation_followup_evidence() -> None:
    query = "What book did Melanie read from Caroline's suggestion?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    followup = _item(
        "recommendation_followup",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D17:10 Melanie: Thanks, Caroline. Been reading that book you "
            "recommended a while ago and painting to keep busy."
        ),
        score_signals={"query_expansion_reason": "book_suggestion_bridge"},
    )
    topical = _item(
        "topical_book",
        score=0.715,
        retrieval_source="keyword_chunks",
        text="D14:4 Melanie read a book about painting techniques.",
        score_signals={"query_expansion_reason": "book_suggestion_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topical, followup),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["recommendation_followup"].score > by_id["topical_book"].score
    assert (
        "recommendation_followup_evidence"
        in by_id["recommendation_followup"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_uses_suggestion_source_roles() -> None:
    query = "What book did Melanie read from Caroline's suggestion?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (reversed_roles, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_to_melanie"].score > by_id["melanie_to_caroline"].score
    assert (
        "action_role_actor_recipient_match"
        in by_id["caroline_to_melanie"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_recipient_reversed"
        in by_id["melanie_to_caroline"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_positive_event_participation_over_missed_event() -> None:
    query = "What LGBTQ+ events has Caroline participated in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    attended = _item(
        "attended_pride",
        score=0.8,
        retrieval_source="keyword_chunks",
        text=(
            "D5:1 Caroline: Last week I went to an LGBTQ pride parade. "
            "Everyone was happy and I felt like I belonged."
        ),
    )
    missed = _item(
        "missed_pride",
        score=0.82,
        retrieval_source="keyword_chunks",
        text=(
            "D10:7 Caroline: Last weekend our city held a pride parade. "
            "People marched with flags, but I missed it."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (missed, attended),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["attended_pride"].score > by_id["missed_pride"].score
    assert (
        "event_participation_positive_match"
        in by_id["attended_pride"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "event_participation_mismatch"
        in by_id["missed_pride"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_broad_lgbtq_event_slot_coverage() -> None:
    query = "What LGBTQ+ events has Caroline participated in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    multi_slot = _item(
        "multi_event_slots",
        score=0.77,
        retrieval_source="keyword_aggregation_chunks",
        text=(
            "D9:2 Caroline joined a mentorship program for LGBTQ youth. "
            "D10:3 Caroline joined a new LGBTQ activist group. "
            "D14:33 Caroline organized an LGBTQ art show with her paintings."
        ),
        score_signals={"query_expansion_reason": "event_participation_bridge"},
    )
    single_slot = _item(
        "single_pride_event",
        score=0.765,
        retrieval_source="keyword_chunks",
        text="D5:1 Caroline went to an LGBTQ pride parade and felt accepted.",
        score_signals={"query_expansion_reason": "lgbtq_pride_event_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (single_slot, multi_slot),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["multi_event_slots"].score > by_id["single_pride_event"].score
    assert (
        "aggregation_list_slot_diverse_evidence"
        in by_id["multi_event_slots"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_answer_shape_missing"
        not in by_id["multi_event_slots"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_evidence_feature_missing"
        not in by_id["multi_event_slots"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "aggregation_list_single_evidence_incomplete"
        in by_id["single_pride_event"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_broad_inventory_slot_coverage() -> None:
    query = "What causes does John feel passionate about supporting?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    multi_slot = _item(
        "john_cause_slots",
        score=0.77,
        retrieval_source="keyword_chunks",
        text=(
            "D15:3 John is passionate about veterans and their rights. "
            "D12:5 John supports education reform and infrastructure development."
        ),
        score_signals={
            "query_expansion_reason": "cause_education_infrastructure_inventory_bridge"
        },
    )
    single_slot = _item(
        "john_veterans_only",
        score=0.785,
        retrieval_source="keyword_chunks",
        text="D15:3 John is passionate about veterans and their rights.",
        score_signals={"query_expansion_reason": "cause_veterans_inventory_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (single_slot, multi_slot),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["john_cause_slots"].score > by_id["john_veterans_only"].score
    assert (
        "aggregation_list_slot_diverse_evidence"
        in by_id["john_cause_slots"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "aggregation_list_single_evidence_incomplete"
        in by_id["john_veterans_only"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_cause_awareness_event_evidence() -> None:
    query = "What did the charity race raise awareness for?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact = _item(
        "mental_health_race_awareness",
        score=0.76,
        retrieval_source="keyword_chunks",
        text=(
            "D2:2 Caroline: That charity race sounds great, Mel! Making a "
            "difference and raising awareness for mental health is super rewarding."
        ),
        score_signals={"query_expansion_reason": "cause_awareness_event_bridge"},
    )
    promotion_noise = _item(
        "promotion_awareness_noise",
        score=0.79,
        retrieval_source="keyword_chunks",
        text=(
            "D12:5 Jon needed marketing strategies to reach his target audience "
            "and raise awareness for the dance studio."
        ),
        score_signals={"query_expansion_reason": "cause_awareness_event_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (promotion_noise, exact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["mental_health_race_awareness"].score > by_id[
        "promotion_awareness_noise"
    ].score
    assert (
        by_id["mental_health_race_awareness"]
        .diagnostics["score_signals"]
        .get("cause_awareness_answer_evidence")
        == 3.0
    )
    assert (
        "cause_awareness_exact_evidence"
        in by_id["mental_health_race_awareness"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "cause_awareness_promotion_noise"
        in by_id["promotion_awareness_noise"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_activity_companion_evidence() -> None:
    query = "Who did Melanie go camping with?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    companion = _item(
        "melanie_family_camping",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D9:1 Melanie: I went camping with my family and enjoyed "
            "unplugging with the kids."
        ),
    )
    missing_companion = _item(
        "melanie_camping_topical",
        score=0.735,
        retrieval_source="keyword_chunks",
        text="D10:4 Melanie: I went camping last weekend and loved the trail.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (missing_companion, companion),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_family_camping"].score > by_id["melanie_camping_topical"].score
    assert (
        "activity_companion_positive_match"
        in by_id["melanie_family_camping"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "activity_companion_missing_evidence"
        in by_id["melanie_camping_topical"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_negated_activity_companion_evidence() -> None:
    query = "Who did Melanie go camping with?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    companion = _item(
        "melanie_family_camping",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D9:1 Melanie: I went camping with my family and the kids.",
    )
    alone = _item(
        "melanie_camping_alone",
        score=0.76,
        retrieval_source="keyword_chunks",
        text="D10:4 Melanie: I went camping alone without my family.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alone, companion),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_family_camping"].score > by_id["melanie_camping_alone"].score
    assert (
        "activity_companion_negated_evidence"
        in by_id["melanie_camping_alone"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_weak_activity_source_sibling() -> None:
    query = "What does Melanie do with her family on hikes?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    activity = _item(
        "campfire_activity",
        score=0.8,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D16:4 Melanie: We roasted marshmallows and shared stories around "
            "the campfire after hiking with the kids."
        ),
        score_signals={
            "query_expansion_reason": "family_hike_activity_bridge",
            "query_expansion_reason_priority": 4,
        },
    )
    noisy_sibling = _item(
        "support_cafe_sibling",
        score=0.82,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D16:16 Melanie: Glad you found people who uplift and accept you. "
            "The cafe had thoughtful signs."
        ),
        score_signals={
            "query_expansion_reason": "family_hike_activity_bridge",
            "query_expansion_reason_priority": 4,
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (noisy_sibling, activity),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["campfire_activity"].score > by_id["support_cafe_sibling"].score
    assert (
        "activity_source_sibling_noise"
        in by_id["support_cafe_sibling"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_family_hike_actions_over_topic_only() -> None:
    query = "What does Melanie do with her family on hikes?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    campfire_actions = _item(
        "campfire_actions",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D16:4 Melanie roasted marshmallows and shared stories around "
            "the campfire with her family."
        ),
    )
    topic_only = _item(
        "hike_photo",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="Melanie hikes with her kids and takes nature photos near a trail.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, campfire_actions),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["campfire_actions"].score > by_id["hike_photo"].score
    assert (
        "family_hike_detail_exact_evidence"
        in by_id["campfire_actions"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "family_hike_detail_topic_only_noise"
        in by_id["hike_photo"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_capped_source_sibling_low_signal() -> None:
    query = "What job might Maria pursue in the future?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    strong_evidence = _item(
        "front_desk_evidence",
        score=0.94,
        retrieval_source="keyword_chunks",
        text=(
            "D32:14 Maria spent time volunteering at the shelter front desk. "
            "Seeing people get food or a bed made her feel fulfilled and "
            "showed she could make a difference in people's lives."
        ),
        score_signals={
            "query_expansion_reason": "volunteer_career_inference_bridge",
            "query_expansion_reason_priority": 4,
        },
    )
    weak_sibling = _item(
        "generic_shelter_sibling",
        score=0.976,
        retrieval_source="keyword_source_sibling_chunks",
        text="D1:3 Maria was busy volunteering at the homeless shelter and doing yoga.",
        score_signals={
            "query_expansion_reason": "volunteer_career_inference_bridge",
            "query_expansion_reason_priority": 4,
            "source_sibling_score_cap_applied": 1,
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (weak_sibling, strong_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["front_desk_evidence"].score > by_id["generic_shelter_sibling"].score
    assert (
        "capped_source_sibling_low_signal"
        in by_id["generic_shelter_sibling"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_keeps_duration_and_frequency_source_siblings() -> None:
    duration_query = "How long has Maria volunteered at the shelter?"
    duration_plan = build_query_expansion_plan(duration_query)
    duration_intent = build_query_anchor_intent(duration_query)
    duration_item = _item(
        "duration_sibling",
        score=0.95,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D4:6 Maria: I started volunteering at the homeless shelter "
            "three years ago and I still help at the front desk."
        ),
        score_signals={
            "query_expansion_reason": "decomposition_activity_duration",
            "source_sibling_score_cap_applied": 0,
        },
    )

    duration_reranked = apply_deterministic_rerank_adjustments(
        (duration_item,),
        query=duration_query,
        plan=duration_plan,
        query_anchor_intent=duration_intent,
    )[0]
    duration_reasons = set(
        duration_reranked.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )

    assert "activity_source_sibling_noise" not in duration_reasons
    assert "capped_source_sibling_low_signal" not in duration_reasons

    frequency_query = "How often does Maria volunteer at the shelter?"
    frequency_plan = build_query_expansion_plan(frequency_query)
    frequency_intent = build_query_anchor_intent(frequency_query)
    frequency_item = _item(
        "frequency_sibling",
        score=0.95,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D9:4 Maria: I volunteer at the homeless shelter every weekend "
            "and usually help on Friday nights too."
        ),
        score_signals={
            "query_expansion_reason": "decomposition_frequency_recurrence",
            "source_sibling_score_cap_applied": 0,
        },
    )

    frequency_reranked = apply_deterministic_rerank_adjustments(
        (frequency_item,),
        query=frequency_query,
        plan=frequency_plan,
        query_anchor_intent=frequency_intent,
    )[0]
    frequency_reasons = set(
        frequency_reranked.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )

    assert "activity_source_sibling_noise" not in frequency_reasons
    assert "capped_source_sibling_low_signal" not in frequency_reasons


def test_deterministic_rerank_penalizes_volunteer_career_wrong_person_noise() -> None:
    query = "What job might Maria pursue in the future?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    strong_evidence = _item(
        "maria_shelter_talks",
        score=0.94,
        retrieval_source="keyword_chunks",
        source_refs=(SourceRef(source_type="locomo_turn", source_id="doc:session_11:D11:10:turn"),),
        text=(
            "D11:10 Maria: I recently gave a few talks at the homeless shelter "
            "I volunteer at. It was fulfilling and I received compliments."
        ),
        score_signals={
            "query_expansion_reason": "volunteer_career_inference_bridge",
            "query_expansion_reason_priority": 4,
        },
    )
    wrong_person_noise = _item(
        "john_career_fair",
        score=0.96,
        retrieval_source="keyword_chunks",
        text=(
            'D10:15 John: The sign at the career fair said, "Always look on '
            'the bright side of life."'
        ),
        score_signals={
            "query_expansion_reason": "volunteer_career_inference_bridge",
            "query_expansion_reason_priority": 4,
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (wrong_person_noise, strong_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["maria_shelter_talks"].score > by_id["john_career_fair"].score
    assert (
        "volunteer_career_weak_evidence"
        in by_id["john_career_fair"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_volunteer_career_exact_turn_over_broad_summary() -> None:
    query = "What job might Maria pursue in the future?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact_turn = _item(
        "exact_turn",
        score=0.94,
        retrieval_source="keyword_chunks",
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id="doc:session_27:D27:4:turn"),
        ),
        text=(
            "D27:4 Maria: I started volunteering at the shelter after seeing "
            "a struggling family, and it has been fulfilling."
        ),
        score_signals={
            "query_expansion_reason": "volunteer_career_inference_bridge",
            "query_expansion_reason_priority": 4,
        },
    )
    broad_summary = _item(
        "broad_summary",
        score=0.96,
        retrieval_source="keyword_chunks",
        text=(
            "Maria has been doing charity work at a homeless shelter and finds it fulfilling. "
            "John also wants to make a difference in the community."
        ),
        source_refs=(
            SourceRef(
                source_type="locomo_observation",
                source_id="doc:session_14:observation",
            ),
        ),
        score_signals={
            "query_expansion_reason": "volunteer_career_inference_bridge",
            "query_expansion_reason_priority": 4,
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (broad_summary, exact_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["exact_turn"].score > by_id["broad_summary"].score
    assert (
        "volunteer_career_broad_evidence"
        in by_id["broad_summary"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_career_fit_evidence_over_topic_noise() -> None:
    query = "What job might Maria pursue in the future?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    career_fit = _item(
        "maria_shelter_fit",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D11:10 Maria volunteered at the shelter front desk, found it "
            "fulfilling, and received compliments from residents."
        ),
    )
    topic_noise = _item(
        "john_career_fair",
        score=0.72,
        retrieval_source="keyword_chunks",
        text='D10:15 John saw a career fair sign that said "Always look on the bright side."',
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_noise, career_fit),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["maria_shelter_fit"].score > by_id["john_career_fair"].score
    assert (
        "inference_career_fit_evidence"
        in by_id["maria_shelter_fit"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_career_topic_only_noise"
        in by_id["john_career_fair"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_animal_career_evidence_over_gaming_noise() -> None:
    query = "What alternative career might Nate consider after gaming?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    animal_fit = _item(
        "nate_turtle_care",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Nate keeps pet turtles, cleans their tank, and enjoys feeding them.",
    )
    gaming_noise = _item(
        "nate_gaming_noise",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Nate won another gaming tournament and bought a new console.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (gaming_noise, animal_fit),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["nate_turtle_care"].score > by_id["nate_gaming_noise"].score
    assert (
        "inference_animal_career_fit_evidence"
        in by_id["nate_turtle_care"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_animal_career_topic_only_noise"
        in by_id["nate_gaming_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_gaming_only_goal_for_animal_career() -> None:
    query = "What alternative career might Nate consider after gaming?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    animal_fit = _item(
        "nate_turtle_diet",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D25:19 Nate says the turtles eat vegetables, fruits, and insects "
            "and have a varied diet."
        ),
    )
    gaming_only_goal = _item(
        "nate_gaming_goal",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Nate wants to become a champion streamer after gaming tournaments "
            "and bought another console."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (gaming_only_goal, animal_fit),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["nate_turtle_diet"].score > by_id["nate_gaming_goal"].score
    assert (
        "current_goal_animal_career_mismatch"
        in by_id["nate_gaming_goal"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_career_field_decision_evidence() -> None:
    query = "What fields would Caroline be likely to pursue in her educaton?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    field_decision = _item(
        "caroline_counseling_field",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D1:11 Caroline is keen on counseling and working in mental health, "
            "and she would love to support people with similar issues."
        ),
    )
    generic_options = _item(
        "caroline_generic_options",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D1:9 Caroline said she will continue education and check out career "
            "options, which is pretty exciting."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_options, field_decision),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_counseling_field"].score > by_id["caroline_generic_options"].score
    assert (
        "inference_career_field_decision_evidence"
        in by_id["caroline_counseling_field"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_negated_career_decision_noise() -> None:
    query = "What career path has Caroline decided to persue?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    decided = _item(
        "caroline_counseling_path",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D4:13 Caroline decided she wants to pursue a career path in "
            "counseling and mental health work."
        ),
    )
    negated = _item(
        "caroline_writing_noise",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D12:2 Caroline wrote a short story about career uncertainty, but "
            "did not decide to pursue writing as a job."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negated, decided),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_counseling_path"].score > by_id["caroline_writing_noise"].score
    assert (
        "inference_career_field_decision_evidence"
        in by_id["caroline_counseling_path"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_career_negated_decision_noise"
        in by_id["caroline_writing_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_friend_team_evidence_over_single_contact() -> None:
    query = "Is it likely that Nate has friends besides Joanna?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    team_evidence = _item(
        "nate_team_friends",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Nate plays Valorant with online teammates and gaming friends "
            "from tournaments."
        ),
    )
    joanna_only = _item(
        "nate_joanna_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Nate played a video game with Joanna after school.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (joanna_only, team_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["nate_team_friends"].score > by_id["nate_joanna_only"].score
    assert (
        "inference_friend_team_evidence"
        in by_id["nate_team_friends"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_friend_team_single_contact_noise"
        in by_id["nate_joanna_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_friend_team_evidence_without_likely_marker() -> None:
    query = "Does Nate have friends besides Joanna?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    team_evidence = _item(
        "nate_team_friends",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Nate plays Valorant with online teammates and gaming friends "
            "from tournaments."
        ),
    )
    joanna_only = _item(
        "nate_joanna_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Nate played a video game with Joanna after school.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (joanna_only, team_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["nate_team_friends"].score > by_id["nate_joanna_only"].score
    assert (
        "inference_friend_team_evidence"
        in by_id["nate_team_friends"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_friend_team_single_contact_noise"
        in by_id["nate_joanna_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_named_single_contact_friend_noise() -> None:
    query = "Does Nate have friends other than Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    team_evidence = _item(
        "nate_team_friends",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Nate plays Valorant with online teammates and gaming friends "
            "from tournaments."
        ),
    )
    alex_only = _item(
        "nate_alex_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Nate played Counter Strike with Alex after school.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alex_only, team_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["nate_team_friends"].score > by_id["nate_alex_only"].score
    assert (
        "inference_friend_team_single_contact_noise"
        in by_id["nate_alex_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_russian_friend_team_evidence() -> None:
    query = "Есть ли у Нейта друзья помимо Жанны?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    team_evidence = _item(
        "nate_team_friends_ru",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Нейт играет в Valorant с онлайн-командой и друзьями по турнирам.",
    )
    single_contact = _item(
        "nate_zhanna_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Нейт играл в видеоигру с Жанной после школы.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (single_contact, team_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["nate_team_friends_ru"].score > by_id["nate_zhanna_only"].score
    assert (
        "inference_friend_team_evidence"
        in by_id["nate_team_friends_ru"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_friend_team_single_contact_noise"
        in by_id["nate_zhanna_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_degree_policy_evidence_over_measurement_noise() -> None:
    query = "What might John's degree be in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    policy_degree = _item(
        "john_policy_degree",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="John studied political science and public policy at university.",
    )
    measurement_noise = _item(
        "john_temperature_degree",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="John set the thermostat to 68 degrees before leaving.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (measurement_noise, policy_degree),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["john_policy_degree"].score > by_id["john_temperature_degree"].score
    assert (
        "inference_degree_policy_evidence"
        in by_id["john_policy_degree"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_degree_measurement_noise"
        in by_id["john_temperature_degree"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_post_event_activity_timing_turn() -> None:
    query = "When did Melanie go on a hike after the roadtrip?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact_turn = _item(
        "post_roadtrip_hike",
        score=0.94,
        retrieval_source="keyword_chunks",
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id="doc:session_18:D18:17:turn"),
        ),
        text=(
            "D18:17 Melanie: Yup, we just did it yesterday! The kids loved it "
            "and it was a nice way to relax after the road trip."
        ),
        score_signals={
            "query_expansion_reason": "post_event_activity_timing_bridge",
            "query_expansion_reason_priority": 5,
        },
    )
    weak_sibling = _item(
        "self_care_noise",
        score=0.976,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D2:5 Melanie: I carve out me-time each day with running, reading, "
            "and violin after work."
        ),
        score_signals={
            "query_expansion_reason": "post_event_activity_timing_bridge",
            "query_expansion_reason_priority": 5,
            "source_sibling_score_cap_applied": 1,
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (weak_sibling, exact_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["post_roadtrip_hike"].score > by_id["self_care_noise"].score
    assert (
        "post_event_activity_timing_exact_evidence"
        in by_id["post_roadtrip_hike"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "post_event_activity_timing_weak_evidence"
        in by_id["self_care_noise"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_shoe_usage_question_turn_over_color_noise() -> None:
    query = "What are the new shoes that Melanie got used for?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    question_turn = _item(
        "walking_or_running_question",
        score=0.94,
        retrieval_source="keyword_chunks",
        source_refs=(SourceRef(source_type="locomo_turn", source_id="doc:session_7:D7:19:turn"),),
        text="D7:19 Caroline: Love that purple color! For walking or running?",
        score_signals={
            "query_expansion_reason": "shoe_usage_bridge",
            "query_expansion_reason_priority": 4,
        },
    )
    color_noise = _item(
        "painting_color_noise",
        score=0.976,
        retrieval_source="keyword_chunks",
        text=(
            "D16:13 Caroline: I love the red and blue colors in this painting "
            "about my path as a trans woman."
        ),
        score_signals={
            "query_expansion_reason": "shoe_usage_bridge",
            "query_expansion_reason_priority": 4,
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (color_noise, question_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["walking_or_running_question"].score > by_id["painting_color_noise"].score
    assert (
        "shoe_usage_exact_evidence"
        in by_id["walking_or_running_question"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "shoe_usage_weak_evidence"
        in by_id["painting_color_noise"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_music_artist_band_bridge_prefers_live_seen_evidence() -> None:
    plan = build_query_expansion_plan("What musical artists/bands has Melanie seen?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Melanie saw Coldplay and Imagine Dragons live at a summer concert.",
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "music_artist_band_bridge"
    assert relevance.distinctive_term_hits >= 5
    assert score >= 0.85


def test_music_artist_band_bridge_finds_answer_only_artist_turn() -> None:
    plan = build_query_expansion_plan("What musical artists/bands has Melanie seen?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D11:3 Melanie: It was Matt Patterson, he is so talented! "
            "His voice and songs were amazing."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "music_artist_answer_bridge"
    assert relevance.distinctive_term_hits >= 5
    assert score >= 0.85


def test_music_artist_band_bridge_does_not_prioritize_listened_song_only() -> None:
    plan = build_query_expansion_plan("What musical artists/bands has Melanie seen?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Melanie listened to Ed Sheeran's Perfect and liked the song.",
    )

    assert reason == "original_query"
    assert relevance.distinctive_term_hits == 1


def test_animal_career_bridge_scores_turtle_care_evidence() -> None:
    plan = build_query_expansion_plan("What alternative career might Nate consider after gaming?")

    cases = (
        (
            "D5:8 Nate: Just keep their area clean, feed them properly, "
            "and make sure they get enough light. It is actually kind of fun.",
            "animal_care_instruction_bridge",
        ),
        (
            "D19:3 Nate: My little dudes got a new tank! Check them out, "
            "they are so cute, right?! visual query: cute pet turtles tank",
            "animal_habitat_setup_bridge",
        ),
        (
            "D25:19 Nate: They eat a combination of vegetables, fruits, and insects. "
            "They have a varied diet.",
            "animal_diet_evidence_bridge",
        ),
        (
            "D28:25 Nate: Turtles really bring me joy and peace. I saw another "
            "at a pet store and got him because the tank is big enough for three.",
            "animal_affinity_pet_store_bridge",
        ),
    )
    for text, expected_reason in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == expected_reason
        assert relevance.distinctive_term_hits >= 4
        assert score >= 0.9


def test_keyword_chunk_score_boosts_event_participation_help_bridge() -> None:
    plan = build_query_expansion_plan("What events has Caroline participated in to help children?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D3:3 Caroline gave a school speech about gender identity and "
            "inspired students to be better allies."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "event_participation_help_bridge"
    assert score >= 0.87


def test_keyword_chunk_score_boosts_avoidance_constraint_bridge() -> None:
    plan = build_query_expansion_plan("Which foods would Alex not eat?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex avoids peanuts and never eats shellfish because of allergies.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "avoidance_constraint_bridge"
    assert score >= 0.9


def test_keyword_chunk_score_boosts_cant_eat_avoidance_constraint_bridge() -> None:
    plan = build_query_expansion_plan("Which foods can't Alex eat?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex cannot eat peanuts and avoids shellfish because of allergies.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "avoidance_constraint_bridge"
    assert score >= 0.9


def test_keyword_chunk_score_boosts_project_avoidance_constraint_bridge() -> None:
    plan = build_query_expansion_plan("What should we avoid for Project Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Project Atlas should avoid launching before invoice approval because it is unsafe.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "avoidance_constraint_bridge"
    assert score >= 0.86


def test_keyword_chunk_score_boosts_negative_preference_bridge() -> None:
    plan = build_query_expansion_plan("What does Melanie not like?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Melanie dislikes loud theme parks and avoids noisy rides.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "negative_preference_bridge"
    assert score >= 0.87


def test_keyword_chunk_score_boosts_negative_interest_bridge() -> None:
    plan = build_query_expansion_plan("What is Alex not interested in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex is not interested in frontend work and has no interest in UI tasks.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "negative_preference_bridge"
    assert score >= 0.86


def test_keyword_chunk_score_boosts_food_preference_bridge() -> None:
    plan = build_query_expansion_plan("Which meat does Audrey prefer eating more than others?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D10:13 Audrey: I love cooking. My favorite recipe is Chicken Pot Pie, "
            "and roasted chicken is one of my favorite comfort meals."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "food_preference_bridge"
    assert score >= 0.88


def test_keyword_chunk_score_boosts_state_residence_inference_bridge() -> None:
    plan = build_query_expansion_plan("Which US state do Audrey and Andrew potentially live in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D11:9 Andrew image caption: a photo of a map of a park with a lot "
            "of trees. Andrew image query: hiking trails map perfect spot. "
            "Here is the map for the trail."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "state_residence_inference_bridge"
    assert score >= 0.88


def test_keyword_chunk_score_boosts_locomo_why_reason_bridges() -> None:
    cases = (
        (
            build_query_expansion_plan("Why did Gina start her own clothing store?"),
            (
                "Gina lost her Door Dash job and started thinking seriously "
                "about her own clothing store business."
            ),
            "business_start_reason_bridge",
        ),
        (
            build_query_expansion_plan("Why did Maria sit with a little girl at the shelter?"),
            (
                "Maria saw a little girl sitting alone and sad at the shelter "
                "with no family, so she offered comfort and a listening ear."
            ),
            "shelter_comfort_reason_bridge",
        ),
        (
            build_query_expansion_plan(
                "What prominent charity organization might Jordan work with and why?"
            ),
            (
                "Jordan had a TrailCore shoe deal, talked with HydraFuel, liked "
                "SummitGear, and wanted to give back through charity."
            ),
            "charity_brand_sponsorship_bridge",
        ),
        (
            build_query_expansion_plan("Why does Jolene sometimes put off doing yoga?"),
            (
                "Jolene planned to play console games with her partner and "
                "Walking Dead next Saturday instead of doing yoga."
            ),
            "yoga_delay_gaming_bridge",
        ),
    )

    for plan, text, expected_reason in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == expected_reason
        assert score >= 0.88


def test_keyword_chunk_score_boosts_locomo_count_bridges() -> None:
    cases = (
        (
            build_query_expansion_plan("How many tournaments has Nate won?"),
            "Nate won his fourth video game tournament and later became a Valorant champion.",
            "tournament_count_bridge",
        ),
        (
            build_query_expansion_plan("How many charity tournaments has John organized?"),
            "John held a gaming tourney with buddies and raised money for a children's hospital.",
            "charity_tournament_count_bridge",
        ),
        (
            build_query_expansion_plan("How many screenplays has Joanna written?"),
            "Joanna finished her first full screenplay, second script, and third one.",
            "screenplay_count_bridge",
        ),
        (
            build_query_expansion_plan("How many letters has Joanna recieved?"),
            "Joanna got a rejection letter and someone later wrote her another letter.",
            "letter_count_bridge",
        ),
        (
            build_query_expansion_plan("How many pets will Andrew have?"),
            "Andrew adopted Toby, another pup from a shelter, and another doggo.",
            "pet_count_bridge",
        ),
        (
            build_query_expansion_plan("How many times has Joanna found new hiking trails?"),
            "Joanna found an awesome hiking trail and later found more amazing trails.",
            "hiking_trail_count_bridge",
        ),
    )

    for plan, text, expected_reason in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == expected_reason
        assert score >= 0.88


def test_keyword_chunk_score_boosts_locomo_personal_list_fact_bridges() -> None:
    cases = (
        (
            build_query_expansion_plan("What instruments does Melanie play?"),
            "Melanie plays clarinet and violin when she needs to relax.",
            "instrument_play_bridge",
        ),
        (
            build_query_expansion_plan("What martial arts has John done?"),
            "John has done kickboxing for energy and taekwondo with loved ones.",
            "exercise_activity_inventory_bridge",
        ),
        (
            build_query_expansion_plan("What are Joanna's hobbies?"),
            "Joanna enjoys writing, reading, watching movies, exploring nature, and friends.",
            "hobby_interest_bridge",
        ),
        (
            build_query_expansion_plan("What books has Tim read?"),
            "Tim read Harry Potter, The Hobbit, A Dance with Dragons, and Wheel of Time.",
            "book_reading_list_bridge",
        ),
        (
            build_query_expansion_plan("What mediums does Nate use to play games?"),
            "Nate plays games on GameCube, PC, and Playstation with upgraded equipment.",
            "gaming_medium_bridge",
        ),
        (
            build_query_expansion_plan("What pets does Nate have?"),
            "Nate has a dog named Max and turtles, plus he got them a new friend.",
            "pet_inventory_bridge",
        ),
        (
            build_query_expansion_plan(
                "Which outdoor gear company likely signed up John for an endorsement deal?"
            ),
            "John liked Under Armour after Nike and Gatorade deals for basketball gear.",
            "endorsement_gear_brand_bridge",
        ),
    )

    for plan, text, expected_reason in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == expected_reason
        assert score >= 0.88


def test_keyword_chunk_score_boosts_temporal_event_detail_bridge() -> None:
    cases = (
        (
            build_query_expansion_plan("When did Caroline go to the adoption meeting?"),
            "Caroline went to a council meeting for adoption last Friday.",
        ),
        (
            build_query_expansion_plan("When did Caroline join a new activist group?"),
            "Caroline joined a new LGBTQ activist group last Tues.",
        ),
        (
            build_query_expansion_plan("When did Gina design a limited collection of hoodies?"),
            "Gina made a limited edition hoodie line last week.",
        ),
        (
            build_query_expansion_plan("When did John join the online support group?"),
            "John joined a service-focused online support group last week.",
        ),
    )

    for plan, text in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == "temporal_event_detail_bridge"
        assert score >= 0.88


def test_keyword_chunk_score_boosts_event_sequence_decomposition_policy() -> None:
    relevance = score_query_relevance(
        query=(
            "Atlas after following later next timeline outcome follow up decision result changed"
        ),
        text="After the Atlas call, Alex said the launch date changed as the next outcome.",
    )

    score = keyword_chunk_score(
        relevance,
        query_expansion_reason="decomposition_event_sequence",
    )

    assert query_expansion_reason_priority("decomposition_event_sequence") == 4
    assert score >= 0.84


def test_deterministic_rerank_prefers_exact_after_conversation_sequence() -> None:
    query = "What did Alex decide after talking with Sam about Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact = _item(
        "sam_atlas_decision",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "After talking with Sam about Atlas, Alex decided to wait for "
            "invoice approval before launch."
        ),
    )
    wrong_thread = _item(
        "priya_stripe_change",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="After talking with Priya about Stripe, Alex changed the billing retry plan.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (wrong_thread, exact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["sam_atlas_decision"].score > by_id["priya_stripe_change"].score
    assert (
        "event_sequence_exact_evidence"
        in by_id["sam_atlas_decision"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_sequence_answer_over_topic_note() -> None:
    query = "What did Alex decide after talking with Sam about Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_note = _item(
        "sam_atlas_topic_note",
        score=0.76,
        retrieval_source="keyword_chunks",
        text="After talking with Sam about Atlas, Alex reviewed launch meeting notes.",
    )
    exact = _item(
        "sam_atlas_decision",
        score=0.70,
        retrieval_source="keyword_chunks",
        text=(
            "After talking with Sam about Atlas, Alex decided to wait for "
            "invoice approval before launch."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_note, exact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["sam_atlas_decision"].score > by_id["sam_atlas_topic_note"].score
    assert (
        "event_sequence_shape_missing"
        in by_id["sam_atlas_topic_note"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_russian_sequence_answer_over_topic_note() -> None:
    query = "Что решил Алекс после созвона по Атласу?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_note = _item(
        "atlas_topic_note_ru",
        score=0.76,
        retrieval_source="keyword_chunks",
        text="После созвона по Атласу Алекс просмотрел заметки по запуску.",
    )
    exact = _item(
        "atlas_decision_ru",
        score=0.70,
        retrieval_source="keyword_chunks",
        text="После созвона по Атласу Алекс решил перейти на OpenAI для запуска.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_note, exact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["atlas_decision_ru"].score > by_id["atlas_topic_note_ru"].score
    assert (
        "event_sequence_exact_evidence"
        in by_id["atlas_decision_ru"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_keyword_chunk_score_boosts_inference_support_decomposition_policy() -> None:
    relevance = score_query_relevance(
        query=(
            "Melanie inference supporting evidence likely would considered observed "
            "indicates support supportive encouraging acceptance care help"
        ),
        text=(
            "Melanie encourages Caroline, supports her identity, and helps her feel "
            "accepted by the community."
        ),
    )

    score = keyword_chunk_score(
        relevance,
        query_expansion_reason="decomposition_inference_support",
    )

    assert query_expansion_reason_priority("decomposition_inference_support") == 2
    assert score >= 0.84


def test_keyword_chunk_score_boosts_support_role_fit_bridge_policy() -> None:
    relevance = score_query_relevance(
        query=(
            "Caroline Alex support role fit mentor mentoring guidance advice coach "
            "volunteer counseling counselor listened listening comfort empathy patient "
            "helped accepted supportive safe trust similar issues reliable responsible care"
        ),
        text=(
            "Caroline listened to Alex, offered guidance and comfort, helped him "
            "feel safe, and had experience with similar issues."
        ),
    )

    score = keyword_chunk_score(
        relevance,
        query_expansion_reason="support_role_fit_bridge",
    )

    assert query_expansion_reason_priority("support_role_fit_bridge") == 4
    assert score >= 0.84


def test_keyword_chunk_score_boosts_support_network_bridge_policy() -> None:
    plan = build_query_expansion_plan("Who supports Caroline?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline's friends, family and mentors are her rocks. They are there "
            "for her, motivate her, and give her strength."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "support_network_bridge"
    assert query_expansion_reason_priority("support_network_bridge") == 4
    assert score >= 0.84


def test_keyword_chunk_score_boosts_support_network_helped_through_family_roles() -> None:
    plan = build_query_expansion_plan("Who helped Caroline through it?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline's mother Maya and coach Lena were there for her, comforted "
            "her, and helped her through it."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "support_network_bridge"
    assert relevance.distinctive_term_hits >= 5
    assert score >= 0.84


def test_support_network_rerank_prefers_exact_social_support_over_technical_support() -> None:
    query = "Who supports Caroline?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    exact = _item(
        "exact",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline's friends, family and mentors are her rocks. They are there "
            "for her and give her strength."
        ),
        score_signals={"query_expansion_reason": "support_network_bridge"},
    )
    weak = _item(
        "weak",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline wrote technical notes that support the OpenAI provider "
            "integration and SDK runtime."
        ),
        score_signals={"query_expansion_reason": "support_network_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (exact, weak),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )

    assert reranked[0].score > reranked[1].score
    assert "support_network_exact_evidence" in reranked[0].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]
    assert "support_network_weak_evidence" in reranked[1].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]


def test_support_network_rerank_treats_family_roles_as_exact_social_support() -> None:
    query = "Who helped Caroline through it?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    family_role = _item(
        "family-role",
        score=0.68,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline's mother and coach were always there for her, comforted "
            "her, and helped her through the hard time."
        ),
        score_signals={"query_expansion_reason": "support_network_bridge"},
    )
    weak = _item(
        "weak",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline helped review a backend support checklist for the SDK.",
        score_signals={"query_expansion_reason": "support_network_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (family_role, weak),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )

    assert reranked[0].item_id == "family-role"
    assert "support_network_exact_evidence" in reranked[0].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]
    assert "support_network_weak_evidence" in reranked[1].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]


def test_support_network_rerank_covers_negative_experience_support_bridge() -> None:
    query = "Who supports Caroline when she has a negative experience?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    support_roles = _item(
        "support_roles",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D3:11 Caroline's friends, family and mentors are her rocks. "
            "They motivate her and give her strength to push on."
        ),
    )
    technical_support = _item(
        "technical_support",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline contacted customer support after a negative API experience.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (technical_support, support_roles),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["support_roles"].score > by_id["technical_support"].score
    assert (
        "support_network_exact_evidence"
        in by_id["support_roles"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_keyword_chunk_score_boosts_multimodal_evidence_bridge_policies() -> None:
    cases = [
        (
            "What OCR text was in the screenshot?",
            "Screenshot OCR detected text label title: Atlas launch deadline moved.",
            "visual_text_evidence_bridge",
        ),
        (
            "What did Alex say in the audio?",
            "Audio transcript: Alex said the Atlas launch deadline moved.",
            "audio_transcript_evidence_bridge",
        ),
        (
            "What did Alex say in the video?",
            "Video transcript and keyframe evidence: Alex said the Atlas launch deadline moved.",
            "video_transcript_evidence_bridge",
        ),
    ]

    for query, text, expected_reason in cases:
        plan = build_query_expansion_plan(query)
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == expected_reason
        assert query_expansion_reason_priority(reason) == 4
        assert score >= 0.9


def test_keyword_chunk_score_boosts_event_summary_bridge() -> None:
    plan = build_query_expansion_plan("What did we discuss during the launch review?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Launch review meeting notes: Alex discussed the Atlas rollout, "
            "decision was to move the deadline, and Mira owns the follow up action item."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "event_summary_bridge"
    assert query_expansion_reason_priority(reason) == 4
    assert score >= 0.89


def test_keyword_chunk_score_boosts_artifact_inventory_bridge() -> None:
    plan = build_query_expansion_plan("Which files are related to Project Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Project Atlas artifact inventory: uploaded screenshot file, document, "
            "OCR evidence, and original file metadata are linked to the launch review."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "artifact_inventory_bridge"
    assert query_expansion_reason_priority(reason) == 4
    assert score >= 0.9


def test_keyword_chunk_score_boosts_stale_state_temporal_bridge() -> None:
    plan = build_query_expansion_plan("Which memory is stale for Project Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Project Atlas had an old invoice plan that was superseded by a "
            "new approval rule and is now outdated."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "stale_state_temporal_bridge"
    assert score >= 0.879


def test_keyword_chunk_score_boosts_deprecated_state_temporal_bridge() -> None:
    plan = build_query_expansion_plan("Which Project Atlas policy is deprecated?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Project Atlas used a previous policy that was superseded by a "
            "new approval rule and is no longer current."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "stale_state_temporal_bridge"
    assert score >= 0.87


def test_keyword_chunk_score_boosts_state_transition_bridge() -> None:
    plan = build_query_expansion_plan("What did Atlas switch from LocalAI to?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Atlas provider transition: LocalAI was replaced by OpenAI after "
            "the review. The current active provider is OpenAI, and LocalAI "
            "is no longer valid."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason in {"state_transition_bridge", "decomposition_state_transition"}
    assert relevance.distinctive_term_hits >= 7
    assert score > 0.9


def test_deterministic_rerank_prefers_explicit_state_transition_over_topic_note() -> None:
    query = "What changed after the Atlas call?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_note = _item(
        "atlas_after_call_topic",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="After the Atlas call, Alex reviewed provider notes for the launch.",
    )
    transition = _item(
        "atlas_provider_transition",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="After the Atlas call, Atlas changed from LocalAI to OpenAI.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_note, transition),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["atlas_provider_transition"].score > by_id["atlas_after_call_topic"].score
    assert (
        "state_transition_exact_evidence"
        in by_id["atlas_provider_transition"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_russian_explicit_state_transition() -> None:
    query = "Что изменилось после созвона по Атласу?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_note = _item(
        "atlas_after_call_topic_ru",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="После созвона по Атласу Алекс просмотрел заметки по провайдеру.",
    )
    transition = _item(
        "atlas_provider_transition_ru",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="После созвона по Атласу провайдер сменился с LocalAI на OpenAI.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_note, transition),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["atlas_provider_transition_ru"].score > by_id[
        "atlas_after_call_topic_ru"
    ].score
    assert (
        "state_transition_exact_evidence"
        in by_id["atlas_provider_transition_ru"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_keyword_chunk_score_boosts_age_birthday_bridge_for_how_old_query() -> None:
    plan = build_query_expansion_plan("How old is Alex?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex was born in 1992 and his birthday is in June.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "age_birthday_bridge"
    assert score >= 0.88


def test_keyword_chunk_score_boosts_age_birthday_bridge_for_russian_age_query() -> None:
    plan = build_query_expansion_plan("Сколько лет Алексу?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Алекс родился в 1992 году, день рождения у него в июне.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "age_birthday_bridge"
    assert score >= 0.86


def test_keyword_chunk_score_boosts_birthplace_bridge_for_where_born_query() -> None:
    plan = build_query_expansion_plan("Where was Alex born?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex was born in Sweden, his home country, before moving abroad.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "birthplace_origin_bridge"
    assert score >= 0.88


def test_birthplace_bridge_scores_location_evidence_above_birthdate_evidence() -> None:
    plan = build_query_expansion_plan("Where was Alex born?")
    _, location_reason, location_relevance = best_query_relevance(
        plan,
        text="Alex was born in Sweden, his home country, and grew up near Stockholm.",
    )
    _, birthdate_reason, birthdate_relevance = best_query_relevance(
        plan,
        text="Alex was born in 1992 and his birthday is in June.",
    )

    location_score = keyword_chunk_score(
        location_relevance,
        query_expansion_reason=location_reason,
    )
    birthdate_score = keyword_chunk_score(
        birthdate_relevance,
        query_expansion_reason=birthdate_reason,
    )

    assert location_reason == "birthplace_origin_bridge"
    assert location_score > birthdate_score


def test_keyword_chunk_score_boosts_current_residence_bridge() -> None:
    plan = build_query_expansion_plan("Where does Alex live now?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex currently lives in Berlin and is based in Germany now.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "current_residence_bridge"
    assert score >= 0.88


def test_current_residence_bridge_scores_current_home_above_birthplace() -> None:
    plan = build_query_expansion_plan("Where does Alex live now?")
    _, current_reason, current_relevance = best_query_relevance(
        plan,
        text="Alex currently lives in Berlin and calls Germany home now.",
    )
    _, birthplace_reason, birthplace_relevance = best_query_relevance(
        plan,
        text="Alex was born in Sweden, his home country, before moving abroad.",
    )

    current_score = keyword_chunk_score(
        current_relevance,
        query_expansion_reason=current_reason,
    )
    birthplace_score = keyword_chunk_score(
        birthplace_relevance,
        query_expansion_reason=birthplace_reason,
    )

    assert current_reason == "current_residence_bridge"
    assert current_score > birthplace_score


def test_keyword_chunk_score_boosts_relocation_destination_bridge() -> None:
    plan = build_query_expansion_plan("Where did Alex move to?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex moved to Berlin last year and settled in Germany.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "relocation_destination_bridge"
    assert score >= 0.86


def test_relocation_destination_bridge_scores_destination_above_origin() -> None:
    plan = build_query_expansion_plan("Where did Alex move to?")
    _, destination_reason, destination_relevance = best_query_relevance(
        plan,
        text="Alex moved to Berlin and settled in Germany.",
    )
    _, origin_reason, origin_relevance = best_query_relevance(
        plan,
        text="Alex moved from Sweden, his home country.",
    )

    destination_score = keyword_chunk_score(
        destination_relevance,
        query_expansion_reason=destination_reason,
    )
    origin_score = keyword_chunk_score(
        origin_relevance,
        query_expansion_reason=origin_reason,
    )

    assert destination_reason == "relocation_destination_bridge"
    assert destination_score > origin_score


def test_keyword_chunk_score_boosts_current_occupation_bridge() -> None:
    plan = build_query_expansion_plan("What does Alex do for work?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex works as a product designer and his current job is at Finch Labs.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "current_occupation_bridge"
    assert score >= 0.88


def test_current_occupation_bridge_scores_current_role_above_future_career_plan() -> None:
    plan = build_query_expansion_plan("What is Alex's job?")
    _, current_reason, current_relevance = best_query_relevance(
        plan,
        text="Alex works as a product designer and that is his current job.",
    )
    _, future_reason, future_relevance = best_query_relevance(
        plan,
        text="Alex wants to pursue a future career in counseling.",
    )

    current_score = keyword_chunk_score(
        current_relevance,
        query_expansion_reason=current_reason,
    )
    future_score = keyword_chunk_score(
        future_relevance,
        query_expansion_reason=future_reason,
    )

    assert current_reason == "current_occupation_bridge"
    assert current_score > future_score


def test_keyword_chunk_score_boosts_deadline_commitment_bridge() -> None:
    plan = build_query_expansion_plan("When is the Atlas launch deadline?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Meeting notes: Alex confirmed the Atlas launch deadline and due date is 2026-08-15."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "deadline_commitment_bridge"
    assert relevance.distinctive_term_hits >= 4
    assert score > 0.9


def test_keyword_chunk_score_boosts_followup_task_bridge() -> None:
    plan = build_query_expansion_plan("What action items came from the Atlas meeting?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Atlas meeting notes: action item task follow up is assigned to Alex "
            "as the owner responsible for sending the invoice."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "followup_task_bridge"
    assert relevance.distinctive_term_hits >= 5
    assert score > 0.89


def test_keyword_chunk_score_boosts_promise_commitment_bridge() -> None:
    plan = build_query_expansion_plan("What did Alex promise after Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Atlas call notes: Alex promised a follow up commitment to send "
            "the invoice by the due date."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "followup_task_bridge"
    assert relevance.distinctive_term_hits >= 6
    assert score > 0.91


def test_keyword_chunk_score_boosts_need_to_commitment_bridge() -> None:
    plan = build_query_expansion_plan("What does Alex need to do after Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Atlas call notes: Alex needs to send the invoice as the follow up "
            "action item."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "followup_task_bridge"
    assert relevance.distinctive_term_hits >= 5
    assert score > 0.9


def test_keyword_chunk_score_boosts_supposed_to_commitment_bridge() -> None:
    plan = build_query_expansion_plan("What is Alex supposed to do after Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Atlas call notes: Alex is supposed to send the invoice as the "
            "follow up action item."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "followup_task_bridge"
    assert relevance.distinctive_term_hits >= 5
    assert score > 0.89


def test_keyword_chunk_score_boosts_gotcha_failure_bridge() -> None:
    plan = build_query_expansion_plan("What should I watch out for in Atlas deployment?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Atlas deployment known issue gotcha pitfall: Docker failed with "
            "a blocker. Workaround root cause warning: wait for Qdrant health checks."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason in {"gotcha_failure_bridge", "decomposition_gotcha_failure"}
    assert relevance.distinctive_term_hits >= 6
    assert score > 0.92


def test_keyword_chunk_score_boosts_speaker_turn_bridge() -> None:
    plan = build_query_expansion_plan("What did Alex say about Project Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="D3:4 Alex: Project Atlas should wait until invoice approval.",
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "speaker_turn_bridge"
    assert score >= 0.87


def test_keyword_chunk_score_boosts_conversation_transcript_bridge() -> None:
    plan = build_query_expansion_plan("What did Alex mention in the DM about Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Transcript: Alex mentioned Project Atlas in the conversation. "
            "The message had one action item and a follow up."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "conversation_transcript_evidence_bridge"
    assert score >= 0.89


def test_keyword_chunk_score_boosts_covered_call_topic_evidence() -> None:
    plan = build_query_expansion_plan("What was discussed in the call about Atlas?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Transcript conversation covered Project Atlas migration risks and next steps."
        ),
    )

    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "event_summary_bridge"
    assert score >= 0.82


def test_query_expansion_reason_priority_promotes_exact_trait_evidence() -> None:
    assert query_expansion_reason_priority("personality_drive_bridge") > (
        query_expansion_reason_priority("decomposition_inference_support")
    )
    assert query_expansion_reason_priority("conversation_transcript_evidence_bridge") > (
        query_expansion_reason_priority("personality_trait_bridge")
    )
    assert query_expansion_reason_priority("age_birthday_bridge") > (
        query_expansion_reason_priority("personality_trait_bridge")
    )


def test_dedupe_rank_items_prefers_high_signal_reason_within_score_tolerance() -> None:
    generic = _item(
        "same_chunk",
        score=0.804,
        retrieval_source="keyword_chunks",
        score_signals={
            "query_expansion_reason": "personality_trait_bridge",
            "query_expansion_reason_priority": 2,
        },
    )
    transcript = _item(
        "same_chunk",
        score=0.8,
        retrieval_source="keyword_chunks",
        score_signals={
            "query_expansion_reason": "conversation_transcript_evidence_bridge",
            "query_expansion_reason_priority": 4,
        },
    )

    (merged,) = dedupe_rank_items((generic, transcript))

    assert merged.diagnostics["score_signals"]["query_expansion_reason"] == (
        "conversation_transcript_evidence_bridge"
    )
    assert merged.diagnostics["score_signals"]["query_expansion_reason_priority"] == 4


def test_dedupe_rank_items_prefers_strong_exact_source_sibling_body_over_aggregation() -> None:
    exact_turn = ContextItem(
        item_id="same_chunk",
        item_type="chunk",
        text="EXACT_D4_6 John stayed calm and asked for assistance.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-41:session_4:D4:6:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "attribute_calm_resourcefulness_bridge",
                "query_expansion_reason_priority": 4,
                "distinctive_term_hits": 9,
            },
        },
    )
    broad_aggregation = ContextItem(
        item_id="same_chunk",
        item_type="chunk",
        text="BROAD_SESSION_4 merged session context.",
        score=0.99,
        source_refs=(SourceRef(source_type="document", source_id="locomo:conv-41:session_4"),),
        diagnostics={
            "retrieval_source": "keyword_aggregation_chunks",
            "retrieval_sources": ["keyword_aggregation_chunks"],
            "score_signals": {
                "query_expansion_reason": "attribute_calm_resourcefulness_bridge",
                "query_expansion_reason_priority": 4,
                "distinctive_term_hits": 9,
            },
        },
    )

    (merged,) = dedupe_rank_items((broad_aggregation, exact_turn))

    assert "EXACT_D4_6" in merged.text
    assert "keyword_source_sibling_chunks" in merged.diagnostics["retrieval_sources"]
    assert "keyword_aggregation_chunks" in merged.diagnostics["retrieval_sources"]


def test_dedupe_rank_items_prefers_exact_turn_body_over_marker_stub() -> None:
    marker_stub = ContextItem(
        item_id="same_chunk",
        item_type="chunk",
        text="D10:9.",
        score=0.99,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_10:D10:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_inventory_list",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 4,
            },
        },
    )
    exact_body = ContextItem(
        item_id="same_chunk",
        item_type="chunk",
        text=(
            "D10:9 Riley: I have been testing out dairy-free dessert recipes "
            "for friends and family. Here's a pic of a cake I made recently!"
        ),
        score=0.97,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_10:D10:9:turn",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_inventory_list",
                "distinctive_term_hits": 2,
            },
        },
    )

    (merged,) = dedupe_rank_items((marker_stub, exact_body))

    assert "testing out dairy-free dessert recipes" in merged.text
    assert "keyword_source_sibling_chunks" in merged.diagnostics["retrieval_sources"]
    assert "keyword_chunks" in merged.diagnostics["retrieval_sources"]


def test_dedupe_rank_items_keeps_stronger_score_outside_tolerance() -> None:
    generic = _item(
        "same_chunk",
        score=0.84,
        retrieval_source="keyword_chunks",
        score_signals={
            "query_expansion_reason": "personality_trait_bridge",
            "query_expansion_reason_priority": 2,
        },
    )
    transcript = _item(
        "same_chunk",
        score=0.8,
        retrieval_source="keyword_chunks",
        score_signals={
            "query_expansion_reason": "conversation_transcript_evidence_bridge",
            "query_expansion_reason_priority": 4,
        },
    )

    (merged,) = dedupe_rank_items((generic, transcript))

    assert merged.diagnostics["score_signals"]["query_expansion_reason"] == (
        "personality_trait_bridge"
    )
    assert merged.diagnostics["score_signals"]["query_expansion_reason_priority"] == 2


def test_keyword_chunk_score_boosts_reliable_locomo_failure_bridges() -> None:
    cases = [
        (
            "What activities has Melanie done with her family?",
            (
                "Melanie took her kids to the museum, painted nature scenes, and "
                "roasted marshmallows on a family camping trip."
            ),
            "family_activity_bridge",
        ),
        (
            "Does John live close to a beach or the mountains?",
            (
                "John goes on weekly walks by the ocean and shared a sunset beach "
                "photo with a sailboat."
            ),
            "beach_or_mountains_inference_bridge",
        ),
        (
            "What job might Maria pursue in the future?",
            (
                "Maria volunteers at a homeless shelter front desk, gives talks, "
                "helps people, and finds it fulfilling."
            ),
            "volunteer_career_inference_bridge",
        ),
        (
            "What pets would not cause any discomfort to Joanna?",
            (
                "Joanna is allergic to reptiles and animals with fur, and even "
                "cockroaches make pets difficult."
            ),
            "pet_allergy_discomfort_bridge",
        ),
        (
            "What underlying condition might Joanna have based on her allergies?",
            (
                "Joanna is allergic to reptiles, animals with fur, cockroaches, "
                "and gets puffy and itchy."
            ),
            "allergy_condition_inference_bridge",
        ),
        (
            "What symbols are important to Caroline?",
            (
                "Caroline said the rainbow flag mural and eagle symbolize freedom, "
                "pride, courage, and resilience."
            ),
            "symbol_importance_bridge",
        ),
        (
            "What Console does Nate own?",
            ("Nate plays Xenoblade Chronicles, and the image caption shows Nintendo game covers."),
            "console_game_cover_bridge",
        ),
        (
            "What are the new shoes that Caroline got used for?",
            "Caroline asked whether the purple new shoes were for walking or running.",
            "shoe_usage_bridge",
        ),
        (
            "What is Melanie's reason for getting into running?",
            (
                "D7:20 Melanie said running longer helps her destress and clear "
                "her mind. D7:21 Caroline asked what got her into running."
            ),
            "running_reason_question_bridge",
        ),
        (
            "How did Caroline feel while watching the meteor shower?",
            "Watching the meteor shower made her feel tiny and in awe of the universe.",
            "meteor_shower_feeling_bridge",
        ),
        (
            "What transgender-specific events has Caroline attended?",
            (
                "Caroline attended a transgender poetry reading, a safe place for "
                "self expression and identities."
            ),
            "transgender_poetry_event_bridge",
        ),
        (
            "What transgender-specific events has Caroline attended?",
            (
                "Caroline said the transgender conference was a safe and supportive "
                "event for professionals in the community."
            ),
            "transgender_conference_event_bridge",
        ),
        (
            "What book did Melanie read from Caroline's suggestion?",
            (
                "Caroline recommended Becoming Nicole by Amy Ellis Nutt, a true "
                "story about a trans girl and family."
            ),
            "book_suggestion_bridge",
        ),
        (
            "What attributes describe John?",
            (
                "John gave food and supplies at a homeless shelter, organized a toy "
                "drive, stayed calm, and helped save a family from a burning building."
            ),
            "attribute_service_helpfulness_bridge",
        ),
        (
            "What types of pottery have Melanie and her kids made?",
            (
                "Melanie and the kids made pottery pieces from clay, including a "
                "painted bowl and a cup with a dog face."
            ),
            "pottery_type_bridge",
        ),
        (
            "Where did Caroline move from 4 years ago?",
            (
                "Caroline got a necklace from her grandma in her home country, "
                "Sweden, and it reminds her of her roots."
            ),
            "relocation_origin_bridge",
        ),
        (
            "Would John be open to moving to another country?",
            (
                "D7:2 John is running for office again and is excited about "
                "public service. D24:3 John heard inspiring stories from a "
                "veteran and remembered why he wanted to join the military."
            ),
            "relocation_willingness_inference_bridge",
        ),
        (
            "Would John be open to moving to another country?",
            (
                "D24:3 John heard cool stories from a veteran, saw resilience "
                "and hope, and remembered why he wanted to join the military."
            ),
            "military_service_willingness_bridge",
        ),
        (
            "Would John be considered a patriotic person?",
            (
                "D8:18 John retook the aptitude test with great results and "
                "felt drawn to serving his country; the photo showed a flag "
                "and eagle."
            ),
            "patriotic_service_inference_bridge",
        ),
        (
            "Who supports Caroline when she has a negative experience?",
            (
                "Caroline's friends, family and mentors are her rocks. They "
                "motivate her and give her strength to push on."
            ),
            "negative_experience_support_bridge",
        ),
        (
            "What symbols are important to Caroline?",
            ("Caroline shared a pendant necklace with a transgender symbol, a cross, and a heart."),
            "symbol_importance_bridge",
        ),
        (
            "Would Caroline likely have Dr. Seuss books on her bookshelf?",
            (
                "Caroline has lots of kids' books, classics, stories from different "
                "cultures, and educational books."
            ),
            "children_books_inference_bridge",
        ),
        (
            "What subject have Caroline and Melanie both painted?",
            (
                "Caroline shared a photo of a painting of a sunset on a small easel, "
                "a finished painted subject."
            ),
            "shared_painted_subject_bridge",
        ),
        (
            "Would Melanie likely enjoy the song The Four Seasons by Vivaldi?",
            ("Melanie is a fan of classical music like Bach and Mozart, plus modern music."),
            "classical_music_preference_bridge",
        ),
        (
            "What activities does Melanie partake in?",
            (
                "Melanie went camping with her fam, unplugged, and hung with the "
                "kids after a quiet weekend."
            ),
            "decomposition_activity_participation",
        ),
        (
            "When did Melanie go camping in June?",
            (
                "session_4 date: 10:37 am on 27 June, 2023. D4:8 Melanie "
                "explored nature, roasted marshmallows around the campfire, "
                "and even went on a hike with her family."
            ),
            "temporal_event_detail_bridge",
        ),
        (
            "Would Caroline be considered religious?",
            (
                "D14:19 Caroline: It was made for a local church and shows time "
                "changing our lives. I made it to show my own journey as a "
                "transgender woman and how we should accept growth and change."
            ),
            "religious_inference_bridge",
        ),
    ]

    for query, text, expected_reason in cases:
        plan = build_query_expansion_plan(query)
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        assert reason == expected_reason
        assert score >= 0.88


def test_deterministic_rerank_prefers_temporal_camping_event_details() -> None:
    query = "When did Melanie go camping in June?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    raw_event_detail = _item(
        "d4_8_campfire_detail",
        score=0.9275,
        retrieval_source="keyword_chunks",
        text=(
            "D4:8 Melanie: It was an awesome time, Caroline! We explored "
            "nature, roasted marshmallows around the campfire and even went "
            "on a hike. The view from the top was amazing! The 2 younger "
            "kids love nature. It was so special having these moments "
            "together as a family - I'll never forget it!"
        ),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_4:D4:8:turn",
            ),
        ),
    )
    literal_topic = _item(
        "literal_topic",
        score=0.8985,
        retrieval_source="keyword_chunks",
        text=(
            "D9:1 Melanie: I went camping with my family last weekend and "
            "talked about June plans."
        ),
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-26:session_9:D9:1:turn",
            ),
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (literal_topic, raw_event_detail),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["d4_8_campfire_detail"].score > by_id["literal_topic"].score
    assert (
        "temporal_camping_detail_evidence"
        in by_id["d4_8_campfire_detail"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_relocation_origin_bridge_does_not_overrank_family_home_decoys() -> None:
    plan = build_query_expansion_plan("Where did Caroline move from 4 years ago?")
    _, origin_reason, origin_relevance = best_query_relevance(
        plan,
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and it reminds me of my roots."
        ),
    )
    _, decoy_reason, decoy_relevance = best_query_relevance(
        plan,
        text=(
            "D19:5 Caroline: My dream is to create a safe and loving home for "
            "these kids, with love and acceptance for everyone."
        ),
    )

    assert origin_reason == "relocation_origin_bridge"
    assert decoy_reason == "relocation_origin_bridge"
    assert keyword_chunk_score(
        origin_relevance,
        query_expansion_reason=origin_reason,
    ) > keyword_chunk_score(
        decoy_relevance,
        query_expansion_reason=decoy_reason,
    )
    assert origin_relevance.distinctive_term_hits > decoy_relevance.distinctive_term_hits


def test_religious_inference_bridge_beats_generic_current_goal_decoys() -> None:
    plan = build_query_expansion_plan("Would Caroline be considered religious?")
    _, religious_reason, religious_relevance = best_query_relevance(
        plan,
        text=(
            "D14:19 Caroline: It was made for a local church and shows time "
            "changing our lives. I made it to show my own journey as a "
            "transgender woman and how we should accept growth and change."
        ),
    )
    _, decoy_reason, decoy_relevance = best_query_relevance(
        plan,
        text=(
            "D7:7 Caroline: I struggled with mental health, and support I got "
            "was really helpful, so I started looking into counseling jobs."
        ),
    )

    assert religious_reason == "religious_inference_bridge"
    assert decoy_reason != "decomposition_current_preference_or_goal"
    assert keyword_chunk_score(
        religious_relevance,
        query_expansion_reason=religious_reason,
    ) > keyword_chunk_score(
        decoy_relevance,
        query_expansion_reason=decoy_reason,
    )


def test_deterministic_rerank_prefers_children_books_inference_evidence() -> None:
    query = "Would Caroline likely have Dr. Seuss books on her bookshelf?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    children_books = _item(
        "children_books",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline has lots of kids' books, classics, stories from different "
            "cultures, and educational books."
        ),
    )
    generic_bookshelf = _item(
        "generic_bookshelf",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline's bookshelf includes fantasy novels, Game of Thrones, "
            "and several long series she finished."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (children_books, generic_bookshelf),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["children_books"].score > by_id["generic_bookshelf"].score
    assert (
        "inference_children_books_fit_evidence"
        in by_id["children_books"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "inference_children_books_topic_only_noise"
        in by_id["generic_bookshelf"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_religious_inference_evidence() -> None:
    query = "Would Caroline be considered religious?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    church_evidence = _item(
        "church_evidence",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D14:19 Caroline: It was made for a local church and shows time "
            "changing our lives. I made it to show my own journey as a "
            "transgender woman and how we should accept growth and change."
        ),
    )
    topical_journey = _item(
        "topical_journey",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D15:4 Caroline described her transgender journey, acceptance, "
            "growth, and how her life changed after the interview."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (church_evidence, topical_journey),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["church_evidence"].score > by_id["topical_journey"].score
    assert (
        "inference_religious_fit_evidence"
        in by_id["church_evidence"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_religious_topic_only_noise"
        in by_id["topical_journey"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_keeps_religious_contrast_evidence_below_direct_fit() -> None:
    query = "Would Caroline be considered religious?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    church_evidence = _item(
        "church_evidence",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline made stained glass artwork for a local church.",
    )
    political_noise = _item(
        "political_noise",
        score=0.73,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline said religious conservatives made her feel unwelcoming "
            "during her transgender journey."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (church_evidence, political_noise),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["church_evidence"].score > by_id["political_noise"].score
    assert (
        "inference_religious_contrast_evidence"
        in by_id["political_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_keyword_chunk_source_score_boost_prefers_activity_observations() -> None:
    plan = build_query_expansion_plan("What activities does Melanie partake in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "session_9 observations | D9:1 Melanie went camping with her family "
            "two weekends ago. D9:1 Melanie enjoys unplugging and hanging out "
            "with her kids. D9:17 Melanie and her kids finished a painting."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_9:observation",
    )

    assert reason == "decomposition_activity_participation"
    assert (
        keyword_chunk_source_score_boost(
            relevance,
            query_expansion_reason=reason,
            source_external_id="locomo:conv-26:session_9:observation",
        )
        > 0
    )
    assert boost > 0
    assert boost >= 0.09
    assert boosted >= 0.99
    assert boosted > score


def test_keyword_chunk_source_score_boost_prefers_item_purchase_observations() -> None:
    plan = build_query_expansion_plan("What items has Melanie bought?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "session_19 observations | D19:2 Melanie bought family figurines "
            "yesterday. D7:18 Melanie got some new shoes."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_19:observation",
    )

    assert reason == "item_purchase_bridge"
    assert boost > 0
    assert boosted > score


def test_keyword_chunk_source_score_boost_prefers_animal_career_observations() -> None:
    plan = build_query_expansion_plan("What alternative career might Nate consider after gaming?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "session_25 observations | D25:19 Nate's turtles have a varied diet "
            "including vegetables, fruits, and insects. D28:25 Nate has a third "
            "turtle as a pet and enjoys turtles as companions."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-42:session_25:observation",
    )

    assert reason == "animal_affinity_pet_store_bridge"
    assert boost > 0
    assert boosted > score


def test_keyword_chunk_source_score_boost_prefers_event_summary_docs() -> None:
    plan = build_query_expansion_plan("What events has Caroline participated in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "session_4 events | Caroline participated in LGBTQ community advocacy "
            "campaigns and joined a youth mentorship program."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-12:session_4:events",
    )

    assert reason == "event_participation_bridge"
    assert boost > 0
    assert boosted > score


def test_keyword_chunk_source_score_boost_allows_strong_exact_activity_turns() -> None:
    plan = build_query_expansion_plan("What activities does Melanie partake in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D9:1 Melanie went camping with her family two weekends ago and "
            "enjoyed unplugging with her kids."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_9:D9:1:turn",
    )

    assert boost > 0
    assert boosted > score


def test_keyword_chunk_source_score_boost_prefers_family_hike_observations() -> None:
    plan = build_query_expansion_plan("What does Melanie do with her family on hikes?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "session_10 observations | Melanie's family camping trip included "
            "roasting marshmallows and telling stories around the campfire."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_10:observation",
    )

    assert reason == "family_hike_activity_bridge"
    assert boost > 0
    assert boosted > score


def test_broad_attribute_query_prefers_specific_attribute_facets() -> None:
    plan = build_query_expansion_plan("What attributes describe John?")
    cases = [
        (
            (
                "D2:14 John: Yeah, they are my rock in tough times and always "
                "cheer me on. I'm really thankful for their love. Family time "
                "means a lot to me."
            ),
            "attribute_family_support_bridge",
            0.9,
        ),
        (
            (
                "D4:6 John: I tried to stay calm and asked for assistance, "
                "which helped me handle the situation and make it back safely."
            ),
            "attribute_calm_resourcefulness_bridge",
            0.9,
        ),
        (
            (
                "D3:5 John: We went to a homeless shelter to give out food and "
                "supplies and organized a toy drive for kids in need."
            ),
            "attribute_service_helpfulness_bridge",
            0.9,
        ),
        (
            (
                "D26:6 John: We pulled together. I got a surge of energy and "
                "purpose, and we were able to save a family from a burning building."
            ),
            "attribute_rescue_purpose_bridge",
            0.9,
        ),
        (
            (
                "D15:3 John: I feel passionate about supporting veterans and "
                "their rights through public service."
            ),
            "attribute_trait_inventory_bridge",
            0.88,
        ),
        (
            (
                "D9:8 John: Education and infrastructure policy interest me, "
                "and I like thinking through the tradeoffs rationally."
            ),
            "attribute_trait_inventory_bridge",
            0.88,
        ),
    ]

    for text, expected_reason, expected_min_score in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == expected_reason
        assert (
            keyword_chunk_score(relevance, query_expansion_reason=reason)
            >= expected_min_score
        )


def test_attribute_source_boost_prefers_precise_evidence_over_session_summary() -> None:
    plan = build_query_expansion_plan("What attributes describe John?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:6 John: I tried to stay calm and asked for assistance, "
            "which helped me handle the situation and make it back safely."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    precise_boosted, precise_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_4:D4:6:turn",
    )
    summary_boosted, summary_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_4:summary",
    )

    assert reason == "attribute_calm_resourcefulness_bridge"
    assert precise_boost > 0
    assert precise_boosted > score
    assert summary_boost == 0.0
    assert summary_boosted == score


def test_allergy_condition_source_boost_prefers_precise_evidence_turn() -> None:
    plan = build_query_expansion_plan(
        "What underlying condition might Joanna have based on her allergies?"
    )
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D2:23 Joanna: I'm allergic to most reptiles and animals with fur. "
            "It can be a bit of a drag."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-42:session_2:D2:23:turn",
    )

    assert reason == "allergy_condition_inference_bridge"
    assert boost > 0
    assert boosted > score


def test_allergy_condition_rerank_penalizes_weak_evidence_overlap() -> None:
    query = "What underlying condition might Joanna have based on her allergies?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    strong = _item(
        "strong",
        score=0.93,
        retrieval_source="keyword_chunks",
        text=(
            "D2:23 Joanna: I'm allergic to most reptiles and animals with fur. "
            "It can be a bit of a drag."
        ),
    )
    weak = _item(
        "weak",
        score=0.93,
        retrieval_source="keyword_source_sibling_chunks",
        text="D13:14 Joanna: That cute stuffed animal is a nice reminder.",
    )

    ranked_strong, ranked_weak = apply_deterministic_rerank_adjustments(
        (strong, weak),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )

    assert ranked_strong.score > ranked_weak.score
    assert "allergy_condition_weak_evidence" in (
        ranked_weak.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_allergy_condition_evidence() -> None:
    query = "What underlying condition might Joanna have based on her allergies?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    strong = _item(
        "strong",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D2:23 Joanna: I'm allergic to most reptiles and animals with fur. "
            "My face gets puffy and itchy."
        ),
    )
    topic_only = _item(
        "topic_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D2:24 Joanna: I keep cute reptile photos and animal drawings as reminders.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (strong, topic_only),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["strong"].score > by_id["topic_only"].score
    assert (
        "inference_allergy_condition_evidence"
        in by_id["strong"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "inference_allergy_condition_topic_only_noise"
        in by_id["topic_only"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_personality_source_boost_prefers_precise_trait_turn_over_session_summary() -> None:
    plan = build_query_expansion_plan("What personality traits might Melanie say Caroline has?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D7:4 Melanie: Wow, Caroline. We've come so far, but there's more to do. "
            "Your drive to help is awesome! What's your plan to pitch in?"
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    precise_boosted, precise_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_7:D7:4:turn",
    )
    summary_boosted, summary_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_7:summary",
    )
    observation_boosted, observation_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_7:observation",
    )

    assert reason == "personality_drive_bridge"
    assert precise_boost > 0
    assert precise_boosted > score
    assert summary_boost == 0.0
    assert summary_boosted == score
    assert observation_boost == 0.0
    assert observation_boosted == score


def test_volunteer_career_source_boost_prefers_precise_evidence_over_session_summary() -> None:
    plan = build_query_expansion_plan("What job might Maria pursue in the future?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D11:10 Maria: I recently gave a few talks at the homeless shelter "
            "I volunteer at. It was fulfilling and I received compliments from "
            "other volunteers."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    precise_boosted, precise_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_11:D11:10:turn",
    )
    summary_boosted, summary_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_11:summary",
    )

    assert reason == "volunteer_career_inference_bridge"
    assert precise_boost > 0
    assert precise_boosted > score
    assert summary_boost == 0.0
    assert summary_boosted == score


def test_degree_policy_source_boost_prefers_precise_evidence_over_summary() -> None:
    plan = build_query_expansion_plan("What might John's degree be in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D9:6 John: I'm considering going into policymaking because of my "
            "degree and my passion for making a positive impact."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    precise_boosted, precise_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_9:D9:6:turn",
    )
    summary_boosted, summary_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_9:summary",
    )

    assert reason == "degree_policy_inference_bridge"
    assert precise_boost > 0
    assert precise_boosted > score
    assert summary_boost == 0.0
    assert summary_boosted == score


def test_exercise_activity_source_boost_accepts_exact_single_activity_turn() -> None:
    plan = build_query_expansion_plan("What martial arts has John done?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="D2:28 John: I'm off to do some taekwondo!",
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_2:D2:28:turn",
    )

    assert reason == "exercise_activity_inventory_bridge"
    assert relevance.distinctive_term_hits >= 2
    assert boost > 0
    assert boosted > score


def test_deterministic_rerank_prefers_exercise_performance_transfer_evidence() -> None:
    query = "What other exercises can help John with his basketball performance?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    social_strength_noise = _item(
        "john_family_strength",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="John's family supports him and gives him strength before big games.",
    )
    yoga_transfer = _item(
        "john_yoga_transfer",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "John is trying out yoga to get a little extra strength and flexibility. "
            "It is challenging but worth it."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (social_strength_noise, yoga_transfer),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["john_yoga_transfer"].score > by_id["john_family_strength"].score
    assert (
        "exercise_performance_transfer_evidence"
        in by_id["john_yoga_transfer"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "exercise_performance_social_strength_noise"
        in by_id["john_family_strength"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_state_residence_source_boost_prefers_precise_map_turn() -> None:
    plan = build_query_expansion_plan("Which US state do Audrey and Andrew potentially live in?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D11:9 Andrew image caption: a photo of a map of a park with a lot "
            "of trees. Andrew image query: hiking trails map perfect spot. "
            "Here is the map for the trail."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-44:session_11:D11:9:turn",
    )
    observation_boosted, observation_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-44:session_11:observation",
    )

    assert reason == "state_residence_inference_bridge"
    assert boost > 0
    assert boosted > score
    assert observation_boost == 0.0
    assert observation_boosted == score


def test_national_park_source_boost_prefers_precise_visual_turns() -> None:
    plan = build_query_expansion_plan(
        "Which national park could Audrey and Andrew be referring to in their conversations?"
    )
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D11:9 Andrew: Here is the map for the trail. image caption: "
            "a photo of a map of a park with a lot of trees. visual query: "
            "hiking trails map perfect spot."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-44:session_11:D11:9:turn",
    )
    observation_boosted, observation_boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-44:session_11:observation",
    )

    assert reason == "national_park_inference_bridge"
    assert boost > 0
    assert boosted > score
    assert observation_boost == 0.0
    assert observation_boosted == score


def test_deterministic_rerank_prefers_state_residence_geo_evidence() -> None:
    query = "Which US state do Audrey and Andrew potentially live in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    technical_noise = _item(
        "andrew_state_machine_noise",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="Andrew talked about a state machine and map code in the app repository.",
    )
    map_evidence = _item(
        "andrew_map_trail",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Andrew image caption: a photo of a map of a park with a lot of "
            "trees. Andrew image query: hiking trails map perfect spot."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (technical_noise, map_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["andrew_map_trail"].score > by_id["andrew_state_machine_noise"].score
    assert (
        "inference_state_residence_geo_evidence"
        in by_id["andrew_map_trail"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_state_residence_technical_noise"
        in by_id["andrew_state_machine_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_national_park_visual_inference_evidence() -> None:
    query = "Which national park could Audrey and Andrew be referring to in their conversations?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic_park_noise = _item(
        "generic_city_park",
        score=0.77,
        retrieval_source="keyword_chunks",
        text="Andrew went to a city park with his dog after work.",
    )
    national_park_turn = _item(
        "audrey_national_park_trip",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D5:8 Audrey: Last Friday we took a road trip - we went to a "
            "beautiful national park and my dogs had a blast. image caption: "
            "three dogs running through a field of grass. visual query: "
            "dogs playing field flowers national park."
        ),
    )
    trail_map_turn = _item(
        "andrew_trail_map",
        score=0.71,
        retrieval_source="keyword_chunks",
        text=(
            "D11:9 Andrew: Here is the map for the trail. image caption: "
            "a photo of a map of a park with a lot of trees. visual query: "
            "hiking trails map perfect spot."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_park_noise, national_park_turn, trail_map_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["audrey_national_park_trip"].score > by_id["generic_city_park"].score
    assert by_id["andrew_trail_map"].score > by_id["generic_city_park"].score
    assert (
        "national_park_exact_evidence"
        in by_id["audrey_national_park_trip"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "national_park_visual_trail_map_evidence"
        in by_id["andrew_trail_map"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "national_park_generic_park_noise"
        in by_id["generic_city_park"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_named_state_city_residence_evidence() -> None:
    query = "Does James live in Connecticut?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    technical_noise = _item(
        "james_state_machine_noise",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="James mentioned Connecticut while debugging state machine code in the app.",
    )
    city_evidence = _item(
        "james_stamford_shelter",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="James adopted a pup from a shelter in Stamford last week and named it Ned.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (technical_noise, city_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["james_stamford_shelter"].score > by_id["james_state_machine_noise"].score
    assert (
        "inference_state_residence_city_state_evidence"
        in by_id["james_stamford_shelter"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_state_residence_technical_noise"
        in by_id["james_state_machine_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_political_values_evidence() -> None:
    query = "What would Caroline's political leaning likely be?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_noise = _item(
        "caroline_political_news",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="Caroline discussed political news but did not share any views.",
    )
    values_evidence = _item(
        "caroline_political_values",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline said religious conservatives made her feel unwelcoming "
            "about her transition and LGBTQ rights."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_noise, values_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_political_values"].score > by_id["caroline_political_news"].score
    assert (
        "inference_political_values_evidence"
        in by_id["caroline_political_values"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_political_topic_only_noise"
        in by_id["caroline_political_news"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_identity_self_evidence() -> None:
    query = "What is Caroline's identity?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    direct_identity = _item(
        "caroline_identity",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline is a transgender woman embracing her true self and gender identity.",
    )
    support_group_topic = _item(
        "caroline_support_group",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Caroline went to an LGBTQ support group and felt accepted.",
    )
    pride_topic = _item(
        "caroline_pride_mural",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Caroline saw a transgender pride flag mural.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (support_group_topic, pride_topic, direct_identity),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_identity"].score > by_id["caroline_support_group"].score
    assert by_id["caroline_identity"].score > by_id["caroline_pride_mural"].score
    assert (
        "identity_exact_evidence"
        in by_id["caroline_identity"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "identity_topic_only_evidence"
        in by_id["caroline_support_group"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_community_membership_evidence() -> None:
    query = "Would Melanie be considered a member of the LGBTQ community?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    ally_noise = _item(
        "melanie_ally_noise",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Melanie is supportive of Caroline and encourages the LGBTQ community as an ally.",
    )
    pride_ally_noise = _item(
        "melanie_pride_ally_noise",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Melanie went to a pride event as an ally.",
    )
    membership = _item(
        "melanie_lgbtq_membership",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Melanie identifies as part of the LGBTQ community and joined "
            "the pride support group."
        ),
    )
    topic_noise = _item(
        "melanie_community_event",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie attended a public community fundraiser downtown.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (ally_noise, pride_ally_noise, topic_noise, membership),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_lgbtq_membership"].score > by_id["melanie_ally_noise"].score
    assert by_id["melanie_lgbtq_membership"].score > by_id[
        "melanie_pride_ally_noise"
    ].score
    assert by_id["melanie_lgbtq_membership"].score > by_id["melanie_community_event"].score
    assert (
        "inference_community_membership_evidence"
        in by_id["melanie_lgbtq_membership"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_community_membership_ally_noise"
        in by_id["melanie_ally_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_community_membership_ally_noise"
        in by_id["melanie_pride_ally_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_community_membership_topic_only_noise"
        in by_id["melanie_community_event"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_keyword_chunk_source_score_boost_prefers_inference_observations() -> None:
    cases = [
        (
            "What attributes describe John?",
            (
                "session_4 observations | D4:2 D4:6 John handled an unexpected "
                "incident by staying calm and asking for assistance. D26:6 John "
                "helped save a family from a burning building and made a difference."
            ),
            "attribute_calm_resourcefulness_bridge",
        ),
        (
            "What types of pottery have Melanie and her kids made?",
            (
                "session_8 observations | D5:6 D5:8 Melanie made a pottery bowl "
                "in class. D8:4 Melanie and her kids made a clay cup with a dog face."
            ),
            "pottery_type_bridge",
        ),
        (
            "How many hikes has Joanna been on?",
            (
                "session_28 observations | D7:6 Joanna saw a sunset while hiking. "
                "D11:5 Joanna loved a spot on the hike. D28:22 Joanna took a sunset "
                "picture on a hike near Fort Wayne."
            ),
            "hike_count_activity_bridge",
        ),
        (
            "What transgender-specific events has Caroline attended?",
            (
                "session_17 observations | D17:13 D17:17 D17:19 Caroline recently "
                "went to a transgender poetry reading event that was empowering."
            ),
            "transgender_poetry_event_bridge",
        ),
        (
            "What transgender-specific events has Caroline attended?",
            (
                "session_15 observations | D15:3 D15:9 D15:11 D15:13 Caroline "
                "volunteered at an LGBTQ youth center and helped organize a talent "
                "show for the kids with a band on stage."
            ),
            "transgender_youth_center_event_bridge",
        ),
        (
            "Would Caroline want to move back to her home country soon?",
            (
                "session_19 observations | D19:1 Caroline passed the adoption "
                "agency interviews last Friday. D19:3 Caroline wants to build "
                "her own family and put a roof over kids through adoption."
            ),
            "adoption_current_goal_bridge",
        ),
        (
            "What symbols are important to Caroline?",
            (
                "session_14 observations | D14:13 Caroline cares about the "
                "rainbow flag mural and eagle because they symbolize freedom, "
                "pride, courage, and resilience."
            ),
            "symbol_importance_bridge",
        ),
        (
            "How did Caroline feel while watching the meteor shower?",
            (
                "session_10 observations | D10:18 Caroline watched a meteor "
                "shower on a camping trip and felt tiny and in awe of the universe."
            ),
            "meteor_shower_feeling_bridge",
        ),
    ]

    for query, text, expected_reason in cases:
        plan = build_query_expansion_plan(query)
        _, reason, relevance = best_query_relevance(plan, text=text)
        score = keyword_chunk_score(relevance, query_expansion_reason=reason)

        boosted, boost = apply_keyword_chunk_source_score_boost(
            score,
            relevance,
            query_expansion_reason=reason,
            source_external_id="locomo:conv-x:session_1:observation",
        )

        assert reason == expected_reason
        assert boost > 0
        assert boosted > score


def test_deterministic_rerank_prefers_symbol_importance_evidence() -> None:
    query = "What symbols are important to Caroline?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    meaning_evidence = _item(
        "meaning_evidence",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline said the rainbow flag mural and eagle symbolize freedom, "
            "pride, courage, and resilience."
        ),
    )
    technical_symbol = _item(
        "technical_symbol",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline documented an important unicode symbol icon in the UI interface.",
    )
    personal_object = _item(
        "personal_object",
        score=0.69,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline shared a pendant necklace with a transgender symbol, "
            "a cross, and a heart."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (meaning_evidence, technical_symbol, personal_object),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["meaning_evidence"].score > by_id["technical_symbol"].score
    assert by_id["personal_object"].score > by_id["technical_symbol"].score
    assert (
        "symbol_importance_exact_evidence"
        in by_id["meaning_evidence"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "symbol_importance_personal_object"
        in by_id["personal_object"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "symbol_importance_weak_evidence"
        in by_id["technical_symbol"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_boosts_visual_symbol_object_evidence() -> None:
    query = "What symbols are important to Caroline?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    visual_object = _item(
        "visual_symbol_object",
        score=0.69,
        retrieval_source="keyword_chunks",
        text=(
            "D4:1 Caroline shared an image. visual query: pendant necklace "
            "with transgender symbol, cross, and heart."
        ),
    )
    topic_only = _item(
        "technical_symbol",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline documented an important unicode symbol icon in the UI interface.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, visual_object),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["visual_symbol_object"].score > by_id["technical_symbol"].score
    assert (
        "symbol_importance_visual_object"
        in by_id["visual_symbol_object"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        by_id["visual_symbol_object"].diagnostics["score_signals"][
            "symbol_importance_visual_evidence"
        ]
        == 3.0
    )


def test_context_rank_key_prefers_visual_symbol_evidence_over_necklace_meaning() -> None:
    query = "What symbols are important to Caroline?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    visual_object = _item(
        "visual_symbol_object",
        score=0.99,
        retrieval_source="keyword_chunks",
        text=(
            "D4:1 Caroline shared an image. image caption: a person holding "
            "a necklace with a cross and a heart. visual query: pendant "
            "transgender symbol."
        ),
    )
    necklace_meaning = _item(
        "necklace_meaning",
        score=0.99,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D4:3 Caroline: This necklace is special and stands for love, "
            "faith, strength, and family roots."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (necklace_meaning, visual_object),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert (
        context_rank_key(by_id["visual_symbol_object"])
        < context_rank_key(by_id["necklace_meaning"])
    )


def test_deterministic_rerank_prefers_symbol_meaning_evidence() -> None:
    query = "What does Caroline's necklace symbolize?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    meaning_evidence = _item(
        "necklace_meaning",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D4:3 Caroline: This necklace is a gift from my grandma in my home "
            "country. It stands for love, faith and strength, and reminds me "
            "of my roots."
        ),
    )
    object_only = _item(
        "necklace_object_only",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="D8:2 Caroline wore a necklace in the photo and smiled.",
    )
    technical_symbol = _item(
        "technical_symbol",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline documented what the necklace icon symbol means in the UI.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (meaning_evidence, object_only, technical_symbol),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["necklace_meaning"].score > by_id["technical_symbol"].score
    assert by_id["necklace_meaning"].score > by_id["necklace_object_only"].score
    assert (
        "symbol_importance_exact_evidence"
        in by_id["necklace_meaning"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "symbol_importance_weak_evidence"
        in by_id["technical_symbol"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_patriotic_service_source_boost_accepts_precise_turn_evidence() -> None:
    plan = build_query_expansion_plan("Would John be considered a patriotic person?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D8:18 John retook the aptitude test with great results and felt "
            "drawn to serving his country. The image caption shows a flag and eagle."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-41:session_8:D8:18:turn",
    )

    assert reason == "patriotic_service_inference_bridge"
    assert boost > 0
    assert boosted > score


def test_patriotic_service_bridge_matches_supportive_volunteer_followup() -> None:
    plan = build_query_expansion_plan("Would John be considered a patriotic person?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D8:20 John chatted with family and friends. They were supportive "
            "and understand why he wants to volunteer, and he is proud to have "
            "this opportunity."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "patriotic_service_inference_bridge"
    assert score >= 0.9


def test_patriotic_service_rerank_penalizes_weak_support_overlap() -> None:
    query = "Would John be considered a patriotic person?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    strong = _item(
        "strong",
        score=0.93,
        retrieval_source="keyword_chunks",
        text="D8:18 John felt drawn to serving his country after an aptitude test.",
    )
    weak = _item(
        "weak",
        score=0.93,
        retrieval_source="keyword_chunks",
        text="D3:11 John mentioned a volunteer opportunity.",
    )

    ranked_strong, ranked_weak = apply_deterministic_rerank_adjustments(
        (strong, weak),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )

    assert ranked_strong.score > ranked_weak.score
    assert "patriotic_service_weak_evidence" in (
        ranked_weak.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_patriotic_service_evidence_over_symbol_topic() -> None:
    query = "Would John be considered a patriotic person?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    service_evidence = _item(
        "service_evidence",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D8:18 John retook the aptitude test and felt drawn to serving "
            "his country."
        ),
    )
    symbol_topic = _item(
        "symbol_topic",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="The image caption shows a flag and eagle in John's notebook.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (service_evidence, symbol_topic),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["service_evidence"].score > by_id["symbol_topic"].score
    assert (
        "inference_patriotic_service_fit_evidence"
        in by_id["service_evidence"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_patriotic_topic_only_noise"
        in by_id["symbol_topic"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_running_reason_rerank_penalizes_weak_emotion_overlap() -> None:
    query = "What is Melanie's reason for getting into running?"
    plan = build_query_expansion_plan(query)
    query_anchor_intent = build_query_anchor_intent(query)
    strong = _item(
        "strong",
        score=0.93,
        retrieval_source="keyword_chunks",
        text=(
            "D7:20 Melanie has been running longer because it helps her "
            "destress and clear her mind."
        ),
    )
    weak = _item(
        "weak",
        score=0.93,
        retrieval_source="keyword_source_sibling_chunks",
        text="D2:5 Running helps destress.",
    )

    ranked_strong, ranked_weak = apply_deterministic_rerank_adjustments(
        (strong, weak),
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
    )

    assert ranked_strong.score > ranked_weak.score
    assert "running_reason_weak_evidence" in (
        ranked_weak.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_running_reason_question_bridge_matches_short_question_turn() -> None:
    plan = build_query_expansion_plan("What is Caroline's reason for getting into running?")
    _, reason, relevance = best_query_relevance(
        plan,
        text="D7:21 Caroline: Wow! What got you into running?",
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    assert reason == "running_reason_question_bridge"
    assert score >= 0.86


def test_activity_source_boost_accepts_exact_turn_evidence() -> None:
    plan = build_query_expansion_plan("What activities has Melanie done with her family?")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D1:18 Melanie: Taking care of ourselves is vital. "
            "I'm off to go swimming with the kids."
        ),
    )
    score = keyword_chunk_score(relevance, query_expansion_reason=reason)

    boosted, boost = apply_keyword_chunk_source_score_boost(
        score,
        relevance,
        query_expansion_reason=reason,
        source_external_id="locomo:conv-26:session_1:D1:18:turn",
    )

    assert reason in {"activity_visual_selfcare_bridge", "family_swimming_activity_bridge"}
    assert boost > 0
    assert boosted > score


def test_query_anchor_intent_boost_prefers_matching_entity_evidence() -> None:
    melanie = _item(
        "melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie is supportive, encouraging, and helps Caroline feel accepted.",
    )
    caroline = _item(
        "caroline",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline is supportive, encouraging, and helps the community.",
    )
    intent = build_query_anchor_intent("Would Melanie be considered an ally?")

    boosted = apply_query_anchor_intent_boosts((melanie, caroline), intent=intent)

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["score_signals"]["query_anchor_intent_boost"] > 0
    assert boosted[0].diagnostics["provenance"]["query_anchor_intent_reasons"] == [
        "query_person_identity_match"
    ]


def test_query_anchor_intent_boost_rejects_wrong_person_same_project() -> None:
    wrong_person = _item(
        "wrong_person",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Dana discussed Project Atlas launch notes yesterday.",
    )
    intent = build_query_anchor_intent("What did Alex say about Project Atlas?")

    boosted = apply_query_anchor_intent_boosts((wrong_person,), intent=intent)

    assert boosted == (wrong_person,)


def test_query_anchor_intent_boost_does_not_apply_twice() -> None:
    item = _item(
        "melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie is supportive, encouraging, and helps Caroline feel accepted.",
    )
    intent = build_query_anchor_intent("Would Melanie be considered an ally?")

    first_pass = apply_query_anchor_intent_boosts((item,), intent=intent)
    second_pass = apply_query_anchor_intent_boosts(first_pass, intent=intent)

    assert second_pass[0].score == first_pass[0].score


def test_context_requirement_boost_prefers_requested_image_text_evidence() -> None:
    generic = _item(
        "generic",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Atlas billing changed in a broad planning note.",
    )
    image_evidence = ContextItem(
        item_id="artifact_image_ocr",
        item_type="extraction_artifact",
        text="Screenshot OCR detected text: Atlas billing threshold is 25k.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="image-1",
                chunk_id="ocr-region-1",
                bbox=(10.0, 20.0, 120.0, 80.0),
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence"],
            "evidence_modality": "image",
            "evidence_kind": "ocr_region",
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["artifact_evidence"]},
        },
    )
    query = "What text is written in the screenshot about Atlas?"

    boosted = apply_context_requirement_boosts(
        (generic, image_evidence),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > image_evidence.score
    assert boosted[1].score > boosted[0].score
    assert (
        boosted[1].diagnostics["score_signals"]["context_requirement_boost"]
        > (boosted[0].diagnostics["score_signals"]["context_requirement_boost"])
    )
    assert boosted[1].diagnostics["provenance"]["context_requirement_matched_modalities"] == [
        "image"
    ]
    assert (
        "extracted_text"
        in boosted[1].diagnostics["provenance"]["context_requirement_matched_evidence_features"]
    )


def test_context_requirement_boost_infers_visual_evidence_from_source_ref() -> None:
    generic = _item(
        "generic",
        score=0.68,
        retrieval_source="keyword_chunks",
        text="Project Atlas invoice owner Alex appears in a generic text note.",
    )
    visual_evidence = ContextItem(
        item_id="artifact_visual_region",
        item_type="extraction_artifact",
        text="Project Atlas screenshot invoice owner Alex appears in the top-left region.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="image-1",
                chunk_id="ocr-region-1",
                bbox=(12.0, 32.0, 300.0, 88.0),
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence"],
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["artifact_evidence"]},
        },
    )
    query = "where on screen is Project Atlas screenshot invoice owner Alex"

    boosted = apply_context_requirement_boosts(
        (generic, visual_evidence),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    score_signals = boosted[1].diagnostics["score_signals"]
    assert boosted[1].score > boosted[0].score
    assert score_signals["context_requirement_boost"] >= 0.03
    assert (
        score_signals["context_requirement_boost"]
        > boosted[0].diagnostics["score_signals"]["context_requirement_boost"]
    )
    assert score_signals["context_requirement_matched_modality_count"] == 1
    assert score_signals["context_requirement_matched_feature_count"] >= 2
    assert boosted[1].diagnostics["provenance"]["context_requirement_matched_modalities"] == [
        "image"
    ]
    assert (
        "visual_region"
        in boosted[1].diagnostics["provenance"]["context_requirement_matched_evidence_features"]
    )


def test_context_requirement_boost_prefers_audio_timestamp_evidence() -> None:
    note = _item(
        "note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex mentioned Atlas follow-up in a text note.",
    )
    transcript = ContextItem(
        item_id="artifact_audio_transcript",
        item_type="extraction_artifact",
        text="Call transcript: Alex said the Atlas follow-up is approved.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="audio-1",
                chunk_id="segment-1",
                time_start_ms=1_200,
                time_end_ms=4_400,
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence"],
            "evidence_modality": "audio",
            "evidence_kind": "transcript_segment",
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["artifact_evidence"]},
        },
    )
    query = "What did Alex say in the call, with timestamp?"

    boosted = apply_context_requirement_boosts(
        (note, transcript),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > transcript.score
    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"]["context_requirement_matched_modalities"] == [
        "audio"
    ]
    assert (
        "time_range"
        in boosted[1].diagnostics["provenance"]["context_requirement_matched_evidence_features"]
    )


def test_context_requirement_boost_prefers_profile_summary_shape() -> None:
    fact = _item(
        "single_fact",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex likes hiking.",
    )
    summary = _item(
        "profile_summary",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Alex profile summary: key facts include his work, residence, "
            "preferences, recent events, and current goals."
        ),
    )
    query = "Who is Alex?"

    boosted = apply_context_requirement_boosts(
        (fact, summary),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert (
        "summary"
        in boosted[1].diagnostics["provenance"]["context_requirement_matched_answer_shapes"]
    )


def test_context_requirement_boost_prefers_project_summary_shape() -> None:
    fact = _item(
        "single_project_fact",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Project Atlas uses the new ingestion worker.",
    )
    summary = _item(
        "project_summary",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Project Atlas summary: current status, decisions, owners, "
            "risks, documents, and recent meetings are tracked together."
        ),
    )
    query = "What is Project Atlas?"

    boosted = apply_context_requirement_boosts(
        (fact, summary),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert (
        "summary"
        in boosted[1].diagnostics["provenance"]["context_requirement_matched_answer_shapes"]
    )


def test_context_requirement_boost_prefers_entity_relation_inventory_shape() -> None:
    single = _item(
        "single_relation_fact",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Project Atlas has a note mentioning Alex.",
    )
    inventory = _item(
        "relation_inventory",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Project Atlas connected people list: stakeholders Alex, Maria, "
            "and Sam are involved as owner, reviewer, and launch contact."
        ),
    )
    query = "Which people are involved in Project Atlas?"

    boosted = apply_context_requirement_boosts(
        (single, inventory),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert (
        "list"
        in boosted[1].diagnostics["provenance"]["context_requirement_matched_answer_shapes"]
    )
    assert (
        "relationship"
        in boosted[1].diagnostics["provenance"]["context_requirement_matched_answer_shapes"]
    )


def test_context_requirement_boost_does_not_treat_responsibility_as_summary() -> None:
    item = _item(
        "responsible",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex is responsible for the Atlas launch checklist.",
    )
    query = "Who is responsible for Project Atlas?"

    (boosted,) = apply_context_requirement_boosts(
        (item,),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert "summary" not in boosted.diagnostics["provenance"].get(
        "context_requirement_matched_answer_shapes",
        [],
    )


def test_context_requirement_boost_does_not_treat_project_role_as_summary() -> None:
    item = _item(
        "project_role",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Project Atlas is responsible for the billing migration workflow.",
    )
    query = "What is Project Atlas responsible for?"

    (boosted,) = apply_context_requirement_boosts(
        (item,),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert "summary" not in boosted.diagnostics["provenance"].get(
        "context_requirement_matched_answer_shapes",
        [],
    )


def test_deterministic_rerank_prefers_canonical_person_anchor_for_profile_summary() -> None:
    generic = _item(
        "generic_alex_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex appeared in the Project Atlas planning note.",
    )
    anchor = _anchor_item(
        "alex_anchor",
        score=0.711,
        kind="person",
        text=(
            "person: Alex. aliases: Alexander. description: product engineer "
            "working on Project Atlas. identity: Alex, Alexander, engineer."
        ),
    )
    query = "Who is Alex?"

    reranked = apply_deterministic_rerank_adjustments(
        (generic, anchor),
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_anchor"].score > by_id["generic_alex_note"].score
    assert (
        "canonical_anchor_summary_profile"
        in by_id["alex_anchor"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_multi_intent_decomposition_evidence() -> None:
    generic = _item(
        "generic_atlas_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Project Atlas owner Alex appears in a generic planning note.",
    )
    multi_intent = _item(
        "multi_intent_decision",
        score=0.711,
        retrieval_source="keyword_chunks",
        text=(
            "After the billing call, Alex decided Project Atlas should wait "
            "for invoice approval. The decision followed the call."
        ),
    )
    query = "What decision did Alex make about Project Atlas after the billing call?"

    reranked = apply_deterministic_rerank_adjustments(
        (generic, multi_intent),
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["multi_intent_decision"].score > by_id["generic_atlas_note"].score
    assert (
        "query_decomposition_multi_intent_covered"
        in by_id["multi_intent_decision"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        by_id["multi_intent_decision"]
        .diagnostics["score_signals"]["query_decomposition_covered_reason_count"]
        >= 2
    )
    assert "query_decomposition_multi_intent_covered" not in by_id[
        "generic_atlas_note"
    ].diagnostics["provenance"].get("deterministic_rerank_reasons", [])


def test_deterministic_rerank_prefers_canonical_project_anchor_for_summary() -> None:
    generic = _item(
        "generic_atlas_chunk",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Project Atlas appeared in a migration checklist.",
    )
    anchor = _anchor_item(
        "atlas_anchor",
        score=0.711,
        kind="project",
        text=(
            "project: Project Atlas. aliases: Atlas. description: memory "
            "ingestion project. identity: Atlas, memory, ingestion."
        ),
    )
    query = "What is Project Atlas?"

    reranked = apply_deterministic_rerank_adjustments(
        (generic, anchor),
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["atlas_anchor"].score > by_id["generic_atlas_chunk"].score
    assert (
        "canonical_anchor_summary_profile"
        in by_id["atlas_anchor"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_canonical_organization_anchor_for_summary() -> None:
    generic = _item(
        "generic_openai_chunk",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="OpenAI appeared in a vendor comparison note.",
    )
    anchor = _anchor_item(
        "openai_anchor",
        score=0.711,
        kind="organization",
        text=(
            "organization: OpenAI. aliases: OpenAI Inc. description: AI vendor "
            "used for transcription and vision. identity: OpenAI, vendor, AI."
        ),
    )
    query = "What is company OpenAI?"

    reranked = apply_deterministic_rerank_adjustments(
        (generic, anchor),
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["openai_anchor"].score > by_id["generic_openai_chunk"].score
    assert (
        "canonical_anchor_summary_profile"
        in by_id["openai_anchor"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_skips_canonical_summary_for_project_role_query() -> None:
    anchor = _anchor_item(
        "atlas_anchor",
        score=0.72,
        kind="project",
        text=(
            "project: Project Atlas. aliases: Atlas. description: memory "
            "ingestion project. identity: Atlas, memory, ingestion."
        ),
    )
    query = "What is Project Atlas responsible for?"

    (reranked,) = apply_deterministic_rerank_adjustments(
        (anchor,),
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )

    assert "canonical_anchor_summary_profile" not in reranked.diagnostics[
        "provenance"
    ].get("deterministic_rerank_reasons", [])


def test_context_requirement_boost_skips_queries_without_explicit_requirements() -> None:
    item = _item(
        "status",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Status is ready.",
    )
    query = "status update"

    boosted = apply_context_requirement_boosts(
        (item,),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
    )

    assert boosted == (item,)


def test_context_requirement_boost_does_not_apply_twice() -> None:
    item = ContextItem(
        item_id="artifact_image_ocr",
        item_type="extraction_artifact",
        text="Screenshot OCR detected text: Atlas billing threshold is 25k.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="image-1",
                chunk_id="ocr-region-1",
                bbox=(10.0, 20.0, 120.0, 80.0),
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence"],
            "evidence_modality": "image",
            "evidence_kind": "ocr_region",
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["artifact_evidence"]},
        },
    )
    query = "What text is written in the screenshot about Atlas?"
    intent = build_query_anchor_intent(query)

    first_pass = apply_context_requirement_boosts((item,), query=query, query_anchor_intent=intent)
    second_pass = apply_context_requirement_boosts(
        first_pass,
        query=query,
        query_anchor_intent=intent,
    )

    assert second_pass[0].score == first_pass[0].score


def test_context_requirement_boost_prefers_answer_shape_match() -> None:
    generic = _item(
        "generic",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Nate enjoys video game tournaments and trains often.",
    )
    count_evidence = _item(
        "count",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Nate won his fourth video game tournament last Friday.",
    )
    query = "How many tournaments has Nate won?"

    boosted = apply_context_requirement_boosts(
        (generic, count_evidence),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["count"]


def test_context_requirement_boost_counts_enumerated_list_for_count_query() -> None:
    generic = _item(
        "generic_pet_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Gina loves pets and volunteers at the shelter.",
    )
    enumerated = _item(
        "enumerated_pet_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Gina has a rescue dog, a cat, and a turtle at home.",
    )
    query = "How many pets does Gina have?"

    boosted = apply_context_requirement_boosts(
        (generic, enumerated),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["count"]


def test_context_requirement_boost_counts_approximate_total_visit_answers() -> None:
    generic = _item(
        "generic_visit_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Morgan talked about visits to the clinic and follow-up care.",
    )
    approximate_count = _item(
        "approximate_visit_count",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Morgan made several visits to the clinic for follow-up care.",
    )
    query = "What was the total for Morgan's clinic visits?"

    boosted = apply_context_requirement_boosts(
        (generic, approximate_count),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["count"]


def test_context_requirement_boost_prefers_causal_answer_shape_match() -> None:
    generic = _item(
        "generic_store_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Gina opened an online clothing store with dresses and shoes.",
    )
    reason = _item(
        "store_reason_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Gina started her clothing store so she could share handmade dresses.",
    )
    query = "Why did Gina start her clothing store?"

    boosted = apply_context_requirement_boosts(
        (generic, reason),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["causal"]


def test_deterministic_rerank_prefers_causal_belonging_evidence_over_generic_event() -> None:
    query = "What gave Caroline a sense of belonging?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "caroline_support_group",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Caroline joined an online support group for general planning advice.",
    )
    causal = _item(
        "caroline_pride_belonging",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "The LGBTQ pride parade made Caroline feel at home in the community "
            "and gave her a sense of belonging."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, causal),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_pride_belonging"].score > by_id["caroline_support_group"].score
    assert (
        "causal_answer_evidence"
        in by_id["caroline_pride_belonging"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_domain_reason_evidence_over_topical_decoy() -> None:
    query = "Why did Gina start her own clothing store?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topical = _item(
        "gina_store_topic",
        score=0.76,
        retrieval_source="keyword_chunks",
        text="Gina mentioned her clothing store during a planning update.",
    )
    reason = _item(
        "gina_job_loss",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Gina lost her Door Dash job, so she started thinking seriously "
            "about opening her own clothing store."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topical, reason),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["gina_job_loss"].score > by_id["gina_store_topic"].score
    assert (
        "causal_reason_exact_evidence"
        in by_id["gina_job_loss"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "causal_reason_weak_evidence"
        in by_id["gina_store_topic"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_current_goal_over_home_country_decoy() -> None:
    query = "Would Caroline want to move back to her home country soon?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    decoy = _item(
        "home_country_decoy",
        score=0.74,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline misses her home country sometimes and talked about moving "
            "back someday."
        ),
    )
    current_goal = _item(
        "adoption_goal",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline hopes to build her own family and put a roof over kids who "
            "have not had that before. Adoption is her current goal."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (decoy, current_goal),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["adoption_goal"].score > by_id["home_country_decoy"].score
    assert (
        "current_goal_exact_evidence"
        in by_id["adoption_goal"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "current_goal_weak_evidence"
        in by_id["home_country_decoy"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_active_commitment_over_move_back_decoy() -> None:
    query = "Would Maria move back to Chicago soon?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    decoy = _item(
        "old_home_decoy",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Maria misses Chicago and talked about moving back someday.",
    )
    active_commitment = _item(
        "austin_commitment",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Maria signed a yearlong lease in Austin, started a local role, "
            "and plans to stay through spring."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (decoy, active_commitment),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["austin_commitment"].score > by_id["old_home_decoy"].score
    assert (
        "current_goal_exact_evidence"
        in by_id["austin_commitment"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "current_goal_weak_evidence"
        in by_id["old_home_decoy"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_context_requirement_boost_prefers_location_answer_shape_match() -> None:
    generic = _item(
        "generic_move_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex discussed moving someday but did not name a city.",
    )
    location = _item(
        "alex_location_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex currently lives in Berlin and is based in Germany now.",
    )
    query = "Where does Alex live now?"

    boosted = apply_context_requirement_boosts(
        (generic, location),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["location"]


def test_context_requirement_boost_does_not_generic_boost_action_role_shape() -> None:
    recommendation = _item(
        "caroline_recommendation",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    query = "Who recommended Becoming Nicole to Melanie?"

    boosted = apply_context_requirement_boosts(
        (recommendation,),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[0].score > recommendation.score
    assert boosted[0].diagnostics["score_signals"][
        "context_requirement_matched_answer_shape_count"
    ] == 0
    assert boosted[0].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["action_role"]


def test_context_requirement_boost_prefers_preference_answer_shape_match() -> None:
    generic = _item(
        "generic_music_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex discussed ambient music during the studio call.",
    )
    preference = _item(
        "alex_music_preference",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex likes ambient music and is a fan of Brian Eno.",
    )
    query = "What music does Alex like?"

    boosted = apply_context_requirement_boosts(
        (generic, preference),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["preference"]


def test_context_requirement_boost_prefers_commonality_answer_shape_match() -> None:
    generic = _item(
        "shared_photo_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline shared a photo of a painting with Melanie.",
    )
    commonality = _item(
        "shared_hobbies",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline and Melanie both enjoy painting and weekend camping.",
    )
    query = "What hobbies do Caroline and Melanie have in common?"

    boosted = apply_context_requirement_boosts(
        (generic, commonality),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["commonality", "list"]


def test_deterministic_rerank_prefers_true_commonality_over_shared_artifact() -> None:
    query = "What hobbies do Caroline and Melanie have in common?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    shared_artifact = _item(
        "shared_photo_note",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Caroline shared a photo of a painting with Melanie.",
    )
    commonality = _item(
        "shared_hobbies",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline and Melanie both enjoy painting and weekend camping.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (shared_artifact, commonality),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["shared_hobbies"].score > by_id["shared_photo_note"].score
    assert (
        "commonality_exact_evidence"
        in by_id["shared_hobbies"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "commonality_weak_evidence"
        in by_id["shared_photo_note"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_shared_painted_subject_over_topic_only() -> None:
    query = "What subject have Caroline and Melanie both painted?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    caroline_sunset = _item(
        "caroline_sunset_painting",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D14:5 Caroline finished a new work. visual query: sunset painting.",
    )
    melanie_sunset = _item(
        "melanie_sunset_painting",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D8:6 Melanie loves painting nature-inspired work with her kids. "
            "visual query: sunset painting."
        ),
    )
    topic_only = _item(
        "generic_shared_painting",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="Caroline and Melanie both enjoy painting on weekends.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, caroline_sunset, melanie_sunset),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_sunset_painting"].score > by_id["generic_shared_painting"].score
    assert by_id["melanie_sunset_painting"].score > by_id["generic_shared_painting"].score
    assert (
        "shared_painted_subject_exact_evidence"
        in by_id["caroline_sunset_painting"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "shared_painted_subject_topic_only_noise"
        in by_id["generic_shared_painting"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_context_requirement_boost_prefers_who_else_commonality_match() -> None:
    original_person = _item(
        "caroline_camping",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline likes camping on weekends.",
    )
    also_person = _item(
        "maria_also_camping",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Maria also likes camping and hiking on weekends.",
    )
    query = "Who else likes camping like Caroline?"

    boosted = apply_context_requirement_boosts(
        (original_person, also_person),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["commonality"]


def test_deterministic_rerank_prefers_who_else_commonality_answer() -> None:
    query = "Who else likes camping like Caroline?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    original_person = _item(
        "caroline_camping",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Caroline likes camping on weekends.",
    )
    also_person = _item(
        "maria_also_camping",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Maria also likes camping and hiking on weekends.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (original_person, also_person),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["maria_also_camping"].score > by_id["caroline_camping"].score
    assert (
        "commonality_who_else_evidence"
        in by_id["maria_also_camping"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "query_anchor_conflict_overridden_by_commonality_who_else"
        in by_id["maria_also_camping"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "commonality_original_person_noise"
        in by_id["caroline_camping"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_context_requirement_boost_prefers_relationship_answer_shape_match() -> None:
    generic = _item(
        "alex_school_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex went to school with Maria.",
    )
    relationship = _item(
        "alex_old_friend",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex's old friend from school is Maria.",
    )
    query = "Who is Alex's old friend from school?"

    boosted = apply_context_requirement_boosts(
        (generic, relationship),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["relationship"]


def test_deterministic_rerank_prefers_relationship_status_over_social_decoy() -> None:
    query = "What is Caroline's relationship status?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    social_decoy = _item(
        "caroline_old_friend",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Caroline's old friend from school is Maria.",
    )
    status = _item(
        "caroline_single_parent",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline is single and described herself as a single parent.",
    )
    work_partner = _item(
        "caroline_project_partner",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Caroline's project partner on Atlas is Maria.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (social_decoy, work_partner, status),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_single_parent"].score > by_id["caroline_old_friend"].score
    assert by_id["caroline_single_parent"].score > by_id["caroline_project_partner"].score
    assert (
        "relationship_status_exact_evidence"
        in by_id["caroline_single_parent"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "relationship_status_weak_evidence"
        in by_id["caroline_project_partner"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_relationship_duration_over_generic_relation() -> None:
    query = "How long has Alex known Maria?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "alex_old_friend",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Alex's old friend from school is Maria.",
    )
    duration = _item(
        "alex_maria_known_for_years",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex and Maria have known each other for seven years.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, duration),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_maria_known_for_years"].score > by_id["alex_old_friend"].score
    assert (
        "relationship_duration_exact_evidence"
        in by_id["alex_maria_known_for_years"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "relationship_duration_weak_evidence"
        in by_id["alex_old_friend"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_friend_group_duration_evidence() -> None:
    query = "How long has Caroline had her current group of friends for?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "caroline_friends_support",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Caroline said her friends are supportive and help her through hard times.",
    )
    duration = _item(
        "caroline_known_friends_for_years",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D3:13 Caroline: I've known these friends for 4 years, since I "
            "moved from my home country."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, duration),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_known_friends_for_years"].score > by_id[
        "caroline_friends_support"
    ].score
    assert (
        "relationship_duration_exact_evidence"
        in by_id["caroline_known_friends_for_years"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "relationship_duration_weak_evidence"
        in by_id["caroline_friends_support"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_post_event_emotion_evidence() -> None:
    query = "How did Caroline feel about her family after the accident?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "melanie_family_accident_generic",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D18:3 Melanie mentioned an accident during the family roadtrip.",
    )
    supportive = _item(
        "supportive_family_statement",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D18:4 Caroline: Life's unpredictable, but moments like these "
            "remind us how important our loved ones are. Family's everything."
        ),
    )
    emotion = _item(
        "melanie_family_emotion",
        score=0.69,
        retrieval_source="keyword_chunks",
        text=(
            "D18:5 Melanie: Yeah, you're right, Caroline. Family's super "
            "important to me. Especially after the accident, I've thought a "
            "lot about how much I need them. They mean the world to me and "
            "I'm so thankful to have them."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, supportive, emotion),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_family_emotion"].score > by_id[
        "melanie_family_accident_generic"
    ].score
    assert by_id["melanie_family_emotion"].score > by_id[
        "supportive_family_statement"
    ].score
    assert (
        "post_event_family_appreciation_evidence"
        in by_id["melanie_family_emotion"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "post_event_emotion_weak_evidence"
        in by_id["melanie_family_accident_generic"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_relationship_origin_over_generic_relation() -> None:
    query = "Where did Alex meet Maria?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "alex_old_friend_school",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Alex's old friend from school is Maria.",
    )
    origin = _item(
        "alex_maria_first_met",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex and Maria first met at college during orientation in 2018.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, origin),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_maria_first_met"].score > by_id["alex_old_friend_school"].score
    assert (
        "relationship_origin_exact_evidence"
        in by_id["alex_maria_first_met"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "relationship_origin_weak_evidence"
        in by_id["alex_old_friend_school"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_russian_relationship_origin_evidence() -> None:
    query = "Где Алекс познакомился с Марией?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "alex_maria_old_school_friend",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Алекс и Мария старые друзья из школы.",
    )
    origin = _item(
        "alex_maria_met_college",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Алекс и Мария познакомились в колледже на ориентации.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, origin),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_maria_met_college"].score > by_id[
        "alex_maria_old_school_friend"
    ].score
    assert (
        "relationship_origin_exact_evidence"
        in by_id["alex_maria_met_college"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "relationship_origin_weak_evidence"
        in by_id["alex_maria_old_school_friend"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_age_birth_evidence_over_old_word_noise() -> None:
    query = "How old is Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    old_word_noise = _item(
        "alex_old_friend",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Alex's old friend from school is Maria.",
    )
    birth_evidence = _item(
        "alex_birth_year",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex was born in 1992 and his birthday is in June.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (old_word_noise, birth_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_birth_year"].score > by_id["alex_old_friend"].score
    assert (
        "age_birthday_exact_evidence"
        in by_id["alex_birth_year"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "age_birthday_weak_evidence"
        in by_id["alex_old_friend"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_birthplace_over_birthdate_noise() -> None:
    query = "Where was Alex born?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    birthdate_noise = _item(
        "alex_birth_year",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Alex was born in 1992 and his birthday is in June.",
    )
    birthplace = _item(
        "alex_birthplace",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex was born in Sweden, his home country, before moving abroad.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (birthdate_noise, birthplace),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_birthplace"].score > by_id["alex_birth_year"].score
    assert (
        "birthplace_exact_evidence"
        in by_id["alex_birthplace"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "age_birthday_birthplace_query_noise"
        in by_id["alex_birth_year"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_context_requirement_boost_prefers_commitment_answer_shape_match() -> None:
    generic = _item(
        "atlas_discussion",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Atlas was discussed during the meeting with Alex.",
    )
    commitment = _item(
        "atlas_action_item",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Atlas meeting notes: action item task follow up is assigned to Alex.",
    )
    query = "What action items came from the Atlas meeting?"

    boosted = apply_context_requirement_boosts(
        (generic, commitment),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["commitment"]


def test_context_requirement_boost_prefers_existence_answer_shape_match() -> None:
    generic = _item(
        "atlas_topic_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Project Atlas was approved after the billing call.",
    )
    existence = _item(
        "alex_mentioned_atlas",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex mentioned Project Atlas during the billing call.",
    )
    query = "Do we know whether Alex ever mentioned Project Atlas?"

    boosted = apply_context_requirement_boosts(
        (generic, existence),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["existence"]


def test_context_requirement_boost_does_not_generic_boost_state_update_shape() -> None:
    current = _item(
        "current_provider",
        score=0.7,
        retrieval_source="postgres_facts",
        text="Atlas provider remains valid and current: OpenAI.",
    )
    query = "What is the latest current Atlas provider?"

    boosted = apply_context_requirement_boosts(
        (current,),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[0].score == current.score
    assert "context_requirement_reason" not in boosted[0].diagnostics


def test_context_requirement_boost_prefers_ordinal_answer_shape_match() -> None:
    generic = _item(
        "generic_tournament_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Nate won video game tournaments at charity arcade nights.",
    )
    ordinal = _item(
        "ordinal_tournament_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Nate won his fourth video game tournament at the charity arcade night.",
    )
    query = "Which tournament did Nate win fourth?"

    boosted = apply_context_requirement_boosts(
        (generic, ordinal),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["ordinal"]


def test_context_requirement_boost_prefers_inference_support_answer_shape() -> None:
    generic = _item(
        "generic_melanie_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie visited Caroline after the community meetup.",
    )
    support = _item(
        "melanie_support_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie encourages Caroline and helps her feel accepted and supported.",
    )
    query = "Would Melanie be considered an ally?"

    boosted = apply_context_requirement_boosts(
        (generic, support),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["inference"]


def test_deterministic_rerank_prefers_support_role_fit_evidence_over_generic_support() -> None:
    query = "Would Caroline be a good mentor for Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "caroline_generic_support_network",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Caroline's friends and family support her and give her strength.",
    )
    role_fit = _item(
        "caroline_role_fit",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline mentored LGBTQ youth, listened patiently, and helped "
            "people feel safe in the community program."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, role_fit),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_role_fit"].score > by_id["caroline_generic_support_network"].score
    assert (
        "inference_support_role_fit_evidence"
        in by_id["caroline_role_fit"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_generic_support_noise"
        in by_id["caroline_generic_support_network"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_counterfactual_support_evidence() -> None:
    query = "Would Caroline support Alex joining the pride group?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "caroline_generic_support_network",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Caroline's friends and family support her and give her strength.",
    )
    evidence = _item(
        "caroline_pride_support_evidence",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline has been supportive and encouraging at pride groups. "
            "She helped Alex feel welcome and safe in the community."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_pride_support_evidence"].score > by_id[
        "caroline_generic_support_network"
    ].score
    assert (
        "inference_counterfactual_support_evidence"
        in by_id["caroline_pride_support_evidence"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_counterfactual_support_noise"
        in by_id["caroline_generic_support_network"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_generic_behavior_inference_evidence() -> None:
    query = "Would Alex be considered reliable?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_only = _item(
        "alex_reliability_topic",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Alex discussed reliability as a product metric in the backend review.",
    )
    behavior = _item(
        "alex_reliable_behavior",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex kept his promises, followed through, and prepared the launch notes early.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, behavior),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_reliable_behavior"].score > by_id["alex_reliability_topic"].score
    assert (
        "inference_behavior_evidence"
        in by_id["alex_reliable_behavior"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_helpful_behavior_inference_evidence() -> None:
    query = "Would Alex be considered helpful?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_only = _item(
        "alex_helpful_topic",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Alex discussed helpful onboarding copy during the product review.",
    )
    behavior = _item(
        "alex_helpful_behavior",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Alex listened patiently, helped Sam debug the launch, and "
            "reassured the team before release."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, behavior),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_helpful_behavior"].score > by_id["alex_helpful_topic"].score
    assert (
        "inference_behavior_evidence"
        in by_id["alex_helpful_behavior"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_direct_trait_inference_evidence() -> None:
    query = "Would Caroline be considered patient?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic_only = _item(
        "patient_topic",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Caroline read an article about patient intake forms.",
    )
    direct_trait = _item(
        "caroline_patient_trait",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline is thoughtful and patient with new volunteers.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topic_only, direct_trait),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_patient_trait"].score > by_id["patient_topic"].score
    assert (
        "inference_behavior_evidence"
        in by_id["caroline_patient_trait"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_preference_fit_evidence_over_negative_noise() -> None:
    query = 'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    negative_noise = _item(
        "melanie_podcast_noise",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="Melanie usually listens to podcasts instead.",
    )
    preference_fit = _item(
        "melanie_classical_music",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie is a fan of classical music like Bach and Mozart.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative_noise, preference_fit),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_classical_music"].score > by_id["melanie_podcast_noise"].score
    assert (
        "inference_preference_fit_evidence"
        in by_id["melanie_classical_music"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_negative_preference_noise"
        in by_id["melanie_podcast_noise"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_negative_preference_fit_over_unrelated_instead() -> None:
    query = 'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    unrelated_instead = _item(
        "podcast_instead",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Melanie usually listens to podcasts instead.",
    )
    negative_fit = _item(
        "classical_dislike",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie avoids classical music and dislikes orchestra concerts.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (unrelated_instead, negative_fit),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["classical_dislike"].score > by_id["podcast_instead"].score
    assert (
        "inference_negative_preference_fit_evidence"
        in by_id["classical_dislike"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_negative_preference_noise"
        in by_id["podcast_instead"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_comparison_preference_evidence() -> None:
    query = "Would Melanie be more interested in a national park or a theme park?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    option_echo = _item(
        "theme_park_option_echo",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Melanie discussed whether a national park or a theme park sounded nice someday.",
    )
    outdoor_fit = _item(
        "melanie_outdoor_fit",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="Melanie loves camping, hiking, and quiet outdoor trips in national parks.",
    )
    theme_negative = _item(
        "melanie_theme_negative",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie dislikes loud theme parks and avoids noisy rides.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (option_echo, outdoor_fit, theme_negative),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_outdoor_fit"].score > by_id["theme_park_option_echo"].score
    assert by_id["melanie_theme_negative"].score > by_id["theme_park_option_echo"].score
    assert (
        "inference_preference_fit_evidence"
        in by_id["melanie_outdoor_fit"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_negative_preference_fit_evidence"
        in by_id["melanie_theme_negative"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_classical_music_topic_without_preference() -> None:
    query = 'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    preference_fit = _item(
        "melanie_classical_music",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie is a fan of classical music like Bach and Mozart.",
    )
    topic_only = _item(
        "vivaldi_topic_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="The orchestra discussed Vivaldi and classical symphony forms in music class.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (preference_fit, topic_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_classical_music"].score > by_id["vivaldi_topic_only"].score
    assert (
        "inference_preference_fit_evidence"
        in by_id["melanie_classical_music"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_classical_music_topic_only_noise"
        in by_id["vivaldi_topic_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_explicit_preference_over_topical_match() -> None:
    query = "Which meat does Audrey prefer eating more than others?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topical = _item(
        "audrey_chicken_recipe",
        score=0.76,
        retrieval_source="keyword_chunks",
        text="Audrey cooked chicken with lemon for the fundraiser.",
    )
    preference = _item(
        "audrey_roasted_chicken",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Audrey says roasted chicken is one of her favorite comfort meals.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topical, preference),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["audrey_roasted_chicken"].score > by_id["audrey_chicken_recipe"].score
    assert (
        "preference_exact_evidence"
        in by_id["audrey_roasted_chicken"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "preference_weak_evidence"
        in by_id["audrey_chicken_recipe"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_book_author_world_evidence_over_bookshelf() -> None:
    query = "Would Tim enjoy reading books by C. S. Lewis or John Greene?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    bookshelf = _item(
        "tim_bookshelf",
        score=0.99,
        retrieval_source="keyword_chunks",
        text=(
            "D20:19 Tim: Here's my bookshelf with some favorites. "
            "visual query: bookshelf Harry Potter Game of Thrones."
        ),
        score_signals={"query_expansion_reason": "book_reading_list_bridge"},
    )
    world_evidence = _item(
        "tim_potter_world",
        score=0.99,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D1:16 Tim: We'll be discussing the Harry Potter universe, "
            "characters, spells, and magical creatures."
        ),
        score_signals={"query_expansion_reason": "book_suggestion_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (bookshelf, world_evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert (
        by_id["tim_potter_world"].diagnostics["score_signals"][
            "book_author_preference_world_evidence"
        ]
        == 3.0
    )
    assert context_rank_key(by_id["tim_potter_world"]) < context_rank_key(by_id["tim_bookshelf"])
    assert (
        "book_author_preference_generic_collection"
        in by_id["tim_bookshelf"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_context_requirement_boost_prefers_constraint_answer_shape() -> None:
    positive = _item(
        "alex_positive_food_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex eats peanuts and enjoys shellfish at weekend dinners.",
    )
    constraint = _item(
        "alex_food_constraint",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex cannot eat peanuts and avoids shellfish because of allergies.",
    )
    query = "Which foods can't Alex eat?"

    boosted = apply_context_requirement_boosts(
        (positive, constraint),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["constraint"]


def test_deterministic_rerank_prefers_choice_answer_shape_over_option_echo() -> None:
    query = "Does John live close to a beach or the mountains?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    concrete = _item(
        "john_beach_evidence",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="John goes on weekly walks by the ocean and lives close to the beach.",
    )
    option_echo = _item(
        "john_option_echo",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="John discussed whether a beach or mountains sounded nice someday.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (option_echo, concrete),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["john_beach_evidence"].score > by_id["john_option_echo"].score
    assert (
        "explicit_answer_shape_covered"
        in by_id["john_beach_evidence"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "beach_mountains_proximity_evidence"
        in by_id["john_beach_evidence"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_answer_shape_missing"
        in by_id["john_option_echo"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "beach_mountains_topic_only_noise"
        in by_id["john_option_echo"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_speaker_answer_shape() -> None:
    query = "Who said Project Atlas was approved?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    speaker_turn = _item(
        "alex_turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex: Project Atlas was approved after the billing call.",
    )
    generic_note = _item(
        "generic_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Project Atlas was approved after the billing call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_note, speaker_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_turn"].score > by_id["generic_note"].score
    assert (
        "speaker_answer_shape_covered"
        in by_id["alex_turn"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_answer_shape_missing"
        in by_id["generic_note"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_conversation_participant_answer_shape() -> None:
    query = "Who did Alex talk to about Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    participant = _item(
        "participant_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex talked to Maria about Project Atlas.",
    )
    generic_note = _item(
        "generic_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex discussed Project Atlas during the billing call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_note, participant),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["participant_note"].score > by_id["generic_note"].score
    assert (
        "explicit_answer_shape_covered"
        in by_id["participant_note"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "conversation_counterparty_exact_evidence"
        in by_id["participant_note"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_answer_shape_missing"
        in by_id["generic_note"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_negative_conversation_counterparty_evidence() -> None:
    query = "Who did Alex talk to about Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    relevant = _item(
        "sam_turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex talked with Sam about Project Atlas rollout.",
    )
    negative = _item(
        "negative_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Sam said Project Atlas is delayed, but there was no conversation with Alex.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, relevant),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["sam_turn"].score > by_id["negative_note"].score
    assert (
        "conversation_counterparty_negative_evidence"
        in by_id["negative_note"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )

    short_query = "Who did Alex call?"
    (short_negative,) = apply_deterministic_rerank_adjustments(
        (
            _item(
                "short_negative",
                score=0.72,
                retrieval_source="keyword_chunks",
                text="Alex did not call Sam.",
            ),
        ),
        query=short_query,
        plan=build_query_expansion_plan(short_query),
        query_anchor_intent=build_query_anchor_intent(short_query),
    )

    assert (
        "conversation_counterparty_negative_evidence"
        in short_negative.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_conversation_topic_answer_shape() -> None:
    query = "What did Alex and Maria talk about?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic = _item(
        "topic_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex talked with Maria about Project Atlas.",
    )
    participant_only = _item(
        "participant_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex talked with Maria after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (participant_only, topic),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["topic_note"].score > by_id["participant_only"].score
    assert (
        "explicit_answer_shape_covered"
        in by_id["topic_note"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "conversation_topic_exact_evidence"
        in by_id["topic_note"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_answer_shape_missing"
        in by_id["participant_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_conversation_topic_alternate_wording() -> None:
    query = "What was the conversation with Maria about?"
    possessive_query = "What was Alex's conversation with Maria about?"
    plan = build_query_expansion_plan(query)
    possessive_plan = build_query_expansion_plan(possessive_query)
    intent = build_query_anchor_intent(query)
    possessive_intent = build_query_anchor_intent(possessive_query)
    topic = _item(
        "topic_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex talked with Maria about Project Atlas.",
    )
    participant_only = _item(
        "participant_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex talked with Maria after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (participant_only, topic),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    possessive_reranked = apply_deterministic_rerank_adjustments(
        (participant_only, topic),
        query=possessive_query,
        plan=possessive_plan,
        query_anchor_intent=possessive_intent,
    )
    by_id = {item.item_id: item for item in reranked}
    possessive_by_id = {item.item_id: item for item in possessive_reranked}

    assert by_id["topic_note"].score > by_id["participant_only"].score
    assert possessive_by_id["topic_note"].score > possessive_by_id["participant_only"].score
    assert (
        "explicit_answer_shape_covered"
        in by_id["topic_note"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_answer_shape_covered"
        in possessive_by_id["topic_note"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_covered_call_topic_wording() -> None:
    query = "What was Alex's call with Maria about?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topic = _item(
        "covered_call",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex's call with Maria covered Project Atlas migration risks.",
    )
    call_only = _item(
        "call_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex had a call with Maria after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (call_only, topic),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["covered_call"].score > by_id["call_only"].score
    assert (
        "conversation_topic_exact_evidence"
        in by_id["covered_call"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_negative_conversation_topic_evidence() -> None:
    query = "What did Alex and Maria talk about?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    relevant = _item(
        "topic_note",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex and Maria talked about Project Atlas and invoice approval.",
    )
    negative = _item(
        "negative_topic",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex and Maria did not talk about Project Atlas during lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, relevant),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["topic_note"].score > by_id["negative_topic"].score
    assert (
        "conversation_topic_negative_evidence"
        in by_id["negative_topic"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_latest_conversation_event_shape() -> None:
    query = "What was my latest call with Alex about?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    event_note = _item(
        "latest_call",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Yesterday's call with Alex covered Project Atlas migration risks.",
    )
    generic_note = _item(
        "generic_alex",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex owns the Project Atlas renewal follow-up.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_note, event_note),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["latest_call"].score > by_id["generic_alex"].score
    assert (
        "conversation_recency_temporal_evidence"
        in by_id["latest_call"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "conversation_recency_missing_event_evidence"
        in by_id["generic_alex"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_relative_time_conversation_event_shape() -> None:
    query = "What did I discuss with Alex two hours ago?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    event_note = _item(
        "recent_discussion",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Two hours ago I discussed Project Atlas migration risks with Alex.",
    )
    generic_note = _item(
        "generic_alex",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex owns the Project Atlas renewal follow-up.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_note, event_note),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["recent_discussion"].score > by_id["generic_alex"].score
    assert (
        "conversation_recency_temporal_evidence"
        in by_id["recent_discussion"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "conversation_recency_missing_event_evidence"
        in by_id["generic_alex"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_russian_message_recency_event() -> None:
    query = "Что Алекс написал вчера?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    event_note = _item(
        "alex_message_yesterday",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Вчера Алекс написал про Atlas migration risks.",
    )
    generic_note = _item(
        "generic_alex",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex owns the Project Atlas renewal follow-up.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_note, event_note),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_message_yesterday"].score > by_id["generic_alex"].score
    assert (
        "conversation_recency_temporal_evidence"
        in by_id["alex_message_yesterday"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_uses_temporal_hint_for_latest_conversation() -> None:
    query = "What was the latest conversation with Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    current_event = _item(
        "current_event",
        score=0.7,
        retrieval_source="keyword_chunks",
        event_temporal_hint_code="today",
        text="Call with Alex covered invoice background.",
    )
    undated_event = _item(
        "undated_event",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="Call with Alex covered invoice background.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (undated_event, current_event),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["current_event"].score > by_id["undated_event"].score
    assert (
        "conversation_recency_temporal_hint_evidence"
        in by_id["current_event"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "conversation_recency_missing_temporal_evidence"
        in by_id["undated_event"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_uses_temporal_hint_alias_for_latest_conversation() -> None:
    query = "Что было на последнем созвоне с Алексом?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    current_event = _item(
        "current_event",
        score=0.7,
        retrieval_source="keyword_chunks",
        temporal_hint_code="today",
        text="Созвон с Алексом был про invoice background.",
    )
    undated_event = _item(
        "undated_event",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="Созвон с Алексом был про invoice background.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (undated_event, current_event),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["current_event"].score > by_id["undated_event"].score
    assert (
        "conversation_recency_temporal_hint_evidence"
        in by_id["current_event"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_dated_latest_conversation_over_undated() -> None:
    query = "What was the latest conversation with Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    dated_event = _item(
        "dated_event",
        score=0.7,
        retrieval_source="keyword_chunks",
        event_temporal_hint_code="last_week",
        text="Call with Alex covered invoice background.",
    )
    undated_event = _item(
        "undated_event",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="Call with Alex covered invoice background.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (undated_event, dated_event),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["dated_event"].score > by_id["undated_event"].score
    assert (
        "conversation_recency_dated_temporal_hint_evidence"
        in by_id["dated_event"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_upcoming_event_hint_for_next_meeting() -> None:
    query = "When is the next meeting with Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    upcoming_event = _item(
        "upcoming_event",
        score=0.7,
        retrieval_source="keyword_chunks",
        event_temporal_hint_code="next_week",
        text="Meeting with Alex is about invoice background.",
    )
    previous_event = _item(
        "previous_event",
        score=0.71,
        retrieval_source="keyword_chunks",
        event_temporal_hint_code="last_week",
        text="Meeting with Alex was about invoice background.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (previous_event, upcoming_event),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["upcoming_event"].score > by_id["previous_event"].score
    assert (
        "temporal_query_upcoming_event_future_temporal_hint"
        in by_id["upcoming_event"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "temporal_query_upcoming_event_past_temporal_hint_conflict"
        in by_id["previous_event"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_wrong_person_decoy() -> None:
    query = "Would Melanie be considered an ally?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        retrieval_sources=("keyword_chunks", "vector_chunks", "canonical_anchors"),
        text="Melanie encourages Caroline and helps her feel accepted and supported.",
    )
    wrong_person = _item(
        "caroline",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="Caroline encourages the community and helps people feel supported.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, wrong_person),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert reranked[1].diagnostics["score_signals"]["deterministic_rerank_penalty"] > 0
    assert (
        "query_anchor_conflict"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_temporal_answer_shape_match() -> None:
    query = "When did Caroline go to the adoption meeting?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "generic_adoption",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline attended an adoption council meeting and felt inspired.",
    )
    temporal = _item(
        "temporal_adoption",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="Caroline went to the adoption council meeting last Friday.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, temporal),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    reranked_by_id = {item.item_id: item for item in reranked}

    assert reranked_by_id["temporal_adoption"].score > reranked_by_id["generic_adoption"].score
    assert (
        "explicit_requirement_covered"
        in reranked_by_id["temporal_adoption"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "explicit_requirement_missing"
        in reranked_by_id["generic_adoption"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_current_active_memory_over_superseded() -> None:
    query = "Which Atlas provider is still valid?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    active = _item(
        "active_provider",
        score=0.7,
        retrieval_source="postgres_facts",
        fact_status="active",
        text="Atlas provider remains valid and active: OpenAI.",
    )
    superseded = _item(
        "superseded_provider",
        score=0.72,
        retrieval_source="superseded_review",
        fact_status="superseded",
        review_only=True,
        text="Atlas provider was previously valid: LocalAI.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (active, superseded),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["active_provider"].score > by_id["superseded_provider"].score
    assert (
        "temporal_query_current_active_match"
        in by_id["active_provider"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "temporal_query_current_superseded_conflict"
        in by_id["superseded_provider"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_demotes_plain_text_stale_state_for_current_query() -> None:
    query = "Which Atlas provider is still valid?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    active = _item(
        "active_provider",
        score=0.7,
        retrieval_source="postgres_facts",
        fact_status="active",
        text="Atlas provider remains valid and active: OpenAI.",
    )
    stale_text = _item(
        "stale_text_provider",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="LocalAI is no longer valid for Atlas after the provider switch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (active, stale_text),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["active_provider"].score > by_id["stale_text_provider"].score
    assert (
        "temporal_query_current_stale_text_conflict"
        in by_id["stale_text_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "current_state_stale_conflict"
        in by_id["stale_text_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_boosts_current_state_text_for_current_query() -> None:
    query = "What is the current Atlas provider?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    active = _item(
        "active_provider",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Atlas final decision: OpenAI is the selected current provider.",
    )
    stale_topic = _item(
        "stale_topic_provider",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="LocalAI was a previous Atlas provider before the review.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (stale_topic, active),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["active_provider"].score > by_id["stale_topic_provider"].score
    assert (
        "current_state_exact_evidence"
        in by_id["active_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_previous_state_for_no_longer_query() -> None:
    query = "Which Atlas provider is no longer valid?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    active = _item(
        "active_provider",
        score=0.72,
        retrieval_source="postgres_facts",
        fact_status="active",
        text="Atlas provider remains valid and active: OpenAI.",
    )
    superseded = _item(
        "superseded_provider",
        score=0.7,
        retrieval_source="superseded_review",
        fact_status="superseded",
        review_only=True,
        text="Atlas provider is no longer valid: LocalAI.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (active, superseded),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["superseded_provider"].score > by_id["active_provider"].score
    assert (
        "temporal_query_previous_state_evidence"
        in by_id["superseded_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "stale_state_exact_evidence"
        in by_id["superseded_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "stale_state_current_conflict"
        in by_id["active_provider"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_missed_event_for_participation_query() -> None:
    query = "What LGBTQ+ events has Caroline participated in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    missed = _item(
        "missed-pride",
        score=0.8,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline said the city held a pride parade with flags and signs, but she missed it."
        ),
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (missed,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked.diagnostics["score_signals"]["deterministic_rerank_penalty"] > 0
    assert (
        "event_participation_mismatch"
        in reranked.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_weak_event_participation_source_sibling() -> None:
    query = "What LGBTQ+ events has Caroline participated in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    direct = _item(
        "direct-pride",
        score=0.9,
        retrieval_source="keyword_source_sibling_chunks",
        text="D5:1 Caroline: Last week I went to an LGBTQ+ pride parade.",
    )
    weak_sibling = _item(
        "weak-sibling",
        score=0.9,
        retrieval_source="keyword_source_sibling_chunks",
        text="D15:13 Caroline: Wow! Did you see that band?",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (weak_sibling, direct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["direct-pride"].score > by_id["weak-sibling"].score
    assert (
        "event_participation_source_sibling_noise"
        in by_id["weak-sibling"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_keeps_event_visual_reference_source_sibling() -> None:
    query = "What LGBTQ+ events has Caroline participated in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    visual_reference = _item(
        "visual-reference",
        score=0.9,
        retrieval_source="keyword_source_sibling_chunks",
        text="D15:13 Caroline: Wow! Did you see that band?",
        score_signals={"source_sibling_dialogue_visual_reference": 1},
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (visual_reference,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert (
        "event_participation_source_sibling_noise"
        not in reranked.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_not_blocked_status_match() -> None:
    query = "Which project is not blocked?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    not_blocked = _item(
        "not_blocked",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Project Atlas is active and not blocked.",
    )
    blocked = _item(
        "blocked",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Project Orion is blocked by invoice approval.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (not_blocked, blocked),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "status_polarity_not_blocked_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "status_polarity_blocked_conflict"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert not any(
        "query_anchor_conflict" in item.diagnostics["provenance"]["deterministic_rerank_reasons"]
        for item in reranked
    )


def test_deterministic_rerank_prefers_negative_preference_match() -> None:
    query = "What does Melanie not like?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    negative = _item(
        "negative",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie does not like loud theme parks.",
    )
    positive = _item(
        "positive",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie likes theme parks and loud rides.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, positive),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "negative_preference_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "negative_preference_positive_conflict"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_cant_eat_negative_match() -> None:
    query = "Which foods can't Alex eat?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    negative = _item(
        "negative",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex cannot eat peanuts and avoids shellfish.",
    )
    positive = _item(
        "positive",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex eats peanuts and enjoys shellfish.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, positive),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "negative_preference_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "negative_preference_positive_conflict"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_absence_contrast_positive_evidence() -> None:
    query = "What pet did I mention named Luna instead of a hamster?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    positive = _item(
        "positive",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="My cat Luna needs a new carrier.",
    )
    negative = _item(
        "negative",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="I bought hamster bedding for a neighbor.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, positive),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["positive"].score > by_id["negative"].score
    assert (
        "absence_contrast_positive_match"
        in by_id["positive"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "absence_contrast_negative_only_conflict"
        in by_id["negative"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_handles_absence_contrast_negative_descriptor() -> None:
    query = "What pet did I mention called Luna instead of a pet hamster?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    positive = _item(
        "positive",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="My cat Luna needs a new carrier.",
    )
    negative = _item(
        "negative",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="I bought hamster bedding for a neighbor.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, positive),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["positive"].score > by_id["negative"].score
    assert (
        "absence_contrast_positive_match"
        in by_id["positive"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "absence_contrast_negative_only_conflict"
        in by_id["negative"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_explicit_choice_absence_contrast() -> None:
    query = "Which provider did the team choose, OpenAI instead of Anthropic?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    positive = _item(
        "positive",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="The team chose OpenAI for the summary provider.",
    )
    negative = _item(
        "negative",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="An old note evaluated Anthropic for the summary provider.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, positive),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["positive"].score > by_id["negative"].score
    assert (
        "absence_contrast_positive_match"
        in by_id["positive"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "absence_contrast_negative_only_conflict"
        in by_id["negative"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_pet_species_mismatch() -> None:
    query = "What hamster did I mention?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    cat_note = _item(
        "cat_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="I mentioned my cat Luna during the call.",
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (cat_note,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked.score < cat_note.score
    assert (
        "object_kind_species_mismatch"
        in reranked.diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_does_not_penalize_dog_shelter_as_pet_mismatch() -> None:
    query = "What dog shelter does Maria volunteer at?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    shelter_note = _item(
        "shelter_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Maria volunteers at the dog shelter on weekends.",
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (shelter_note,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert "object_kind_species_mismatch" not in reranked.diagnostics.get(
        "provenance",
        {},
    ).get("deterministic_rerank_reasons", [])


def test_deterministic_rerank_does_not_penalize_exact_source_sibling_speaker_bridge() -> None:
    query = "Would John be open to moving to another country?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    score_signals = {
        "query_expansion_reason": "military_service_willingness_bridge",
        "query_expansion_reason_priority": 4,
        "source_sibling_group_level_seed": 1,
    }
    john_bridge = _item(
        "john_bridge",
        score=0.99,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D24:3 John: I heard cool stories from an elderly veteran named Samuel. "
            "It was inspiring and heartbreaking, but seeing their resilience filled "
            "me with hope to join the military."
        ),
        score_signals=score_signals,
    )
    wrong_speaker = _item(
        "wrong_speaker",
        score=0.99,
        retrieval_source="keyword_source_sibling_chunks",
        text=(
            "D24:3 Samuel: I heard cool stories from an elderly veteran named John. "
            "It was inspiring and heartbreaking, but seeing their resilience filled "
            "me with hope to join the military."
        ),
        score_signals=score_signals,
    )

    reranked = apply_deterministic_rerank_adjustments(
        (john_bridge, wrong_speaker),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["john_bridge"].score > by_id["wrong_speaker"].score
    assert by_id["wrong_speaker"].score < by_id["john_bridge"].score
    john_reasons = by_id["john_bridge"].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]
    assert (
        "query_anchor_conflict_overridden_by_source_speaker"
        in john_reasons
    )
    assert "query_anchor_conflict" not in john_reasons
    assert (
        "query_anchor_conflict"
        in by_id["wrong_speaker"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_does_not_penalize_keyword_turn_speaker_bridge() -> None:
    query = "Would John be open to moving to another country?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    john_bridge = _item(
        "john_bridge",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D24:3 John: I heard cool stories from an elderly veteran named Samuel. "
            "It was inspiring and heartbreaking, but seeing their resilience filled "
            "me with hope. It reminded me why I wanted to join the military."
        ),
    )
    wrong_speaker = _item(
        "wrong_speaker",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D24:3 Samuel: I heard cool stories from an elderly veteran named John. "
            "It was inspiring and heartbreaking, but seeing their resilience filled "
            "me with hope. It reminded me why I wanted to join the military."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (john_bridge, wrong_speaker),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}
    john_reasons = by_id["john_bridge"].diagnostics["provenance"][
        "deterministic_rerank_reasons"
    ]

    assert by_id["john_bridge"].score > by_id["wrong_speaker"].score
    assert "query_anchor_conflict_overridden_by_source_speaker" in john_reasons
    assert "query_anchor_conflict" not in john_reasons
    assert (
        "query_anchor_conflict"
        in by_id["wrong_speaker"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_willingness_evidence_over_relocation_decoy() -> None:
    query = "Would John be open to moving to another country?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    topical_decoy = _item(
        "john_relocation_history",
        score=0.75,
        retrieval_source="keyword_chunks",
        text="John moved from another country as a child and misses his old hometown.",
    )
    willingness = _item(
        "john_military_willingness",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "John said he would be open to moving abroad for an international "
            "service mission."
        ),
    )
    public_office = _item(
        "john_public_office_goal",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D7:2 John wanted to run for public office again and was excited "
            "about local politics."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (topical_decoy, willingness, public_office),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["john_military_willingness"].score > by_id["john_relocation_history"].score
    assert by_id["john_public_office_goal"].score > by_id["john_relocation_history"].score
    assert (
        "inference_willingness_fit_evidence"
        in by_id["john_military_willingness"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_willingness_fit_evidence"
        in by_id["john_public_office_goal"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "inference_willingness_topic_only_noise"
        in by_id["john_relocation_history"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_penalizes_single_hit_long_query_overlap() -> None:
    query = "unrelated yakutsk cooking recipe quantum aquarium warranty"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    relevant = _item(
        "relevant",
        score=0.742,
        retrieval_source="vector_chunks",
        text="Yakutsk cooking recipe notes mention a quantum aquarium warranty.",
    )
    decoy = _item(
        "decoy",
        score=0.75,
        retrieval_source="vector_chunks",
        text="Warranty renewal paperwork was archived for Project Atlas.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (decoy, relevant),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["relevant"].score > by_id["decoy"].score
    assert (
        "weak_long_query_overlap"
        in by_id["decoy"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "weak_long_query_overlap"
        not in by_id["relevant"].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_negative_interest_match() -> None:
    query = "What is Alex not interested in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    negative = _item(
        "negative",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex is not interested in frontend work.",
    )
    positive = _item(
        "positive",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex is interested in frontend work.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (negative, positive),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "negative_preference_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_activity_owned_by_query_speaker() -> None:
    query = "What activities does Melanie partake in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    melanie_activity = _item(
        "melanie_activity",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=("D9:1 Melanie: I went camping with my family and enjoyed unplugging with the kids."),
    )
    caroline_vocative = _item(
        "caroline_vocative",
        score=0.73,
        retrieval_source="keyword_chunks",
        text=(
            "D16:9 Caroline: Melanie, those bowls are amazing. Painting helped "
            "me express my gender identity."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (melanie_activity, caroline_vocative),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > melanie_activity.score
    assert reranked[1].score < caroline_vocative.score
    assert (
        "activity_owner_speaker_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "activity_owner_speaker_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_friend_place_owned_by_query_speaker() -> None:
    query = "Where has Maria made friends?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    maria_gym = _item(
        "maria_gym",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D19:1 Maria: I joined a gym last week and the people there are supportive."
        ),
        score_signals={"query_expansion_reason": "friend_place_inventory_bridge"},
    )
    john_support_group = _item(
        "john_support_group",
        score=0.74,
        retrieval_source="keyword_chunks",
        text=(
            "D27:1 John: Hey Maria, I asked family and friends to join my virtual "
            "support group."
        ),
        score_signals={"query_expansion_reason": "friend_place_inventory_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (maria_gym, john_support_group),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > maria_gym.score
    assert reranked[1].score < john_support_group.score
    assert (
        "activity_owner_speaker_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "activity_owner_speaker_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_inventory_exact_place_over_generic_noise() -> None:
    query = "Where has Maria made friends?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact_place = _item(
        "maria_shelter_friend",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D4:1 Maria: I made friends with fellow volunteers at the homeless shelter.",
        score_signals={"query_expansion_reason": "friend_place_inventory_bridge"},
    )
    generic_group = _item(
        "generic_support_group",
        score=0.755,
        retrieval_source="keyword_chunks",
        text=(
            "D27:1 Maria asked family and friends to join a virtual support group "
            "for a community project."
        ),
        score_signals={"query_expansion_reason": "friend_place_inventory_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_group, exact_place),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["maria_shelter_friend"].score > by_id["generic_support_group"].score
    assert (
        "inventory_list_exact_evidence"
        in by_id["maria_shelter_friend"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "inventory_list_weak_evidence"
        in by_id["generic_support_group"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_friend_place_shelter_anchor() -> None:
    query = "Where has Maria made friends?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    shelter_anchor = _item(
        "d2_shelter_anchor",
        score=0.94,
        retrieval_source="keyword_chunks",
        text=(
            "D2:1 Maria donated her old car to a homeless shelter where she volunteers."
        ),
        score_signals={"query_expansion_reason": "friend_place_shelter_inventory_bridge"},
    )
    later_activity = _item(
        "d11_shelter_talks",
        score=0.945,
        retrieval_source="keyword_chunks",
        text=(
            "D11:10 Maria recently gave a few talks at the homeless shelter "
            "she volunteers at."
        ),
        score_signals={"query_expansion_reason": "friend_place_shelter_inventory_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (later_activity, shelter_anchor),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert context_rank_key(by_id["d2_shelter_anchor"]) < context_rank_key(
        by_id["d11_shelter_talks"]
    )
    assert (
        "friend_place_shelter_anchor_evidence"
        in by_id["d2_shelter_anchor"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        by_id["d2_shelter_anchor"].diagnostics["score_signals"][
            "friend_place_shelter_anchor_evidence"
        ]
        == 3.0
    )
    assert (
        "friend_place_shelter_anchor_evidence"
        not in by_id["d11_shelter_talks"].diagnostics["score_signals"]
    )


def test_deterministic_rerank_reuses_item_relevance_signals(monkeypatch) -> None:
    query = "Where has Maria made friends?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    item = _item(
        "d2_shelter_anchor",
        score=0.94,
        retrieval_source="keyword_chunks",
        text="D2:1 Maria donated her old car to a homeless shelter where she volunteers.",
        score_signals={
            "query_expansion_reason": "friend_place_shelter_inventory_bridge",
            "query_term_count": 7,
            "unique_term_hits": 6,
            "capped_frequency_hits": 6,
            "hit_ratio": 0.85,
            "distinctive_term_count": 5,
            "distinctive_term_hits": 5,
            "phrase_bigram_count": 6,
            "phrase_bigram_hits": 2,
            "phrase_boost": 0.012,
            "query_relevance_boost": 0.07,
        },
    )

    def fail_recompute(*args, **kwargs):
        raise AssertionError("diagnostic relevance fast-path was not used")

    monkeypatch.setattr(context_ranking_module, "best_query_relevance", fail_recompute)

    (reranked,) = apply_deterministic_rerank_adjustments(
        (item,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked.score > item.score
    assert (
        reranked.diagnostics["score_signals"]["deterministic_rerank_query_reason"]
        == "friend_place_shelter_inventory_bridge"
    )


def test_deterministic_rerank_already_applied_uses_normalized_fast_path(
    monkeypatch,
) -> None:
    query = "Where has Maria made friends?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    item = _item(
        "already_reranked",
        score=0.94,
        retrieval_source="keyword_chunks",
        text="D2:1 Maria donated her old car to a homeless shelter where she volunteers.",
    )
    diagnostics = dict(item.diagnostics)
    diagnostics["provenance"] = {
        **dict(diagnostics["provenance"]),
        "deterministic_rerank_applied": True,
    }
    item = replace(item, diagnostics=diagnostics)

    def fail_renormalize(*args, **kwargs):
        raise AssertionError("already-applied fast path re-normalized diagnostics")

    monkeypatch.setattr(
        context_ranking_module,
        "normalize_context_diagnostics",
        fail_renormalize,
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (item,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked is item


def test_deterministic_rerank_keeps_inventory_slots_query_specific() -> None:
    query = "What types of pottery have Melanie and her kids made?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    pottery = _item(
        "pottery_bowl",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D8:4 Melanie: The kids made clay bowls and a small cup.",
        score_signals={"query_expansion_reason": "decomposition_inventory_list"},
    )
    country_noise = _item(
        "country_noise",
        score=0.755,
        retrieval_source="keyword_chunks",
        text="D15:2 Melanie visited Spain and talked about countries abroad.",
        score_signals={"query_expansion_reason": "decomposition_inventory_list"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (country_noise, pottery),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["pottery_bowl"].score > by_id["country_noise"].score
    assert (
        "inventory_list_exact_evidence"
        in by_id["pottery_bowl"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "inventory_list_exact_evidence"
        not in by_id["country_noise"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_requires_specific_country_inventory_evidence() -> None:
    query = "What European countries has Maria been to?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    specific_country = _item(
        "visited_spain",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D13:24 Maria visited Spain during a school trip.",
        score_signals={"query_expansion_reason": "travel_country_inventory_bridge"},
    )
    generic_country = _item(
        "generic_country",
        score=0.755,
        retrieval_source="keyword_chunks",
        text="D13:20 Maria visited countries abroad and talked about travel plans.",
        score_signals={"query_expansion_reason": "travel_country_inventory_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_country, specific_country),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["visited_spain"].score > by_id["generic_country"].score
    assert (
        "inventory_list_exact_evidence"
        in by_id["visited_spain"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "inventory_list_exact_evidence"
        not in by_id["generic_country"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_specific_city_visit_inventory_evidence() -> None:
    query = "Which city have both Jean and John visited?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    visited_rome = _item(
        "visited_rome",
        score=0.71,
        retrieval_source="keyword_chunks",
        text="D15:1 Jon took a short trip last week to Rome to clear his mind.",
        score_signals={"query_expansion_reason": "travel_country_inventory_bridge"},
    )
    generic_trip = _item(
        "generic_trip",
        score=0.74,
        retrieval_source="keyword_chunks",
        text="D15:3 Jon talked about travel plans and visited places abroad.",
        score_signals={"query_expansion_reason": "travel_country_inventory_bridge"},
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_trip, visited_rome),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["visited_rome"].score > by_id["generic_trip"].score
    assert (
        "inventory_list_exact_evidence"
        in by_id["visited_rome"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "commonality_anchor_mismatch"
        not in by_id["visited_rome"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "inventory_list_exact_evidence"
        not in by_id["generic_trip"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_does_not_treat_volunteering_people_query_as_shelter_slot() -> None:
    query = "What people has Maria met and helped while volunteering?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    shelter_context = _item(
        "shelter_context",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D2:1 Maria volunteered at the homeless shelter every weekend.",
        score_signals={"query_expansion_reason": "decomposition_inventory_list"},
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (shelter_context,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    reasons = reranked.diagnostics.get("provenance", {}).get(
        "deterministic_rerank_reasons",
        [],
    )
    assert "inventory_list_exact_evidence" not in reasons


def test_deterministic_rerank_prefers_attributed_speaker_over_subject_self_report() -> None:
    query = "What personality traits might Melanie say Caroline has?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    melanie_trait = _item(
        "melanie_trait",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D16:18 Melanie: The sign was just a precaution, I had a great time. "
            "But thank you for your concern, you're so thoughtful!"
        ),
    )
    caroline_self_report = _item(
        "caroline_self_report",
        score=0.73,
        retrieval_source="keyword_chunks",
        text=(
            "D16:9 Caroline: Painting and drawing have helped me express my "
            "feelings and explore my identity."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (melanie_trait, caroline_self_report),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "melanie_trait"
    assert (
        "speaker_attribution_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "speaker_attribution_subject_self_report"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_direct_speaker_for_say_query() -> None:
    query = "What did Alex say about Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alex_turn = _item(
        "alex_turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex: Project Atlas should wait until the invoice check passes.",
    )
    third_party_turn = _item(
        "third_party_turn",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="D3:5 Dana: Alex and Project Atlas came up during planning.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alex_turn, third_party_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "speaker_attribution_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "speaker_attribution_other_speaker"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_direct_speaker_for_existence_query() -> None:
    query = "Did Alex ever mention Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alex_turn = _item(
        "alex_turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex: I mentioned Project Atlas during the billing call.",
    )
    wrong_speaker_turn = _item(
        "wrong_speaker_turn",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="D3:5 Dana: I mentioned Project Atlas during planning with Alex.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alex_turn, wrong_speaker_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "speaker_attribution_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "speaker_attribution_other_speaker"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_relation_requirement_decoy() -> None:
    query = "Did Alex ever mention Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    evidence = _item(
        "alex_mentioned_atlas",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex: I mentioned Project Atlas during the billing call.",
    )
    decoy = _item(
        "alex_atlas_anchor_only",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex and Project Atlas appeared in the planning summary.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (decoy, evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_mentioned_atlas"].score > by_id["alex_atlas_anchor_only"].score
    assert (
        "relation_requirement_match"
        in by_id["alex_mentioned_atlas"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "relation_requirement_missing_relation"
        in by_id["alex_atlas_anchor_only"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_relation_requirement_wrong_object() -> None:
    query = "Did Alex ever mention Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    evidence = _item(
        "alex_mentioned_atlas",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Alex mentioned Atlas during the billing call.",
    )
    wrong_object = _item(
        "alex_mentioned_apollo",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex mentioned Project Apollo during the billing call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (wrong_object, evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_mentioned_atlas"].score > by_id["alex_mentioned_apollo"].score
    assert (
        "relation_requirement_object_mismatch"
        in by_id["alex_mentioned_apollo"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_possession_relation_decoy() -> None:
    query = "Is there any evidence that Alex has a cat?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    evidence = _item(
        "alex_cat_negative_evidence",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="No evidence mentions Alex having a cat.",
    )
    decoy = _item(
        "alex_cat_cafe",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex visited the Cat Cafe after the billing call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (decoy, evidence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_cat_negative_evidence"].score > by_id["alex_cat_cafe"].score
    assert (
        "relation_requirement_missing_relation"
        in by_id["alex_cat_cafe"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_correct_action_actor_recipient_order() -> None:
    query = "What did Alex promise Maria after the Atlas call?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "alex_promised_maria",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex promised Maria he would send the Atlas invoice after the call.",
    )
    reversed_roles = _item(
        "maria_promised_alex",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D3:4 Maria promised Alex she would send the Atlas invoice after the call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_recipient_reversed"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_supports_lowercase_action_role_query() -> None:
    query = "what did alex promise maria after the atlas call?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "alex_promised_maria",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex promised Maria he would send the Atlas invoice after the call.",
    )
    reversed_roles = _item(
        "maria_promised_alex",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D3:4 Maria promised Alex she would send the Atlas invoice after the call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_recipient_reversed"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_direct_recipient_action_evidence() -> None:
    query = "Who did Alex tell about the Atlas delay?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "alex_told_maria",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex told Maria about the Atlas delay after the call.",
    )
    reversed_roles = _item(
        "maria_told_alex",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D3:4 Maria told Alex about the Atlas delay after the call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_to_recipient_evidence"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_requested_recipient_wrong_context() -> None:
    query = "Who did Alex ask to send the Atlas invoice?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "alex_asked_dana_invoice",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex asked Dana to send the Atlas invoice after the call.",
    )
    wrong_context = _item(
        "alex_asked_maria_lunch",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex asked Maria to book lunch after the call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, wrong_context),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_to_recipient_evidence"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_requested_context_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_wrong_decision_owner() -> None:
    query = "What did Caroline decide about adoption after the interview?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    caroline_decision = _item(
        "caroline_decision",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D19:3 Caroline decided to continue adoption after the agency interview.",
    )
    dana_decision = _item(
        "dana_decision",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D19:3 Adoption was mentioned near an interview, but Dana decided the next step.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (caroline_decision, dana_decision),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_supports_nominal_decision_query() -> None:
    query = "What decision did Caroline make after the interview?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    caroline_decision = _item(
        "caroline_decision",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D19:3 Caroline made the decision to continue adoption after the interview.",
    )
    dana_decision = _item(
        "dana_decision",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D19:3 Dana made the decision to continue adoption after the interview.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (caroline_decision, dana_decision),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_supports_nominal_promise_recipient_query() -> None:
    query = "What promise did Alex make to Maria after the Atlas call?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "alex_promised_maria",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex made a promise to Maria to send the Atlas invoice after the call.",
    )
    reversed_roles = _item(
        "maria_promised_alex",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D3:4 Maria made a promise to Alex to send the Atlas invoice after the call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_recipient_reversed"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_responsible_owner() -> None:
    query = "Is Alex responsible for the Atlas invoice?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alex_owner = _item(
        "alex_owner",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Alex is responsible for the Atlas invoice follow-up.",
    )
    maria_owner = _item(
        "maria_owner",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="D3:4 Maria is responsible for the Atlas invoice follow-up.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alex_owner, maria_owner),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_owner_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_owner_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_uses_recommendation_recipient_role() -> None:
    query = "Who recommended Becoming Nicole to Melanie?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_preserves_introduced_object_target_order() -> None:
    query = "Who introduced Maria to Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_introduced_maria_to_alex",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline introduced Maria to Alex at the Atlas meetup.",
    )
    reversed_roles = _item(
        "caroline_introduced_alex_to_maria",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline introduced Alex to Maria at the Atlas meetup.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_information_source_role() -> None:
    query = "Who did John hear inspiring stories from?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "john_heard_from_samuel",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="John heard inspiring stories from an elderly veteran named Samuel.",
    )
    reversed_roles = _item(
        "samuel_heard_from_john",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Samuel heard inspiring stories from John.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_information_source_evidence"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_information_source_reversed"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_support_recipient_role() -> None:
    query = "Who helped Maria with the Atlas migration?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_helped_maria",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline helped Maria with the Atlas migration after the workshop.",
    )
    reversed_roles = _item(
        "maria_helped_caroline",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Maria helped Caroline with the Atlas migration after the workshop.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_lent_recipient_role() -> None:
    query = "Who lent Alex the camera?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "maria_lent_alex",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Maria lent Alex the camera after the workshop.",
    )
    reversed_roles = _item(
        "alex_lent_maria",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex lent Maria the camera after the workshop.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_borrow_source_role() -> None:
    query = "Who did Alex borrow the camera from?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "maria_lent_alex",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Maria lent Alex the camera after the workshop.",
    )
    reversed_roles = _item(
        "alex_lent_maria",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Alex lent Maria the camera after the workshop.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_transfer_source_evidence"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_transfer_source_reversed"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_possession_gift_source_evidence() -> None:
    query = "Who gave Caroline the necklace?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    gift_source = _item(
        "caroline_necklace_gift_source",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and it reminds me of my roots."
        ),
    )
    topical_necklace = _item(
        "caroline_necklace_symbols",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "D8:2 Caroline shared a pendant necklace with a transgender symbol, "
            "a cross, and a heart."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (gift_source, topical_necklace),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_necklace_gift_source"].score > by_id["caroline_necklace_symbols"].score
    assert (
        "possession_source_evidence"
        in by_id["caroline_necklace_gift_source"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "possession_source_missing"
        in by_id["caroline_necklace_symbols"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_possession_gift_object_evidence() -> None:
    query = "What was grandma's gift to Caroline?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    gift_object = _item(
        "caroline_grandma_gift",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and it reminds me of my roots."
        ),
    )
    family_support = _item(
        "caroline_family_support",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline said her family supports her and gives her strength.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (gift_object, family_support),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "caroline_grandma_gift"


def test_deterministic_rerank_prefers_family_origin_evidence() -> None:
    query = "What country is Caroline's grandma from?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    origin = _item(
        "caroline_grandma_origin",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and it reminds me of my roots."
        ),
    )
    home_decoy = _item(
        "caroline_home_decoy",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline is building a safe home for her future children.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (origin, home_decoy),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "caroline_grandma_origin"


def test_deterministic_rerank_prefers_got_from_possession_source_evidence() -> None:
    query = "Where did Caroline's necklace come from?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    origin = _item(
        "caroline_necklace_origin",
        score=0.7,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline got a necklace from her grandma in her home country, "
            "Sweden, and it reminds her of her roots."
        ),
    )
    home_decoy = _item(
        "caroline_home_decoy",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Caroline wants to create a safe and loving home for kids, with "
            "acceptance for everyone."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (origin, home_decoy),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "caroline_necklace_origin"
    assert (
        "possession_source_evidence"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_penalizes_negated_action_role_evidence() -> None:
    query = "Who helped Maria with the Atlas migration?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_helped_maria",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline helped Maria with the Atlas migration after the workshop.",
    )
    negated = _item(
        "negated_help",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline did not help Maria with the Atlas migration after the workshop.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, negated),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_negated_evidence"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_support_presence_role() -> None:
    query = "Who was there for Caroline after the interview?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "melanie_there_for_caroline",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Melanie was there for Caroline after the agency interview.",
    )
    reversed_roles = _item(
        "caroline_there_for_melanie",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Caroline was there for Melanie after the agency interview.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_uses_whose_recommendation_recipient_role() -> None:
    query = "Whose recommendation did Melanie follow when she read Becoming Nicole?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_supports_lowercase_recipient_role_query() -> None:
    query = "who recommended Becoming Nicole to melanie?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_supports_russian_recommendation_recipient_role() -> None:
    query = "Кто посоветовал Мелани прочитать Becoming Nicole?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie_ru",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Кэролайн посоветовала Мелани прочитать Becoming Nicole.",
    )
    reversed_roles = _item(
        "melanie_to_caroline_ru",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Мелани посоветовала Кэролайн прочитать Becoming Nicole.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_recipient_mismatch"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_uses_recommendation_actor_and_recipient_roles() -> None:
    query = "What did Caroline recommend to Melanie?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (correct, reversed_roles),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "action_role_actor_recipient_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "action_role_actor_recipient_reversed"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_handles_russian_direct_speaker_query() -> None:
    query = "Что сказал Алекс про Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alex_turn = _item(
        "alex_turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        text="D3:4 Алекс: Project Atlas ждет проверки инвойса.",
    )
    third_party_turn = _item(
        "third_party_turn",
        score=0.73,
        retrieval_source="keyword_chunks",
        text="D3:5 Дана: Алекс и Project Atlas всплыли на планировании.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alex_turn, third_party_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "speaker_attribution_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "speaker_attribution_other_speaker"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_multisignal_artifact_evidence() -> None:
    query = "What text is written in the screenshot about Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    generic = _item(
        "generic",
        score=0.73,
        retrieval_source="vector_chunks",
        text="Project Atlas was discussed in a planning note.",
    )
    artifact = ContextItem(
        item_id="artifact_image_ocr",
        item_type="extraction_artifact",
        text="Screenshot OCR detected text: Project Atlas budget threshold is 25k.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="image-1",
                chunk_id="ocr-region-1",
                bbox=(10.0, 20.0, 160.0, 70.0),
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": [
                "artifact_evidence",
                "vector_chunks",
                "canonical_anchors",
            ],
            "evidence_modality": "image",
            "evidence_kind": "ocr_region",
            "score_signals": {"base_score": 0.7},
            "provenance": {
                "retrieval_sources": [
                    "artifact_evidence",
                    "vector_chunks",
                    "canonical_anchors",
                ]
            },
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic, artifact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[1].score > reranked[0].score
    assert (
        reranked[1].diagnostics["score_signals"]["deterministic_rerank_boost"]
        > reranked[0].diagnostics["score_signals"]["deterministic_rerank_boost"]
    )
    assert (
        "explicit_requirement_covered"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_first_party_artifact_inventory_evidence() -> None:
    query = "Which files are related to Project Atlas?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    note = _item(
        "atlas_file_note",
        score=0.72,
        retrieval_source="keyword_chunks",
        text=(
            "Project Atlas file note: someone mentioned a screenshot and document "
            "might exist for the launch review."
        ),
    )
    artifact = ContextItem(
        item_id="atlas_screenshot_ocr",
        item_type="extraction_artifact",
        text=(
            "Project Atlas artifact inventory: uploaded screenshot file metadata, "
            "OCR evidence, original image asset, and linked launch review source refs."
        ),
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="asset-image-1",
                chunk_id="ocr-region-1",
                bbox=(8.0, 12.0, 220.0, 88.0),
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence", "vector_chunks"],
            "evidence_kind": "ocr_region",
            "evidence_modality": "image",
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["artifact_evidence", "vector_chunks"]},
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (note, artifact),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[1].score > reranked[0].score
    assert (
        reranked[1]
        .diagnostics["score_signals"]
        .get("artifact_inventory_first_party_evidence")
        == 1.0
    )
    assert (
        "artifact_inventory_first_party_evidence"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "artifact_inventory_first_party_evidence"
        not in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        reranked[0]
        .diagnostics["score_signals"]
        .get("artifact_inventory_unbacked_reference")
        == 1.0
    )
    assert (
        "artifact_inventory_unbacked_reference"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_localized_transcript_evidence() -> None:
    query = "What did the transcript say at 02:15?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    plain_transcript = ContextItem(
        item_id="plain_call_segment",
        item_type="extraction_artifact",
        text="Transcript segment at 02:15: Alex said the launch checklist is needed.",
        score=0.73,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="audio-1",
                chunk_id="segment-0215",
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence"],
            "evidence_modality": "audio",
            "evidence_kind": "transcript_segment",
            "score_signals": {"base_score": 0.73},
            "provenance": {"retrieval_sources": ["artifact_evidence"]},
        },
    )
    transcript = ContextItem(
        item_id="atlas_call_segment",
        item_type="extraction_artifact",
        text="Transcript segment at 02:15: Alex said the launch checklist is needed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="audio-1",
                chunk_id="segment-0215",
                time_start_ms=135000,
                time_end_ms=142000,
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence", "vector_chunks"],
            "evidence_modality": "audio",
            "evidence_kind": "transcript_segment",
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["artifact_evidence", "vector_chunks"]},
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (plain_transcript, transcript),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[1].score > reranked[0].score
    assert (
        "localized_evidence_source"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_quote_backed_source_citation() -> None:
    query = "Show source citation for the Atlas decision"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    summary = _item(
        "atlas_decision_summary",
        score=0.72,
        retrieval_source="keyword_chunks",
        text="Atlas decision summary: Alex approved the launch path.",
    )
    citation = ContextItem(
        item_id="atlas_decision_quote",
        item_type="chunk",
        text="Evidence quote from the meeting transcript: Alex approved the Atlas launch path.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="meeting-notes-1",
                chunk_id="chunk-7",
                quote_preview="Alex approved the Atlas launch path.",
            ),
        ),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )

    reranked = apply_deterministic_rerank_adjustments(
        (summary, citation),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[1].score > reranked[0].score
    assert (
        "citation_quote_evidence"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "citation_quote_evidence"
        not in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_does_not_localize_plain_source_ref() -> None:
    query = "What did Alex say in the Project Atlas call?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="plain_audio_segment",
        item_type="extraction_artifact",
        text="Transcript segment: Alex said Project Atlas needs the launch checklist.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="audio-1",
                chunk_id="segment",
            ),
        ),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "retrieval_sources": ["artifact_evidence"],
            "evidence_modality": "audio",
            "evidence_kind": "transcript_segment",
            "score_signals": {"base_score": 0.7},
            "provenance": {"retrieval_sources": ["artifact_evidence"]},
        },
    )

    (reranked,) = apply_deterministic_rerank_adjustments(
        (item,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    reasons = reranked.diagnostics["provenance"].get("deterministic_rerank_reasons", [])
    assert "localized_evidence_source" not in reasons
    assert "multi_localized_evidence_source" not in reasons


def test_deterministic_rerank_does_not_apply_twice() -> None:
    query = "What changed after the Atlas call?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    item = _item(
        "atlas",
        score=0.7,
        retrieval_source="keyword_chunks",
        retrieval_sources=("keyword_chunks", "vector_chunks"),
        text="Alex said after the Atlas call that the launch date changed.",
    )

    first_pass = apply_deterministic_rerank_adjustments(
        (item,),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    second_pass = apply_deterministic_rerank_adjustments(
        first_pass,
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert second_pass[0].score == first_pass[0].score


def _item(
    item_id: str,
    *,
    score: float,
    retrieval_source: str,
    retrieval_sources: tuple[str, ...] | None = None,
    source_refs: tuple[SourceRef, ...] | None = None,
    text: str | None = None,
    score_signals: dict[str, object] | None = None,
    fact_status: str | None = None,
    event_temporal_hint_code: str | None = None,
    temporal_hint_code: str | None = None,
    review_only: bool = False,
) -> ContextItem:
    listed_sources = retrieval_sources or (retrieval_source,)
    signals: dict[str, object] = {"base_score": score}
    if score_signals:
        signals.update(score_signals)
    provenance: dict[str, object] = {"retrieval_sources": list(listed_sources)}
    if fact_status:
        provenance["fact_status"] = fact_status
    if event_temporal_hint_code:
        provenance["event_temporal_hint_code"] = event_temporal_hint_code
    if temporal_hint_code:
        provenance["temporal_hint_code"] = temporal_hint_code
    diagnostics: dict[str, object] = {
        "retrieval_source": retrieval_source,
        "retrieval_sources": list(listed_sources),
        "score_signals": signals,
        "provenance": provenance,
    }
    if review_only:
        diagnostics["review_only"] = True
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text or item_id,
        score=score,
        source_refs=source_refs or (SourceRef(source_type="document", source_id="doc"),),
        diagnostics=diagnostics,
    )


def _anchor_item(
    item_id: str,
    *,
    score: float,
    kind: str,
    text: str,
) -> ContextItem:
    diagnostics = {
        "retrieval_source": "canonical_anchors",
        "retrieval_sources": ["canonical_anchors"],
        "anchor_kind": kind,
        "score_signals": {
            "base_score": score,
            "anchor_kind": kind,
            "anchor_identity_term_count": 3,
            "anchor_alias_identity_term_count": 1,
        },
        "provenance": {
            "retrieval_sources": ["canonical_anchors"],
            "anchor_kind": kind,
            "anchor_identity_profile": {
                "anchor_kind": kind,
                "identity_term_count": 3,
                "alias_identity_term_count": 1,
            },
            "source_ref_count": 1,
        },
    }
    return ContextItem(
        item_id=item_id,
        item_type="anchor",
        text=text,
        score=score,
        source_refs=(
            SourceRef(source_type="memory_anchor", source_id=f"anchor:{item_id}"),
        ),
        diagnostics=diagnostics,
    )
