"""Graphiti-derived candidate provider seam for context_building."""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    CandidateHit,
    ContextCandidateHitProviderPort,
    ContextCandidateRequest,
)


class GraphitiContextCandidateProvider:
    """Placeholder for future graph-derived context candidates."""

    adapter_name = "graphiti"
    feature_id = FEATURE_ID

    async def find_candidate_hits(
        self,
        _request: ContextCandidateRequest,
    ) -> tuple[CandidateHit, ...]:
        _raise_not_implemented("find_candidate_hits")


def create_graphiti_context_candidate_provider() -> ContextCandidateHitProviderPort:
    """Create the feature-owned Graphiti candidate provider placeholder."""

    return GraphitiContextCandidateProvider()


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"context_building Graphiti candidate provider {operation} is a placeholder seam; "
        "real Graphiti graph recall wiring is deferred."
    )


__all__ = (
    "GraphitiContextCandidateProvider",
    "create_graphiti_context_candidate_provider",
)
