"""Invalidate derived cognition when a canonical source version changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveCandidateIdentity,
    CognitiveProjectionInvalidation,
    CognitiveScope,
    InvalidationDecision,
    assess_invalidation,
)
from ..ports import CognitiveProjectionRepositoryPort


@dataclass(frozen=True, slots=True)
class PersistCognitiveCandidateCommand:
    candidate: CognitiveCandidate
    current_visible_evidence: tuple[CanonicalEvidenceIdentity, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PersistCognitiveCandidateHandler:
    projections: CognitiveProjectionRepositoryPort
    policy_version: str = "cognitive-dependencies-v1"

    async def execute(self, command: PersistCognitiveCandidateCommand) -> None:
        assessment = assess_invalidation(
            command.candidate,
            current_visible_evidence=command.current_visible_evidence,
            policy_version=self.policy_version,
        )
        if assessment.decision is InvalidationDecision.INVALIDATE:
            raise ValueError("Cannot persist cognition from stale canonical evidence")
        if command.created_at.utcoffset() is None:
            raise ValueError("Cognitive projection creation time must be timezone-aware")
        persisted = await self.projections.upsert_if_evidence_current(
            command.candidate,
            current_visible_evidence=command.current_visible_evidence,
            created_at=command.created_at,
        )
        if not persisted:
            raise ValueError("Cannot persist cognition from stale canonical evidence")


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceChangedCommand:
    scope: CognitiveScope
    evidence_type: str
    evidence_id: str
    current_version: int | None
    currently_visible: bool
    source_event_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.evidence_type.strip() or not self.evidence_id.strip():
            raise ValueError("Canonical evidence change requires type and id")
        if self.currently_visible and self.current_version is None:
            raise ValueError("Visible canonical evidence requires current_version")
        if self.current_version is not None and self.current_version < 1:
            raise ValueError("Canonical evidence current_version must be positive")
        if not self.source_event_id.strip():
            raise ValueError("Canonical evidence change requires source_event_id")
        if self.occurred_at.utcoffset() is None:
            raise ValueError("Canonical evidence change time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class InvalidateCognitiveDependenciesResult:
    invalidated_candidate_ids: tuple[CognitiveCandidateIdentity, ...]


@dataclass(frozen=True, slots=True)
class InvalidateCognitiveDependenciesHandler:
    projections: CognitiveProjectionRepositoryPort

    async def execute(
        self,
        command: CanonicalEvidenceChangedCommand,
    ) -> InvalidateCognitiveDependenciesResult:
        dependents = await self.projections.list_active_dependents(
            scope=command.scope,
            evidence_type=command.evidence_type,
            evidence_id=command.evidence_id,
        )
        invalidated: list[CognitiveCandidateIdentity] = []
        for dependency_set in dependents:
            matching_versions = {
                identity.version
                for identity in dependency_set.evidence_identities
                if identity.evidence_type == command.evidence_type
                and identity.evidence_id == command.evidence_id
            }
            if not matching_versions:
                continue
            if command.currently_visible and matching_versions == {command.current_version}:
                continue
            reason = (
                "canonical_source_hidden"
                if not command.currently_visible
                else "canonical_source_version_changed"
            )
            changed = await self.projections.invalidate(
                CognitiveProjectionInvalidation(
                    candidate_id=dependency_set.candidate_id,
                    invalidated_at=command.occurred_at,
                    reason_code=reason,
                    source_event_id=command.source_event_id,
                )
            )
            if changed:
                invalidated.append(dependency_set.candidate_id)
        return InvalidateCognitiveDependenciesResult(tuple(invalidated))


__all__ = (
    "CanonicalEvidenceChangedCommand",
    "InvalidateCognitiveDependenciesHandler",
    "InvalidateCognitiveDependenciesResult",
    "PersistCognitiveCandidateCommand",
    "PersistCognitiveCandidateHandler",
)
