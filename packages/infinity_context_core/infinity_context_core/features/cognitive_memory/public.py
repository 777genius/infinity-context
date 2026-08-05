"""Narrow public API for provider-neutral cognitive memory foundations."""

from .application import ProviderCognitiveDerivationUseCase
from .domain import (
    FEATURE_ID,
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveCandidateIdentity,
    CognitiveDerivationOrigin,
    CognitiveEvidenceRef,
    CognitiveKind,
    CognitiveMemoryFeature,
    CognitiveMemoryInvariantError,
    CognitiveProjectionVersion,
    CognitiveScope,
    InvalidationAssessment,
    InvalidationDecision,
    PromotionAssessment,
    PromotionDecision,
    assess_invalidation,
    assess_promotion,
)
from .ports import (
    CognitiveDerivationDraft,
    CognitiveDerivationPort,
    CognitiveDerivationRequest,
    CognitiveDerivationSource,
)

__all__ = (
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
