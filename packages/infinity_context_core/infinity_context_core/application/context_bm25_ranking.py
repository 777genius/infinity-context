"""BM25 lexical ranking policy for context candidates."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_stats,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY as _QUERY_REASON_PRIORITY,
)
from infinity_context_core.application.dto import ContextItem

_BM25_K1 = 1.2
_BM25_B = 0.75
_BM25_MAX_BOOST = 0.035
_QueryExpansionTerms = tuple[tuple[str, str, tuple[LexicalQueryTerm, ...]], ...]
_QueryExpansionTermsFn = Callable[[QueryExpansionPlan], _QueryExpansionTerms]
_QueryTermsFn = Callable[[str], tuple[LexicalQueryTerm, ...]]
_QueryTermFrequencyFn = Callable[[LexicalQueryTerm, Mapping[str, int]], int]


@dataclass(frozen=True)
class _Bm25Document:
    item: ContextItem
    term_frequencies: tuple[int, ...]
    length: int


@dataclass(frozen=True)
class _Bm25PreparedItem:
    item: ContextItem
    text_counts: Mapping[str, int]
    length: int


@dataclass(frozen=True)
class _Bm25QueryMatch:
    normalized_score: float
    query_term_count: int
    matched_term_count: int
    query_reason: str
    query_coverage: float = 0.0


_Bm25TermFrequencyCache = dict[tuple[int, LexicalQueryTerm], int]


def apply_bm25_lexical_boosts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
    max_boost: float = _BM25_MAX_BOOST,
    query_terms_fn: _QueryTermsFn = query_terms,
    query_term_frequency_fn: _QueryTermFrequencyFn = query_term_frequency,
) -> tuple[ContextItem, ...]:
    if len(items) <= 1 or k1 <= 0 or not 0 <= b <= 1 or max_boost <= 0:
        return items
    terms = query_terms_fn(query)
    if not terms:
        return items
    documents, raw_scores = _bm25_raw_scores(
        items=items,
        terms=terms,
        k1=k1,
        b=b,
        query_term_frequency_fn=query_term_frequency_fn,
    )
    max_raw_score = max(raw_scores, default=0.0)
    if max_raw_score <= 0:
        return items
    return tuple(
        _with_bm25_lexical_boost(
            document.item,
            raw_score=raw_score,
            max_raw_score=max_raw_score,
            max_boost=max_boost,
            query_term_count=len(terms),
            matched_term_count=sum(1 for frequency in document.term_frequencies if frequency > 0),
        )
        for document, raw_score in zip(documents, raw_scores, strict=True)
    )


def apply_query_plan_bm25_lexical_boosts(
    items: tuple[ContextItem, ...],
    *,
    plan: QueryExpansionPlan,
    bm25_text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
    max_boost: float = _BM25_MAX_BOOST,
    query_expansion_terms_fn: _QueryExpansionTermsFn | None = None,
    query_term_frequency_fn: _QueryTermFrequencyFn = query_term_frequency,
) -> tuple[ContextItem, ...]:
    if len(items) <= 1 or k1 <= 0 or not 0 <= b <= 1 or max_boost <= 0:
        return items
    matches = _best_bm25_query_matches(
        items=items,
        plan=plan,
        k1=k1,
        b=b,
        bm25_text_stats_cache=bm25_text_stats_cache,
        query_expansion_terms_fn=query_expansion_terms_fn,
        query_term_frequency_fn=query_term_frequency_fn,
    )
    if not any(match.normalized_score > 0 for match in matches):
        return items
    return tuple(
        _with_bm25_lexical_boost(
            item,
            raw_score=match.normalized_score,
            max_raw_score=1.0,
            max_boost=max_boost,
            query_term_count=match.query_term_count,
            matched_term_count=match.matched_term_count,
            query_reason=match.query_reason,
            query_coverage=match.query_coverage,
        )
        for item, match in zip(items, matches, strict=True)
    )


@lru_cache(maxsize=512)
def _query_expansion_terms_for_signature(
    signature: tuple[tuple[str, str], ...],
) -> _QueryExpansionTerms:
    return tuple((query, reason, query_terms(query)) for query, reason in signature)


def _query_expansion_terms(plan: QueryExpansionPlan) -> _QueryExpansionTerms:
    return _query_expansion_terms_for_signature(
        tuple((expansion.query, expansion.reason) for expansion in plan.retrieval_queries)
    )


def _best_bm25_query_matches(
    *,
    items: tuple[ContextItem, ...],
    plan: QueryExpansionPlan,
    k1: float,
    b: float,
    bm25_text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
    query_expansion_terms_fn: _QueryExpansionTermsFn | None = None,
    query_term_frequency_fn: _QueryTermFrequencyFn = query_term_frequency,
) -> tuple[_Bm25QueryMatch, ...]:
    prepared_items = tuple(
        _bm25_prepared_item(item, text_stats_cache=bm25_text_stats_cache)
        for item in items
    )
    term_frequency_cache: _Bm25TermFrequencyCache = {}
    best_matches = tuple(
        _Bm25QueryMatch(
            normalized_score=0.0,
            query_term_count=0,
            matched_term_count=0,
            query_reason="",
            query_coverage=0.0,
        )
        for _ in items
    )
    query_expansion_terms_fn = query_expansion_terms_fn or _query_expansion_terms
    for _, reason, terms in query_expansion_terms_fn(plan):
        if not terms:
            continue
        documents, raw_scores = _bm25_raw_scores_for_prepared(
            prepared_items=prepared_items,
            terms=terms,
            k1=k1,
            b=b,
            term_frequency_cache=term_frequency_cache,
            query_term_frequency_fn=query_term_frequency_fn,
        )
        max_raw_score = max(raw_scores, default=0.0)
        if max_raw_score <= 0:
            continue
        query_matches: list[_Bm25QueryMatch] = []
        for document, raw_score in zip(documents, raw_scores, strict=True):
            matched_term_count = sum(1 for frequency in document.term_frequencies if frequency > 0)
            coverage = _bm25_query_coverage(
                matched_term_count=matched_term_count,
                query_term_count=len(terms),
            )
            query_matches.append(
                _Bm25QueryMatch(
                    normalized_score=round(
                        min(1.0, raw_score / max_raw_score) * coverage,
                        6,
                    ),
                    query_term_count=len(terms),
                    matched_term_count=matched_term_count,
                    query_reason=reason,
                    query_coverage=coverage,
                )
            )
        best_matches = tuple(
            _select_bm25_query_match(best, candidate)
            for best, candidate in zip(best_matches, tuple(query_matches), strict=True)
        )
    return best_matches


def _select_bm25_query_match(
    best: _Bm25QueryMatch,
    candidate: _Bm25QueryMatch,
) -> _Bm25QueryMatch:
    if candidate.matched_term_count <= 0:
        return best
    if candidate.normalized_score > best.normalized_score:
        return candidate
    if candidate.normalized_score < best.normalized_score:
        return best
    if candidate.matched_term_count > best.matched_term_count:
        return candidate
    if candidate.matched_term_count < best.matched_term_count:
        return best
    candidate_priority = _QUERY_REASON_PRIORITY.get(candidate.query_reason, 0)
    best_priority = _QUERY_REASON_PRIORITY.get(best.query_reason, 0)
    if candidate_priority > best_priority:
        return candidate
    if candidate_priority < best_priority:
        return best
    if candidate.query_reason == "original_query" and best.query_reason != "original_query":
        return candidate
    return best


def _bm25_raw_scores(
    *,
    items: tuple[ContextItem, ...],
    terms: tuple[LexicalQueryTerm, ...],
    k1: float,
    b: float,
    query_term_frequency_fn: _QueryTermFrequencyFn = query_term_frequency,
) -> tuple[tuple[_Bm25Document, ...], tuple[float, ...]]:
    prepared_items = tuple(_bm25_prepared_item(item) for item in items)
    return _bm25_raw_scores_for_prepared(
        prepared_items=prepared_items,
        terms=terms,
        k1=k1,
        b=b,
        query_term_frequency_fn=query_term_frequency_fn,
    )


def _bm25_raw_scores_for_prepared(
    *,
    prepared_items: tuple[_Bm25PreparedItem, ...],
    terms: tuple[LexicalQueryTerm, ...],
    k1: float,
    b: float,
    term_frequency_cache: _Bm25TermFrequencyCache | None = None,
    query_term_frequency_fn: _QueryTermFrequencyFn = query_term_frequency,
) -> tuple[tuple[_Bm25Document, ...], tuple[float, ...]]:
    documents = tuple(
        _bm25_document(
            prepared=item,
            prepared_index=index,
            terms=terms,
            term_frequency_cache=term_frequency_cache,
            query_term_frequency_fn=query_term_frequency_fn,
        )
        for index, item in enumerate(prepared_items)
    )
    average_length = sum(document.length for document in documents) / len(documents)
    document_frequencies = tuple(
        sum(1 for document in documents if document.term_frequencies[index] > 0)
        for index, _ in enumerate(terms)
    )
    raw_scores = tuple(
        _bm25_score(
            term_frequencies=document.term_frequencies,
            document_frequencies=document_frequencies,
            document_count=len(documents),
            document_length=document.length,
            average_document_length=max(1.0, average_length),
            k1=k1,
            b=b,
        )
        for document in documents
    )
    return documents, raw_scores


def _bm25_query_coverage(*, matched_term_count: int, query_term_count: int) -> float:
    if matched_term_count <= 0 or query_term_count <= 0:
        return 0.0
    denominator = min(8, max(3, query_term_count))
    return round(min(1.0, matched_term_count / denominator), 4)


def _bm25_document(
    *,
    prepared: _Bm25PreparedItem,
    prepared_index: int,
    terms: tuple[LexicalQueryTerm, ...],
    term_frequency_cache: _Bm25TermFrequencyCache | None = None,
    query_term_frequency_fn: _QueryTermFrequencyFn = query_term_frequency,
) -> _Bm25Document:
    return _Bm25Document(
        item=prepared.item,
        term_frequencies=tuple(
            _bm25_term_frequency(
                prepared=prepared,
                prepared_index=prepared_index,
                term=term,
                term_frequency_cache=term_frequency_cache,
                query_term_frequency_fn=query_term_frequency_fn,
            )
            for term in terms
        ),
        length=prepared.length,
    )


def _bm25_term_frequency(
    *,
    prepared: _Bm25PreparedItem,
    prepared_index: int,
    term: LexicalQueryTerm,
    term_frequency_cache: _Bm25TermFrequencyCache | None,
    query_term_frequency_fn: _QueryTermFrequencyFn,
) -> int:
    if term_frequency_cache is None:
        return query_term_frequency_fn(term, prepared.text_counts)
    cache_key = (prepared_index, term)
    cached = term_frequency_cache.get(cache_key)
    if cached is not None:
        return cached
    frequency = query_term_frequency_fn(term, prepared.text_counts)
    term_frequency_cache[cache_key] = frequency
    return frequency


def _bm25_prepared_item(
    item: ContextItem,
    *,
    text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
) -> _Bm25PreparedItem:
    if text_stats_cache is not None:
        cached = text_stats_cache.get(item.text)
        if cached is not None:
            counts, length = cached
            return _Bm25PreparedItem(item=item, text_counts=counts, length=length)
    counts, sequence_length = text_variant_stats(item.text)
    length = max(1, sequence_length)
    if text_stats_cache is not None:
        text_stats_cache[item.text] = (counts, length)
    return _Bm25PreparedItem(
        item=item,
        text_counts=counts,
        length=length,
    )


def _bm25_score(
    *,
    term_frequencies: tuple[int, ...],
    document_frequencies: tuple[int, ...],
    document_count: int,
    document_length: int,
    average_document_length: float,
    k1: float,
    b: float,
) -> float:
    score = 0.0
    length_ratio = document_length / average_document_length
    normalizer = k1 * (1 - b + b * length_ratio)
    for frequency, document_frequency in zip(
        term_frequencies,
        document_frequencies,
        strict=True,
    ):
        if frequency <= 0 or document_frequency <= 0:
            continue
        idf = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
        score += idf * (frequency * (k1 + 1)) / (frequency + normalizer)
    return round(score, 8)


def _with_bm25_lexical_boost(
    item: ContextItem,
    *,
    raw_score: float,
    max_raw_score: float,
    max_boost: float,
    query_term_count: int,
    matched_term_count: int,
    query_reason: str = "original_query",
    query_coverage: float | None = None,
) -> ContextItem:
    if _bm25_lexical_already_applied(item):
        return item
    if raw_score <= 0 or max_raw_score <= 0 or matched_term_count <= 0:
        return item
    normalized_score = min(1.0, raw_score / max_raw_score)
    boost = round(max_boost * normalized_score, 4)
    if boost <= 0:
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    diagnostics["bm25_lexical_reason"] = "BM25 lexical rerank over candidate pool"
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "bm25_lexical_raw_score": round(raw_score, 6),
        "bm25_lexical_normalized_score": round(normalized_score, 4),
        "bm25_lexical_boost": boost,
        "bm25_lexical_query_term_count": query_term_count,
        "bm25_lexical_matched_term_count": matched_term_count,
        "bm25_lexical_query_reason": query_reason,
    }
    if query_coverage is not None:
        diagnostics["score_signals"]["bm25_lexical_query_coverage"] = round(
            query_coverage,
            4,
        )
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "bm25_lexical_applied": True,
        "bm25_lexical_query_reason": query_reason,
    }
    return replace(
        item,
        score=min(0.99, round(item.score + boost, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _bm25_lexical_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "bm25_lexical_applied")


def _provenance_flag_is_true(diagnostics: object, flag: str) -> bool:
    normalized = normalize_context_diagnostics(diagnostics)
    provenance = safe_diagnostic_mapping(normalized.get("provenance"))
    return provenance.get(flag) is True
