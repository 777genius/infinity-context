"""Graphiti anti-corruption adapter for identity-only context candidates."""

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
class GraphitiCandidatePointer:
    """Versioned canonical pointer returned by bounded graph recall."""

    canonical_id: str
    canonical_version: int
    rank: int
    query_key: str = "graphiti"
    match_reasons: tuple[str, ...] = ("graph_relation",)


class GraphitiCandidateLookupPort(Protocol):
    async def find_candidate_pointers(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[GraphitiCandidatePointer, ...]:
        """Return a stable, already bounded identity/version/rank page."""


@dataclass(frozen=True, slots=True)
class GraphitiContextCandidateProvider:
    """Translate versioned graph pointers without exposing graph-owned text."""

    lookup: GraphitiCandidateLookupPort

    adapter_name = "graphiti"
    feature_id = FEATURE_ID
    provider_id = "graphiti"

    async def find_candidate_hits(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[CandidateHit, ...]:
        pointers = await self.lookup.find_candidate_pointers(request)
        if len(pointers) > request.limit:
            raise RuntimeError("graphiti candidate lookup exceeded the requested page bound")
        expected_rank = request.offset + 1
        hits: list[CandidateHit] = []
        seen: set[tuple[str, int]] = set()
        for pointer in pointers:
            identity = (pointer.canonical_id, pointer.canonical_version)
            if identity in seen or pointer.rank != expected_rank:
                raise RuntimeError("graphiti candidate lookup returned an unstable ranking")
            seen.add(identity)
            expected_rank += 1
            hits.append(
                CandidateHit(
                    canonical_id=pointer.canonical_id,
                    canonical_version=pointer.canonical_version,
                    provider_id=self.provider_id,
                    query_key=pointer.query_key,
                    rank=pointer.rank,
                    match_reasons=pointer.match_reasons,
                )
            )
        return tuple(hits)


def create_graphiti_context_candidate_provider(
    *, lookup: GraphitiCandidateLookupPort
) -> ContextCandidateHitProviderPort:
    return GraphitiContextCandidateProvider(lookup=lookup)


__all__ = (
    "GraphitiCandidateLookupPort",
    "GraphitiCandidatePointer",
    "GraphitiContextCandidateProvider",
    "create_graphiti_context_candidate_provider",
)
