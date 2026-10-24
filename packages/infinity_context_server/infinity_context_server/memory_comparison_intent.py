"""Compatibility imports for the benchmark-owned retrieval intent policy.

New code should use infinity_context_benchmarks.retrieval_intent. Canonical
classes/functions belong to their actual implementation modules; historical
imports and pickles continue resolving through these explicit aliases.
"""

from __future__ import annotations

# Preserve the original supported namespace, including imported helper symbols.
# ruff: noqa: F401
import re
from collections.abc import Sequence
from dataclasses import dataclass

from infinity_context_benchmarks.retrieval_intent.comparison_patterns import (
    _COMMONALITY_INTENT_RE,
    _COMPARATIVE_CHOICE_INTENT_RE,
    _EXPLICIT_DIFFERENCE_INTENT_RE,
    _has_commonality_intent,
    _has_comparative_choice_intent,
    _has_contrast_intent,
    _has_count_intent,
    _has_explicit_difference_intent,
    _has_list_intent,
    _has_negative_absence_intent,
)
from infinity_context_benchmarks.retrieval_intent.contracts import (
    RetrievalEntityIntent,
    RetrievalIntent,
    RetrievalRelationIntent,
    RetrievalTimeIntent,
)
from infinity_context_benchmarks.retrieval_intent.event_patterns import (
    _has_action_event_intent,
    _has_adoption_reaction_intent,
    _has_causal_support_intent,
    _has_communication_intent,
    _has_community_membership_intent,
    _has_current_goal_intent,
    _has_direct_emotion_response_intent,
    _has_direct_support_role_question,
    _has_exchange_intent,
    _has_future_home_move_goal_intent,
    _has_inference_support_intent,
    _has_location_transition_intent,
    _has_motivation_artifact_lookup,
    _has_participation_event_intent,
    _has_support_goal_intent,
    _is_direct_support_relation_intent,
)
from infinity_context_benchmarks.retrieval_intent.evidence import (
    infer_bundle_evidence_roles,
    infer_evidence_need,
    infer_risk_flags,
    merge_relation_evidence_needs,
)
from infinity_context_benchmarks.retrieval_intent.profile_patterns import (
    _has_activity_profile_intent,
    _has_commitment_profile_intent,
    _has_contact_profile_intent,
    _has_date_profile_intent,
    _has_diet_profile_intent,
    _has_education_profile_intent,
    _has_employment_profile_intent,
    _has_health_profile_intent,
    _has_pet_profile_intent,
    _has_skill_profile_intent,
    _has_status_profile_intent,
    _has_vehicle_profile_intent,
    _is_kinship_status_lookup,
)
from infinity_context_benchmarks.retrieval_intent.relations import (
    _RELATION_FACET_CONFIG,
    _TEMPORAL_SUPPORT_VARIANTS,
    _dedupe_relation_intents,
    _relation_facet_reason_codes,
    infer_relation_intents,
)
from infinity_context_benchmarks.retrieval_intent.temporal import (
    _ORDINAL_EVENT_TERM_RE,
    _RELATIVE_ORDINAL_PERIOD_TERMS,
    _RELATIVE_SEASON_TERMS,
    _RELATIVE_TIME_TERMS,
    _RELATIVE_WEEKDAY_TERMS,
    _SEASON_TERMS,
    _has_ordinal_event_term,
    infer_time_intent_kind,
)
