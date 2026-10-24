"""Query relevance ranking policy; one implementation authority."""

from __future__ import annotations

import re
from collections.abc import Callable

from infinity_context_core.application.context_bm25_ranking import (
    _query_expansion_terms,
    _QueryExpansionTerms,
)
from infinity_context_core.application.context_lexical import text_variant_profile
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY as _QUERY_REASON_PRIORITY,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS as _QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    score_query_terms_relevance_against_profile,
)

QueryExpansionTermsFn = Callable[[object], _QueryExpansionTerms]
QueryRelevanceRankKeyFn = Callable[
    [tuple[str, str, QueryRelevance]], tuple[bool, int, int, int, float, bool]
]
TextVariantProfileFn = Callable[
    [str], tuple[dict[str, int], tuple[tuple[str, dict[str, int]], ...]]
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


def query_reason_priority_for_relevance(reason: str, relevance: QueryRelevance) -> int:
    return _query_reason_priority_for_relevance(reason, relevance)


_STRICT_QUERY_REASON_MIN_DISTINCTIVE_HITS = {
    "book_suggestion_bridge": 4,
    "music_artist_answer_bridge": 4,
}


_DIRECT_VISUAL_TEXT_QUERY_RE = re.compile(
    r"\b(?:what|which)\b(?=.{0,120}\b(?:ocr|text|written|label|title)\b)"
    r"(?=.{0,120}\b(?:screenshot|screen|image|visual)\b)",
    re.IGNORECASE | re.DOTALL,
)


_ARTIFACT_CONTEXT_COMPOSITE_QUERY_RE = re.compile(
    r"\b(?:changed|after|before|call|meeting|conversation|about)\b",
    re.IGNORECASE,
)


_BOOK_SUGGESTION_PROJECT_FALSE_FRIEND_RE = re.compile(
    r"\b(?:project|launch|planning|proposal|task|workflow)\s+suggestion\b|"
    r"\bsuggestion\s+(?:from|about)\b(?=.{0,80}\b(?:project|launch|planning|proposal|task)\b)",
    re.IGNORECASE | re.DOTALL,
)


_BOOK_SUGGESTION_EVIDENCE_CUE_RE = re.compile(
    r"[\"“][^\"”]{2,80}[\"”]|"
    r"\b(?:book|novel|memoir|author|chapter|must[-\s]?see|great\s+read|"
    r"read\s+(?:the\s+)?book|recommended\s+(?:the\s+)?book|"
    r"suggested\s+(?:the\s+)?book)\b",
    re.IGNORECASE,
)


def best_query_relevance_for_plan(
    plan: QueryExpansionPlan,
    *,
    text: str,
    query_expansion_terms_fn: Callable[
        [QueryExpansionPlan], _QueryExpansionTerms
    ] = _query_expansion_terms,
    text_variant_profile_fn: Callable[..., object] = text_variant_profile,
) -> tuple[str, str, QueryRelevance]:
    text_counts, text_variants = text_variant_profile_fn(text)
    scored = tuple(
        (
            (
                query,
                reason,
                score_query_terms_relevance_against_profile(
                    terms=terms, text_counts=text_counts, text_variants=text_variants
                ),
            )
            for query, reason, terms in query_expansion_terms_fn(plan)
        )
    )
    strict_filtered = tuple(
        item
        for item in scored
        if not _strict_query_reason_below_minimum(reason=item[1], relevance=item[2])
    )
    filtered = tuple(
        item
        for item in strict_filtered or scored
        if not _query_relevance_false_friend(plan=plan, item=item, text=text)
    )
    return max(
        filtered or strict_filtered or scored,
        key=lambda item: _query_relevance_rank_key_for_plan(plan, item),
    )


def query_relevance_rank_key(
    item: tuple[str, str, QueryRelevance],
) -> tuple[bool, int, int, int, float, bool]:
    _, reason, relevance = item
    return (
        is_query_relevance_sufficient(relevance),
        _query_reason_priority_for_relevance(reason, relevance),
        relevance.distinctive_term_hits,
        relevance.unique_term_hits,
        relevance.score_boost,
        reason == "original_query",
    )


def _query_relevance_rank_key_for_plan(
    plan: QueryExpansionPlan,
    item: tuple[str, str, QueryRelevance],
) -> tuple[bool, int, int, int, float, bool]:
    query, reason, relevance = item
    priority = _query_reason_priority_for_relevance(reason, relevance)
    if reason == "visual_text_evidence_bridge" and _is_direct_visual_text_query(
        plan.original_query
    ):
        priority += 2
    if reason == "decomposition_quantity_count" and _is_direct_quantity_query(plan.original_query):
        priority += 2
    if reason == "decomposition_sport_team_attribute" and any(
        item.reason == "decomposition_activity_duration" for item in plan.decompositions
    ):
        # Preserve the domain-specific decomposition when a compound query also
        # requests a generic measured-duration answer unit.
        priority += 2
    return (
        is_query_relevance_sufficient(relevance),
        priority,
        relevance.distinctive_term_hits,
        relevance.unique_term_hits,
        relevance.score_boost,
        reason == "original_query",
    )


def _is_direct_visual_text_query(query: str) -> bool:
    return bool(
        _DIRECT_VISUAL_TEXT_QUERY_RE.search(query)
        and _ARTIFACT_CONTEXT_COMPOSITE_QUERY_RE.search(query) is None
    )


def _is_direct_quantity_query(query: str) -> bool:
    return bool(
        re.search(
            r"\b(?:how many|how much|number of|count|total)\b",
            query,
            re.IGNORECASE,
        )
    )


def _query_relevance_false_friend(
    *,
    plan: QueryExpansionPlan,
    item: tuple[str, str, QueryRelevance],
    text: str,
) -> bool:
    _, reason, relevance = item
    if reason != "book_suggestion_bridge":
        return False
    if relevance.distinctive_term_hits < 5:
        return False
    query = plan.original_query.casefold()
    if "book" not in query:
        return False
    if _BOOK_SUGGESTION_EVIDENCE_CUE_RE.search(text):
        return False
    return _BOOK_SUGGESTION_PROJECT_FALSE_FRIEND_RE.search(text) is not None


def _strict_query_reason_below_minimum(
    *,
    reason: str,
    relevance: QueryRelevance,
) -> bool:
    min_hits = _STRICT_QUERY_REASON_MIN_DISTINCTIVE_HITS.get(reason)
    return min_hits is not None and relevance.distinctive_term_hits < min_hits


def _query_reason_priority_for_relevance(
    reason: str,
    relevance: QueryRelevance,
) -> int:
    min_hits = _QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS.get(reason, 0)
    if relevance.distinctive_term_hits < min_hits:
        return 0
    return _QUERY_REASON_PRIORITY.get(reason, 0)

QueryExpansionTerms = _QueryExpansionTerms
