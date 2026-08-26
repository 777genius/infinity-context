"""Ports for provider-neutral, locator-only Retrieval V2."""

from __future__ import annotations

from typing import Protocol

from infinity_context_core.features.context_building.domain.locator_retrieval_v2 import (
    CanonicalLocatorCandidateV2,
    CanonicalLocatorReadV2,
    LocatorProviderResultV2,
    LocatorRetrievalRequestV2,
)


class LocatorCandidateProviderPortV2(Protocol):
    async def retrieve_locator_candidates(
        self,
        request: LocatorRetrievalRequestV2,
    ) -> LocatorProviderResultV2:
        """Execute all explicit variants and return identity/rank signals only."""


class CanonicalLocatorHydratorPortV2(Protocol):
    async def hydrate_locator_candidates(
        self,
        request: LocatorRetrievalRequestV2,
        canonical_identities: tuple[str, ...],
    ) -> tuple[CanonicalLocatorCandidateV2, ...]:
        """Load current canonical lifecycle and filter attributes in one snapshot."""


class CanonicalLocatorReadPortV2(CanonicalLocatorHydratorPortV2, Protocol):
    async def hydrate_final_locator_read(
        self,
        request: LocatorRetrievalRequestV2,
        canonical_identities: tuple[str, ...],
        radius: int,
    ) -> CanonicalLocatorReadV2:
        """Hydrate exact final seeds and neighbors in one read transaction/snapshot."""


__all__ = (
    "CanonicalLocatorHydratorPortV2",
    "CanonicalLocatorReadPortV2",
    "LocatorCandidateProviderPortV2",
)
