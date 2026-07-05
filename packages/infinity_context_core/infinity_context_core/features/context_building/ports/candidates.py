"""Candidate retrieval ports owned by the context_building feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.context_building.domain import (
    ContextItem,
    ContextQuery,
)


@dataclass(frozen=True, slots=True)
class ContextCandidateRequest:
    """Dependency-facing query for loading candidate context items."""

    query: ContextQuery
    limit: int = 20

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("Candidate request limit must be positive")


class ContextCandidateProviderPort(Protocol):
    async def find_candidates(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        """Return context candidates from a canonical or derived source."""


__all__ = ("ContextCandidateProviderPort", "ContextCandidateRequest")
