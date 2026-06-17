"""Query relevance helpers for context assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryRelevance:
    score_boost: float
    query_term_count: int
    unique_term_hits: int
    capped_frequency_hits: int
    hit_ratio: float


def score_query_relevance(*, query: str, text: str, max_boost: float = 0.12) -> QueryRelevance:
    terms = _terms(query)
    if not terms:
        return QueryRelevance(
            score_boost=0.0,
            query_term_count=0,
            unique_term_hits=0,
            capped_frequency_hits=0,
            hit_ratio=0.0,
        )
    lowered = text.casefold()
    unique_terms = tuple(dict.fromkeys(terms))
    unique_hits = sum(1 for term in unique_terms if term in lowered)
    capped_frequency_hits = sum(min(lowered.count(term), 3) for term in unique_terms)
    hit_ratio = unique_hits / len(unique_terms)
    frequency_boost = min(0.025, capped_frequency_hits * 0.002)
    score_boost = min(max_boost, round(hit_ratio * max_boost + frequency_boost, 4))
    return QueryRelevance(
        score_boost=score_boost,
        query_term_count=len(unique_terms),
        unique_term_hits=unique_hits,
        capped_frequency_hits=capped_frequency_hits,
        hit_ratio=round(hit_ratio, 4),
    )


def _terms(query: str) -> tuple[str, ...]:
    return tuple(term for term in re.findall(r"\w+", query.casefold()) if len(term) >= 3)
