"""Public domain surface for cognitive_memory."""

from .candidate import (
    CognitiveCandidate,
    CognitiveDerivationOrigin,
    CognitiveEvidenceRef,
    CognitiveKind,
)
from .dependencies import (
    CognitiveProjectionDependencySet,
    CognitiveProjectionInvalidation,
    CognitiveProjectionState,
)
from .errors import CognitiveMemoryInvariantError
from .feature import FEATURE_ID, CognitiveMemoryFeature
from .identity import (
    CanonicalEvidenceIdentity,
    CognitiveCandidateIdentity,
    CognitiveProjectionVersion,
    CognitiveScope,
    cognitive_content_hash,
)
from .policies import (
    InvalidationAssessment,
    InvalidationDecision,
    PromotionAssessment,
    PromotionDecision,
    assess_invalidation,
    assess_promotion,
)

__all__ = (
    "FEATURE_ID",
    "CanonicalEvidenceIdentity",
    "CognitiveCandidate",
    "CognitiveCandidateIdentity",
    "CognitiveDerivationOrigin",
    "CognitiveEvidenceRef",
    "CognitiveKind",
    "CognitiveMemoryFeature",
    "CognitiveMemoryInvariantError",
    "CognitiveProjectionVersion",
    "CognitiveProjectionDependencySet",
    "CognitiveProjectionInvalidation",
    "CognitiveProjectionState",
    "CognitiveScope",
    "InvalidationAssessment",
    "InvalidationDecision",
    "PromotionAssessment",
    "PromotionDecision",
    "assess_invalidation",
    "assess_promotion",
    "cognitive_content_hash",
)
