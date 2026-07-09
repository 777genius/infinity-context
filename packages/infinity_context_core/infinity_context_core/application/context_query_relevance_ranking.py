"""Query relevance selection policy for context ranking."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from infinity_context_core.application.context_lexical import LexicalQueryTerm
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY,
    QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    score_query_terms_relevance_against_profile,
)

QueryExpansionTerms: TypeAlias = tuple[tuple[str, str, tuple[LexicalQueryTerm, ...]], ...]
QueryExpansionTermsFn: TypeAlias = Callable[[object], QueryExpansionTerms]
QueryRelevanceRankKeyFn: TypeAlias = Callable[
    [tuple[str, str, QueryRelevance]],
    tuple[bool, int, int, int, float, bool],
]
TextVariantProfileFn: TypeAlias = Callable[
    [str],
    tuple[dict[str, int], tuple[tuple[str, dict[str, int]], ...]],
]


def best_query_relevance(
    plan: object,
    *,
    text: str,
    query_expansion_terms_fn: QueryExpansionTermsFn,
    query_relevance_rank_key_fn: QueryRelevanceRankKeyFn,
    text_variant_profile_fn: TextVariantProfileFn,
) -> tuple[str, str, QueryRelevance]:
    text_counts, text_variants = text_variant_profile_fn(text)
    scored = tuple(
        (
            query,
            reason,
            score_query_terms_relevance_against_profile(
                terms=terms,
                text_counts=text_counts,
                text_variants=text_variants,
            ),
        )
        for query, reason, terms in query_expansion_terms_fn(plan)
    )
    return max(scored, key=query_relevance_rank_key_fn)


def query_relevance_rank_key(
    item: tuple[str, str, QueryRelevance],
) -> tuple[bool, int, int, int, float, bool]:
    _, reason, relevance = item
    return (
        is_query_relevance_sufficient(relevance),
        query_reason_priority_for_relevance(reason, relevance),
        relevance.distinctive_term_hits,
        relevance.unique_term_hits,
        relevance.score_boost,
        reason == "original_query",
    )


def query_reason_priority_for_relevance(
    reason: str,
    relevance: QueryRelevance,
) -> int:
    min_hits = QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS.get(reason, 0)
    if relevance.distinctive_term_hits < min_hits:
        return 0
    return QUERY_REASON_PRIORITY.get(reason, 0)
