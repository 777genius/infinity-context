"""Candidate-only cognitive domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Literal

from .errors import CognitiveMemoryInvariantError
from .identity import (
    CanonicalEvidenceIdentity,
    CognitiveCandidateIdentity,
    CognitiveProjectionVersion,
    CognitiveScope,
    cognitive_content_hash,
)


class CognitiveKind(StrEnum):
    EXPERIENCE = "experience"
    OBSERVATION = "observation"
    LESSON = "lesson"
    MENTAL_MODEL = "mental_model"


class CognitiveDerivationOrigin(StrEnum):
    SOURCE = "source"
    PROVIDER = "provider"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class CognitiveEvidenceRef:
    """Citation locator bound to one exact canonical source version."""

    identity: CanonicalEvidenceIdentity
    citation: str

    def __post_init__(self) -> None:
        if not self.citation.strip():
            raise CognitiveMemoryInvariantError("cognitive evidence citation is required")


@dataclass(frozen=True, slots=True, init=False)
class CognitiveCandidate:
    """Derived evidence candidate that can never be canonical by itself."""

    is_authoritative: ClassVar[Literal[False]] = False

    identity: CognitiveCandidateIdentity
    scope: CognitiveScope
    kind: CognitiveKind
    derivation_origin: CognitiveDerivationOrigin
    content: str
    content_hash: str
    projection_version: CognitiveProjectionVersion
    evidence_identities: tuple[CanonicalEvidenceIdentity, ...]
    evidence_refs: tuple[CognitiveEvidenceRef, ...]
    confidence: float
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __new__(cls) -> CognitiveCandidate:
        raise TypeError("CognitiveCandidate is constructed only by trusted application policy")

    def __post_init__(self) -> None:
        normalized_content = self.content.strip()
        if not normalized_content:
            raise CognitiveMemoryInvariantError("cognitive candidate content is required")
        object.__setattr__(self, "content", normalized_content)
        if isinstance(self.confidence, bool) or not 0.0 <= self.confidence <= 1.0:
            raise CognitiveMemoryInvariantError("cognitive confidence must be between 0 and 1")
        if not self.evidence_identities or not self.evidence_refs:
            raise CognitiveMemoryInvariantError(
                "cognitive candidates require canonical evidence identities and references"
            )
        if len(set(self.evidence_identities)) != len(self.evidence_identities):
            raise CognitiveMemoryInvariantError(
                "duplicate canonical evidence identities are invalid"
            )
        ref_identities = tuple(reference.identity for reference in self.evidence_refs)
        if len(set(ref_identities)) != len(ref_identities):
            raise CognitiveMemoryInvariantError(
                "duplicate cognitive evidence references are invalid"
            )
        if set(ref_identities) != set(self.evidence_identities):
            raise CognitiveMemoryInvariantError(
                "cognitive evidence references must cover the exact evidence identities"
            )
        if any(identity.scope != self.scope for identity in self.evidence_identities):
            raise CognitiveMemoryInvariantError("canonical evidence must share candidate scope")
        for field_name, bound in (("valid_from", self.valid_from), ("valid_to", self.valid_to)):
            if bound is not None and not isinstance(bound, datetime):
                raise CognitiveMemoryInvariantError(f"{field_name} must be a datetime")
            if bound is not None and bound.utcoffset() is None:
                raise CognitiveMemoryInvariantError(f"{field_name} must be timezone-aware")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise CognitiveMemoryInvariantError("valid_to must not precede valid_from")
        expected_hash = cognitive_content_hash(self.content)
        if self.content_hash != expected_hash:
            raise CognitiveMemoryInvariantError("candidate content hash does not match content")
        expected_identity = CognitiveCandidateIdentity.derive(
            scope=self.scope,
            kind=self.kind.value,
            evidence_identities=self.evidence_identities,
            content_hash=self.content_hash,
            projection_version=self.projection_version,
        )
        if self.identity != expected_identity:
            raise CognitiveMemoryInvariantError("candidate identity is not deterministic")


def _create_trusted_cognitive_candidate(
    *,
    scope: CognitiveScope,
    kind: CognitiveKind,
    derivation_origin: CognitiveDerivationOrigin,
    content: str,
    projection_version: CognitiveProjectionVersion,
    evidence_refs: tuple[CognitiveEvidenceRef, ...],
    confidence: float,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> CognitiveCandidate:
    """Internal construction seam; application policy owns origin stamping."""

    evidence_identities = tuple(reference.identity for reference in evidence_refs)
    content_hash = cognitive_content_hash(content)
    identity = CognitiveCandidateIdentity.derive(
        scope=scope,
        kind=kind.value,
        evidence_identities=evidence_identities,
        content_hash=content_hash,
        projection_version=projection_version,
    )
    candidate = object.__new__(CognitiveCandidate)
    values = {
        "identity": identity,
        "scope": scope,
        "kind": kind,
        "derivation_origin": derivation_origin,
        "content": content,
        "content_hash": content_hash,
        "projection_version": projection_version,
        "evidence_identities": evidence_identities,
        "evidence_refs": evidence_refs,
        "confidence": confidence,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    for field_name, value in values.items():
        object.__setattr__(candidate, field_name, value)
    candidate.__post_init__()
    return candidate
