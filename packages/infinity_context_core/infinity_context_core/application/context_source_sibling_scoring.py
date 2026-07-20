"""Source-sibling scoring and deterministic ranking."""

from __future__ import annotations

from dataclasses import replace

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    PRECISE_TURN_SOURCE_SIBLING_REASONS,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_recommendation_list_reason,
    recommendation_list_answer_support_rank,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_answer_evidence,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_chunk_candidate_relevance_sufficient,
)
from infinity_context_core.application.context_source_sibling_contracts import (
    _ObligationEvidenceProjection,
    _SourceGroupSeed,
    _SourceSiblingRank,
)
from infinity_context_core.application.context_source_sibling_evidence_rules import (
    _birdwatching_city_schedule_slot_count,
    _is_activity_duration_source_sibling_strong,
    _is_animal_care_instruction_source_sibling_strong,
    _is_animal_diet_evidence_source_sibling_strong,
    _is_birdwatching_city_schedule_source_sibling_strong,
    _is_book_reading_inventory_source_sibling_strong,
    _is_church_friend_activity_inventory_source_sibling_strong,
    _is_degree_policy_source_sibling_strong,
    _is_direct_source_sibling_answer_evidence,
    _is_frequency_recurrence_source_sibling_strong,
    _is_generic_behavior_source_sibling_strong,
    _is_named_preference_source_sibling_answer_evidence,
    _is_post_event_activity_source_sibling_strong,
    _is_pottery_type_observation_companion_text,
    _is_pottery_type_source_sibling_scope,
    _is_pottery_type_source_sibling_strong,
    _is_running_reason_source_sibling_strong,
    _is_temporal_state_source_sibling_strong,
    _is_volunteer_career_source_sibling_strong,
    _is_volunteering_inventory_source_sibling_strong_for_reason,
    _is_volunteering_service_activity_source_sibling_strong_for_reason,
)
from infinity_context_core.application.context_source_sibling_evidence_shared import (
    _common_interest_answer_slot_count,
    _is_children_preference_source_sibling_strong_for_reason,
    _is_classical_music_preference_source_sibling_strong_for_reason,
    _is_common_interest_source_sibling_scope,
    _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason,
    _is_outdoor_preference_source_sibling_strong_for_reason,
    _is_pet_acquisition_date_anchor,
    _is_sentimental_reminder_source_sibling_strong_for_reason,
    _query_person_matches_text,
)
from infinity_context_core.application.context_source_sibling_identity import (
    _source_session_group,
    source_turn_marker,
)
from infinity_context_core.application.context_source_sibling_patterns import (
    _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS,
    _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS,
    _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON,
    _MAX_SOURCE_GROUPS,
    _POTTERY_TYPE_SOURCE_SIBLING_LOW_SIGNAL_CAP,
    _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP,
    _PRECISE_SOURCE_SIBLING_MIN_STRONG_DISTINCTIVE_HITS,
    _SOURCE_GROUP_PRIMARY_SEED_SCORE,
    _SOURCE_GROUP_SIBLING_SCORES,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    is_country_destination_source_sibling_answer_evidence,
    is_place_inference_source_sibling_answer_evidence,
    is_query_destination_source_sibling_anchor,
    is_themed_location_source_sibling_answer_evidence,
)
from infinity_context_core.application.context_source_sibling_policy import (
    _is_count_activity_followup_source_sibling,
    _is_visual_referent_source_sibling,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MemoryChunk


def source_sibling_score(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> float:
    relevance_specific = is_chunk_candidate_relevance_sufficient(
        query=expansion_query,
        text=text,
        relevance=relevance,
    )
    visual_referent = _is_visual_referent_source_sibling(
        rank=rank,
        relevance=relevance,
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    temporal_state_companion = _is_temporal_state_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
        expansion_query=expansion_query,
    )
    birdwatching_city_companion = _is_birdwatching_city_schedule_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    degree_policy_companion = _is_degree_policy_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    book_reading_inventory = _is_book_reading_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    church_friend_activity_inventory = _is_church_friend_activity_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    volunteering_service_activity = (
        _is_volunteering_service_activity_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    )
    generic_behavior_companion = _is_generic_behavior_source_sibling_strong(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    classical_music_preference = _is_classical_music_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    )
    sentimental_reminder = _is_sentimental_reminder_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    )
    outdoor_preference = _is_outdoor_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    )
    outdoor_activity_visual_companion = (
        _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    )
    children_preference = _is_children_preference_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    )
    direct_answer_evidence = _is_direct_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    count_activity_followup = _is_count_activity_followup_source_sibling(
        rank=rank,
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
        text=text,
    )
    if (
        not relevance_specific
        and not visual_referent
        and not temporal_state_companion
        and not birdwatching_city_companion
        and not degree_policy_companion
        and not book_reading_inventory
        and not church_friend_activity_inventory
        and not volunteering_service_activity
        and not classical_music_preference
        and not sentimental_reminder
        and not outdoor_preference
        and not outdoor_activity_visual_companion
        and not children_preference
        and not direct_answer_evidence
        and not generic_behavior_companion
        and not count_activity_followup
    ):
        return rank.score
    relevance_boost = min(
        0.04,
        relevance.score_boost * 0.16 + relevance.distinctive_term_hits * 0.004,
    )
    visual_boost = 0.018 if visual_referent else 0.0
    temporal_state_boost = 0.014 if temporal_state_companion else 0.0
    generic_behavior_boost = 0.014 if generic_behavior_companion else 0.0
    score_floor = 0.966 if relevance_specific else 0.958
    if temporal_state_companion:
        score_floor = max(score_floor, 0.974)
    if generic_behavior_companion:
        score_floor = max(score_floor, 0.974)
    if birdwatching_city_companion:
        score_floor = max(score_floor, 0.972)
    if book_reading_inventory or church_friend_activity_inventory or volunteering_service_activity:
        score_floor = max(score_floor, 0.986)
    if classical_music_preference or sentimental_reminder:
        score_floor = max(score_floor, 0.986)
    if outdoor_preference:
        score_floor = max(score_floor, 0.984)
    if outdoor_activity_visual_companion:
        score_floor = max(score_floor, 0.986)
    if children_preference:
        score_floor = max(score_floor, 0.986)
    if direct_answer_evidence:
        score_floor = max(score_floor, 0.986)
    if _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    ):
        score_floor = max(score_floor, 0.982)
    if expansion_reason == "pet_acquisition_date_bridge" and _is_pet_acquisition_date_anchor(
        expansion_query=expansion_query,
        text=text,
    ):
        score_floor = max(score_floor, 0.99)
    score = min(
        0.99,
        round(
            max(rank.score, score_floor)
            + relevance_boost
            + visual_boost
            + temporal_state_boost
            + generic_behavior_boost,
            4,
        ),
    )
    score_cap = source_sibling_score_cap(
        expansion_reason=expansion_reason,
        relevance=relevance,
        text=text,
        expansion_query=expansion_query,
    )
    return min(score, score_cap) if score_cap is not None else score


def source_sibling_candidate_rank_key(
    *,
    precise_turn: bool,
    dialogue_visual_reference: bool,
    visual_continuation: bool,
    observation_companion: bool,
    obligation_evidence_rank: int = 1,
    answer_evidence: bool = False,
    answer_evidence_role_rank: int = 0,
    marker_coverage: int,
    relevance: QueryRelevance,
    score: float,
    rank: _SourceSiblingRank,
    chunk: MemoryChunk,
) -> tuple[float | int | str, ...]:
    return (
        0 if observation_companion else 1,
        0 if precise_turn else 1,
        0 if dialogue_visual_reference else 1,
        0 if visual_continuation else 1,
        -marker_coverage,
        obligation_evidence_rank,
        0 if answer_evidence else 1,
        answer_evidence_role_rank if answer_evidence else 0,
        -relevance.distinctive_term_hits,
        -relevance.unique_term_hits,
        -relevance.hit_ratio,
        -score,
        rank.group_priority,
        rank.turn_distance,
        0 if rank.turn_delta > 0 else 1,
        chunk.source_external_id,
        chunk.sequence,
        str(chunk.id),
    )


def source_sibling_obligation_evidence_score(*, score: float, rank: int) -> float:
    """Apply a bounded score preference for direct obligations over generic advice."""

    if rank == 0:
        return max(score, 0.99)
    if rank == 2:
        return min(score, 0.9)
    if rank == 3:
        return min(score, 0.92)
    return score


def with_source_sibling_obligation_evidence_signal(
    item: ContextItem,
    *,
    rank: int,
    projection: _ObligationEvidenceProjection | None = None,
    canonical_text_length: int = 0,
) -> ContextItem:
    """Annotate an opaque-document candidate with its obligation evidence rank."""

    diagnostics = dict(item.diagnostics or {})
    score = source_sibling_obligation_evidence_score(score=item.score, rank=rank)
    existing_signals = _score_signals(diagnostics)
    existing_signals.pop("application_evidence_contract_tier", None)
    diagnostics["score_signals"] = {
        **({"application_evidence_contract_tier": 1} if rank == 0 else {}),
        **existing_signals,
        "source_sibling_obligation_evidence_rank": rank,
        "final_score": score,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "source_sibling_obligation_evidence_rank": rank,
        **_obligation_projection_provenance(
            projection=projection,
            canonical_text_length=canonical_text_length,
        ),
    }
    return replace(item, score=score, diagnostics=diagnostics)


def source_sibling_score_cap(
    *,
    expansion_reason: str,
    relevance: QueryRelevance,
    text: str,
    expansion_query: str = "",
) -> float | None:
    if _is_degree_policy_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return None
    if (
        _is_book_reading_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_church_friend_activity_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_volunteering_service_activity_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_volunteering_inventory_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    ):
        return None
    if _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return None
    if (
        expansion_reason in PRECISE_TURN_SOURCE_SIBLING_REASONS
        and relevance.distinctive_term_hits < _PRECISE_SOURCE_SIBLING_MIN_STRONG_DISTINCTIVE_HITS
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query="",
    ) and not _is_pottery_type_source_sibling_strong(text):
        return _POTTERY_TYPE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "animal_care_instruction_bridge"
        and not _is_animal_care_instruction_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "animal_diet_evidence_bridge"
        and not _is_animal_diet_evidence_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if expansion_reason in {
        "running_reason_bridge",
        "running_reason_question_bridge",
    } and not _is_running_reason_source_sibling_strong(text):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "volunteer_career_inference_bridge"
        and not _is_volunteer_career_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "degree_policy_inference_bridge"
        and not _is_degree_policy_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == "post_event_activity_timing_bridge"
        and not _is_post_event_activity_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason == _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON
        and not _is_generic_behavior_source_sibling_strong(
            expansion_query="",
            expansion_reason=expansion_reason,
            text=text,
        )
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS
        and not _is_activity_duration_source_sibling_strong(
            text,
            expansion_query=expansion_query,
        )
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS
        and not _is_frequency_recurrence_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    return None


def with_source_sibling_score_signals(
    item: ContextItem,
    *,
    rank: _SourceSiblingRank,
    score_cap: float | None = None,
    dialogue_visual_reference: bool = False,
    visual_continuation: bool = False,
    answer_evidence: bool = False,
    answer_evidence_query: str = "",
    obligation_evidence_rank: int = 1,
    obligation_projection: _ObligationEvidenceProjection | None = None,
    canonical_text_length: int = 0,
) -> ContextItem:
    after_seed_boost = 0.05 if rank.turn_delta > 0 else 0.0
    diagnostics = dict(item.diagnostics or {})
    existing_signals = _score_signals(diagnostics)
    existing_signals.pop("application_evidence_contract_tier", None)
    contract_tier = 1 if answer_evidence and obligation_evidence_rank == 0 else None
    score_signals = {
        **(
            {"application_evidence_contract_tier": contract_tier}
            if contract_tier is not None
            else {}
        ),
        **existing_signals,
        "source_sibling_after_seed_boost": after_seed_boost,
        "source_sibling_score_cap": score_cap,
        "source_sibling_score_cap_applied": 1 if score_cap is not None else 0,
        "source_sibling_dialogue_visual_reference": 1 if dialogue_visual_reference else 0,
        "source_sibling_visual_continuation": 1 if visual_continuation else 0,
        "source_sibling_answer_evidence": 1 if answer_evidence else 0,
        "source_sibling_obligation_evidence_rank": obligation_evidence_rank,
        "source_sibling_obligation_projection_applied": (
            1 if obligation_projection is not None and obligation_projection.applied else 0
        ),
        "source_sibling_group_level_seed": 1 if rank.group_level_seed else 0,
        "source_sibling_group_boost": max(0, _MAX_SOURCE_GROUPS - rank.group_priority),
        "source_sibling_after_seed": 1 if rank.turn_delta > 0 else 0,
        "source_sibling_closeness": max(0, 4 - rank.turn_distance),
        "source_sibling_turn_distance": rank.turn_distance,
        "source_sibling_group_priority": rank.group_priority,
    }
    provenance = {
        **_provenance(diagnostics),
        "source_sibling_turn_delta": rank.turn_delta,
        "source_sibling_turn_distance": rank.turn_distance,
        "source_sibling_group_priority": rank.group_priority,
        "source_sibling_group_level_seed": rank.group_level_seed,
        "source_sibling_score_cap_applied": score_cap is not None,
        "source_sibling_dialogue_visual_reference": dialogue_visual_reference,
        "source_sibling_visual_continuation": visual_continuation,
        "source_sibling_answer_evidence": answer_evidence,
        "source_sibling_obligation_evidence_rank": obligation_evidence_rank,
        **_obligation_projection_provenance(
            projection=obligation_projection,
            canonical_text_length=canonical_text_length,
        ),
    }
    if answer_evidence and answer_evidence_query:
        score_signals["source_sibling_answer_evidence_query"] = answer_evidence_query
        provenance["source_sibling_answer_evidence_query"] = answer_evidence_query
    diagnostics["score_signals"] = score_signals
    diagnostics["provenance"] = provenance
    return replace(
        item,
        score=_apply_source_sibling_score_cap(
            score=source_sibling_obligation_evidence_score(
                score=min(0.99, round(item.score + after_seed_boost, 4)),
                rank=obligation_evidence_rank,
            ),
            score_cap=score_cap,
        ),
        diagnostics=diagnostics,
    )


def source_sibling_rank(
    chunk: MemoryChunk,
    *,
    source_groups: dict[str, _SourceGroupSeed],
) -> _SourceSiblingRank | None:
    marker = source_turn_marker(chunk.source_external_id)
    if marker is None:
        group = _source_session_group(
            chunk.source_external_id,
            allow_opaque_document_source=getattr(chunk, "document_id", None) is not None,
        )
        if group is None:
            return None
        seed = source_groups.get(group)
        if seed is None:
            return None
        return _SourceSiblingRank(
            score=_SOURCE_GROUP_PRIMARY_SEED_SCORE
            if seed.group_level
            else _SOURCE_GROUP_SIBLING_SCORES[1],
            group_priority=seed.priority,
            turn_distance=0,
            turn_delta=0,
            group_level_seed=seed.group_level,
        )
    group, turn = marker
    seed = source_groups.get(group)
    if seed is None or not seed.turns:
        if seed is not None and seed.group_level:
            return _SourceSiblingRank(
                score=_SOURCE_GROUP_PRIMARY_SEED_SCORE,
                group_priority=seed.priority,
                turn_distance=0,
                turn_delta=0,
                group_level_seed=True,
            )
        return None
    if seed.group_level:
        return _SourceSiblingRank(
            score=_SOURCE_GROUP_PRIMARY_SEED_SCORE,
            group_priority=seed.priority,
            turn_distance=0,
            turn_delta=0,
            group_level_seed=True,
        )
    if turn == seed.primary_turn:
        return _SourceSiblingRank(
            score=_SOURCE_GROUP_PRIMARY_SEED_SCORE,
            group_priority=seed.priority,
            turn_distance=0,
            turn_delta=0,
        )
    seed_turns = tuple(seed_turn for seed_turn in seed.turns if seed_turn != turn)
    if not seed_turns:
        return None
    turn_delta = min(
        (turn - seed_turn for seed_turn in seed_turns),
        key=lambda delta: (abs(delta), delta < 0),
    )
    min_distance = abs(turn_delta)
    score = _SOURCE_GROUP_SIBLING_SCORES.get(min_distance)
    if score is None:
        return None
    return _SourceSiblingRank(
        score=score,
        group_priority=seed.priority,
        turn_distance=min_distance,
        turn_delta=turn_delta,
    )


def source_sibling_distant_answer_evidence_rank(
    chunk: MemoryChunk,
    *,
    expansion_query: str,
    source_groups: dict[str, _SourceGroupSeed],
    expansion_reason: str,
    text: str,
) -> _SourceSiblingRank | None:
    """Allow high-signal same-session evidence turns beyond the short sibling window."""

    slot_count = _distant_source_sibling_answer_slot_count(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )
    if slot_count <= 0:
        return None
    marker = source_turn_marker(chunk.source_external_id)
    if marker is None:
        return None
    group, turn = marker
    seed = source_groups.get(group)
    if seed is None or seed.group_level:
        return None
    if seed.turns:
        turn_delta = min(
            (turn - seed_turn for seed_turn in seed.turns),
            key=lambda delta: (abs(delta), delta < 0),
        )
    else:
        turn_delta = turn - seed.primary_turn
    return _SourceSiblingRank(
        score=0.966 + min(slot_count, 3) * 0.004,
        group_priority=seed.priority,
        turn_distance=min(abs(turn_delta), 5),
        turn_delta=turn_delta,
    )


def _distant_source_sibling_answer_slot_count(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> int:
    if expansion_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_slot_count(text)
    slot_count = aggregation_answer_slot_count(query=expansion_query, text=text)
    if _is_common_interest_source_sibling_scope(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return max(slot_count, _common_interest_answer_slot_count(text))
    if _is_named_preference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if is_place_inference_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if is_themed_location_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if is_query_destination_source_sibling_anchor(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if _query_person_matches_text(
        expansion_query=expansion_query,
        text=text,
    ) and is_country_destination_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if (
        is_recommendation_list_reason(expansion_reason)
        and recommendation_list_answer_support_rank(
            text=text,
            query_reason=expansion_reason,
        )
        <= 2
    ):
        return max(slot_count, 2)
    if _query_person_matches_text(
        expansion_query=expansion_query,
        text=text,
    ) and is_relationship_status_answer_evidence(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    if _is_direct_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return max(slot_count, 2)
    return slot_count


def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


def _apply_source_sibling_score_cap(*, score: float, score_cap: float | None) -> float:
    return min(score, score_cap) if score_cap is not None else score


def _obligation_projection_provenance(
    *,
    projection: _ObligationEvidenceProjection | None,
    canonical_text_length: int,
) -> dict[str, object]:
    if projection is None or not projection.applied:
        return {"source_sibling_obligation_projection_applied": False}
    return {
        "source_sibling_obligation_projection_applied": True,
        "source_sibling_obligation_projection_spans": [
            [start, end] for start, end in projection.spans
        ],
        "source_sibling_obligation_projection_canonical_text_length": max(0, canonical_text_length),
    }
