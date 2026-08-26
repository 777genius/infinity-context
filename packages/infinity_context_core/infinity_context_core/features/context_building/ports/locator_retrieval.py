"""Ports for provider-neutral, locator-only Retrieval."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.context_building.domain.locator_retrieval import (
    CanonicalLocatorCandidate,
    CanonicalLocatorRead,
    LocatorProviderResult,
    LocatorRetrievalRequest,
)


class LocatorCandidateProviderPort(Protocol):
    async def retrieve_locator_candidates(
        self,
        request: LocatorRetrievalRequest,
    ) -> LocatorProviderResult:
        """Execute all explicit variants and return identity/rank signals only."""


class CanonicalLocatorHydratorPort(Protocol):
    async def hydrate_locator_candidates(
        self,
        request: LocatorRetrievalRequest,
        canonical_identities: tuple[str, ...],
    ) -> tuple[CanonicalLocatorCandidate, ...]:
        """Load current canonical lifecycle and filter attributes in one snapshot."""


class CanonicalLocatorReadPort(CanonicalLocatorHydratorPort, Protocol):
    async def hydrate_final_locator_read(
        self,
        request: LocatorRetrievalRequest,
        canonical_identities: tuple[str, ...],
        radius: int,
    ) -> CanonicalLocatorRead:
        """Hydrate exact final seeds and neighbors in one read transaction/snapshot."""


__all__ = (
    "CanonicalLocatorHydratorPort",
    "CanonicalLocatorReadPort",
    "LocatorCandidateProviderPort",
)
