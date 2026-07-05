"""Application query/result DTOs for context building."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.context_building.domain import (
    ContextBudget,
    ContextBundle,
    ContextQuery,
)


@dataclass(frozen=True, slots=True)
class BuildContextQuery:
    """Request to assemble prompt-ready evidence for one user query."""

    query: ContextQuery
    budget: ContextBudget
    candidate_limit: int = 20
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.candidate_limit < 1:
            raise ValueError("Candidate limit must be positive")


@dataclass(frozen=True, slots=True)
class BuildContextResult:
    """Result returned by the context builder application boundary."""

    bundle: ContextBundle


__all__ = ("BuildContextQuery", "BuildContextResult")
