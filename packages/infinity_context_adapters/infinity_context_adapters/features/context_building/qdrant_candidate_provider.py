"""Qdrant anti-corruption adapter for locator candidate signals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    LocatorProviderHit,
    LocatorProviderResult,
    LocatorRetrievalRequest,
)
from infinity_context_core.ports.adapters import EmbeddingPort, PortStatus


@dataclass(frozen=True, slots=True)
class QdrantLocatorPointer:
    canonical_identity: str
    canonical_version: int
    score: float


class QdrantLocatorSearchPort(Protocol):
    async def search_locator_chunks(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        query_vector: tuple[float, ...],
        query_text: str,
        limit: int,
        filter_spec: Mapping[str, object],
    ) -> tuple[Mapping[str, object], ...]: ...


@dataclass(frozen=True, slots=True)
class QdrantContextCandidateProvider:
    """Translate retrieval filters and preserve Qdrant's raw similarity/rank."""

    search: QdrantLocatorSearchPort
    embedder: EmbeddingPort
    provider_id: str = "qdrant_dense"
    adapter_name = "qdrant"
    feature_id = FEATURE_ID

    async def retrieve_locator_candidates(
        self, request: LocatorRetrievalRequest
    ) -> LocatorProviderResult:
        embeddings = await self.embedder.embed_texts(
            tuple(variant.query for variant in request.queries)
        )
        if embeddings.status != PortStatus.OK or len(embeddings.vectors) != len(request.queries):
            return LocatorProviderResult(status="unavailable", reason_code="provider_unavailable")
        spec = translate_qdrant_locator_filters(request)
        hits: list[LocatorProviderHit] = []
        for variant, vector in zip(request.queries, embeddings.vectors, strict=True):
            points = await self.search.search_locator_chunks(
                space_id=request.scope.space_id,
                memory_scope_id=request.scope.memory_scope_id,
                thread_id=request.scope.thread_id,
                query_vector=vector,
                query_text=variant.query,
                limit=request.bounds.candidate_limit,
                filter_spec=spec,
            )
            for rank, point in enumerate(points, start=1):
                identity = point.get("canonical_identity")
                version = point.get("canonical_version")
                score = point.get("score")
                if (
                    not isinstance(identity, str)
                    or not isinstance(version, int)
                    or isinstance(version, bool)
                    or not isinstance(score, int | float)
                    or isinstance(score, bool)
                ):
                    return LocatorProviderResult(
                        status="unqualified", reason_code="provider_unqualified"
                    )
                hits.append(
                    LocatorProviderHit(
                        canonical_identity=identity,
                        canonical_version=version,
                        provider_id=self.provider_id,
                        query_id=variant.query_id,
                        provider_rank=rank,
                        raw_score_kind="similarity",
                        raw_score_value=float(score),
                    )
                )
        return LocatorProviderResult(status="available", hits=tuple(hits))


def translate_qdrant_locator_filters(
    request: LocatorRetrievalRequest,
) -> dict[str, object]:
    """Build an exact provider-neutral filter spec consumed by Qdrant primitives."""

    filters = request.hard_filters
    must: list[dict[str, object]] = [
        {"key": "space_id", "match": request.scope.space_id},
        {"key": "memory_scope_id", "match": request.scope.memory_scope_id},
        {"key": "lifecycle_status", "match": "active"},
    ]
    must_not: list[dict[str, object]] = []
    should = [
        {
            "must": [
                {"key": "source_key", "match": pair.source_key},
                {
                    "key": "projection_generation",
                    "match": pair.projection_generation,
                },
            ]
        }
        for pair in filters.source_generations
    ]
    if request.scope.thread_id is None:
        must.append({"key": "thread_id", "is_null": True})
    else:
        must.append({"key": "thread_id", "match": request.scope.thread_id})
    for key, values in (
        ("document_key", filters.document_keys),
        ("kind", filters.kinds),
    ):
        if values:
            must.append({"key": key, "match_any": list(values)})
    if filters.category is not None:
        must.append({"key": "category", "match": filters.category})
    if filters.tags_any:
        must.append({"key": "tags", "match_any": list(filters.tags_any)})
    for tag in filters.tags_all:
        must.append({"key": "tags", "match": tag})
    if filters.actor_keys:
        must.append({"key": "actor_keys", "match_any": list(filters.actor_keys)})
    if filters.time_interval is not None:
        must.extend(
            (
                {"key": "start_at", "lte": filters.time_interval.end_at.isoformat()},
                {"key": "end_at", "gte": filters.time_interval.start_at.isoformat()},
            )
        )
    if filters.relative_time_interval is not None:
        must.extend(
            (
                {
                    "key": "relative_start_ms",
                    "lte": filters.relative_time_interval.end_ms,
                },
                {
                    "key": "relative_end_ms",
                    "gte": filters.relative_time_interval.start_ms,
                },
            )
        )
    if filters.excluded_source_keys:
        must_not.append({"key": "source_key", "match_any": list(filters.excluded_source_keys)})
    if filters.tags_none:
        must_not.append({"key": "tags", "match_any": list(filters.tags_none)})
    return {
        "must": must,
        "must_not": must_not,
        "should": should,
        "minimum_should_match": 1,
    }


def create_qdrant_context_candidate_provider(
    *, search: QdrantLocatorSearchPort, embedder: EmbeddingPort
) -> QdrantContextCandidateProvider:
    return QdrantContextCandidateProvider(search=search, embedder=embedder)


__all__ = (
    "QdrantContextCandidateProvider",
    "QdrantLocatorPointer",
    "QdrantLocatorSearchPort",
    "create_qdrant_context_candidate_provider",
    "translate_qdrant_locator_filters",
)
