"""Composition of Retrieval adapters and immutable profile inputs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING

from infinity_context_adapters.features.context_building.qdrant_candidate_provider import (
    QdrantContextCandidateProvider,
)
from infinity_context_adapters.postgres.locator_catalog_attestation import (
    attest_locator_retrieval_catalog,
)
from infinity_context_adapters.postgres.locator_projection_maintenance import (
    PostgresLocatorProjectionMaintenance,
)
from infinity_context_adapters.postgres.locator_retrieval import (
    PostgresCanonicalLocatorReader,
    PostgresLocatorCandidateProvider,
)
from infinity_context_adapters.qdrant.vector_adapter import QdrantVectorMemoryAdapter
from infinity_context_core.ports.adapters import EmbeddingPort, VectorMemoryPort
from sqlalchemy import text

from infinity_context_server.features.context_building.retrieval_service import (
    LocatorRetrievalService,
    RetrievalLaneRuntime,
)

if TYPE_CHECKING:
    from infinity_context_server.config import Settings
    from infinity_context_server.serving_profile import VerifiedServingProfile


def build_locator_retrieval_service(
    *,
    session_factory,
    settings: Settings,
    serving_profile: VerifiedServingProfile,
    query_embeddings: EmbeddingPort,
    diagnostics: object | None = None,
) -> tuple[
    LocatorRetrievalService | None,
    VectorMemoryPort | None,
    PostgresLocatorProjectionMaintenance,
]:
    locator_vector_index = None
    service_revision = serving_profile.service_revision
    if not _verified_revision(service_revision):
        return None, None, PostgresLocatorProjectionMaintenance(session_factory)
    lanes: list[RetrievalLaneRuntime] = [
        RetrievalLaneRuntime(
            provider_id="postgres_keyword",
            provider=PostgresLocatorCandidateProvider(session_factory),
            health=lambda: _postgres_health(session_factory),
            required=True,
            weight_micros=1_000_000,
            profile_qualification=lambda: _postgres_profile_qualified(session_factory),
        )
    ]
    dense_verified = bool(
        settings.qdrant_enabled
        and serving_profile.service_revision
        and serving_profile.embedding_profile_id
        and serving_profile.embedding_profile_digest_sha256
    )
    profile = {
        "profile_manifest_version": "locator-index-profile.v2",
        "contract_version": "context-retrieval.v2",
        "attribute_schema": "document-retrieval-projection.v1",
        "coverage": "top_k_only",
        "filters": [
            "actor_keys",
            "canonical_identity",
            "canonical_version",
            "category",
            "chunk_key",
            "document_key",
            "end_at",
            "index_generation",
            "index_profile_digest",
            "kind",
            "lifecycle_status",
            "locator",
            "memory_scope_id",
            "projection_generation",
            "projection_version",
            "relative_end_ms",
            "relative_start_ms",
            "sequence_ordinal",
            "source_key",
            "space_id",
            "start_at",
            "tags",
            "thread_id",
        ],
        "projection_version": "document-retrieval-projection.v1",
        "ranking_policy": "weighted_rrf_canonical_preferences.v1",
        "ranking_parameters": {
            "rank_constant": 60,
            "weight_scale_micros": 1000000,
            "score_scale_picos": 1000000000000,
            "preference_scale_micros": 1000000,
            "max_preference_boost_micros": 250000,
            "contribution_rounding": "round_half_even",
            "preference_rounding": "floor",
            "canonical_signal_match_policy": "canonical_exact_key_interval_overlap.v1",
        },
        "supports_neighbors": True,
        "bounds": {
            "query_variants": [1, 6],
            "query_characters": [1, 512],
            "provider_lanes": [1, 4],
            "provider_rank": [1, 1000],
            "source_generations": [1, 100],
            "candidate_limit": [1, 1000],
            "result_limit": [1, 50],
            "neighbor_radius": [0, 2],
            "response_byte_limit": [16384, 1048576],
            "deadline_ms": [1, 2000],
            "weight_micros": [100000, 10000000],
        },
        "lanes": [
            {"provider_id": "postgres_keyword", "required": True, "weight_micros": 1000000},
            *(
                [{"provider_id": "qdrant_dense", "required": True, "weight_micros": 1000000}]
                if dense_verified
                else []
            ),
        ],
        "postgres_lexical_revision": "locator-postgres-keyword.v2",
    }
    if dense_verified:
        profile.update(
            {
                "active_index_generation": "locator-active-v2",
                "base_collection": settings.qdrant_collection,
                "dimensions": settings.embeddings_dimensions,
                "distance": "cosine",
                "embedding_profile_digest": (serving_profile.embedding_profile_digest_sha256),
                "embedding_profile_id": serving_profile.embedding_profile_id,
                "payload_schema": {
                    "actor_keys": "keyword",
                    "canonical_identity": "keyword",
                    "canonical_version": "integer",
                    "category": "keyword",
                    "chunk_key": "keyword",
                    "document_key": "keyword",
                    "end_at": "datetime",
                    "index_generation": "keyword",
                    "index_profile_digest": "keyword",
                    "kind": "keyword",
                    "lifecycle_status": "keyword",
                    "locator": "keyword",
                    "memory_scope_id": "keyword",
                    "projection_generation": "keyword",
                    "projection_version": "keyword",
                    "relative_end_ms": "integer",
                    "relative_start_ms": "integer",
                    "sequence_ordinal": "integer",
                    "source_key": "keyword",
                    "space_id": "keyword",
                    "start_at": "datetime",
                    "tags": "keyword",
                    "thread_id": "keyword",
                },
                "vector_layout": {"dense": "unnamed", "sparse": None},
            }
        )
    index_digest = hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    collection = f"{settings.qdrant_collection}_locator_v2_{index_digest[:16]}"
    if dense_verified:
        locator_vector_index = QdrantVectorMemoryAdapter(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection_name=collection,
            vector_size=settings.embeddings_dimensions,
            projection_version="document-retrieval-projection.v1",
            index_profile_digest=index_digest,
            index_generation="locator-active-v2",
            locator_writes_enabled=dense_verified,
        )
    if dense_verified and locator_vector_index is not None:
        lanes.append(
            RetrievalLaneRuntime(
                provider_id="qdrant_dense",
                provider=QdrantContextCandidateProvider(
                    search=locator_vector_index,
                    embedder=query_embeddings,
                ),
                health=lambda: _qdrant_health(locator_vector_index, query_embeddings),
                required=True,
                weight_micros=1_000_000,
                profile_qualification=lambda: _qdrant_profile_qualified(
                    locator_vector_index, session_factory
                ),
            )
        )
    return (
        LocatorRetrievalService(
            lanes=tuple(lanes),
            canonical_reader=PostgresCanonicalLocatorReader(session_factory),
            service_revision=service_revision,
            sdk_revision=service_revision,
            index_profile_digest=index_digest,
            profile_kind="full" if dense_verified else "lexical",
            diagnostics=diagnostics,
        ),
        locator_vector_index,
        PostgresLocatorProjectionMaintenance(session_factory),
    )


async def _postgres_health(session_factory) -> bool:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception:
        return False


async def _postgres_profile_qualified(session_factory) -> bool:
    try:
        async with session_factory() as session:
            if session.bind is None or session.bind.dialect.name != "postgresql":
                return False
            return (await attest_locator_retrieval_catalog(session)).qualified
    except Exception:
        return False


async def _qdrant_health(vector, embedder) -> bool:
    try:
        vector_capability, embedding_capability = await asyncio.gather(
            vector.capabilities(), embedder.capabilities()
        )
        return bool(
            vector_capability.enabled
            and vector_capability.healthy
            and vector_capability.supports_search
            and vector_capability.supports_filters
            and embedding_capability.enabled
            and embedding_capability.healthy
        )
    except Exception:
        return False


async def _qdrant_profile_qualified(vector, session_factory) -> bool:
    try:
        canonical_profile, capability = await asyncio.gather(
            _postgres_profile_qualified(session_factory),
            vector.capabilities(),
        )
        return bool(
            canonical_profile
            and capability.enabled
            and capability.healthy
            and capability.supports_search
            and capability.supports_filters
        )
    except Exception:
        return False


def _verified_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = ("build_locator_retrieval_service",)
