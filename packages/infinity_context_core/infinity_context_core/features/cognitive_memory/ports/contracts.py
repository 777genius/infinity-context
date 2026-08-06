"""Provider-neutral input contract for replaceable cognitive derivation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain import (
    CanonicalEvidenceIdentity,
    CognitiveEvidenceRef,
    CognitiveKind,
    CognitiveMemoryInvariantError,
    CognitiveProjectionVersion,
    CognitiveScope,
)


@dataclass(frozen=True, slots=True)
class CognitiveDerivationSource:
    """Canonical content supplied to derivation after Postgres hydration."""

    identity: CanonicalEvidenceIdentity
    reference: CognitiveEvidenceRef
    content: str

    def __post_init__(self) -> None:
        if self.reference.identity != self.identity:
            raise CognitiveMemoryInvariantError("derivation source reference identity must match")
        if not self.content.strip():
            raise CognitiveMemoryInvariantError("derivation source content is required")


@dataclass(frozen=True, slots=True)
class CognitiveDerivationRequest:
    """Provider-neutral synthesis request over canonically hydrated evidence."""

    scope: CognitiveScope
    sources: tuple[CognitiveDerivationSource, ...]
    projection_version: CognitiveProjectionVersion

    def __post_init__(self) -> None:
        if not self.sources:
            raise CognitiveMemoryInvariantError("cognitive derivation requires canonical sources")
        identities = tuple(source.identity for source in self.sources)
        if len(set(identities)) != len(identities):
            raise CognitiveMemoryInvariantError(
                "duplicate cognitive derivation sources are invalid"
            )
        if any(source.identity.scope != self.scope for source in self.sources):
            raise CognitiveMemoryInvariantError("derivation sources must share request scope")


@dataclass(frozen=True, slots=True)
class CognitiveDerivationDraft:
    """Untrusted provider output without origin, identity, scope, or projection authority."""

    kind: CognitiveKind
    content: str
    evidence_refs: tuple[CognitiveEvidenceRef, ...]
    confidence: float
    valid_from: datetime | None = None
    valid_to: datetime | None = None
