"""Postgres canonical candidate provider seam for context_building."""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    ContextCandidateProviderPort,
    ContextCandidateRequest,
    ContextItem,
)


class PostgresContextCandidateProvider:
    """Placeholder for future canonical context candidate queries."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    async def find_candidates(
        self,
        _request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        _raise_not_implemented("find_candidates")


def create_postgres_context_candidate_provider() -> ContextCandidateProviderPort:
    """Create the feature-owned Postgres candidate provider placeholder."""

    return PostgresContextCandidateProvider()


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"context_building Postgres candidate provider {operation} is a placeholder seam; "
        "real canonical query wiring is deferred."
    )


__all__ = (
    "PostgresContextCandidateProvider",
    "create_postgres_context_candidate_provider",
)
