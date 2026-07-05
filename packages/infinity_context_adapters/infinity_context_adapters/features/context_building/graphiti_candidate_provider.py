"""Graphiti-derived candidate provider seam for context_building."""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    ContextCandidateProviderPort,
    ContextCandidateRequest,
    ContextItem,
)


class GraphitiContextCandidateProvider:
    """Placeholder for future graph-derived context candidates."""

    adapter_name = "graphiti"
    feature_id = FEATURE_ID

    async def find_candidates(
        self,
        _request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        _raise_not_implemented("find_candidates")


def create_graphiti_context_candidate_provider() -> ContextCandidateProviderPort:
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
