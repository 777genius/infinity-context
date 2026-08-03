"""Plan-aware retrieval and ranking for canonical facts."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application import (
    context_building_legacy_candidate_adapter as _candidate_policy,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    query_reason_priority_for_relevance,
    query_relevance_rank_key,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    has_project_identity_mismatch,
    is_fact_candidate_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.dto import BuildContextQuery
from infinity_context_core.domain.entities import MemoryFact
from infinity_context_core.ports.repositories import ActiveFactSearch, FactRepositoryPort

_MAX_FAIR_DERIVED_HEADS_PER_QUERY = 8
_MAX_FAIR_DERIVED_RESERVED = 20
_MAX_CANONICAL_FACT_CANDIDATES = 200
_DEFAULT_CANONICAL_FACT_SEARCH_CAP = 100
_DEFAULT_CANONICAL_FACT_RERANK_CAP = 40
_CURRENT_TRUTH_DERIVED_CANONICAL_REASONS = frozenset(
    {
        "current_state_temporal_bridge",
        "decomposition_knowledge_update_current",
    }
)


@dataclass(frozen=True)
class CanonicalFactMatch:
    """A canonical fact paired with the query that best retrieved it."""

    fact: MemoryFact
    query: str
    reason: str
    relevance: QueryRelevance


@dataclass(frozen=True)
class CanonicalFactQueryResult:
    """Raw repository result for one bounded retrieval query."""

    retrieval_query: QueryExpansion
    facts: tuple[MemoryFact, ...]


@dataclass(frozen=True)
class CanonicalFactRetrievalResult:
    """Fused fact candidates plus enough metadata for later reranking."""

    matches: tuple[CanonicalFactMatch, ...]
    query_results: tuple[CanonicalFactQueryResult, ...]
    request_count: int
    raw_fact_count: int
    batch_api_used: bool


@dataclass(frozen=True)
class CanonicalFactSelectionResult:
    """Collector-ready canonical facts and retrieval diagnostics."""

    facts: tuple[MemoryFact, ...]
    matches: tuple[CanonicalFactMatch, ...]
    diagnostics: dict[str, object]


async def collect_plan_aware_active_facts(
    repository: FactRepositoryPort,
    *,
    query: BuildContextQuery,
    memory_scope_ids: tuple[str, ...],
    query_plan: QueryExpansionPlan | None,
) -> CanonicalFactSelectionResult:
    """Apply bounded planning plus canonical and protected-head selection."""

    retrieval_queries = _candidate_policy._bounded_derived_retrieval_queries(
        query_plan,
        fallback=query.query,
    )
    retrieval = await retrieve_plan_aware_active_facts(
        repository,
        space_id=str(query.space_id),
        memory_scope_ids=memory_scope_ids,
        thread_id=str(query.thread_id) if query.thread_id else None,
        retrieval_queries=retrieval_queries,
        total_limit=query.max_facts,
        category=query.category,
        tags_any=query.tags_any,
        tags_all=query.tags_all,
        tags_none=query.tags_none,
    )
    matches = retrieval.matches[: canonical_fact_rerank_pool_limit(query.max_facts)]
    return CanonicalFactSelectionResult(
        facts=tuple(match.fact for match in matches),
        matches=matches,
        diagnostics={
            "canonical_fact_query_count": retrieval.request_count,
            "canonical_fact_query_reasons": [item.reason for item in retrieval_queries],
            "canonical_fact_search_batch_api_used": int(retrieval.batch_api_used),
            "canonical_fact_search_raw_fact_count": retrieval.raw_fact_count,
        },
    )


async def retrieve_plan_aware_active_facts(
    repository: FactRepositoryPort,
    *,
    space_id: str,
    memory_scope_ids: tuple[str, ...],
    thread_id: str | None,
    retrieval_queries: tuple[QueryExpansion, ...],
    total_limit: int,
    category: str | None = None,
    tags_any: tuple[str, ...] = (),
    tags_all: tuple[str, ...] = (),
    tags_none: tuple[str, ...] = (),
) -> CanonicalFactRetrievalResult:
    """Fetch, relevance-rank, and fuse canonical facts across a bounded query plan."""

    candidate_limit = canonical_fact_rerank_pool_limit(total_limit)
    if candidate_limit <= 0:
        return CanonicalFactRetrievalResult((), (), 0, 0, False)
    indexed_queries = _dedupe_retrieval_queries(retrieval_queries)
    base_search_limit = canonical_fact_candidate_limit(total_limit)
    searches = tuple(
        ActiveFactSearch(
            space_id=space_id,
            memory_scope_ids=memory_scope_ids,
            thread_id=thread_id,
            query=retrieval_query.query,
            limit=base_search_limit,
            category=category,
            tags_any=tags_any,
            tags_all=tags_all,
            tags_none=tags_none,
        )
        for _, retrieval_query in indexed_queries
    )
    find_active_many = getattr(repository, "find_active_many", None)
    if searches and callable(find_active_many):
        fact_groups = await find_active_many(searches)
        batch_api_used = True
    else:
        fact_groups = [
            await repository.find_active(
                space_id=search.space_id,
                memory_scope_ids=search.memory_scope_ids,
                thread_id=search.thread_id,
                query=search.query,
                limit=search.limit,
                category=search.category,
                tags_any=search.tags_any,
                tags_all=search.tags_all,
                tags_none=search.tags_none,
            )
            for search in searches
        ]
        batch_api_used = False

    query_results: list[CanonicalFactQueryResult] = []
    rankings: dict[str, tuple[str, ...]] = {}
    ranked_matches_by_query: list[tuple[QueryExpansion, tuple[CanonicalFactMatch, ...]]] = []
    match_by_id: dict[str, CanonicalFactMatch] = {}
    for (index, retrieval_query), facts in zip(indexed_queries, fact_groups, strict=True):
        fact_tuple = tuple(facts)
        query_results.append(
            CanonicalFactQueryResult(
                retrieval_query=retrieval_query,
                facts=fact_tuple,
            )
        )
        ranked_matches = rank_fact_matches_for_query(
            fact_tuple,
            retrieval_query=retrieval_query,
            limit=len(fact_tuple),
        )
        ranked_matches_by_query.append((retrieval_query, ranked_matches))
        rankings[_candidate_policy._retrieval_query_rank_key(index, retrieval_query)] = tuple(
            str(match.fact.id) for match in ranked_matches
        )
        for match in ranked_matches:
            fact_id = str(match.fact.id)
            current = match_by_id.get(fact_id)
            if current is None or _fact_match_is_preferred(match, current=current):
                match_by_id[fact_id] = match

    original_head_ids = tuple(
        ranking[0]
        for ranking_key, ranking in rankings.items()
        if ranking and ranking_key.endswith(":original_query")
    )
    protected_ids = _candidate_policy._protected_query_head_keys(rankings)
    fair_derived_ids = _fair_strong_derived_head_keys(
        tuple(ranked_matches_by_query),
        excluded_ids=frozenset((*original_head_ids, *protected_ids)),
        limit=min(_MAX_FAIR_DERIVED_RESERVED, candidate_limit // 2),
    )
    selected_ids = tuple(
        dict.fromkeys(
            (
                *original_head_ids,
                *protected_ids,
                *fair_derived_ids,
                *_candidate_policy._fused_ranked_keys(
                    rankings,
                    limit=candidate_limit,
                    max_rank_floor=candidate_limit,
                ),
            )
        )
    )[:candidate_limit]
    return CanonicalFactRetrievalResult(
        matches=tuple(match_by_id[fact_id] for fact_id in selected_ids if fact_id in match_by_id),
        query_results=tuple(query_results),
        request_count=len(searches),
        raw_fact_count=sum(len(group) for group in fact_groups),
        batch_api_used=batch_api_used,
    )


def rank_fact_matches_for_query(
    facts: tuple[MemoryFact, ...],
    *,
    retrieval_query: QueryExpansion,
    limit: int,
) -> tuple[CanonicalFactMatch, ...]:
    if limit <= 0 or not facts:
        return ()
    ranked: list[tuple[tuple[float | int, ...], CanonicalFactMatch]] = []
    for index, fact in enumerate(facts):
        match = canonical_fact_match(fact, retrieval_query=retrieval_query)
        if has_project_identity_mismatch(query=match.query, text=fact.text):
            continue
        if not _canonical_fact_match_is_admissible(match):
            continue
        if not is_fact_candidate_relevance_sufficient(match.relevance):
            continue
        ranked.append(((*_relevance_rank_key(match.relevance), -index), match))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return tuple(match for _, match in ranked[:limit])


def canonical_fact_match(
    fact: MemoryFact,
    *,
    retrieval_query: QueryExpansion,
) -> CanonicalFactMatch:
    return CanonicalFactMatch(
        fact=fact,
        query=retrieval_query.query,
        reason=retrieval_query.reason,
        relevance=score_query_relevance(
            query=retrieval_query.query,
            text=fact.text,
            max_boost=0.03,
        ),
    )


def canonical_fact_candidate_limit(max_facts: int) -> int:
    if max_facts <= 0:
        return 0
    return min(
        _MAX_CANONICAL_FACT_CANDIDATES,
        max(_DEFAULT_CANONICAL_FACT_SEARCH_CAP, max_facts),
        max(max_facts * 4, max_facts + 8),
    )


def canonical_fact_rerank_pool_limit(max_facts: int) -> int:
    if max_facts <= 0:
        return 0
    return min(
        _MAX_CANONICAL_FACT_CANDIDATES,
        max(_DEFAULT_CANONICAL_FACT_RERANK_CAP, max_facts),
        max(max_facts * 4, max_facts + 3),
    )


def _fair_strong_derived_head_keys(
    ranked_matches_by_query: tuple[tuple[QueryExpansion, tuple[CanonicalFactMatch, ...]], ...],
    *,
    excluded_ids: frozenset[str],
    limit: int,
) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    lanes = tuple(
        _strong_unique_lane_ids(ranked_matches)
        for retrieval_query, ranked_matches in ranked_matches_by_query
        if retrieval_query.reason != "original_query"
    )
    selected: list[str] = []
    seen = set(excluded_ids)
    for depth in range(_MAX_FAIR_DERIVED_HEADS_PER_QUERY):
        for lane in lanes:
            if depth >= len(lane):
                continue
            fact_id = lane[depth]
            if fact_id in seen:
                continue
            seen.add(fact_id)
            selected.append(fact_id)
            if len(selected) >= limit:
                return tuple(selected)
    return tuple(selected)


def _strong_unique_lane_ids(
    ranked_matches: tuple[CanonicalFactMatch, ...],
) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for match in ranked_matches:
        fact_id = str(match.fact.id)
        if fact_id in seen or not _is_strong_derived_match(match.relevance):
            continue
        seen.add(fact_id)
        selected.append(fact_id)
        if len(selected) >= _MAX_FAIR_DERIVED_HEADS_PER_QUERY:
            break
    return tuple(selected)


def _is_strong_derived_match(relevance: QueryRelevance) -> bool:
    return (
        relevance.hit_ratio >= 0.6
        and relevance.unique_term_hits >= 3
        and relevance.distinctive_term_hits >= 3
        and (relevance.phrase_bigram_hits > 0 or relevance.distinctive_term_hits >= 4)
    )


def _is_strong_current_truth_match(relevance: QueryRelevance) -> bool:
    return (
        relevance.hit_ratio >= 0.15
        and relevance.unique_term_hits >= 4
        and relevance.distinctive_term_hits >= 4
        and (relevance.phrase_bigram_hits > 0 or relevance.distinctive_term_hits >= 5)
    )


def _canonical_fact_match_is_admissible(match: CanonicalFactMatch) -> bool:
    if match.reason == "original_query":
        return True
    if match.reason in _CURRENT_TRUTH_DERIVED_CANONICAL_REASONS:
        return _is_strong_current_truth_match(match.relevance)
    return query_reason_priority_for_relevance(
        match.reason, match.relevance
    ) > 0 or _is_strong_derived_match(match.relevance)


def _dedupe_retrieval_queries(
    retrieval_queries: tuple[QueryExpansion, ...],
) -> tuple[tuple[int, QueryExpansion], ...]:
    result: list[tuple[int, QueryExpansion]] = []
    seen: set[str] = set()
    for index, retrieval_query in enumerate(retrieval_queries):
        normalized = " ".join(retrieval_query.query.split()).casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append((index, retrieval_query))
    return tuple(result)


def _match_rank_key(match: CanonicalFactMatch) -> tuple[float | int, ...]:
    return query_relevance_rank_key((match.query, match.reason, match.relevance))


def _fact_match_is_preferred(
    candidate: CanonicalFactMatch,
    *,
    current: CanonicalFactMatch,
) -> bool:
    if candidate.reason == "original_query" or current.reason == "original_query":
        derived_reason = (
            current.reason if candidate.reason == "original_query" else candidate.reason
        )
        if derived_reason in _CURRENT_TRUTH_DERIVED_CANONICAL_REASONS:
            return candidate.reason == "original_query"
    candidate_rank = _match_rank_key(candidate)
    current_rank = _match_rank_key(current)
    if candidate_rank != current_rank:
        return candidate_rank > current_rank
    return candidate.reason == "original_query" and current.reason != "original_query"


def _relevance_rank_key(relevance: QueryRelevance) -> tuple[float | int, ...]:
    return (
        relevance.phrase_bigram_hits,
        relevance.phrase_boost,
        relevance.score_boost,
        relevance.unique_term_hits,
        relevance.hit_ratio,
        relevance.capped_frequency_hits,
    )
