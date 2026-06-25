from infinity_context_core.application.context_domain_rerank_apply import (
    apply_domain_rerank_signals,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_apply_domain_rerank_signals_collects_adjustments_and_reasons() -> None:
    item = ContextItem(
        item_id="audrey_roasted_chicken",
        item_type="chunk",
        text="Audrey says roasted chicken is one of her favorite comfort meals.",
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"query_expansion_reason": "food_preference_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="Which meat does Audrey prefer eating more than others?",
        query_reason="food_preference_bridge",
        item=item,
        relevance=QueryRelevance(
            score_boost=0.0,
            query_term_count=5,
            unique_term_hits=5,
            capped_frequency_hits=5,
            hit_ratio=1.0,
            distinctive_term_count=5,
            distinctive_term_hits=5,
        ),
    )

    assert adjustment.boost > 0
    assert adjustment.penalty == 0
    assert "preference_exact_evidence" in adjustment.reasons


def test_apply_domain_rerank_signals_includes_outdoor_preference_evidence() -> None:
    item = ContextItem(
        item_id="melanie_perseid_trip",
        item_type="chunk",
        text=(
            "Melanie remembered the camping trip where her family watched the Perseid "
            "meteor shower and felt at one with the universe."
        ),
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"query_expansion_reason": "outdoor_preference_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="Would Melanie be more interested in a national park or a theme park?",
        query_reason="outdoor_preference_bridge",
        item=item,
        relevance=QueryRelevance(
            score_boost=0.0,
            query_term_count=6,
            unique_term_hits=6,
            capped_frequency_hits=6,
            hit_ratio=1.0,
            distinctive_term_count=6,
            distinctive_term_hits=5,
        ),
    )

    assert adjustment.boost > 0
    assert adjustment.penalty == 0
    assert "outdoor_preference_exact_evidence" in adjustment.reasons


def test_apply_domain_rerank_signals_includes_causal_reason_evidence() -> None:
    item = ContextItem(
        item_id="gina_job_loss",
        item_type="chunk",
        text=(
            "Gina lost her Door Dash job, so she started thinking seriously "
            "about opening her own clothing store."
        ),
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"query_expansion_reason": "business_start_reason_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="Why did Gina start her own clothing store?",
        query_reason="business_start_reason_bridge",
        item=item,
        relevance=QueryRelevance(
            score_boost=0.0,
            query_term_count=5,
            unique_term_hits=5,
            capped_frequency_hits=5,
            hit_ratio=1.0,
            distinctive_term_count=5,
            distinctive_term_hits=5,
        ),
    )

    assert adjustment.boost > 0
    assert "causal_reason_exact_evidence" in adjustment.reasons


def test_apply_domain_rerank_signals_boosts_birdwatching_schedule_exact_evidence() -> None:
    item = ContextItem(
        item_id="andrew_birdwatching_binos",
        item_type="chunk",
        text=(
            "D20:21 Andrew: Nice! Looks like you're prepared. I'll bring my "
            "binos and a notebook to log them at the trip."
        ),
        score=0.97,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-44:session_20:D20:21:turn",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {"query_expansion_reason": "birdwatching_city_schedule_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="What could Andrew do to make birdwatching fit in his city schedule?",
        query_reason="birdwatching_city_schedule_bridge",
        item=item,
        relevance=_relevance(distinctive_term_hits=7),
    )

    assert adjustment.boost > 0
    assert "birdwatching_city_schedule_exact_evidence" in adjustment.reasons
    assert (
        dict(adjustment.rank_signals)["birdwatching_city_schedule_answer_evidence"] >= 2
    )


def test_apply_domain_rerank_signals_penalizes_birdwatching_broad_activity_noise() -> None:
    item = ContextItem(
        item_id="generic_city_dogs",
        item_type="chunk",
        text=(
            "D11:3 Andrew: Dogs make life fun in the city, but finding parks "
            "and enough room can be tough."
        ),
        score=0.99,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="locomo:conv-44:D11:3"),),
        diagnostics={
            "score_signals": {"query_expansion_reason": "decomposition_activity_participation"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="What could Andrew do to make birdwatching fit in his city schedule?",
        query_reason="decomposition_activity_participation",
        item=item,
        relevance=_relevance(distinctive_term_hits=7),
    )

    assert adjustment.penalty > 0
    assert "birdwatching_city_schedule_broad_activity_noise" in adjustment.reasons


def test_apply_domain_rerank_signals_boosts_slot_diverse_pottery_aggregation() -> None:
    item = ContextItem(
        item_id="pottery_aggregation",
        item_type="chunk",
        text=(
            "D5:6 Melanie made a painted pottery bowl in class. "
            "D8:4 Melanie and her kids made a clay cup with a dog face."
        ),
        score=0.78,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_aggregation_chunks",
            "retrieval_sources": ["keyword_aggregation_chunks"],
            "score_signals": {"query_expansion_reason": "pottery_type_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="What types of pottery have Melanie and her kids made?",
        query_reason="pottery_type_bridge",
        item=item,
        relevance=_relevance(distinctive_term_hits=9),
    )

    assert adjustment.boost >= 0.058
    assert "aggregation_list_slot_diverse_evidence" in adjustment.reasons
    assert "aggregation_list_multi_evidence" not in adjustment.reasons


def test_apply_domain_rerank_signals_boosts_slot_diverse_vector_event_evidence() -> None:
    item = ContextItem(
        item_id="lgbtq_events_vector",
        item_type="chunk",
        text=(
            "D1:3 Caroline attended an LGBTQ support group. D3:1 She gave a "
            "school speech about her transgender journey. D5:1 She marched "
            "in a pride parade."
        ),
        score=0.81,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "vector_chunks",
            "retrieval_sources": ["vector_chunks"],
            "score_signals": {"query_expansion_reason": "event_participation_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="What LGBTQ+ events has Caroline participated in?",
        query_reason="event_participation_bridge",
        item=item,
        relevance=_relevance(distinctive_term_hits=8),
    )

    assert adjustment.boost >= 0.058
    assert "aggregation_list_slot_diverse_evidence" in adjustment.reasons


def test_apply_domain_rerank_signals_boosts_broad_lgbtq_event_slots() -> None:
    item = ContextItem(
        item_id="lgbtq_event_activity_vector",
        item_type="chunk",
        text=(
            "D9:2 Caroline joined a mentorship program for LGBTQ youth. "
            "D10:3 She joined a new LGBTQ activist group. "
            "D14:33 She organized an LGBTQ art show with her paintings."
        ),
        score=0.79,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "vector_chunks",
            "retrieval_sources": ["vector_chunks"],
            "score_signals": {"query_expansion_reason": "event_participation_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="What LGBTQ+ events has Caroline participated in?",
        query_reason="event_participation_bridge",
        item=item,
        relevance=_relevance(distinctive_term_hits=8),
    )

    assert adjustment.boost >= 0.058
    assert "aggregation_list_slot_diverse_evidence" in adjustment.reasons


def test_apply_domain_rerank_signals_penalizes_single_slot_list_evidence() -> None:
    item = ContextItem(
        item_id="single_pride_event",
        item_type="chunk",
        text="D5:1 Caroline marched in a pride parade with rainbow flags.",
        score=0.82,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"query_expansion_reason": "lgbtq_pride_event_bridge"},
        },
    )

    adjustment = apply_domain_rerank_signals(
        query="What LGBTQ+ events has Caroline participated in?",
        query_reason="lgbtq_pride_event_bridge",
        item=item,
        relevance=_relevance(distinctive_term_hits=7),
        has_multi_evidence_aggregation_candidate=True,
    )

    assert adjustment.penalty >= 0.04
    assert "aggregation_list_single_evidence_incomplete" in adjustment.reasons


def _relevance(*, distinctive_term_hits: int) -> QueryRelevance:
    return QueryRelevance(
        score_boost=0.0,
        query_term_count=8,
        unique_term_hits=distinctive_term_hits,
        capped_frequency_hits=distinctive_term_hits,
        hit_ratio=1.0,
        distinctive_term_count=8,
        distinctive_term_hits=distinctive_term_hits,
    )
