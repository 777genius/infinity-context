"""Source-sibling ranking helpers for prompt-safe context assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from infinity_context_core.application.context_generic_behavior_inference import (
    generic_behavior_inference_signal,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    PRECISE_TURN_SOURCE_SIBLING_REASONS,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_chunk_candidate_relevance_sufficient,
)
from infinity_context_core.application.context_source_sibling_patterns import (
    _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS,
    _ACTIVITY_DURATION_SOURCE_SIBLING_SIGNAL_RE,
    _ANIMAL_CARE_INSTRUCTION_SOURCE_SIBLING_RE,
    _BIRDWATCHING_CITY_SCHEDULE_ACCESS_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_EQUIPMENT_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_HOBBY_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_PRESSURE_SLOT_RE,
    _BIRDWATCHING_CITY_SCHEDULE_SOURCE_SIBLING_RE,
    _COUNT_ACTIVITY_FOLLOWUP_SOURCE_SIBLING_REASONS,
    _DEGREE_POLICY_SOURCE_SIBLING_RE,
    _DIALOGUE_MARKER_RE,
    _DIALOGUE_VISUAL_REFERENCE_RE,
    _EVENT_VISUAL_SOURCE_SIBLING_REASONS,
    _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS,
    _FREQUENCY_RECURRENCE_SOURCE_SIBLING_SIGNAL_RE,
    _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON,
    _MAX_SOURCE_GROUP_SIBLING_ITEMS,
    _MAX_SOURCE_GROUPS,
    _MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS,
    _MAX_SOURCE_SIBLING_GROUPS,
    _POST_EVENT_ACTIVITY_SOURCE_SIBLING_RE,
    _POTTERY_TYPE_SOURCE_SIBLING_ACTION_RE,
    _POTTERY_TYPE_SOURCE_SIBLING_LOW_SIGNAL_CAP,
    _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE,
    _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP,
    _PRECISE_SOURCE_SIBLING_MIN_STRONG_DISTINCTIVE_HITS,
    _RUNNING_REASON_SOURCE_SIBLING_RE,
    _SOURCE_GROUP_PRIMARY_SEED_SCORE,
    _SOURCE_GROUP_SIBLING_SCORES,
    _SOURCE_GROUP_SUFFIXES,
    _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE,
    _TURN_SOURCE_ID_RE,
    _VISUAL_REFERENT_SIBLING_RE,
    _VISUAL_SOURCE_SIBLING_QUERY_RE,
    _VISUAL_SOURCE_SIBLING_REASONS,
    _VOLUNTEER_CAREER_SOURCE_SIBLING_CONTEXT_RE,
    _VOLUNTEER_CAREER_SOURCE_SIBLING_SIGNAL_RE,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MemoryChunk


@dataclass(frozen=True)
class _SourceGroupSeed:
    priority: int
    primary_turn: int
    turns: frozenset[int]
    group_level: bool = False


@dataclass(frozen=True)
class _SourceSiblingRank:
    score: float
    group_priority: int
    turn_distance: int
    turn_delta: int
    group_level_seed: bool = False


def source_sibling_group_limit() -> int:
    return _MAX_SOURCE_SIBLING_GROUPS


def source_sibling_item_limit() -> int:
    return _MAX_SOURCE_GROUP_SIBLING_ITEMS


def source_sibling_companion_extra_item_limit() -> int:
    return _MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS


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
    )
    birdwatching_city_companion = _is_birdwatching_city_schedule_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    degree_policy_companion = _is_degree_policy_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    )
    generic_behavior_companion = _is_generic_behavior_source_sibling_strong(
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
    if _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    ):
        score_floor = max(score_floor, 0.982)
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
    )
    return min(score, score_cap) if score_cap is not None else score


def source_sibling_candidate_rank_key(
    *,
    precise_turn: bool,
    dialogue_visual_reference: bool,
    visual_continuation: bool,
    observation_companion: bool,
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


def source_sibling_score_cap(
    *,
    expansion_reason: str,
    relevance: QueryRelevance,
    text: str,
) -> float | None:
    if _is_degree_policy_source_sibling_strong(
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
        expansion_reason in {"running_reason_bridge", "running_reason_question_bridge"}
        and not _is_running_reason_source_sibling_strong(text)
    ):
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
        and not _is_activity_duration_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    if (
        expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS
        and not _is_frequency_recurrence_source_sibling_strong(text)
    ):
        return _PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP
    return None


def is_pottery_type_observation_companion(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
    text: str,
) -> bool:
    if not str(chunk.source_external_id).endswith(":observation"):
        return False
    return _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    )


def source_sibling_marker_coverage_count(*, expansion_reason: str, text: str) -> int:
    if expansion_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_slot_count(text)
    if not _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return 0
    return len(tuple(dict.fromkeys(_DIALOGUE_MARKER_RE.findall(text))))


def is_same_document_answer_companion(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
    text: str,
) -> bool:
    return is_pottery_type_observation_companion(
        chunk=chunk,
        expansion_reason=expansion_reason,
        text=text,
    )


def is_pottery_type_retrieval_scope(*, expansion_reason: str, expansion_query: str) -> bool:
    return _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
    )


def is_pottery_type_evidence_text(text: str) -> bool:
    return _is_pottery_type_source_sibling_strong(text)


def source_sibling_companion_extra_slot(*, chunk: MemoryChunk, text: str) -> str:
    if not str(chunk.source_external_id).endswith(":observation"):
        return ""
    markers = tuple(dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(text)))
    if len(markers) < 2:
        return ""
    return f"{chunk.source_external_id}:{markers[0]}:{markers[-1]}"


def source_sibling_relevance_allowed(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
    ) and not _is_pottery_type_source_sibling_strong(text):
        return False
    if expansion_reason == "animal_care_instruction_bridge":
        return _is_animal_care_instruction_source_sibling_strong(text)
    if (
        expansion_reason in {"running_reason_bridge", "running_reason_question_bridge"}
        and not _is_running_reason_source_sibling_strong(text)
    ):
        return False
    if (
        expansion_reason == "post_event_activity_timing_bridge"
        and not _is_post_event_activity_source_sibling_strong(text)
    ):
        return False
    if expansion_reason == _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON:
        return _is_generic_behavior_source_sibling_strong(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "degree_policy_inference_bridge":
        return _is_degree_policy_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS:
        return _is_activity_duration_source_sibling_strong(text)
    if expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS:
        return _is_frequency_recurrence_source_sibling_strong(text)
    if _is_birdwatching_city_schedule_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_count_activity_followup_source_sibling(
        rank=rank,
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
        text=text,
    ):
        return True
    return is_chunk_candidate_relevance_sufficient(
        query=expansion_query,
        text=text,
        relevance=relevance,
    ) or _is_visual_referent_source_sibling(
        rank=rank,
        relevance=relevance,
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )


def is_visual_continuation_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        rank.group_level_seed
        and rank.turn_delta > 0
        and rank.turn_distance <= 1
        and _is_visual_referent_source_sibling(
            rank=rank,
            relevance=relevance,
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    )


def is_dialogue_visual_reference_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _visual_source_sibling_priority_allowed(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return False
    if not rank.group_level_seed:
        return False
    if relevance.unique_term_hits <= 0 and relevance.distinctive_term_hits <= 0:
        return False
    return _DIALOGUE_VISUAL_REFERENCE_RE.search(text) is not None


def is_precise_source_sibling_turn(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in PRECISE_TURN_SOURCE_SIBLING_REASONS
        and source_turn_marker(chunk.source_external_id) is not None
    )


def with_source_sibling_score_signals(
    item: ContextItem,
    *,
    rank: _SourceSiblingRank,
    score_cap: float | None = None,
    dialogue_visual_reference: bool = False,
    visual_continuation: bool = False,
) -> ContextItem:
    after_seed_boost = 0.05 if rank.turn_delta > 0 else 0.0
    diagnostics = dict(item.diagnostics or {})
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        "source_sibling_after_seed_boost": after_seed_boost,
        "source_sibling_score_cap": score_cap,
        "source_sibling_score_cap_applied": 1 if score_cap is not None else 0,
        "source_sibling_dialogue_visual_reference": 1 if dialogue_visual_reference else 0,
        "source_sibling_visual_continuation": 1 if visual_continuation else 0,
        "source_sibling_group_level_seed": 1 if rank.group_level_seed else 0,
        "source_sibling_group_boost": max(0, _MAX_SOURCE_GROUPS - rank.group_priority),
        "source_sibling_after_seed": 1 if rank.turn_delta > 0 else 0,
        "source_sibling_closeness": max(0, 4 - rank.turn_distance),
        "source_sibling_turn_distance": rank.turn_distance,
        "source_sibling_group_priority": rank.group_priority,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "source_sibling_turn_delta": rank.turn_delta,
        "source_sibling_turn_distance": rank.turn_distance,
        "source_sibling_group_priority": rank.group_priority,
        "source_sibling_group_level_seed": rank.group_level_seed,
        "source_sibling_score_cap_applied": score_cap is not None,
        "source_sibling_dialogue_visual_reference": dialogue_visual_reference,
        "source_sibling_visual_continuation": visual_continuation,
    }
    return replace(
        item,
        score=_apply_source_sibling_score_cap(
            score=min(0.99, round(item.score + after_seed_boost, 4)),
            score_cap=score_cap,
        ),
        diagnostics=diagnostics,
    )


def source_group_seed_turns(
    seed_chunks: tuple[MemoryChunk, ...],
) -> dict[str, _SourceGroupSeed]:
    groups: dict[str, tuple[int, int, set[int], bool]] = {}
    for chunk in seed_chunks:
        marker = source_turn_marker(chunk.source_external_id)
        if marker is None:
            group = _source_session_group(chunk.source_external_id)
            if group is None:
                continue
            if group not in groups:
                groups[group] = (len(groups), 0, set(), True)
            else:
                priority, primary_turn, turns, _ = groups[group]
                groups[group] = (priority, primary_turn, turns, True)
            if len(groups) >= _MAX_SOURCE_GROUPS:
                break
            continue
        group, turn = marker
        if group not in groups:
            groups[group] = (len(groups), turn, set(), False)
        priority, primary_turn, turns, group_level = groups[group]
        turns.add(turn)
        groups[group] = (priority, primary_turn or turn, turns, group_level)
        if len(groups) >= _MAX_SOURCE_GROUPS:
            break
    return {
        group: _SourceGroupSeed(
            priority=priority,
            primary_turn=primary_turn,
            turns=frozenset(turns),
            group_level=group_level,
        )
        for group, (priority, primary_turn, turns, group_level) in groups.items()
    }


def source_turn_marker(source_external_id: str) -> tuple[str, int] | None:
    source_id = " ".join(str(source_external_id).split())
    if not source_id:
        return None
    match = _TURN_SOURCE_ID_RE.match(source_id)
    if match is None:
        return None
    group = match.group("group").strip()
    if not group or len(group.split(":")) < 3:
        return None
    try:
        turn = int(match.group("turn"))
    except ValueError:
        return None
    return group, turn


def source_sibling_rank(
    chunk: MemoryChunk,
    *,
    source_groups: dict[str, _SourceGroupSeed],
) -> _SourceSiblingRank | None:
    marker = source_turn_marker(chunk.source_external_id)
    if marker is None:
        group = _source_session_group(chunk.source_external_id)
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
    source_groups: dict[str, _SourceGroupSeed],
    expansion_reason: str,
    text: str,
) -> _SourceSiblingRank | None:
    """Allow high-signal same-session evidence turns beyond the short sibling window."""

    if expansion_reason != "birdwatching_city_schedule_bridge":
        return None
    marker = source_turn_marker(chunk.source_external_id)
    if marker is None:
        return None
    group, turn = marker
    seed = source_groups.get(group)
    if seed is None or seed.group_level:
        return None
    slot_count = _birdwatching_city_schedule_slot_count(text)
    if slot_count <= 0:
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


def _is_pottery_type_source_sibling_strong(text: str) -> bool:
    return (
        _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE.search(text) is not None
        and _POTTERY_TYPE_SOURCE_SIBLING_ACTION_RE.search(text) is not None
    )


def _is_animal_care_instruction_source_sibling_strong(text: str) -> bool:
    return _ANIMAL_CARE_INSTRUCTION_SOURCE_SIBLING_RE.search(text) is not None


def _is_pottery_type_source_sibling_reason(expansion_reason: str) -> bool:
    return expansion_reason.replace("_", "-") in {
        "pottery-type-bridge",
        "decomposition-inventory-list",
    }


def _is_pottery_type_source_sibling_scope(*, expansion_reason: str, expansion_query: str) -> bool:
    if expansion_reason == "pottery_type_bridge":
        return True
    if expansion_reason != "decomposition_inventory_list":
        return False
    return _POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE.search(expansion_query) is not None


def _is_pottery_type_observation_companion_text(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _is_pottery_type_source_sibling_reason(expansion_reason):
        return False
    return _is_pottery_type_source_sibling_strong(text) and "related turns:" in text.lower()


def _is_running_reason_source_sibling_strong(text: str) -> bool:
    return _RUNNING_REASON_SOURCE_SIBLING_RE.search(text) is not None


def _is_volunteer_career_source_sibling_strong(text: str) -> bool:
    return (
        _VOLUNTEER_CAREER_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _VOLUNTEER_CAREER_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_degree_policy_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != "degree_policy_inference_bridge":
        return False
    return _DEGREE_POLICY_SOURCE_SIBLING_RE.search(text) is not None


def _is_post_event_activity_source_sibling_strong(text: str) -> bool:
    return _POST_EVENT_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None


def _is_temporal_state_source_sibling_strong(*, expansion_reason: str, text: str) -> bool:
    if expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS:
        return _is_activity_duration_source_sibling_strong(text)
    if expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS:
        return _is_frequency_recurrence_source_sibling_strong(text)
    return False


def _is_activity_duration_source_sibling_strong(text: str) -> bool:
    return (
        _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _ACTIVITY_DURATION_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_frequency_recurrence_source_sibling_strong(text: str) -> bool:
    return (
        _STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE.search(text) is not None
        and _FREQUENCY_RECURRENCE_SOURCE_SIBLING_SIGNAL_RE.search(text) is not None
    )


def _is_birdwatching_city_schedule_source_sibling_strong(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "birdwatching_city_schedule_bridge"
        and _BIRDWATCHING_CITY_SCHEDULE_SOURCE_SIBLING_RE.search(text) is not None
    )


def _birdwatching_city_schedule_slot_count(text: str) -> int:
    slots = 0
    for pattern in (
        _BIRDWATCHING_CITY_SCHEDULE_ACCESS_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_EQUIPMENT_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_PRESSURE_SLOT_RE,
        _BIRDWATCHING_CITY_SCHEDULE_HOBBY_SLOT_RE,
    ):
        if pattern.search(text) is not None:
            slots += 1
    return slots


def _is_generic_behavior_source_sibling_strong(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON:
        return False
    if (
        generic_behavior_inference_signal(query=expansion_query, text=text).reason
        == "inference_behavior_evidence"
    ):
        return True
    # Score caps do not receive the winning expansion query. This strict fallback
    # keeps concrete behavior turns uncapped while still rejecting topic-only text.
    return (
        generic_behavior_inference_signal(query=text, text=text).reason
        == "inference_behavior_evidence"
    )


def _is_count_activity_followup_source_sibling(
    *,
    rank: _SourceSiblingRank,
    expansion_reason: str,
    expansion_query: str,
    text: str,
) -> bool:
    if expansion_reason not in _COUNT_ACTIVITY_FOLLOWUP_SOURCE_SIBLING_REASONS:
        return False
    if rank.turn_delta <= 0 or rank.turn_distance > 2:
        return False
    subject = _query_subject_name(expansion_query)
    if not subject:
        return False
    return re.search(rf"\b{re.escape(subject)}\b", text, re.IGNORECASE) is not None


def _query_subject_name(query: str) -> str:
    match = re.match(r"\s*([A-Z][A-Za-z][A-Za-z'-]*)\b", query)
    return match.group(1) if match is not None else ""


def _is_visual_referent_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _visual_source_sibling_priority_allowed(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return False
    if rank.turn_distance > 2:
        return False
    if relevance.unique_term_hits <= 0 and relevance.distinctive_term_hits <= 0:
        return False
    return _VISUAL_REFERENT_SIBLING_RE.search(text) is not None


def _visual_source_sibling_priority_allowed(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _VISUAL_SOURCE_SIBLING_REASONS
        or expansion_reason in _EVENT_VISUAL_SOURCE_SIBLING_REASONS
        or _VISUAL_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _source_session_group(source_external_id: str) -> str | None:
    source_id = " ".join(str(source_external_id).split())
    if not source_id:
        return None
    parts = source_id.split(":")
    if len(parts) >= 4 and parts[-1].casefold() in _SOURCE_GROUP_SUFFIXES:
        group = ":".join(parts[:-1])
        return group if _source_group_has_session_tail(group) else None
    return source_id if _source_group_has_session_tail(source_id) else None


def _source_group_has_session_tail(source_id: str) -> bool:
    parts = source_id.split(":")
    return bool(parts and re.fullmatch(r"session_\d+", parts[-1], re.IGNORECASE))


def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


def _apply_source_sibling_score_cap(*, score: float, score_cap: float | None) -> float:
    return min(score, score_cap) if score_cap is not None else score
