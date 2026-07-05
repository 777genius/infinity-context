"""Qdrant-derived candidate provider seam for context_building."""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    ContextCandidateProviderPort,
    ContextCandidateRequest,
    ContextItem,
)


class QdrantContextCandidateProvider:
    """Placeholder for future vector/RAG context candidates."""

    adapter_name = "qdrant"
    feature_id = FEATURE_ID

    async def find_candidates(
        self,
        _request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        _raise_not_implemented("find_candidates")


def create_qdrant_context_candidate_provider() -> ContextCandidateProviderPort:
    """Create the feature-owned Qdrant candidate provider placeholder."""

    return QdrantContextCandidateProvider()


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"context_building Qdrant candidate provider {operation} is a placeholder seam; "
        "real Qdrant RAG wiring is deferred."
    )


__all__ = (
    "QdrantContextCandidateProvider",
    "create_qdrant_context_candidate_provider",
)
