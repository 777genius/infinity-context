"""Identity-only recall candidates from canonical and derived indexes."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.context_building.domain.context import ContextItem


@dataclass(frozen=True, slots=True)
class CandidateHit:
    """A match pointer that cannot inject provider-owned content into a prompt."""

    canonical_id: str
    canonical_version: int
    provider_id: str
    query_key: str
    rank: int
    match_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("canonical_id", "provider_id", "query_key"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"Candidate hit {field_name} cannot be blank")
        if (
            not isinstance(self.canonical_version, int)
            or isinstance(self.canonical_version, bool)
            or not 1 <= self.canonical_version <= 9_007_199_254_740_991
        ):
            raise ValueError("Candidate hit canonical_version must be positive")
        if self.rank < 1:
            raise ValueError("Candidate hit rank must be positive")


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    """A deterministic fusion result retaining auditable provider evidence."""

    canonical_id: str
    score: float
    hits: tuple[CandidateHit, ...]


@dataclass(frozen=True, slots=True)
class HydratedContextCandidate:
    """Canonical prompt item and the exact version used to build it."""

    canonical_id: str
    canonical_version: int
    item: ContextItem

    def __post_init__(self) -> None:
        if self.item.item_id != self.canonical_id:
            raise ValueError("Hydrated candidate item_id must match canonical_id")
        if (
            not isinstance(self.canonical_version, int)
            or isinstance(self.canonical_version, bool)
            or not 1 <= self.canonical_version <= 9_007_199_254_740_991
        ):
            raise ValueError("Hydrated candidate version must be positive")


__all__ = ("CandidateHit", "FusedCandidate", "HydratedContextCandidate")
