"""Bounded canonical keyword seeds for aggregation requests."""

from __future__ import annotations

from infinity_context_core.application.context_count_cardinality import (
    keyword_aggregation_intent,
)
from infinity_context_core.application.context_distinct_set_evidence import (
    distinct_set_retrieval_terms,
    extract_distinct_set_request,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.dto import BuildContextQuery
from infinity_context_core.domain.entities import MemoryChunk
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MAX_AGGREGATION_ADMISSION_SEARCH_RESULTS = 72


async def aggregation_admission_seed_chunks(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    query: BuildContextQuery,
    query_plan: QueryExpansionPlan,
    canonical_chunks: tuple[MemoryChunk, ...],
) -> tuple[tuple[MemoryChunk, ...], dict[str, object]]:
    """Recover a bounded tail from the request and its distinct-set contract."""

    diagnostics = {
        "keyword_aggregation_admission_queries": 0,
        "keyword_aggregation_admission_seed_chunks": len(canonical_chunks),
        "keyword_aggregation_admission_seed_chunks_added": 0,
    }
    if (
        query.max_chunks <= 0
        or keyword_aggregation_intent(query.query, query_plan=query_plan) is None
    ):
        return canonical_chunks, diagnostics
    search_queries = [query.query]
    if (request := extract_distinct_set_request(query.query)) is not None:
        retrieval_terms = distinct_set_retrieval_terms(request)
        distinct_query = " ".join(retrieval_terms)
        if distinct_query and distinct_query.casefold() != query.query.casefold():
            search_queries.append(distinct_query)
        target_query = " ".join(request.target_terms)
        if target_query and target_query.casefold() not in {
            value.casefold() for value in search_queries
        }:
            search_queries.append(target_query)
        for action in request.action_terms[:4]:
            action_query = " ".join((action, *request.target_terms))
            if action_query and action_query.casefold() not in {
                value.casefold() for value in search_queries
            }:
                search_queries.append(action_query)
    matches: list[MemoryChunk] = []
    async with uow_factory() as uow:
        for search_query in search_queries:
            matches.extend(
                await uow.chunks.keyword_search(
                    space_id=str(query.space_id),
                    memory_scope_ids=tuple(str(value) for value in query.memory_scope_ids),
                    thread_id=str(query.thread_id) if query.thread_id else None,
                    query=search_query,
                    limit=_MAX_AGGREGATION_ADMISSION_SEARCH_RESULTS,
                )
            )
    chunks = _dedupe_seed_chunks((*canonical_chunks, *matches))
    diagnostics["keyword_aggregation_admission_queries"] = len(search_queries)
    diagnostics["keyword_aggregation_admission_seed_chunks"] = len(chunks)
    diagnostics["keyword_aggregation_admission_seed_chunks_added"] = len(chunks) - len(
        canonical_chunks
    )
    return chunks, diagnostics


def _dedupe_seed_chunks(chunks: tuple[MemoryChunk, ...]) -> tuple[MemoryChunk, ...]:
    selected: list[MemoryChunk] = []
    seen: set[str] = set()
    for chunk in chunks:
        key = str(chunk.id)
        if key in seen:
            continue
        seen.add(key)
        selected.append(chunk)
    return tuple(selected)
