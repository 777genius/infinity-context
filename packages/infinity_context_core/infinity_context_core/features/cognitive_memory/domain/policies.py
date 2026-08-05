"""Trust policies for cognitive promotion and source invalidation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .candidate import CognitiveCandidate, CognitiveDerivationOrigin, CognitiveKind
from .errors import CognitiveMemoryInvariantError
from .identity import CanonicalEvidenceIdentity


class PromotionDecision(StrEnum):
    SOURCE_ONLY = "source_only"
    PENDING_REVIEW = "pending_review"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PromotionAssessment:
    """Routing decision; promotion still uses the canonical suggestion/fact lifecycle."""

    decision: PromotionDecision
    reason: str
    policy_version: str

    def __post_init__(self) -> None:
        if not self.reason.strip() or not self.policy_version.strip():
            raise CognitiveMemoryInvariantError("promotion reason and policy version are required")


class InvalidationDecision(StrEnum):
    CURRENT = "current"
    INVALIDATE = "invalidate"


@dataclass(frozen=True, slots=True)
class InvalidationAssessment:
    """Whether exact canonical source versions remain current and visible."""

    decision: InvalidationDecision
    reason: str
    policy_version: str

    def __post_init__(self) -> None:
        if not self.reason.strip() or not self.policy_version.strip():
            raise CognitiveMemoryInvariantError(
                "invalidation reason and policy version are required"
            )


def assess_promotion(
    candidate: CognitiveCandidate,
    *,
    current_visible_evidence: tuple[CanonicalEvidenceIdentity, ...],
    policy_version: str,
) -> PromotionAssessment:
    """Keep synthesis non-authoritative and route review-sensitive output to review."""

    invalidation = assess_invalidation(
        candidate,
        current_visible_evidence=current_visible_evidence,
        policy_version=policy_version,
    )
    if invalidation.decision is InvalidationDecision.INVALIDATE:
        return PromotionAssessment(
            PromotionDecision.DENY,
            invalidation.reason,
            policy_version,
        )
    if candidate.derivation_origin is not CognitiveDerivationOrigin.SOURCE or candidate.kind in {
        CognitiveKind.LESSON,
        CognitiveKind.MENTAL_MODEL,
    }:
        return PromotionAssessment(
            PromotionDecision.PENDING_REVIEW,
            "synthesized or provider-derived cognition requires existing review lifecycle",
            policy_version,
        )
    return PromotionAssessment(
        PromotionDecision.SOURCE_ONLY,
        "source-backed candidate remains cited evidence until canonical lifecycle accepts it",
        policy_version,
    )


def assess_invalidation(
    candidate: CognitiveCandidate,
    *,
    current_visible_evidence: tuple[CanonicalEvidenceIdentity, ...],
    policy_version: str,
) -> InvalidationAssessment:
    """Invalidate before retrieval/context when any exact canonical identity changed."""

    expected = set(candidate.evidence_identities)
    current = set(current_visible_evidence)
    if expected != current:
        return InvalidationAssessment(
            InvalidationDecision.INVALIDATE,
            "canonical source version, status, visibility, or scope no longer matches",
            policy_version,
        )
    return InvalidationAssessment(
        InvalidationDecision.CURRENT,
        "all canonical source identities are current and visible",
        policy_version,
    )
