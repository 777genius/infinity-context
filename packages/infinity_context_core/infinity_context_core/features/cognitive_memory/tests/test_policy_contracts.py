"""Promotion and invalidation policy contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from inspect import signature

import pytest

from ..domain.candidate import _create_trusted_cognitive_candidate
from ..public import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveDerivationOrigin,
    CognitiveEvidenceRef,
    CognitiveKind,
    CognitiveProjectionVersion,
    CognitiveScope,
    InvalidationDecision,
    PromotionDecision,
    assess_invalidation,
    assess_promotion,
)


@pytest.fixture
def candidate_factory():
    def create(
        kind: CognitiveKind = CognitiveKind.OBSERVATION,
        origin: CognitiveDerivationOrigin = CognitiveDerivationOrigin.SOURCE,
    ) -> CognitiveCandidate:
        scope = CognitiveScope("space", "scope")
        identity = CanonicalEvidenceIdentity("fact", "fact-1", 3, scope)
        return _create_trusted_cognitive_candidate(
            scope=scope,
            kind=kind,
            derivation_origin=origin,
            content="A cited candidate",
            projection_version=CognitiveProjectionVersion("v1"),
            evidence_refs=(CognitiveEvidenceRef(identity, "fact:fact-1@3"),),
            confidence=0.99,
        )

    return create


@pytest.mark.parametrize("kind", (CognitiveKind.LESSON, CognitiveKind.MENTAL_MODEL))
def test_synthesized_kinds_always_require_existing_review(candidate_factory, kind) -> None:
    assessment = assess_promotion(
        candidate_factory(kind),
        current_visible_evidence=candidate_factory(kind).evidence_identities,
        policy_version="promotion-v1",
    )

    assert assessment.decision is PromotionDecision.PENDING_REVIEW


@pytest.mark.parametrize(
    "origin", (CognitiveDerivationOrigin.PROVIDER, CognitiveDerivationOrigin.ASSISTANT)
)
def test_provider_and_assistant_outputs_require_review(candidate_factory, origin) -> None:
    candidate = candidate_factory(origin=origin)
    assessment = assess_promotion(
        candidate,
        current_visible_evidence=candidate.evidence_identities,
        policy_version="promotion-v1",
    )

    assert assessment.decision is PromotionDecision.PENDING_REVIEW


def test_promotion_uses_immutable_candidate_origin_not_caller_claim(candidate_factory) -> None:
    candidate = candidate_factory(origin=CognitiveDerivationOrigin.PROVIDER)

    assert "origin" not in signature(assess_promotion).parameters
    assert "evidence_is_current" not in signature(assess_promotion).parameters
    with pytest.raises(FrozenInstanceError):
        candidate.derivation_origin = CognitiveDerivationOrigin.SOURCE  # type: ignore[misc]


def test_source_observation_remains_source_only(candidate_factory) -> None:
    candidate = candidate_factory()
    assessment = assess_promotion(
        candidate,
        current_visible_evidence=candidate.evidence_identities,
        policy_version="promotion-v1",
    )

    assert assessment.decision is PromotionDecision.SOURCE_ONLY


def test_stale_source_denies_promotion_and_invalidates_before_use(candidate_factory) -> None:
    candidate = candidate_factory()
    newer = CanonicalEvidenceIdentity("fact", "fact-1", 4, candidate.scope)

    promotion = assess_promotion(
        candidate,
        current_visible_evidence=(newer,),
        policy_version="promotion-v1",
    )
    invalidation = assess_invalidation(
        candidate,
        current_visible_evidence=(newer,),
        policy_version="invalidation-v1",
    )

    assert promotion.decision is PromotionDecision.DENY
    assert invalidation.decision is InvalidationDecision.INVALIDATE


def test_exact_hydrated_source_set_remains_current(candidate_factory) -> None:
    candidate = candidate_factory()

    assessment = assess_invalidation(
        candidate,
        current_visible_evidence=candidate.evidence_identities,
        policy_version="invalidation-v1",
    )

    assert assessment.decision is InvalidationDecision.CURRENT
