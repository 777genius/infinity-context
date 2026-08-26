"""Composition of derived providers and exact identity evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from infinity_context_adapters.noop import (
    NoopEmbeddingAdapter,
    NoopGraphMemoryAdapter,
    NoopVectorMemoryAdapter,
)
from infinity_context_core.ports.adapters import MemoryAdapterPort
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.graph_evidence import GraphProjectionEvidencePort
from infinity_context_core.ports.vector_projection_evidence import VectorProjectionEvidencePort
from sqlalchemy.ext.asyncio import AsyncEngine

from infinity_context_server.config import Settings
from infinity_context_server.derived_identity_evidence import (
    DerivedIdentityEvidenceCoordinator,
    SqlAlchemyProjectionReadiness,
    graphiti_target_commitment_sha256,
)
from infinity_context_server.derived_projection_policy import derived_projection_lane_policies
from infinity_context_server.provider_circuit import ProviderCircuitBreaker


@dataclass(frozen=True, slots=True)
class DerivedProviderBundle:
    raw_vector: MemoryAdapterPort
    raw_graph: MemoryAdapterPort
    vector_evidence: VectorProjectionEvidencePort | None
    graph_evidence: GraphProjectionEvidencePort | None
    identity_evidence: DerivedIdentityEvidenceCoordinator
    qdrant_target_commitment_sha256: str | None
    graphiti_target_commitment_sha256: str | None


def build_derived_provider_bundle(
    *, engine: AsyncEngine, settings: Settings
) -> DerivedProviderBundle:
    raw_vector = _build_vector_adapter(settings)
    raw_graph = _build_graph_adapter(settings)
    vector_evidence = (
        cast(VectorProjectionEvidencePort, raw_vector) if settings.qdrant_enabled else None
    )
    configured_graph_target = (
        graphiti_target_commitment_sha256(neo4j_uri=settings.graphiti_neo4j_uri)
        if settings.graphiti_enabled
        else None
    )
    graph_evidence = _build_graph_projection_evidence(
        settings, target_commitment_sha256=configured_graph_target
    )
    qdrant_target = str(raw_vector.target_commitment_sha256) if settings.qdrant_enabled else None
    graphiti_target = configured_graph_target if graph_evidence is not None else None
    identity_evidence = DerivedIdentityEvidenceCoordinator(
        readiness=SqlAlchemyProjectionReadiness(engine),
        vector_evidence=vector_evidence,
        graph_evidence=graph_evidence,
        graph_target_commitment_sha256=(graphiti_target),
        lane_policies=derived_projection_lane_policies(
            qdrant_enabled=settings.qdrant_enabled,
            graphiti_enabled=settings.graphiti_enabled,
        ),
    )
    return DerivedProviderBundle(
        raw_vector,
        raw_graph,
        vector_evidence,
        graph_evidence,
        identity_evidence,
        qdrant_target,
        graphiti_target,
    )


def _build_vector_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.qdrant_enabled:
        return NoopVectorMemoryAdapter(name="qdrant")
    from infinity_context_adapters.qdrant import QdrantVectorMemoryAdapter

    return QdrantVectorMemoryAdapter(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection_name=settings.qdrant_collection,
        vector_size=settings.embeddings_dimensions,
        hybrid_sparse_enabled=settings.qdrant_hybrid_sparse_enabled,
        sparse_model=settings.qdrant_sparse_model,
        dense_vector_name=settings.qdrant_dense_vector_name,
        sparse_vector_name=settings.qdrant_sparse_vector_name,
    )


def _build_graph_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.graphiti_enabled:
        return NoopGraphMemoryAdapter(name="graphiti")
    from infinity_context_adapters.graphiti import GraphitiGraphMemoryAdapter

    return GraphitiGraphMemoryAdapter(
        neo4j_uri=settings.graphiti_neo4j_uri,
        neo4j_user=settings.graphiti_neo4j_user,
        neo4j_password=settings.graphiti_neo4j_password,
        build_indices=settings.graphiti_build_indices,
    )


def _build_graph_projection_evidence(
    settings: Settings,
    *,
    target_commitment_sha256: str | None,
) -> GraphProjectionEvidencePort | None:
    if not settings.graphiti_enabled:
        return None
    if target_commitment_sha256 is None:
        raise RuntimeError("Graphiti evidence target commitment is unavailable")
    from infinity_context_adapters.graphiti.identity_evidence import (
        Neo4jGraphitiIdentityEvidenceAdapter,
    )

    return Neo4jGraphitiIdentityEvidenceAdapter(
        neo4j_uri=settings.graphiti_neo4j_uri,
        neo4j_user=settings.graphiti_neo4j_user,
        neo4j_password=settings.graphiti_neo4j_password,
        target_commitment_sha256=target_commitment_sha256,
    )


def build_embedding_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.embeddings_enabled:
        return NoopEmbeddingAdapter(name="embeddings")
    if settings.embeddings_provider == "openai":
        from infinity_context_adapters.embeddings import OpenAIEmbeddingAdapter

        return OpenAIEmbeddingAdapter(
            api_key=settings.openai_api_key,
            model=settings.embeddings_model,
            dimensions=settings.embeddings_dimensions,
        )
    return NoopEmbeddingAdapter(name="embeddings")


def build_cognee_adapter(settings: Settings) -> MemoryAdapterPort:
    from infinity_context_adapters.cognee import CogneeMemoryAdapter

    return CogneeMemoryAdapter(
        enabled=settings.cognee_enabled,
        configured=settings.cognee_runtime_configured,
        dataset_prefix=settings.cognee_dataset_prefix,
    )


def build_provider_circuit(
    adapter_name: str,
    operation_kind: str,
    clock: ClockPort,
    settings: Settings,
) -> ProviderCircuitBreaker:
    return ProviderCircuitBreaker(
        adapter_name=adapter_name,
        operation_kind=operation_kind,
        clock=clock,
        failure_threshold=settings.provider_circuit_failure_threshold,
        reset_after_seconds=settings.provider_circuit_reset_after_seconds,
    )


__all__ = (
    "DerivedProviderBundle",
    "build_cognee_adapter",
    "build_derived_provider_bundle",
    "build_embedding_adapter",
    "build_provider_circuit",
)
