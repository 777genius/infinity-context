"""Persistence port for rebuildable cognitive projections and dependencies."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveProjectionDependencySet,
    CognitiveProjectionInvalidation,
    CognitiveScope,
)


class CognitiveProjectionRepositoryPort(Protocol):
    async def upsert_if_evidence_current(
        self,
        candidate: CognitiveCandidate,
        *,
        current_visible_evidence: tuple[CanonicalEvidenceIdentity, ...],
        created_at: datetime,
    ) -> bool:
        """Atomically validate canonical evidence and persist; False means stale."""

    async def list_active_dependents(
        self,
        *,
        scope: CognitiveScope,
        evidence_type: str,
        evidence_id: str,
    ) -> tuple[CognitiveProjectionDependencySet, ...]:
        """Find active projections derived from one canonical source identity."""

    async def invalidate(self, invalidation: CognitiveProjectionInvalidation) -> bool:
        """Invalidate once; return False when already invalidated or absent."""


__all__ = ("CognitiveProjectionRepositoryPort",)
