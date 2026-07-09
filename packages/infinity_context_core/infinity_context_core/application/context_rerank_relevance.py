"""Query relevance diagnostics bridge for deterministic rerank."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from infinity_context_core.application.context_diagnostics import (
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem

BestQueryRelevanceFn = Callable[..., tuple[str, str, QueryRelevance]]


def is_long_query_weak_overlap(relevance: QueryRelevance) -> bool:
    if relevance.query_term_count < 6:
        return False
    if relevance.phrase_bigram_hits > 0:
        return False
    return relevance.distinctive_term_hits <= 1 and relevance.unique_term_hits <= 2


def best_query_relevance_for_rerank(
    plan: QueryExpansionPlan,
    *,
    item: ContextItem,
    cache: dict[str, tuple[str, str, QueryRelevance]] | None,
    best_query_relevance_fn: BestQueryRelevanceFn,
) -> tuple[str, str, QueryRelevance]:
    diagnostics_relevance = _query_relevance_from_item_diagnostics(plan, item)
    if diagnostics_relevance is not None:
        return diagnostics_relevance
    text = item.text
    if cache is None:
        return best_query_relevance_fn(plan, text=text)
    cached = cache.get(text)
    if cached is not None:
        return cached
    result = best_query_relevance_fn(plan, text=text)
    cache[text] = result
    return result


def _query_relevance_from_item_diagnostics(
    plan: QueryExpansionPlan,
    item: ContextItem,
) -> tuple[str, str, QueryRelevance] | None:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    reason_value = signals.get("query_expansion_reason") or diagnostics.get(
        "query_expansion_reason"
    )
    if not isinstance(reason_value, str) or not reason_value:
        return None
    query_text = _query_text_for_expansion_reason(plan, reason_value)
    if query_text is None:
        return None
    relevance = _query_relevance_from_score_signals(signals)
    if relevance is None:
        return None
    return query_text, reason_value, relevance


def _query_text_for_expansion_reason(
    plan: QueryExpansionPlan,
    reason: str,
) -> str | None:
    for expansion in plan.retrieval_queries:
        if expansion.reason == reason:
            return expansion.query
    return None


def _query_relevance_from_score_signals(
    signals: Mapping[str, object],
) -> QueryRelevance | None:
    query_term_count = _non_negative_int_signal(signals.get("query_term_count"))
    unique_term_hits = _non_negative_int_signal(signals.get("unique_term_hits"))
    capped_frequency_hits = _non_negative_int_signal(signals.get("capped_frequency_hits"))
    distinctive_term_count = _non_negative_int_signal(signals.get("distinctive_term_count"))
    distinctive_term_hits = _non_negative_int_signal(signals.get("distinctive_term_hits"))
    phrase_bigram_count = _non_negative_int_signal(signals.get("phrase_bigram_count"))
    phrase_bigram_hits = _non_negative_int_signal(signals.get("phrase_bigram_hits"))
    if (
        query_term_count is None
        or unique_term_hits is None
        or capped_frequency_hits is None
        or distinctive_term_count is None
        or distinctive_term_hits is None
        or phrase_bigram_count is None
        or phrase_bigram_hits is None
    ):
        return None
    hit_ratio = _non_negative_float_signal(signals.get("hit_ratio"))
    score_boost = _non_negative_float_signal(signals.get("query_relevance_boost"))
    phrase_boost = _non_negative_float_signal(signals.get("phrase_boost"))
    if hit_ratio is None or score_boost is None or phrase_boost is None:
        return None
    return QueryRelevance(
        score_boost=score_boost,
        query_term_count=query_term_count,
        unique_term_hits=unique_term_hits,
        capped_frequency_hits=capped_frequency_hits,
        hit_ratio=hit_ratio,
        distinctive_term_count=distinctive_term_count,
        distinctive_term_hits=distinctive_term_hits,
        phrase_bigram_count=phrase_bigram_count,
        phrase_bigram_hits=phrase_bigram_hits,
        phrase_boost=phrase_boost,
    )


def _non_negative_int_signal(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return None


def _non_negative_float_signal(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return max(0.0, float(value))
    return None
