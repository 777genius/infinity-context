"""Provider-facing Postgres candidate seam without SQLAlchemy dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    CandidateHit,
    ContextCandidateHitProviderPort,
    ContextCandidateRequest,
)


@dataclass(frozen=True, slots=True)
class PostgresCandidatePointer:
    canonical_id: str
    canonical_version: int
    rank: int
    query_key: str = "canonical_postgres"


class PostgresCandidateLookupPort(Protocol):
    async def find_candidate_pointers(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[PostgresCandidatePointer, ...]:
        """Return identity-only pointers from a stable canonical ranking."""


@dataclass(frozen=True, slots=True)
class PostgresContextCandidateProvider:
    """Convert data-access pointers into the context feature's safe hit contract."""

    lookup: PostgresCandidateLookupPort
    adapter_name = "postgres"
    feature_id = FEATURE_ID
    provider_id = "postgres"

    async def find_candidate_hits(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[CandidateHit, ...]:
        pointers = await self.lookup.find_candidate_pointers(request)
        return tuple(
            CandidateHit(
                canonical_id=pointer.canonical_id,
                canonical_version=pointer.canonical_version,
                provider_id=self.provider_id,
                query_key=pointer.query_key,
                rank=pointer.rank,
                match_reasons=("canonical_postgres",),
            )
            for pointer in pointers
        )


def create_postgres_context_candidate_provider(
    *,
    lookup: PostgresCandidateLookupPort,
) -> ContextCandidateHitProviderPort:
    return PostgresContextCandidateProvider(lookup=lookup)


__all__ = (
    "PostgresCandidateLookupPort",
    "PostgresCandidatePointer",
    "PostgresContextCandidateProvider",
    "create_postgres_context_candidate_provider",
)
