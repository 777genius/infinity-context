"""Candidate retrieval ports owned by the context_building feature."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_core.features.context_building.domain import (
    CandidateHit,
    ContextItem,
    ContextQuery,
    ContextQueryPlan,
    HydratedContextCandidate,
)


@dataclass(frozen=True, slots=True)
class ContextCandidateRequest:
    """Dependency-facing query for loading candidate context items."""

    query: ContextQuery
    limit: int = 20
    offset: int = 0
    query_plan: ContextQueryPlan | None = None

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("Candidate request limit must be positive")
        if self.offset < 0:
            raise ValueError("Candidate request offset cannot be negative")


class ContextCandidateProviderPort(Protocol):
    """Provider of canonical, hydrated and policy-checked prompt items.

    Derived search indexes must implement ``ContextCandidateHitProviderPort`` instead.
    """

    async def find_candidates(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        """Return prompt-ready candidates from a canonical trust boundary."""


class ContextCandidateHitProviderPort(Protocol):
    async def find_candidate_hits(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[CandidateHit, ...]:
        """Return a stable page of identity/version/rank-only candidates.

        Providers must apply ``offset`` and ``limit`` to one deterministic ranking and
        report ranks relative to the complete ranking, not the returned page.
        """


class CanonicalContextHydratorPort(Protocol):
    async def hydrate_candidates(
        self,
        request: ContextCandidateRequest,
        canonical_ids: tuple[str, ...],
    ) -> tuple[HydratedContextCandidate, ...]:
        """Load and revalidate canonical candidates for the exact request scope."""


class ContextClockPort(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware transaction time."""


__all__ = (
    "CanonicalContextHydratorPort",
    "ContextCandidateHitProviderPort",
    "ContextCandidateProviderPort",
    "ContextCandidateRequest",
    "ContextClockPort",
)
