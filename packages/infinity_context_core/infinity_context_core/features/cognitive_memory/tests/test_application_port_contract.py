"""Provider-neutral application and port boundary tests."""

from __future__ import annotations

import asyncio
from dataclasses import fields
from inspect import iscoroutinefunction

import pytest

from ..public import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveDerivationDraft,
    CognitiveDerivationOrigin,
    CognitiveDerivationPort,
    CognitiveDerivationRequest,
    CognitiveDerivationSource,
    CognitiveEvidenceRef,
    CognitiveKind,
    CognitiveMemoryInvariantError,
    CognitiveProjectionVersion,
    CognitiveScope,
    PromotionDecision,
    ProviderCognitiveDerivationUseCase,
    assess_promotion,
)


class _DraftAdapter:
    def __init__(self, draft: CognitiveDerivationDraft) -> None:
        self._draft = draft

    async def derive(
        self, request: CognitiveDerivationRequest
    ) -> tuple[CognitiveDerivationDraft, ...]:
        del request
        return (self._draft,)


def test_derivation_request_requires_postgres_hydrated_canonical_sources() -> None:
    scope = CognitiveScope("space", "scope")
    identity = CanonicalEvidenceIdentity("document_chunk", "chunk-1", 2, scope)
    reference = CognitiveEvidenceRef(identity, "document:doc-1#chunk-1@2")

    request = CognitiveDerivationRequest(
        scope=scope,
        sources=(CognitiveDerivationSource(identity, reference, "Canonical source text"),),
        projection_version=CognitiveProjectionVersion("v1"),
    )

    assert request.sources[0].identity == identity


def test_single_derivation_port_has_no_provider_or_retrieval_authority_fields() -> None:
    request_fields = {field.name for field in fields(CognitiveDerivationRequest)}

    assert request_fields == {"scope", "sources", "projection_version"}
    assert iscoroutinefunction(CognitiveDerivationPort.derive)


def test_adapter_draft_has_no_origin_or_candidate_identity_authority() -> None:
    draft_fields = {field.name for field in fields(CognitiveDerivationDraft)}

    assert draft_fields == {
        "kind",
        "content",
        "evidence_refs",
        "confidence",
        "valid_from",
        "valid_to",
    }
    assert not hasattr(CognitiveCandidate, "create")
    with pytest.raises(TypeError, match="trusted application policy"):
        CognitiveCandidate()


def test_application_stamps_provider_origin_and_observation_requires_review() -> None:
    scope = CognitiveScope("space", "scope")
    identity = CanonicalEvidenceIdentity("fact", "fact-1", 1, scope)
    reference = CognitiveEvidenceRef(identity, "fact:fact-1@1")
    request = CognitiveDerivationRequest(
        scope=scope,
        sources=(CognitiveDerivationSource(identity, reference, "Canonical source"),),
        projection_version=CognitiveProjectionVersion("v1"),
    )
    adapter = _DraftAdapter(
        CognitiveDerivationDraft(
            kind=CognitiveKind.OBSERVATION,
            content="Provider observation",
            evidence_refs=(reference,),
            confidence=0.9,
        )
    )

    candidate = asyncio.run(ProviderCognitiveDerivationUseCase(adapter).derive(request))[0]
    assessment = assess_promotion(
        candidate,
        current_visible_evidence=candidate.evidence_identities,
        policy_version="promotion-v1",
    )

    assert candidate.derivation_origin is CognitiveDerivationOrigin.PROVIDER
    assert assessment.decision is PromotionDecision.PENDING_REVIEW


def test_application_rejects_provider_evidence_outside_request() -> None:
    scope = CognitiveScope("space", "scope")
    request_identity = CanonicalEvidenceIdentity("fact", "requested", 1, scope)
    request_ref = CognitiveEvidenceRef(request_identity, "fact:requested@1")
    foreign_identity = CanonicalEvidenceIdentity("fact", "foreign", 1, scope)
    foreign_ref = CognitiveEvidenceRef(foreign_identity, "fact:foreign@1")
    request = CognitiveDerivationRequest(
        scope=scope,
        sources=(CognitiveDerivationSource(request_identity, request_ref, "Canonical source"),),
        projection_version=CognitiveProjectionVersion("v1"),
    )
    adapter = _DraftAdapter(
        CognitiveDerivationDraft(
            CognitiveKind.OBSERVATION,
            "Unbound provider observation",
            (foreign_ref,),
            0.5,
        )
    )

    with pytest.raises(CognitiveMemoryInvariantError, match="subset of request evidence"):
        asyncio.run(ProviderCognitiveDerivationUseCase(adapter).derive(request))


def test_public_exports_are_exact_and_narrow() -> None:
    from .. import public

    assert public.__all__ == (
        "FEATURE_ID",
        "CanonicalEvidenceIdentity",
        "CognitiveCandidate",
        "CognitiveCandidateIdentity",
        "CognitiveDerivationDraft",
        "CognitiveDerivationOrigin",
        "CognitiveDerivationPort",
        "CognitiveDerivationRequest",
        "CognitiveDerivationSource",
        "CognitiveEvidenceRef",
        "CognitiveKind",
        "CognitiveMemoryFeature",
        "CognitiveMemoryInvariantError",
        "CognitiveProjectionVersion",
        "CognitiveScope",
        "InvalidationAssessment",
        "InvalidationDecision",
        "PromotionAssessment",
        "PromotionDecision",
        "ProviderCognitiveDerivationUseCase",
        "assess_invalidation",
        "assess_promotion",
    )
