"""Explicit compatibility exports for benchmark-owned candidate scoring.

Canonical metadata names the benchmark implementation owner. Historical imports
and pickles continue resolving through these aliases, including typed delegates
for private helpers whose concrete/protocol annotations intentionally differ.
"""

from __future__ import annotations

# ruff: noqa: F401
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from infinity_context_benchmarks.rerank_policy.answer_shapes import (
    _COUNT_LIST_GENERIC_RELATION_TERMS,
    AnswerabilityPolicy,
    CountListAnswerShapePolicy,
    ValueAnswerShapePolicy,
    _answerability_boost,
    _answerability_boost_eligible,
    _has_count_list_subject_grounding,
    _typed_category_answerability_grounded,
)
from infinity_context_benchmarks.rerank_policy.common import (
    _MISSING_REQUIRED_ANSWER_EVIDENCE_REASONS,
    _has_measured_locality_below,
    _has_missing_required_answer_evidence,
    _has_positive_boost,
    _has_precise_or_unmeasured_source_provenance,
    _reason_codes,
    _rounded_boosts,
)
from infinity_context_benchmarks.rerank_policy.contracts import (
    RerankPolicy,
    RerankPolicyContribution,
    RerankPolicyFeatures,
    RerankPolicyPlan,
)
from infinity_context_benchmarks.rerank_policy.evidence import (
    EntitySpeakerPolicy,
    EvidenceBundlePolicy,
    FocusedTurnPolicy,
    RelationCoveragePolicy,
    SourceGroundingPolicy,
    _direct_speaker_relation_grounded,
    _focused_relation_density_boost,
    _relation_boost,
    _relation_category_coverage_boost,
    _relation_coverage_boost,
    _source_grounding_evidence_grounded,
    _source_grounding_plausible_but_ungrounded,
    _speaker_grounding_eligible,
    _visual_evidence_grounded,
)
from infinity_context_benchmarks.rerank_policy.intent import (
    _LOCATION_SUPPORT_TERMS,
    _PREFERENCE_POLARITY_TERMS,
    ContrastIntentPolicy,
    LocationIntentPolicy,
    MultiHopPolicy,
    NegativeAbsencePolicy,
    PreferenceIntentPolicy,
    _contrast_boost_eligible,
    _has_typed_preference_relation_hit,
    _negative_absence_evidence_grounded,
    _preference_evidence_grounded,
    _preference_reason_grounded,
    _preference_reason_required,
)
from infinity_context_benchmarks.rerank_policy.scoring import (
    _DEFAULT_POLICIES,
    score_rerank_policy_contributions,
)
from infinity_context_benchmarks.rerank_policy.temporal import (
    TemporalPolicy,
    _has_content_temporal_evidence,
    _has_temporal_query_role,
    _stale_only_current_state_evidence,
    _temporal_role_support_eligible,
    _temporal_sequence_direction,
    _temporal_sequence_direction_conflict,
    _temporal_sequence_query_direction,
    _typed_temporal_boost,
)
from infinity_context_benchmarks.rerank_policy.typed_relations import (
    _TYPED_PROFILE_SUPPORT_CATEGORIES,
    _TYPED_RELATION_SUPPORT_NEEDS,
    _TYPED_RELATION_SUPPORT_ROLE_CATEGORIES,
    TypedRelationSupportPolicy,
    _support_goal_category_grounded,
    _typed_profile_category_grounded,
    _typed_relation_support_category_hits,
    _typed_relation_support_grounded,
    _typed_relation_support_hit_roles,
    _typed_relation_support_roles,
)
