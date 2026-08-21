"""Config-only cleanup target authority without provider or database I/O."""

from __future__ import annotations

from infinity_context_adapters.qdrant.identity_evidence import (
    qdrant_target_commitment_sha256,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupTargetAuthority,
    build_managed_benchmark_cleanup_target_authority,
)

from infinity_context_server.config import Settings
from infinity_context_server.derived_identity_target import (
    graphiti_target_commitment_sha256,
)


def current_cleanup_target_authority(
    settings: Settings,
    *,
    infinity_target_identity_sha256: str,
) -> ManagedBenchmarkCleanupTargetAuthority:
    """Recompute exact current targets from authenticated server configuration."""

    if not settings.qdrant_enabled or not settings.graphiti_enabled:
        raise MemoryConflictError(
            "Managed benchmark cleanup target authority requires Qdrant and Graphiti"
        )
    qdrant_target = qdrant_target_commitment_sha256(settings.qdrant_url, settings.qdrant_collection)
    graphiti_target = graphiti_target_commitment_sha256(neo4j_uri=settings.graphiti_neo4j_uri)
    return build_managed_benchmark_cleanup_target_authority(
        infinity_target_identity_sha256=infinity_target_identity_sha256,
        qdrant_target_commitment_sha256=qdrant_target,
        graphiti_target_commitment_sha256=graphiti_target,
    )


__all__ = ("current_cleanup_target_authority",)
