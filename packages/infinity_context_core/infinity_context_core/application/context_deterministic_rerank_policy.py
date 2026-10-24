"""Deterministic rerank policy policy; one implementation authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from infinity_context_core.application.context_action_roles import action_role_rerank_signal
from infinity_context_core.application.context_activity_companion import activity_companion_signal
from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_answer_unit_shapes import is_typed_answer_unit_shape
from infinity_context_core.application.context_conversation_counterparty import (
    conversation_counterparty_evidence_signal,
    conversation_recency_evidence_signal,
    conversation_recency_missing_temporal_signal,
    conversation_recency_temporal_hint_signal,
    conversation_topic_evidence_signal,
)
from infinity_context_core.application.context_diagnostics import diagnostic_retrieval_sources
from infinity_context_core.application.context_domain_rerank_apply import (
    apply_domain_rerank_signals,
)
from infinity_context_core.application.context_domain_rerank_signals import (
    commonality_who_else_anchor_override,
    has_current_state_correction_evidence,
)
from infinity_context_core.application.context_inference_evidence import (
    answer_evidence_rerank_signal,
)
from infinity_context_core.application.context_named_person_preference import (
    named_person_preference_signal,
)
from infinity_context_core.application.context_object_mismatch import object_kind_mismatch_signal
from infinity_context_core.application.context_ordinal_sequence import (
    ordinal_sequence_rerank_signal,
)
from infinity_context_core.application.context_owner_grounding import owner_grounding_signal
from infinity_context_core.application.context_person_kinship import person_kinship_signal
from infinity_context_core.application.context_person_occupation import person_occupation_signal
from infinity_context_core.application.context_person_relation_inventory import (
    person_relation_inventory_signal,
)
from infinity_context_core.application.context_person_residence import person_residence_signal
from infinity_context_core.application.context_person_team_membership import (
    person_team_membership_signal,
)
from infinity_context_core.application.context_pet_ownership import pet_ownership_signal
from infinity_context_core.application.context_polarity_rerank import (
    absence_contrast_signal,
    absence_negation_signal,
    negative_preference_signal,
    schedule_change_signal,
    status_polarity_signal,
)
from infinity_context_core.application.context_possession_source import possession_source_signal
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    match_query_anchor_intent_to_text,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.application.context_relation_requirement import (
    relation_requirement_signal,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    has_project_identity_mismatch,
    is_query_relevance_sufficient,
)
from infinity_context_core.application.context_requirement_ranking import (
    _GENERIC_BOOSTABLE_ANSWER_SHAPES,
)
from infinity_context_core.application.context_requirement_signals import (
    _item_requirement_coverage_signals,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _action_role_confirms_requested_relation,
    _activity_owner_signal,
    _activity_source_sibling_noise,
    _allergy_condition_weak_evidence,
    _capped_source_sibling_low_signal,
    _dialogue_speaker_confirms_query_anchor,
    _event_participation_mismatch,
    _event_participation_positive_match,
    _event_participation_source_sibling_noise,
    _is_item_purchase_temporal_answer_evidence,
    _item_temporal_hint_code,
    _patriotic_service_weak_evidence,
    _post_event_activity_timing_exact_evidence,
    _post_event_activity_timing_weak_evidence,
    _running_reason_weak_evidence,
    _shoe_usage_exact_evidence,
    _shoe_usage_weak_evidence,
    _temporal_answer_signal,
    _temporal_query_signal_already_applied,
    _volunteer_career_broad_evidence,
    _volunteer_career_exact_turn_evidence,
    _volunteer_career_weak_evidence,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _artifact_inventory_evidence_support_signal,
    _canonical_anchor_summary_support_signal,
    _citation_evidence_support_signal,
    _decomposition_coverage_support_signal,
    _localized_evidence_support_signal,
    _source_quote_anchor_matches_query,
)
from infinity_context_core.application.context_rerank_relevance import (
    _best_query_relevance_for_rerank,
    _is_long_query_weak_overlap,
)
from infinity_context_core.application.context_source_grounding import source_grounding_signal
from infinity_context_core.application.context_speaker_attribution import (
    communication_direction_signal,
    speaker_attribution_signal,
)
from infinity_context_core.application.context_temporal_query import (
    TemporalQueryIntent,
    temporal_query_boost_signal,
)
from infinity_context_core.application.dto import ContextItem

_STRONG_EVIDENCE_RERANK_SOURCES = frozenset(
    {
        "approved_context_linked_anchors",
        "approved_context_linked_asset_manifest_evidence",
        "approved_context_linked_assets",
        "approved_context_linked_chunks",
        "approved_context_linked_extraction_artifacts",
        "approved_context_linked_facts",
        "artifact_evidence",
        "canonical_anchor_relations",
        "canonical_anchors",
        "temporal_supersedes_relation",
    }
)


@dataclass(frozen=True)
class _DeterministicRerankSignals:
    boost: float
    penalty: float
    reasons: tuple[str, ...]
    rank_signals: tuple[tuple[str, float], ...]
    source_count: int
    strong_source_count: int
    coverage_ratio: float
    anchor_conflict: bool
    query_reason: str

    @property
    def net_adjustment(self) -> float:
        return round(self.boost - self.penalty, 4)


def _deterministic_rerank_signals(
    item: ContextItem,
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    temporal_query_intent: TemporalQueryIntent,
    requested_total: int,
    has_multi_evidence_aggregation_candidate: bool,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None,
    max_boost: float,
    max_penalty: float,
    best_query_relevance_fn: Callable[..., tuple[str, str, QueryRelevance]],
) -> _DeterministicRerankSignals:
    sources = diagnostic_retrieval_sources(item.diagnostics)
    strong_source_count = len(set(sources).intersection(_STRONG_EVIDENCE_RERANK_SOURCES))
    query_text, query_reason, relevance = _best_query_relevance_for_rerank(
        plan,
        item=item,
        cache=query_relevance_cache,
        best_query_relevance_fn=best_query_relevance_fn,
    )
    del query_text
    coverage = _item_requirement_coverage_signals(
        item, query=query, query_anchor_intent=query_anchor_intent, requested_total=requested_total
    )
    coverage_ratio = coverage.ratio
    anchor_match = match_query_anchor_intent_to_text(query_anchor_intent, item.text)
    source_quote_anchor_matched = (
        "citation" in coverage.requested_evidence_features
        and _source_quote_anchor_matches_query(
            item=item,
            plan=plan,
            query_anchor_intent=query_anchor_intent,
            best_query_relevance_fn=best_query_relevance_fn,
        )
    )
    text_anchor_conflict = query_anchor_intent_text_conflicts(query_anchor_intent, item.text)
    project_identity_conflict = has_project_identity_mismatch(query=query, text=item.text)
    anchor_conflict = text_anchor_conflict or project_identity_conflict
    source_speaker_anchor_override = (
        text_anchor_conflict
        and (not project_identity_conflict)
        and _dialogue_speaker_confirms_query_anchor(
            item=item, query_anchor_intent=query_anchor_intent, relevance=relevance
        )
    )
    commonality_anchor_override = (
        text_anchor_conflict
        and (not project_identity_conflict)
        and commonality_who_else_anchor_override(query=query, query_reason=query_reason, item=item)
    )
    temporal_supersedes_anchor_override = (
        anchor_conflict and "temporal_supersedes_relation" in sources
    )
    current_state_correction_anchor_override = (
        anchor_conflict
        and temporal_query_intent.prefers_current
        and has_current_state_correction_evidence(item.text)
    )
    boost = 0.0
    penalty = 0.0
    reasons: list[str] = []
    rank_signals: dict[str, float] = {}
    if len(sources) >= 2:
        boost += min(0.018, 0.006 * len(sources))
        reasons.append("hybrid_source_diversity")
    if strong_source_count:
        boost += min(0.018, 0.008 * strong_source_count)
        reasons.append("strong_evidence_source")
    if anchor_match is not None:
        boost += min(0.018, max(0.0, anchor_match.score_boost) * 0.35)
        reasons.append("query_anchor_match")
    elif source_quote_anchor_matched:
        boost += 0.012
        reasons.append("source_quote_query_anchor_match")
    if requested_total > 0 and coverage_ratio > 0:
        boost += 0.014 * coverage_ratio
        reasons.append("explicit_requirement_covered")
    answer_shape_boost = 0.0
    boostable_requested_answer_shapes = (
        coverage.requested_answer_shapes & _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    boostable_covered_answer_shapes = (
        coverage.covered_answer_shapes & _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    if boostable_requested_answer_shapes and boostable_covered_answer_shapes:
        answer_shape_boost = 0.018 * (
            len(boostable_covered_answer_shapes) / len(boostable_requested_answer_shapes)
        )
    typed_requested_answer_shapes = frozenset(
        shape for shape in coverage.requested_answer_shapes if is_typed_answer_unit_shape(shape)
    )
    typed_covered_answer_shapes = frozenset(
        shape for shape in coverage.covered_answer_shapes if is_typed_answer_unit_shape(shape)
    )
    if typed_requested_answer_shapes and typed_covered_answer_shapes:
        answer_shape_boost += 0.024 * (
            len(typed_covered_answer_shapes) / len(typed_requested_answer_shapes)
        )
    if "speaker" in coverage.covered_answer_shapes:
        boost += 0.018
        reasons.append("speaker_answer_shape_covered")
    if is_query_relevance_sufficient(relevance):
        relevance_boost = min(
            0.012, relevance.score_boost * 0.1 + relevance.distinctive_term_hits * 0.003
        )
        if relevance_boost > 0:
            boost += relevance_boost
            reasons.append("query_relevance_supported")
    localized_evidence_boost, localized_evidence_reason = _localized_evidence_support_signal(
        item=item,
        relevance=relevance,
        coverage_ratio=coverage_ratio,
        anchor_matched=anchor_match is not None or source_quote_anchor_matched,
        strong_source_count=strong_source_count,
    )
    if localized_evidence_boost > 0:
        boost += localized_evidence_boost
        reasons.append(localized_evidence_reason)
    decomposition_boost, decomposition_reason, decomposition_signals = (
        _decomposition_coverage_support_signal(plan=plan, text=item.text, query_reason=query_reason)
    )
    if decomposition_boost > 0:
        boost += decomposition_boost
        reasons.append(decomposition_reason)
        rank_signals.update(decomposition_signals)
    canonical_summary_boost, canonical_summary_reason = _canonical_anchor_summary_support_signal(
        item=item,
        coverage=coverage,
        relevance=relevance,
        anchor_matched=anchor_match is not None or source_quote_anchor_matched,
        anchor_conflict=anchor_conflict,
        sources=sources,
        strong_source_count=strong_source_count,
    )
    if canonical_summary_boost > 0:
        boost += canonical_summary_boost
        reasons.append(canonical_summary_reason)
    citation_evidence_boost, citation_evidence_reason, citation_evidence_signals = (
        _citation_evidence_support_signal(
            item=item,
            plan=plan,
            coverage=coverage,
            relevance=relevance,
            anchor_matched=anchor_match is not None or source_quote_anchor_matched,
            strong_source_count=strong_source_count,
            best_query_relevance_fn=best_query_relevance_fn,
        )
    )
    if citation_evidence_boost > 0:
        boost += citation_evidence_boost
        reasons.append(citation_evidence_reason)
        rank_signals.update(citation_evidence_signals)
    (
        artifact_inventory_boost,
        artifact_inventory_penalty,
        artifact_inventory_reason,
        artifact_inventory_signals,
    ) = _artifact_inventory_evidence_support_signal(
        item=item,
        plan=plan,
        query_reason=query_reason,
        relevance=relevance,
        coverage_ratio=coverage_ratio,
        anchor_matched=anchor_match is not None or source_quote_anchor_matched,
    )
    if artifact_inventory_boost > 0:
        boost += artifact_inventory_boost
        reasons.append(artifact_inventory_reason)
        rank_signals.update(artifact_inventory_signals)
    if artifact_inventory_penalty > 0:
        penalty += artifact_inventory_penalty
        reasons.append(artifact_inventory_reason)
        rank_signals.update(artifact_inventory_signals)
    owner_boost, owner_penalty, owner_reason = _activity_owner_signal(
        query_anchor_intent=query_anchor_intent, query_reason=query_reason, text=item.text
    )
    if owner_boost > 0:
        boost += owner_boost
        reasons.append(owner_reason)
    if owner_penalty > 0:
        penalty += owner_penalty
        reasons.append(owner_reason)
    speaker_boost, speaker_penalty, speaker_reason = speaker_attribution_signal(
        query=query, text=item.text
    )
    if speaker_boost > 0:
        boost += speaker_boost
        reasons.append(speaker_reason)
    if speaker_penalty > 0:
        penalty += speaker_penalty
        reasons.append(speaker_reason)
    source_grounding_boost, source_grounding_penalty, source_grounding_reason = (
        source_grounding_signal(query=query, text=item.text, source_refs=item.source_refs)
    )
    if source_grounding_boost > 0:
        boost += source_grounding_boost
        reasons.append(source_grounding_reason)
    if source_grounding_penalty > 0:
        penalty += source_grounding_penalty
        reasons.append(source_grounding_reason)
    communication_boost, communication_penalty, communication_reason = (
        communication_direction_signal(query=query, text=item.text)
    )
    if communication_boost > 0:
        boost += communication_boost
        reasons.append(communication_reason)
    if communication_penalty > 0:
        penalty += communication_penalty
        reasons.append(communication_reason)
    if (
        answer_shape_boost > 0
        and owner_penalty <= 0
        and (speaker_penalty <= 0)
        and (source_grounding_penalty <= 0)
        and (communication_penalty <= 0)
        and (not anchor_conflict)
    ):
        boost += answer_shape_boost
        reasons.append("explicit_answer_shape_covered")
    action_signal = action_role_rerank_signal(query=query, text=item.text)
    if action_signal.boost > 0:
        boost += action_signal.boost
        reasons.append(action_signal.reason)
    if action_signal.penalty > 0:
        penalty += action_signal.penalty
        reasons.append(action_signal.reason)
    possession_boost, possession_penalty, possession_reason = possession_source_signal(
        query=query, item=item
    )
    if possession_boost > 0:
        boost += possession_boost
        reasons.append(possession_reason)
    if possession_penalty > 0:
        penalty += possession_penalty
        reasons.append(possession_reason)
    inference_signal = answer_evidence_rerank_signal(query=query, text=item.text)
    if inference_signal.boost > 0:
        boost += inference_signal.boost
        reasons.append(inference_signal.reason)
    if inference_signal.penalty > 0:
        penalty += inference_signal.penalty
        reasons.append(inference_signal.reason)
    polarity_boost, polarity_penalty, polarity_reason = status_polarity_signal(
        query=query, text=item.text
    )
    if polarity_boost > 0:
        boost += polarity_boost
        reasons.append(polarity_reason)
    if polarity_penalty > 0:
        penalty += polarity_penalty
        reasons.append(polarity_reason)
    negative_boost, negative_penalty, negative_reason = negative_preference_signal(
        query=query, text=item.text
    )
    if negative_boost > 0:
        boost += negative_boost
        reasons.append(negative_reason)
    if negative_penalty > 0:
        penalty += negative_penalty
        reasons.append(negative_reason)
    absence_boost, absence_penalty, absence_reason = absence_negation_signal(
        query=query, text=item.text
    )
    if absence_boost > 0:
        boost += absence_boost
        reasons.append(absence_reason)
    if absence_penalty > 0:
        penalty += absence_penalty
        reasons.append(absence_reason)
    schedule_boost, schedule_penalty, schedule_reason = schedule_change_signal(
        query=query, text=item.text
    )
    if schedule_boost > 0:
        boost += schedule_boost
        reasons.append(schedule_reason)
    if schedule_penalty > 0:
        penalty += schedule_penalty
        reasons.append(schedule_reason)
    named_preference_signal = named_person_preference_signal(query=query, text=item.text)
    if named_preference_signal.boost > 0:
        boost += named_preference_signal.boost
        reasons.append(named_preference_signal.reason)
    if named_preference_signal.penalty > 0:
        penalty += named_preference_signal.penalty
        reasons.append(named_preference_signal.reason)
    pet_signal = pet_ownership_signal(query=query, text=item.text)
    if pet_signal.boost > 0:
        boost += pet_signal.boost
        reasons.append(pet_signal.reason)
    if pet_signal.penalty > 0:
        penalty += pet_signal.penalty
        reasons.append(pet_signal.reason)
    owner_grounding = owner_grounding_signal(query=query, text=item.text)
    if owner_grounding.boost > 0:
        boost += owner_grounding.boost
        reasons.append(owner_grounding.reason)
    if owner_grounding.penalty > 0:
        penalty += owner_grounding.penalty
        reasons.append(owner_grounding.reason)
    contrast_boost, contrast_penalty, contrast_reason = absence_contrast_signal(
        query=query, text=item.text
    )
    if contrast_boost > 0:
        boost += contrast_boost
        reasons.append(contrast_reason)
    if contrast_penalty > 0:
        penalty += contrast_penalty
        reasons.append(contrast_reason)
    object_boost, object_penalty, object_reason = object_kind_mismatch_signal(
        query=query, text=item.text
    )
    if object_boost > 0:
        boost += object_boost
        reasons.append(object_reason)
    if object_penalty > 0:
        penalty += object_penalty
        reasons.append(object_reason)
    ordinal_sequence_signal = ordinal_sequence_rerank_signal(query=query, text=item.text)
    if ordinal_sequence_signal.boost > 0:
        boost += ordinal_sequence_signal.boost
        reasons.append(ordinal_sequence_signal.reason)
    if ordinal_sequence_signal.penalty > 0:
        penalty += ordinal_sequence_signal.penalty
        reasons.append(ordinal_sequence_signal.reason)
    relation_signal = relation_requirement_signal(query=query, text=item.text)
    if relation_signal.boost > 0:
        boost += relation_signal.boost
        reasons.append(relation_signal.reason)
    if relation_signal.penalty > 0 and (
        not _is_item_purchase_temporal_answer_evidence(query_reason=query_reason, item=item)
    ):
        penalty += relation_signal.penalty
        reasons.append(relation_signal.reason)
    person_relation_signal = person_relation_inventory_signal(query=query, text=item.text)
    if person_relation_signal.boost > 0:
        boost += person_relation_signal.boost
        reasons.append(person_relation_signal.reason)
    if person_relation_signal.penalty > 0:
        penalty += person_relation_signal.penalty
        reasons.append(person_relation_signal.reason)
    occupation_signal = person_occupation_signal(query=query, text=item.text)
    if occupation_signal.boost > 0:
        boost += occupation_signal.boost
        reasons.append(occupation_signal.reason)
    if occupation_signal.penalty > 0:
        penalty += occupation_signal.penalty
        reasons.append(occupation_signal.reason)
    residence_signal = person_residence_signal(query=query, text=item.text)
    if residence_signal.boost > 0:
        boost += residence_signal.boost
        reasons.append(residence_signal.reason)
    if residence_signal.penalty > 0:
        penalty += residence_signal.penalty
        reasons.append(residence_signal.reason)
    kinship_signal = person_kinship_signal(query=query, text=item.text)
    if kinship_signal.boost > 0:
        boost += kinship_signal.boost
        reasons.append(kinship_signal.reason)
    if kinship_signal.penalty > 0:
        penalty += kinship_signal.penalty
        reasons.append(kinship_signal.reason)
    team_signal = person_team_membership_signal(query=query, text=item.text)
    if team_signal.boost > 0:
        boost += team_signal.boost
        reasons.append(team_signal.reason)
    if team_signal.penalty > 0:
        penalty += team_signal.penalty
        reasons.append(team_signal.reason)
    conversation_boost, conversation_penalty, conversation_reason = (
        conversation_counterparty_evidence_signal(query=query, text=item.text)
    )
    if conversation_boost > 0:
        boost += conversation_boost
        reasons.append(conversation_reason)
    if conversation_penalty > 0:
        penalty += conversation_penalty
        reasons.append(conversation_reason)
    topic_boost, topic_penalty, topic_reason = conversation_topic_evidence_signal(
        query=query, text=item.text
    )
    if topic_boost > 0:
        boost += topic_boost
        reasons.append(topic_reason)
    if topic_penalty > 0:
        penalty += topic_penalty
        reasons.append(topic_reason)
    recency_boost, recency_penalty, recency_reason = conversation_recency_evidence_signal(
        query=query, text=item.text
    )
    if recency_boost > 0:
        boost += recency_boost
        reasons.append(recency_reason)
    if recency_penalty > 0:
        penalty += recency_penalty
        reasons.append(recency_reason)
    temporal_hint_code = _item_temporal_hint_code(item)
    recency_hint_boost, recency_hint_reason = conversation_recency_temporal_hint_signal(
        query=query, temporal_hint_code=temporal_hint_code
    )
    if recency_hint_boost > 0:
        boost += recency_hint_boost
        reasons.append(recency_hint_reason)
    recency_missing_time_penalty, recency_missing_time_reason = (
        conversation_recency_missing_temporal_signal(
            query=query, text=item.text, temporal_hint_code=temporal_hint_code
        )
    )
    if recency_missing_time_penalty > 0:
        penalty += recency_missing_time_penalty
        reasons.append(recency_missing_time_reason)
    if not _temporal_query_signal_already_applied(item):
        temporal_signal = temporal_query_boost_signal(item, intent=temporal_query_intent)
        if temporal_signal.boost > 0:
            boost += temporal_signal.boost
            reasons.append(f"temporal_query_{temporal_signal.code}")
        if temporal_signal.boost < 0:
            penalty += abs(temporal_signal.boost)
            reasons.append(f"temporal_query_{temporal_signal.code}")
    temporal_answer_boost, temporal_answer_penalty, temporal_answer_reason = (
        _temporal_answer_signal(query=query, query_reason=query_reason, item=item)
    )
    if temporal_answer_boost > 0:
        boost += temporal_answer_boost
        reasons.append(temporal_answer_reason)
    if temporal_answer_penalty > 0:
        penalty += temporal_answer_penalty
        reasons.append(temporal_answer_reason)
    if source_speaker_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_source_speaker")
    elif commonality_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_commonality_who_else")
    elif temporal_supersedes_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_temporal_supersedes")
    elif current_state_correction_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_current_state_correction")
    elif anchor_conflict and source_quote_anchor_matched:
        reasons.append("query_anchor_conflict_overridden_by_source_quote")
    elif anchor_conflict and (not _action_role_confirms_requested_relation(action_signal.reason)):
        penalty += 0.07
        reasons.append("query_anchor_conflict")
    elif anchor_conflict:
        reasons.append("query_anchor_conflict_overridden_by_action_role")
    if _event_participation_mismatch(query=query, text=item.text):
        penalty += 0.075
        reasons.append("event_participation_mismatch")
    elif _event_participation_positive_match(query=query, text=item.text):
        boost += 0.018
        reasons.append("event_participation_positive_match")
    elif _event_participation_source_sibling_noise(query=query, item=item):
        penalty += 0.07
        reasons.append("event_participation_source_sibling_noise")
    companion_boost, companion_penalty, companion_reason = activity_companion_signal(
        query=query, item=item, query_anchor_intent=query_anchor_intent
    )
    if companion_boost > 0:
        boost += companion_boost
        reasons.append(companion_reason)
    if companion_penalty > 0:
        penalty += companion_penalty
        reasons.append(companion_reason)
    if _activity_source_sibling_noise(item=item):
        penalty += 0.04
        reasons.append("activity_source_sibling_noise")
    if _capped_source_sibling_low_signal(item=item):
        penalty += 0.06
        reasons.append("capped_source_sibling_low_signal")
    if _allergy_condition_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.07
        reasons.append("allergy_condition_weak_evidence")
    if _patriotic_service_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.055
        reasons.append("patriotic_service_weak_evidence")
    if _running_reason_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.055
        reasons.append("running_reason_weak_evidence")
    if _volunteer_career_exact_turn_evidence(query_reason=query_reason, item=item):
        boost += 0.028
        reasons.append("volunteer_career_exact_turn_evidence")
    if _volunteer_career_weak_evidence(
        query_anchor_intent=query_anchor_intent, query_reason=query_reason, item=item
    ):
        penalty += 0.07
        reasons.append("volunteer_career_weak_evidence")
    if _volunteer_career_broad_evidence(query_reason=query_reason, item=item):
        penalty += 0.07
        reasons.append("volunteer_career_broad_evidence")
    if _post_event_activity_timing_exact_evidence(query_reason=query_reason, item=item):
        boost += 0.032
        reasons.append("post_event_activity_timing_exact_evidence")
    if _post_event_activity_timing_weak_evidence(query_reason=query_reason, item=item):
        penalty += 0.12
        reasons.append("post_event_activity_timing_weak_evidence")
    if _shoe_usage_exact_evidence(query_reason=query_reason, item=item):
        boost += 0.024
        reasons.append("shoe_usage_exact_evidence")
    if _shoe_usage_weak_evidence(query_reason=query_reason, item=item):
        penalty += 0.12
        reasons.append("shoe_usage_weak_evidence")
    domain_adjustment = apply_domain_rerank_signals(
        query=query,
        query_reason=query_reason,
        item=item,
        relevance=relevance,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
    )
    boost += domain_adjustment.boost
    ordinal_sequence_requirement_support = (
        ordinal_sequence_signal.boost > 0
        and ordinal_sequence_signal.reason == "ordinal_sequence_exact_evidence"
    )
    if (
        ordinal_sequence_requirement_support
        and "item_purchase_temporal_weak_evidence" in domain_adjustment.reasons
    ):
        reasons.append("item_purchase_weak_evidence_overridden_by_ordinal_sequence")
    else:
        penalty += domain_adjustment.penalty
    reasons.extend(domain_adjustment.reasons)
    rank_signals.update(domain_adjustment.rank_signals)
    slot_diverse_aggregation = aggregation_answer_slot_count(query=query, text=item.text) >= 2
    event_detail_requirement_support = "temporal_camping_detail_evidence" in reasons
    artifact_inventory_requirement_support = "artifact_inventory_first_party_evidence" in reasons
    if requested_total > 0:
        if coverage_ratio <= 0 and (
            event_detail_requirement_support
            or artifact_inventory_requirement_support
            or ordinal_sequence_requirement_support
        ):
            if event_detail_requirement_support:
                reasons.append("explicit_requirement_supported_by_event_detail")
            if artifact_inventory_requirement_support:
                reasons.append("explicit_requirement_supported_by_artifact_inventory")
            if ordinal_sequence_requirement_support:
                reasons.append("explicit_requirement_supported_by_ordinal_sequence")
        elif coverage_ratio <= 0:
            penalty += 0.025
            reasons.append("explicit_requirement_missing")
        elif coverage_ratio < 0.5 and (not slot_diverse_aggregation):
            penalty += 0.012
            reasons.append("explicit_requirement_partial")
    if (
        coverage.missing_answer_shapes
        and (not slot_diverse_aggregation)
        and (not ordinal_sequence_requirement_support)
    ):
        penalty += min(0.02, 0.014 * len(coverage.missing_answer_shapes))
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_answer_shape_missing")
    if coverage.missing_modalities and (not artifact_inventory_requirement_support):
        penalty += min(0.032, 0.024 * len(coverage.missing_modalities))
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_modality_missing")
    if (
        coverage.missing_evidence_features
        and (not slot_diverse_aggregation)
        and (not artifact_inventory_requirement_support)
    ):
        penalty += min(0.028, 0.02 * len(coverage.missing_evidence_features))
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_evidence_feature_missing")
    if (
        not is_query_relevance_sufficient(relevance)
        and anchor_match is None
        and (coverage_ratio <= 0)
    ):
        penalty += 0.018
        reasons.append("weak_query_relevance")
    elif (
        _is_long_query_weak_overlap(relevance)
        and anchor_match is None
        and (coverage_ratio <= 0)
        and (strong_source_count <= 0)
        and (len(sources) <= 1)
    ):
        penalty += 0.016
        reasons.append("weak_long_query_overlap")
    return _DeterministicRerankSignals(
        boost=round(min(max_boost, boost), 4),
        penalty=round(min(max_penalty, penalty), 4),
        reasons=tuple(dict.fromkeys(reasons)),
        rank_signals=tuple(sorted(rank_signals.items())),
        source_count=len(sources),
        strong_source_count=strong_source_count,
        coverage_ratio=round(coverage_ratio, 4),
        anchor_conflict=anchor_conflict,
        query_reason=query_reason,
    )
