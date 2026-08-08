"""Domain model owned by the memory_facts feature."""

from infinity_context_core.features.memory_facts.domain.fact import (
    MemoryFact,
    MemoryFactClassification,
    MemoryFactConfidence,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactKind,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactStatus,
    MemoryFactTrustLevel,
    MemoryFactVisibility,
)
from infinity_context_core.features.memory_facts.domain.feature import (
    FEATURE_ID,
    MemoryFactsFeature,
)
from infinity_context_core.features.memory_facts.domain.selection import (
    FactEligibilityAssessment,
    FactEligibilityPolicy,
    FactTemporalQueryMode,
    MemoryFactSelectionQuery,
)
from infinity_context_core.features.memory_facts.domain.supersession import (
    FactSupersessionPolicy,
)
from infinity_context_core.features.memory_facts.domain.taxonomy import (
    FactTtlPolicy,
    NormalizedFactTaxonomy,
    normalize_fact_taxonomy_fields,
)
from infinity_context_core.features.memory_facts.domain.temporal import (
    FactCurrentness,
    FactCurrentnessAssessment,
    FactCurrentnessPolicy,
    FactTemporalAssurance,
)
from infinity_context_core.features.memory_facts.domain.temporal_decisions import (
    FactSupersessionRelation,
    FactTemporalDecision,
    FactTemporalDecisionType,
)
from infinity_context_core.features.memory_facts.domain.value_objects import (
    FactCodeScopeReference,
    FactEpistemicContext,
    FactEpistemicMode,
    FactFreshness,
    FactLifecycle,
    FactLifecycleStatus,
    FactQuality,
    FactRetention,
    FactRevision,
    FactTemporalExtent,
    FactTemporalKind,
)

__all__ = (
    "FEATURE_ID",
    "FactCurrentness",
    "FactCurrentnessAssessment",
    "FactCurrentnessPolicy",
    "FactCodeScopeReference",
    "FactEligibilityAssessment",
    "FactEligibilityPolicy",
    "FactEpistemicContext",
    "FactEpistemicMode",
    "FactFreshness",
    "FactLifecycle",
    "FactLifecycleStatus",
    "FactQuality",
    "FactRetention",
    "FactRevision",
    "FactTemporalAssurance",
    "FactSupersessionPolicy",
    "FactSupersessionRelation",
    "FactTemporalDecision",
    "FactTemporalDecisionType",
    "FactTemporalExtent",
    "FactTemporalKind",
    "FactTemporalQueryMode",
    "FactTtlPolicy",
    "MemoryFact",
    "MemoryFactClassification",
    "MemoryFactConfidence",
    "MemoryFactEvidenceRef",
    "MemoryFactIdentity",
    "MemoryFactKind",
    "MemoryFactScope",
    "MemoryFactSelectionQuery",
    "MemoryFactSnapshot",
    "MemoryFactSourceRef",
    "MemoryFactStatus",
    "MemoryFactTrustLevel",
    "MemoryFactVisibility",
    "MemoryFactsFeature",
    "NormalizedFactTaxonomy",
    "normalize_fact_taxonomy_fields",
)
