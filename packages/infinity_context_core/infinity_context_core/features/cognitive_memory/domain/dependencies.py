"""Lifecycle of derived candidates bound to exact canonical source versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import CognitiveMemoryInvariantError
from .identity import CanonicalEvidenceIdentity, CognitiveCandidateIdentity, CognitiveScope


class CognitiveProjectionState(StrEnum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class CognitiveProjectionDependencySet:
    candidate_id: CognitiveCandidateIdentity
    scope: CognitiveScope
    evidence_identities: tuple[CanonicalEvidenceIdentity, ...]

    def __post_init__(self) -> None:
        if not self.evidence_identities:
            raise CognitiveMemoryInvariantError("projection dependencies cannot be empty")
        if any(identity.scope != self.scope for identity in self.evidence_identities):
            raise CognitiveMemoryInvariantError("projection dependencies must share scope")


@dataclass(frozen=True, slots=True)
class CognitiveProjectionInvalidation:
    candidate_id: CognitiveCandidateIdentity
    invalidated_at: datetime
    reason_code: str
    source_event_id: str

    def __post_init__(self) -> None:
        if self.invalidated_at.utcoffset() is None:
            raise CognitiveMemoryInvariantError("invalidation time must be timezone-aware")
        if not self.reason_code.strip() or not self.source_event_id.strip():
            raise CognitiveMemoryInvariantError("invalidation reason and source event are required")


__all__ = (
    "CognitiveProjectionDependencySet",
    "CognitiveProjectionInvalidation",
    "CognitiveProjectionState",
)
